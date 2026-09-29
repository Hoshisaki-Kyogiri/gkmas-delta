"""Stories, audio and video from the Resource folder, for the web console.

Resources keep their real filenames, so everything here is derived from the
names alone: no master database, no network.

Stories are the game's ADV scripts (adv_*.txt): one bracketed command per line,
of which only message / narration / choicegroup carry text a reader wants, and
voice commands say which recorded line goes with which message.

Audio comes as plain .mp3 or as CRI .acb/.awb banks. The HCA audio inside the
banks is unencrypted; vgmstream decodes a whole bank to .wav in one go, into
data/AUDIO/<bank>/. Videos are CRI .usm, remuxed or transcoded to .mp4 by ffmpeg
into data/VIDEO/.
"""

import json
import re
import subprocess
import threading
import time
from pathlib import Path

from . import external
from .errors import UmeError

# Character codes as they appear in filenames and actor ids.
CHARACTERS = {
    "amao": "有村 麻央",
    "andk": "藍井 撫子",
    "atbm": "雨夜 燕",
    "fktn": "藤田 ことね",
    "hmsz": "秦谷 美鈴",
    "hrnm": "姫崎 莉波",
    "hski": "花海 咲季",
    "hume": "花海 佑芽",
    "jkno": "十王 邦夫",
    "jsna": "十王 星南",
    "kcna": "倉本 千奈",
    "kllj": "葛城 リーリヤ",
    "krnh": "賀陽 燐羽",
    "ktko": "黒井 崇男",
    "myu0": "真城 優",
    "nasr": "根緒 亜紗里",
    "sgka": "白草 月花",
    "shro": "篠澤 広",
    "ssmk": "紫雲 清夏",
    "sson": "白草 四音",
    "ttmr": "月村 手毬",
}

STORY_CATEGORIES = {
    "cidol": "偶像卡剧情",
    "csprt": "支援卡剧情",
    "dear": "亲爱度剧情",
    "event": "活动剧情",
    "pstory": "培育剧情",
    "pevent": "培育事件",
    "pstep": "培育日程",
    "produce": "培育课程",
}

AUDIO_KINDS = {"music": "歌曲", "bgm": "BGM", "voice": "语音", "se": "音效", "other": "其他"}
BGM_SCENES = {"adv": "剧情 BGM", "produce": "培育 BGM", "general": "BGM", "lesson": "课程 BGM"}
VOICE_SCENES = {"adv": "剧情语音", "system": "系统语音", "general": "语音"}
VIDEO_GROUPS = {"general": "通用", "adv": "剧情", "live": "Live", "other": "其他"}

AUDIO_SUFFIXES = {".mp3", ".wav"}
VIDEO_SUFFIXES = {".mp4"}
CRI_SUFFIXES = {".acb", ".awb"}

_CATEGORY = re.compile(r"^adv_([a-z]+)")
# A trailing one- or two-digit part number: adv_cidol-amao-3-017_01, adv_event_026_main-02.
# Three digits (adv_dear_amao_036) are an episode number, not a part.
_PART = re.compile(r"^(?P<series>.+?)[_-](?P<part>\d{1,2})$")
_CODE = re.compile(r"(?<![a-z0-9])([a-z]{3}[a-z0-9])(?![a-z0-9])")

# Values run until the next ` key=` or the closing bracket. Text never contains
# a space followed by a bare ASCII key and `=`, while its own markup escapes the
# equals sign (`<r\=...>`), so this split is unambiguous in practice.
_FIELD = r"(?:^|\s){key}=(?P<value>.*?)(?=\s[A-Za-z]+=|\]$)"
_TEXT = re.compile(_FIELD.format(key="text"))
_NAME = re.compile(_FIELD.format(key="name"))
_VOICE = re.compile(_FIELD.format(key="voice"))
_CHOICE = re.compile(r"\[choice text=(?P<value>.*?)(?=\s[A-Za-z]+=|\])")
_START = re.compile(r'"_startTime":(?P<value>-?[0-9.]+)')

