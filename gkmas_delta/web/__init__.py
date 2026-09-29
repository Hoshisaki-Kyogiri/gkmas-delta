"""Local web console.

A small stdlib HTTP server bound to 127.0.0.1, so the release zip gains a GUI
without a single extra dependency. The page drives the same pipeline as the CLI;
everything the pipeline reports through `ui` is mirrored to the browser over
Server-Sent Events, and the terminal window keeps showing the rich output too.

Only one job runs at a time: two pipelines writing the same data directory and
state.json would race each other.
"""

import json
import mimetypes
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__, external, media, pipeline
from ..config import load_config, read_raw, save_values
from ..errors import UmeError
from ..status import local_status, preview_from, server_status
from ..ui import human_size
from ..ui import (
    Cancelled,
    add_listener,
    check_cancel,
    console,
    detail,
    emit,
    error,
    info,
    ok,
    request_cancel,
    reset_cancel,
    step,
    warn,
)

DEFAULT_PORT = 8765
PORT_ATTEMPTS = 20
PAGE = Path(__file__).with_name("index.html")
LOGO = Path(__file__).with_name("logo.webp")
# Noto fonts vendored by tools/fetch_fonts.py; the console works offline.
FONTS = Path(__file__).with_name("fonts")
IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}
# What /data/ may serve: extracted images and browser-playable audio.
SERVABLE_SUFFIXES = IMAGE_SUFFIXES | media.AUDIO_SUFFIXES | media.VIDEO_SUFFIXES
STREAM_CHUNK = 256 * 1024
# One download at a time, however many tabs ask.
_install_lock = threading.Lock()
GALLERY_PAGE_SIZE = 100
# Page sizes the page may ask for; anything else falls back to the default.
GALLERY_PAGE_SIZES = {20, 50, 100, 200}
# Pipeline modes the page may start. None = "whatever the next sensible run is".
MODES = {"update": None, "latest": "latest", "full": "full", "baseline": "baseline", "from": "from"}

mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/css", ".css")


class EventHub:
    """Fan-out of ui events to any number of SSE clients.

    Logs are kept (bounded) so a reloaded page shows what already happened.
    Progress-like events are too chatty to keep; only the latest of each kind
    is held for new clients.
    """

    HISTORY = 2000
    TRANSIENT = ("progress", "tool")

    def __init__(self):
        self._cond = threading.Condition()
        self._seq = 0
        self._history = deque(maxlen=self.HISTORY)
        self._latest = {}

    def publish(self, event: dict) -> None:
        with self._cond:
            self._seq += 1
            event = {**event, "id": self._seq, "time": time.time()}
            if event["kind"] in self.TRANSIENT:
                self._latest[event["kind"]] = event
            else:
                self._history.append(event)
                if event["kind"] == "step":
                    # A new stage starts with no progress bar until it adds one.
                    self._latest.pop("progress", None)
            self._cond.notify_all()

    def since(self, last_id: int, timeout: float) -> list:
        with self._cond:
            if self._seq <= last_id:
                self._cond.wait(timeout)
            events = [event for event in self._history if event["id"] > last_id]
            events += [event for event in self._latest.values() if event["id"] > last_id]
            return events

    @property
    def last_id(self) -> int:
        return self._seq