# sud_music_general_all-017-amao_game, _atbm-004-atbm_game-inst, _unit-amaohrnm-004-amao_game
_MUSIC = re.compile(
    r"^sud_music_general_(?P<group>[a-z0-9]+(?:-[a-z0-9]+)?)-(?P<num>\d{3})-(?P<who>[a-z0-9]+)_game(?P<inst>-inst)?$"
)
_SOUND = re.compile(r"^sud_(?P<kind>vo|bgm|se|music)_(?P<scene>[a-z]+)_(?P<rest>.+)$")
_VIDEO = re.compile(r"^mov_(?P<group>[a-z]+)_")
# A voice cue is its bank name plus `_<speaker>-<index>`.
_CUE = re.compile(r"^(?P<bank>sud_vo_[a-z0-9_.-]+)_[a-z0-9]+-\d+$")

_INDEX_TTL = 30.0
_cache = {}
_locks = {}
_locks_guard = threading.Lock()


def _cached(key, compute):
    """Directory scans are cheap but not free; the page asks for them often."""
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _INDEX_TTL:
        return hit[1]
    value = compute()
    _cache[key] = (now, value)
    return value


def _lock_for(key: str) -> threading.Lock:
    # Two clicks on the same bank must not run two decoders into one folder.
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _inside(root: Path, name: str) -> Path:
    """A file directly in root, by bare name only."""
    path = (root / name).resolve()
    if not name or path.parent != root.resolve() or not path.is_file():
        raise UmeError(f"找不到文件：{name}")
    return path


def character_of(name: str) -> str:
    for code in _CODE.findall(name):
        if code in CHARACTERS:
            return code
    return ""


def _unescape(text: str) -> str:
    # `\n` is a line break; `\{ \}` escape braces inside the JSON-ish clip
    # payloads. `\=` inside markup is left for the page to turn into ruby.
    return text.replace("\\n", "\n").replace("\\{", "{").replace("\\}", "}")


def _start_time(raw: str) -> float:
    match = _START.search(raw)
    return float(match.group("value")) if match else 0.0


# -- stories -------------------------------------------------------------------


def _story_entry(path: Path) -> dict:
    stem = path.stem
    match = _PART.match(stem)
    series, part = (match.group("series"), match.group("part")) if match else (stem, "")
    category = (_CATEGORY.match(stem) or [None, "other"])[1]
    return {
        "file": path.name,
        "series": series,
        "part": part,
        "category": category,
        "character": character_of(stem),
        "mtime": path.stat().st_mtime,
    }


def list_stories(paths) -> dict:
    resources = paths.resources

    def compute():
        if not resources.is_dir():
            return []
        series = {}
        for entry in (_story_entry(p) for p in resources.glob("adv_*.txt")):
            item = series.setdefault(
                entry["series"],
                {
                    "id": entry["series"],
                    "category": entry["category"],
                    "character": entry["character"],
                    "parts": [],
                    "mtime": 0,
                },
            )
            item["parts"].append({"file": entry["file"], "part": entry["part"]})
            item["mtime"] = max(item["mtime"], entry["mtime"])
        revisions = resource_revisions(paths)
        for item in series.values():
            item["parts"].sort(key=lambda p: p["part"])
            item["revision"] = max((revisions.get(p["file"], 0) for p in item["parts"]), default=0)
        return sorted(series.values(), key=lambda s: s["mtime"], reverse=True)

    return {
        "stories": _cached(("stories", str(resources)), compute),
        "categories": STORY_CATEGORIES,
        "characters": CHARACTERS,
    }


def parse_story(path: Path) -> list:
    """The readable lines of one ADV script, in order, with their voice cues."""
    lines = []
    messages = []  # (start time, line) for voice matching
    voices = []  # (start time, cue)
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith("[message "):
            text = _TEXT.search(raw)
            name = _NAME.search(raw)
            if text:
                line = {
                    "type": "message",
                    "name": _unescape(name.group("value")) if name else "",
                    "text": _unescape(text.group("value")),
                    "voices": [],
                }
                lines.append(line)
                messages.append((_start_time(raw), line))
        elif raw.startswith("[voice "):
            cue = _VOICE.search(raw)
            if cue:
                voices.append((_start_time(raw), cue.group("value")))
        elif raw.startswith("[narration "):
            text = _TEXT.search(raw)
            if text:
                lines.append({"type": "narration", "text": _unescape(text.group("value"))})
        elif raw.startswith("[choicegroup "):
            choices = [_unescape(m.group("value")) for m in _CHOICE.finditer(raw)]
            if choices:
                lines.append({"type": "choice", "choices": choices})

    # Commands sit on separate timeline tracks, so file order says nothing about
    # which message a voice belongs to. Its start time does: a voice starts just
    # after its message (0.1 s in practice), so it belongs to the latest message
    # that started at or before it.
    messages.sort(key=lambda m: m[0])
    for start, cue in sorted(voices):
        owner = None
        for message_start, line in messages:
            if message_start > start + 0.05:
                break
            owner = line
        if owner is not None:
            owner["voices"].append(cue)
    return lines


def read_story(resources: Path, filename: str) -> list:
    path = (resources / filename).resolve()
    if path.parent != resources.resolve() or not path.name.startswith("adv_") or path.suffix != ".txt":
        raise FileNotFoundError(filename)
    key = ("story", str(path), path.stat().st_mtime)
    hit = _cache.get(key)
    if hit:
        return hit[1]
    lines = parse_story(path)
    _cache[key] = (time.monotonic(), lines)
    return lines


def search_stories(paths, query: str, limit: int = 200) -> list:
    """Series whose dialogue mentions the query, with a few matching lines."""
    query = query.strip()
    if not query:
        return []
    results = {}
    for series in list_stories(paths)["stories"]:
        for part in series["parts"]:
            try:
                lines = read_story(paths.resources, part["file"])
            except (OSError, FileNotFoundError):
                continue
            for line in lines:
                texts = line.get("choices") or [line.get("text", "")]
                if any(query in t for t in texts) or query == line.get("name"):
                    hit = results.setdefault(series["id"], {"id": series["id"], "count": 0, "samples": []})
                    hit["count"] += 1
                    if len(hit["samples"]) < 3:
                        hit["samples"].append({"file": part["file"], "name": line.get("name", ""), "text": texts[0]})
        if len(results) >= limit:
            break
    return sorted(results.values(), key=lambda r: r["count"], reverse=True)


# -- audio listing -------------------------------------------------------------


def _jacket_index(data_dir: Path, resources: Path, images: Path) -> dict:
    """Jacket stem -> path relative to data_dir, from Resource and extracted images."""

    def compute():
        found = {}
        for root in (resources, images):
            if not root.is_dir():
                continue
            pattern = "img_general_music_jacket_*" if root == resources else "**/img_general_music_jacket_*"
            for path in root.glob(pattern):
                if path.suffix.lower() not in {".png", ".webp", ".jpg"}:
                    continue
                stem = path.stem.split("_#")[0]
                # Resource copies are the originals; keep them over extracted duplicates.
                found.setdefault(stem, path.relative_to(data_dir).as_posix())
        return found

    return _cached(("jackets", str(data_dir)), compute)


def _find_jacket(jackets: dict, group: str, num: str, who: str):
    prefix = "img_general_music_jacket_"
    # Solo songs use `char-`, group songs a per-singer jacket or a shared one.
    exact = [f"char-{group}-{num}", f"{group}-{who}-{num}", f"{group}-{num}-inst", f"{group}-{num}"]
    for candidate in exact:
        if prefix + candidate in jackets:
            return jackets[prefix + candidate]
    # Not every singer's version ships its own jacket; any version of the same
    # song is closer than none.
    same_song = re.compile(rf"^{prefix}(?:char-)?{re.escape(group)}-(?:[a-z0-9]+-)?{num}(?:-inst)?$")
    return next((path for stem, path in sorted(jackets.items()) if same_song.match(stem)), None)