class JobRunner:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._lock = threading.Lock()
        self.current = None
        self.last = None

    def snapshot(self) -> dict:
        return {"running": self.current, "last": self.last}

    def _claim(self, meta: dict) -> None:
        with self._lock:
            if self.current:
                raise UmeError("已有任务在运行。", "等它结束，或先点「取消」。")
            self.current = {**meta, "started_at": time.time()}
        reset_cancel()

    def start(self, mode_key: str, force: bool, start: int | None = None) -> None:
        if mode_key not in MODES:
            raise UmeError(f"未知的操作：{mode_key}")
        if mode_key == "from" and (start is None or start < 1):
            raise UmeError("起点版本号至少是 1。")
        self._claim({"mode": mode_key, "force": force, "start": start})
        threading.Thread(target=self._run, args=(self._update, mode_key, force, start), daemon=True).start()

    def start_convert(self, kind: str, files: list) -> None:
        # Fail before claiming the slot if the tool is missing, so the page can
        # offer the download and simply retry.
        external.require("vgmstream" if kind == "audio" else "ffmpeg")
        self._claim({"mode": "convert", "media": kind, "count": len(files)})
        threading.Thread(target=self._run, args=(self._convert, kind, files), daemon=True).start()

    def _update(self, mode_key: str, force: bool, start: int | None) -> str:
        config = load_config(self.config_path)
        code = pipeline.run(config, requested_mode=MODES[mode_key], force=force, interactive=False, start=start)
        return "ok" if code == 0 else "failed"

    def _convert(self, kind: str, files: list) -> str:
        paths = load_config(self.config_path).paths
        label = "音频" if kind == "audio" else "视频"
        step(f"转换{label}")
        info(f"开始转换 {len(files)} 个{label}文件。")

        def report(index, total, name):
            check_cancel()
            emit("progress", text=f"转换{label} ({index}/{total})", completed=index, total=total, unit="count")

        done, failed = media.convert_many(paths, kind, files, report)
        for name, reason in failed[:10]:
            detail(f"{name} — {reason}")
        if failed:
            warn(f"转换完成 {done} 个，失败 {len(failed)} 个。")
            return "failed"
        ok(f"转换完成，共 {done} 个，保存在 {paths.audio if kind == 'audio' else paths.video}")
        return "ok"

    def _run(self, work, *args) -> None:
        result = "error"
        try:
            # Inside the try: whatever fails here, `finally` must free the slot.
            emit("job", state="running", **self.current)
            result = work(*args)
        except Cancelled as exc:
            if self.current.get("mode") == "convert":
                warn("已取消，已经转换好的文件会保留。")
            else:
                warn(f"{exc.message}{exc.hint}")
            result = "cancelled"
        except UmeError as exc:
            error(exc.message)
            if exc.hint:
                warn(exc.hint)
        except Exception as exc:
            console.print_exception()
            error(f"程序出错：{exc!r}")
            emit("log", level="detail", text=traceback.format_exc(limit=6))
        finally:
            with self._lock:
                self.last = {**self.current, "result": result, "finished_at": time.time()}
                self.current = None
            emit("job", state="idle", **self.last)