def _describe_audio(stem: str, jackets: dict) -> dict:
    music = _MUSIC.match(stem)
    if music:
        num, who, inst = music.group("num"), music.group("who"), bool(music.group("inst"))
        group = music.group("group")
        singer = CHARACTERS.get(who, "全员" if who == "all" else who)
        return {
            "kind": "music",
            "title": f"{group}-{num}",
            "subtitle": f"{singer}{' · 伴奏' if inst else ''}",
            "character": who if who in CHARACTERS else "",
            "jacket": _find_jacket(jackets, group, num, who),
        }
    sound = _SOUND.match(stem)
    if sound:
        kind, scene, rest = sound.group("kind"), sound.group("scene"), sound.group("rest")
        if kind == "vo":
            return {
                "kind": "voice",
                "title": rest,
                "subtitle": VOICE_SCENES.get(scene, "语音"),
                "character": character_of(rest),
                "jacket": None,
            }
        if kind == "bgm":
            return {
                "kind": "bgm",
                "title": rest,
                "subtitle": BGM_SCENES.get(scene, "BGM"),
                "character": character_of(rest),
                "jacket": None,
            }
        if kind == "se":
            return {"kind": "se", "title": rest, "subtitle": "音效", "character": "", "jacket": None}
    return {"kind": "other", "title": stem, "subtitle": "", "character": character_of(stem), "jacket": None}


def list_audio(paths) -> dict:
    """mp3 files plus one entry per CRI bank.

    A bank with both .acb and .awb keeps its audio in the .awb (the .acb holds
    the cue table and at most a short preview), so the .awb is what gets decoded.
    Banks that already have an .mp3 of the same name are left out as duplicates.
    """
    resources = paths.resources

    def compute():
        if not resources.is_dir():
            return []
        jackets = _jacket_index(paths.data_dir, resources, paths.images)
        revisions = resource_revisions(paths)
        by_stem = {}
        for path in resources.iterdir():
            suffix = path.suffix.lower()
            if suffix in {".mp3"} | CRI_SUFFIXES:
                by_stem.setdefault(path.stem, {})[suffix] = path
        tracks = []
        for stem, files in by_stem.items():
            if ".mp3" in files:
                path, bank = files[".mp3"], False
            else:
                path, bank = files.get(".awb") or files[".acb"], True
            tracks.append(
                {
                    "path": path.relative_to(paths.data_dir).as_posix(),
                    "file": path.name,
                    "bank": bank,
                    "size": path.stat().st_size,
                    "revision": max((revisions.get(f.name, 0) for f in files.values()), default=0),
                    **_describe_audio(stem, jackets),
                }
            )
        order = list(AUDIO_KINDS)
        tracks.sort(key=lambda t: (order.index(t["kind"]), t["title"], t["character"] != "", t["subtitle"]))
        return tracks

    tracks = _cached(("audio", str(resources)), compute)
    for track in tracks:
        # Cheap and changes under our feet, so never cached.
        track["converted"] = track["bank"] and _bank_done(paths, Path(track["file"]).stem)
    return {
        "tracks": tracks,
        "kinds": AUDIO_KINDS,
        "characters": CHARACTERS,
        "tools": external.status(),
    }


# -- versions ------------------------------------------------------------------

_DIFF = re.compile(r"^manifest_diff_v(?P<old>\d+)_v?(?P<new>\d+)\.json$")


def resource_revisions(paths) -> dict:
    """Resource filename -> the newest revision whose diff added or changed it.

    Built from the saved diff manifests (ours in manifests/, the old toolkit's in
    DecryptedCache/). Files that predate every diff simply have no entry.
    """

    def compute():
        diffs = []
        for folder in (paths.manifests, paths.legacy_manifests):
            if folder.is_dir():
                for path in folder.iterdir():
                    match = _DIFF.match(path.name)
                    if match:
                        diffs.append((int(match.group("new")), path))
        found = {}
        for revision, path in sorted(diffs):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for entry in manifest.get("resourceList", []):
                if entry.get("state") != "DELETE" and entry.get("name"):
                    found[entry["name"]] = revision
        return found

    return _cached(("revisions", str(paths.data_dir)), compute)