def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - local folder chosen from a fixed list
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _reveal_file(path: Path) -> None:
    """Open the file's folder with the file selected, where the platform can."""
    if sys.platform == "win32":
        # explorer exits non-zero even on success, so don't wait on or check it.
        subprocess.Popen(["explorer", f"/select,{path}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def _revision_dirs(config) -> list:
    """Every revision that has extracted images, newest first."""
    paths = config.paths
    found = {}
    for source, root in (("png", paths.images), ("webp", paths.converted)):
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit():
                found.setdefault(int(child.name[1:]), []).append(source)
    return [{"revision": rev, "sources": sorted(found[rev])} for rev in sorted(found, reverse=True)]


def _gallery_dir(config, revision: int, source: str) -> Path:
    paths = config.paths
    return paths.revision_converted(revision) if source == "webp" else paths.revision_images(revision)


def _list_images(
    config, revision: int, source: str, query: str, offset: int, card: str = "", character: str = "", limit: int = 0
) -> dict:
    if limit not in GALLERY_PAGE_SIZES:
        limit = GALLERY_PAGE_SIZE
    root = _gallery_dir(config, revision, source)
    empty = {"total": 0, "items": [], "characters": [], "names": media.CHARACTERS, "cards": media.CARD_KINDS}
    if not root.is_dir():
        return empty
    # Every page, search keystroke and filter change asks again; a full
    # catalogue holds tens of thousands of files, so scan once per TTL.
    files = media._cached(
        ("gallery", str(root)),
        lambda: [
            (path, path.relative_to(root).as_posix())
            for path in sorted(root.rglob("*"))
            if path.suffix.lower() in IMAGE_SUFFIXES
        ],
    )
    query = query.lower()
    matched = []
    present = set()
    for path, relative in files:
        if query and query not in relative.lower():
            continue
        kind = media.card_kind(path.name)
        if card and kind != card:
            continue
        # The folder chain often names the character when the file doesn't.
        who = media.character_of(relative.replace("/", "_"))
        # Offer every character the other filters leave, not just the chosen one.
        if who:
            present.add(who)
        if character and who != character:
            continue
        matched.append((path, relative, kind, who))

    data_dir = config.paths.data_dir
    items = [
        {
            "path": path.relative_to(data_dir).as_posix(),
            "name": path.name,
            "group": str(Path(relative).parent.as_posix()),
            "card": kind,
            "character": who,
        }
        for path, relative, kind, who in matched[offset : offset + limit]
    ]
    return {**empty, "total": len(matched), "items": items, "characters": sorted(present)}


def _parse_range(header, size: int):
    """(start, end) for a single `bytes=` range, None without one, "invalid" if unsatisfiable."""
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[len("bytes=") :].strip().partition("-")
    try:
        if first:
            start = int(first)
            end = int(last) if last else size - 1
        else:
            # `bytes=-N` asks for the final N bytes.
            start, end = max(size - int(last), 0), size - 1
    except ValueError:
        return None
    if start >= size or start > end:
        return "invalid"
    return start, min(end, size - 1)


def make_handler(config_path: Path, hub: EventHub, jobs: JobRunner):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"gkmas-delta/{__version__}"

        def handle(self):
            # Browsers drop idle keep-alive connections all the time; that's not an error.
            try:
                super().handle()
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass

        def log_message(self, *args):
            # Request lines would drown the pipeline's own output in the terminal.
            pass

        # -- plumbing ---------------------------------------------------------

        def _host_ok(self) -> bool:
            # Rejecting foreign Host headers blocks DNS-rebinding pages from
            # reaching this server through a hostname they control.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in {"127.0.0.1", "localhost", "::1"}

        def _send_json(self, payload, status=HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, exc: UmeError, status=HTTPStatus.BAD_REQUEST) -> None:
            payload = {"error": exc.message, "hint": exc.hint}
            if isinstance(exc, external.ToolMissingError):
                # The page offers to download the tool and then retries.
                tool = exc.tool
                payload["tool"] = {"name": tool.name, "label": tool.label, "size_mb": tool.size_mb}
                status = HTTPStatus.CONFLICT
            self._send_json(payload, status)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise UmeError("请求内容不是有效的 JSON。") from exc

        def _config(self):
            return load_config(config_path)

        # -- routing ----------------------------------------------------------

        def do_GET(self):
            if not self._host_ok():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            url = urlparse(self.path)
            query = parse_qs(url.query)
            try:
                if url.path in ("/", "/index.html"):
                    self._serve_file(PAGE, cache=False)
                elif url.path == "/logo.webp":
                    self._serve_file(LOGO, max_age=86400)
                elif url.path == "/api/ping":
                    self._send_json({"app": "gkmas-delta", "version": __version__})
                elif url.path == "/api/state":
                    self._send_json({"local": local_status(self._config()), "job": jobs.snapshot()})
                elif url.path == "/api/server":
                    self._send_json(server_status(self._config()))
                elif url.path == "/api/config":
                    self._send_json({"values": read_raw(config_path), "path": str(config_path)})
                elif url.path == "/api/preview":
                    start = int(query.get("from", ["0"])[0])
                    if start < 1:
                        raise UmeError("起点版本号至少是 1。")
                    self._send_json(preview_from(self._config(), start))
                elif url.path == "/api/gallery":
                    self._send_json({"revisions": _revision_dirs(self._config())})
                elif url.path == "/api/images":
                    self._send_json(
                        _list_images(
                            self._config(),
                            int(query.get("revision", ["0"])[0]),
                            query.get("source", ["png"])[0],
                            query.get("q", [""])[0],
                            max(0, int(query.get("offset", ["0"])[0])),
                            query.get("card", [""])[0],
                            query.get("character", [""])[0],
                            int(query.get("limit", ["0"])[0]),
                        )
                    )
                elif url.path == "/api/audio":
                    paths = self._config().paths
                    self._send_json(media.list_audio(paths))
                elif url.path == "/api/stories":
                    paths = self._config().paths
                    base = paths.resources.relative_to(paths.data_dir).as_posix()
                    self._send_json({**media.list_stories(paths), "base": base})
                elif url.path == "/api/story":
                    try:
                        lines = media.read_story(self._config().paths.resources, query.get("file", [""])[0])
                    except (OSError, FileNotFoundError):
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._send_json({"lines": lines})
                elif url.path == "/api/videos":
                    paths = self._config().paths
                    self._send_json(media.list_videos(paths))
                elif url.path == "/api/converted":
                    self._send_json(media.converted_size(self._config().paths))
                elif url.path == "/api/tools":
                    self._send_json(external.status())
                elif url.path == "/api/story-search":
                    results = media.search_stories(self._config().paths, query.get("q", [""])[0])
                    self._send_json({"results": results})
                elif url.path == "/api/events":
                    self._stream_events()
                elif url.path.startswith("/fonts/"):
                    self._serve_font(unquote(url.path[len("/fonts/") :]))
                elif url.path.startswith("/data/"):
                    self._serve_data(unquote(url.path[len("/data/") :]))
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except UmeError as exc:
                self._send_error(exc)
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self):
            # A custom header can't be set cross-origin without a CORS preflight,
            # which this server never approves - so other sites can't drive it.
            if not self._host_ok() or self.headers.get("X-Gkmas-Delta") != "1":
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            url = urlparse(self.path)
            try:
                body = self._read_json()
                if url.path == "/api/run":
                    start = body.get("start")
                    if start is not None and not isinstance(start, int):
                        raise UmeError("起点版本号必须是整数。")
                    jobs.start(str(body.get("mode", "update")), bool(body.get("force", False)), start)
                    self._send_json(jobs.snapshot())
                elif url.path == "/api/cancel":
                    if jobs.current:
                        request_cancel()
                        warn("正在取消，等当前文件处理完...")
                    self._send_json(jobs.snapshot())
                elif url.path == "/api/config":
                    config = save_values(body.get("values", {}), config_path)
                    emit("log", level="ok", text="配置已保存。")
                    self._send_json({"values": read_raw(config_path), "data_dir": str(config.paths.data_dir)})
                elif url.path == "/api/open":
                    self._open(body)
                    self._send_json({"ok": True})
                elif url.path == "/api/decode":
                    paths = self._config().paths
                    cues = media.decode_bank(paths, str(body.get("file", "")))
                    self._send_json({"cues": cues})
                elif url.path == "/api/voice":
                    paths = self._config().paths
                    path = media.voice_path(paths, str(body.get("cue", "")))
                    self._send_json({"path": path})
                elif url.path == "/api/video":
                    paths = self._config().paths
                    path = media.convert_video(paths, str(body.get("file", "")))
                    self._send_json({"path": path})
                elif url.path == "/api/convert":
                    kind, files = self._media_request(body)
                    if not files:
                        raise UmeError("没有选中任何文件。")
                    jobs.start_convert(kind, files)
                    self._send_json(jobs.snapshot())
                elif url.path == "/api/clean":
                    kind, files = self._media_request(body)
                    if jobs.current:
                        raise UmeError("有任务在运行，等它结束再清理。")
                    paths = self._config().paths
                    freed = media.clean(paths, kind, files if body.get("files") is not None else None)
                    info(f"已清理 {human_size(freed)} 转换文件。")
                    self._send_json({"freed": freed, **media.converted_size(paths)})
                elif url.path == "/api/tools/install":
                    self._install_tool(str(body.get("name", "")))
                    self._send_json(external.status())
                elif url.path == "/api/reveal":
                    self._reveal(str(body.get("path", "")))
                    self._send_json({"ok": True})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except UmeError as exc:
                self._send_error(exc)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        # -- handlers ---------------------------------------------------------

        def _open(self, body: dict) -> None:
            config = self._config()
            target = body.get("target")
            if target == "data":
                _open_folder(config.paths.data_dir)
            elif target == "config":
                _open_folder(config_path.parent)
            elif target in ("audio", "video"):
                _open_folder(config.paths.audio if target == "audio" else config.paths.video)
            elif target == "images":
                revision = int(body.get("revision") or 0)
                source = body.get("source", "png")
                _open_folder(_gallery_dir(config, revision, source) if revision else config.paths.images)
            else:
                raise UmeError(f"未知的目录：{target}")

        def _media_request(self, body: dict) -> tuple:
            kind = body.get("kind")
            if kind not in ("audio", "video"):
                raise UmeError(f"未知的类型：{kind}")
            files = body.get("files") or []
            if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
                raise UmeError("文件列表格式不对。")
            return kind, files

        def _install_tool(self, name: str) -> None:
            if name not in external.TOOLS:
                raise UmeError(f"未知的工具：{name}")
            tool = external.TOOLS[name]
            info(f"开始下载 {tool.label}（约 {tool.size_mb:g} MB）...")

            def report(done, total):
                emit("tool", name=name, completed=done, total=total)

            with _install_lock:
                if external.locate(name) is None:
                    external.install(name, report=report)
            ok(f"{tool.label} 已就绪。")

        def _reveal(self, relative: str) -> None:
            root = self._config().paths.data_dir.resolve()
            target = (root / relative).resolve()
            # Paths come from the page, so only files that really sit in the data dir.
            if not relative or not target.is_relative_to(root) or not target.is_file():
                raise UmeError("找不到这个文件。", "它可能已经被移动或删除了。")
            _reveal_file(target)

        def _serve_file(self, path: Path, cache: bool = True, max_age: int = 3600) -> None:
            try:
                size = path.stat().st_size
                handle = path.open("rb")
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if content_type.startswith("text/"):
                content_type += "; charset=utf-8"

            # Audio elements seek with Range requests; without 206 answers the
            # browser can only play from the start.
            start, end = 0, size - 1
            ranged = _parse_range(self.headers.get("Range"), size)
            if ranged == "invalid":
                handle.close()
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            if ranged:
                start, end = ranged

            with handle:
                self.send_response(HTTPStatus.PARTIAL_CONTENT if ranged else HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                if ranged:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Cache-Control", f"max-age={max_age}" if cache else "no-store")
                self.end_headers()
                handle.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = handle.read(min(STREAM_CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def _serve_font(self, relative: str) -> None:
            root = FONTS.resolve()
            target = (root / relative).resolve()
            if not target.is_relative_to(root) or target.suffix not in (".woff2", ".css") or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            # fonts.css changes when a family is added; the .woff2 slices it points at don't.
            if target.suffix == ".css":
                self._serve_file(target, cache=False)
            else:
                self._serve_file(target, max_age=31536000)

        def _serve_data(self, relative: str) -> None:
            root = self._config().paths.data_dir.resolve()
            target = (root / relative).resolve()
            # Only media files inside the data directory, never anything above it.
            if not target.is_relative_to(root) or target.suffix.lower() not in SERVABLE_SUFFIXES:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            self._serve_file(target)

        def _stream_events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            # EventSource resends the last id on reconnect, so a dropped
            # connection resumes instead of replaying the whole log.
            last_id = int(self.headers.get("Last-Event-ID") or 0)
            if last_id > hub.last_id:
                last_id = 0  # the server restarted; the page's ids are stale
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            while True:
                events = hub.since(last_id, timeout=15)
                if not events:
                    self.wfile.write(b": keepalive\n\n")
                for event in events:
                    last_id = max(last_id, event["id"])
                    payload = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"id: {event['id']}\ndata: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # SO_REUSEADDR on Windows lets a second process bind a port that is already
    # taken, which would split the console across two servers and two pipelines.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _existing_console(port: int) -> bool:
    """True when our own console already answers on this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as response:
            return json.load(response).get("app") == "gkmas-delta"
    except Exception:
        return False


def _bind(handler, port: int | None):
    candidates = [port] if port else range(DEFAULT_PORT, DEFAULT_PORT + PORT_ATTEMPTS)
    for candidate in candidates:
        try:
            return _Server(("127.0.0.1", candidate), handler)
        except OSError:
            if _existing_console(candidate):
                return candidate
    raise UmeError(
        "找不到可用的端口来启动网页控制台。",
        "用 --port 指定一个没被占用的端口，例如 --port 9000。",
    )


def serve(config_path: Path, port: int | None = None, open_browser: bool = True) -> int:
    # Fail early on a broken config.toml rather than serving a page that can't load.
    load_config(config_path)

    hub = EventHub()
    jobs = JobRunner(config_path)
    add_listener(hub.publish)

    server = _bind(make_handler(config_path, hub, jobs), port)
    if isinstance(server, int):
        # A second double-click just brings the running console to the front;
        # two pipelines on one data directory would corrupt each other's state.
        url = f"http://127.0.0.1:{server}/"
        console.print(f"[bold green]>>>[/bold green] 控制台已经在运行：{url}")
        if open_browser:
            webbrowser.open(url)
        return 0

    url = f"http://127.0.0.1:{server.server_address[1]}/"
    console.print()
    console.print(f"[bold green]>>>[/bold green] 网页控制台已启动：[bold underline]{url}[/bold underline]")
    console.print("    浏览器没自动打开的话，把上面的地址复制到浏览器里。")
    console.print("    [dim]关闭这个窗口 = 退出程序。[/dim]")
    console.print()
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if jobs.current:
            request_cancel()
        console.print()
        warn("控制台已关闭。")
    finally:
        server.server_close()
    return 0