# -- CRI decoding --------------------------------------------------------------


def _bank_dir(paths, stem: str) -> Path:
    return paths.audio / stem


def _bank_done(paths, stem: str) -> bool:
    return (_bank_dir(paths, stem) / ".done").is_file()


def decode_bank(paths, filename: str) -> list:
    """Every stream in one .acb/.awb bank as .wav under data/AUDIO/<bank>/, decoded once."""
    source = _inside(paths.resources, filename)
    if source.suffix.lower() not in CRI_SUFFIXES:
        raise UmeError(f"不是 CRI 音频：{filename}")
    target = _bank_dir(paths, source.stem)
    marker = target / ".done"

    with _lock_for(str(target)):
        if not (marker.is_file() and marker.stat().st_mtime >= source.stat().st_mtime):
            vgmstream = external.require("vgmstream")
            target.mkdir(parents=True, exist_ok=True)
            for old in target.glob("*.wav"):
                old.unlink()
            # -S 0 writes every subsong; ?n names each file after its cue.
            result = subprocess.run(
                [str(vgmstream), "-S", "0", "-o", str(target / "?n.wav"), str(source)],
                capture_output=True,
                text=True,
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0 or not any(target.glob("*.wav")):
                raise UmeError(f"解码失败：{filename}", (result.stderr or result.stdout or "").strip()[-300:])
            marker.touch()

    cues = []
    for wav in sorted(target.glob("*.wav")):
        # The .acb next to an .awb contributes a short "[pre]" preview; skip it
        # unless it's all there is.
        cues.append({"name": wav.stem, "path": wav.relative_to(paths.data_dir).as_posix(), "preview": "[pre]" in wav.stem})
    full = [c for c in cues if not c["preview"]]
    return full or cues


def voice_path(paths, cue: str) -> str:
    """The decoded .wav for one voice cue, decoding its bank if needed."""
    match = _CUE.match(cue)
    if not match:
        raise UmeError(f"看不懂的语音名：{cue}")
    bank = match.group("bank")
    filename = f"{bank}.awb" if (paths.resources / f"{bank}.awb").is_file() else f"{bank}.acb"
    for item in decode_bank(paths, filename):
        if item["name"] == cue:
            return item["path"]
    raise UmeError(f"语音包里没有这一句：{cue}")


# -- video ---------------------------------------------------------------------


def _video_target(paths, stem: str) -> Path:
    return paths.video / f"{stem}.mp4"


def list_videos(paths) -> dict:
    resources = paths.resources

    def compute():
        if not resources.is_dir():
            return []
        revisions = resource_revisions(paths)
        videos = []
        for path in resources.glob("mov_*.usm"):
            group = (_VIDEO.match(path.name) or [None, "other"])[1]
            videos.append(
                {
                    "path": path.relative_to(paths.data_dir).as_posix(),
                    "file": path.name,
                    "title": path.stem.removeprefix("mov_"),
                    "group": group if group in VIDEO_GROUPS else "other",
                    "character": character_of(path.stem),
                    "size": path.stat().st_size,
                    "revision": revisions.get(path.name, 0),
                    "mtime": path.stat().st_mtime,
                }
            )
        return sorted(videos, key=lambda v: v["mtime"], reverse=True)

    videos = _cached(("videos", str(resources)), compute)
    for video in videos:
        video["converted"] = _video_target(paths, Path(video["file"]).stem).is_file()
    return {
        "videos": videos,
        "groups": VIDEO_GROUPS,
        "characters": CHARACTERS,
        "tools": external.status(),
    }


def convert_video(paths, filename: str) -> str:
    """A browser-playable .mp4 of one .usm under data/VIDEO/, converted once."""
    source = _inside(paths.resources, filename)
    if source.suffix.lower() != ".usm":
        raise UmeError(f"不是 USM 视频：{filename}")
    target = _video_target(paths, source.stem)

    with _lock_for(str(target)):
        if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
            return target.relative_to(paths.data_dir).as_posix()
        ffmpeg = external.require("ffmpeg")
        target.parent.mkdir(parents=True, exist_ok=True)

        probe = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-i", str(source)],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # About half the USMs carry H.264, which can be copied as-is. The rest
        # are MPEG-1, which no browser plays, so those get a fast x264 encode.
        is_h264 = "Video: h264" in probe.stderr
        video = ["-c:v", "copy"] if is_h264 else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
        partial = target.with_name(f"{target.stem}.part.mp4")
        result = subprocess.run(
            [
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source),
                *video,
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(partial),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # Some USMs end with a truncated packet; ffmpeg reports it but the
        # output is complete, so judge by the file rather than the exit code.
        if not partial.is_file() or partial.stat().st_size == 0:
            partial.unlink(missing_ok=True)
            raise UmeError(f"视频转换失败：{filename}", result.stderr.strip()[-300:])
        partial.replace(target)
    return target.relative_to(paths.data_dir).as_posix()


# -- batch conversion and cleanup ----------------------------------------------


def convert_many(paths, kind: str, files: list, report) -> tuple:
    """Convert several audio banks or videos in turn. Returns (done, failed names).

    report(index, total, name) is called before each file; raising from it (the
    console's cancel check) stops the batch between files.
    """
    convert = decode_bank if kind == "audio" else convert_video
    done, failed = 0, []
    for index, name in enumerate(files):
        report(index, len(files), name)
        try:
            convert(paths, name)
            done += 1
        except external.ToolMissingError:
            raise
        except UmeError as exc:
            failed.append((name, exc.message))
    report(len(files), len(files), "")
    return done, failed


def _outputs(paths, kind: str, files: list | None = None) -> list:
    """The files this module wrote, and nothing else.

    AUDIO/ and VIDEO/ may be folders the user already had (Windows ignores case,
    so an old toolkit's "video" folder full of tools *is* data/VIDEO). Only
    outputs that map back to a Resource file count: a bank folder named after an
    .acb/.awb, holding .wav files and our marker; an .mp4 named after a .usm.
    """
    resources = paths.resources
    wanted = None if files is None else {Path(name).stem for name in files}
    found = []
    if kind == "audio":
        if not paths.audio.is_dir():
            return []
        for folder in paths.audio.iterdir():
            if not folder.is_dir() or (wanted is not None and folder.name not in wanted):
                continue
            if not any((resources / f"{folder.name}{suffix}").is_file() for suffix in CRI_SUFFIXES):
                continue
            found += [f for f in folder.iterdir() if f.is_file() and (f.suffix == ".wav" or f.name == ".done")]
    else:
        if not paths.video.is_dir():
            return []
        for path in paths.video.iterdir():
            stem = path.name.removesuffix(".part.mp4").removesuffix(".mp4")
            if not path.is_file() or not path.name.endswith(".mp4"):
                continue
            if (wanted is not None and stem not in wanted) or not (resources / f"{stem}.usm").is_file():
                continue
            found.append(path)
    return found


def converted_size(paths) -> dict:
    return {kind: sum(f.stat().st_size for f in _outputs(paths, kind)) for kind in ("audio", "video")}


def clean(paths, kind: str, files: list | None = None) -> int:
    """Delete converted output for the given Resource files, or all of it. Returns bytes freed."""
    freed = 0
    folders = set()
    for path in _outputs(paths, kind, files):
        freed += path.stat().st_size
        path.unlink(missing_ok=True)
        folders.add(path.parent)
    # Bank folders go too once empty; the AUDIO/VIDEO roots never do.
    for folder in folders:
        if folder not in (paths.audio, paths.video):
            try:
                folder.rmdir()
            except OSError:
                pass  # something else lives there; leave it
    return freed
