"""config.toml loading, with a commented default written on first run."""

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError
from .paths import APP_DIR, CONFIG_PATH, DataPaths

DEFAULT_CONFIG_TEXT = """\
# ============================================================
#  gkmas-delta 配置文件
#  改完保存即可，不需要重装。不确定的项保持原样。
# ============================================================

[paths]
# 数据存放位置。留空 = 程序目录下的 data/
# 全量下载需要 15 GB 以上，C 盘不够就填别的盘，例如 "D:/gkmas-data"
data_dir = ""

[update]
# 首次运行且没有历史记录时怎么办：
#   "ask"      问我（默认）
#   "latest"   下载最新一个版本的更新内容（通常几十到几百 MB）
#   "full"     下载整个游戏资源（60 GB 以上，很慢）
#   "baseline" 只记下当前版本号，什么都不下，从下次更新开始
first_run = "ask"

[download]
assets = true        # 下载 assetbundle（图片/模型/特效等）
resources = true     # 下载 resource（音频/文本等）
workers = 16         # 同时下载的连接数。网不好就调小
verify_md5 = true    # 校验已存在文件的 md5，避免更新被漏掉

[process]
deobfuscate = true       # 解混淆 assetbundle
extract_images = true    # 抽取贴图为 PNG
convert_webp = true      # 把指定尺寸的 PNG 转成 webp
keep_base_copy = false   # 额外写一份汇总副本到 base/，会让磁盘占用翻倍

[extract]
# 抽图后端：
#   "unitypy"     纯 Python，无需额外安装（默认）
#   "assetstudio" 调用 AssetStudioModCLI.exe，需要机器上装有 .NET 9 运行时
backend = "unitypy"
# AssetStudioModCLI.exe 的路径。留空 = 自动在程序目录下查找
assetstudio_path = ""

[advanced]
# 游戏大版本更新后，如果提示"清单获取失败"，通常改这两个就能修好
app_version = "205100"
unity_version = "6000.0.67f1"
"""


@dataclass
class Config:
    data_dir: Path
    first_run: str = "ask"
    download_assets: bool = True
    download_resources: bool = True
    workers: int = 16
    verify_md5: bool = True
    deobfuscate: bool = True
    extract_images: bool = True
    convert_webp: bool = True
    keep_base_copy: bool = False
    backend: str = "unitypy"
    assetstudio_path: str = ""
    app_version: str = "205100"
    unity_version: str = "6000.0.67f1"
    paths: DataPaths = field(init=False)

    def __post_init__(self):
        self.paths = DataPaths(self.data_dir)


def ensure_config_file(path: Path = CONFIG_PATH) -> bool:
    """Write the default config if absent. Returns True when newly created."""
    if path.exists():
        return False
    path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return True


def load_config(path: Path = CONFIG_PATH) -> Config:
    ensure_config_file(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"config.toml 格式有误：{exc}",
            "删掉 config.toml 再运行一次，程序会重新生成一份默认配置。",
        ) from exc

    paths_section = raw.get("paths", {})
    update = raw.get("update", {})
    download = raw.get("download", {})
    process = raw.get("process", {})
    extract = raw.get("extract", {})
    advanced = raw.get("advanced", {})

    data_dir_text = str(paths_section.get("data_dir", "") or "").strip()
    data_dir = Path(data_dir_text).expanduser() if data_dir_text else APP_DIR / "data"

    first_run = str(update.get("first_run", "ask")).lower()
    if first_run not in {"ask", "latest", "full", "baseline"}:
        raise ConfigError(
            f"config.toml 里 first_run = \"{first_run}\" 不是有效值。",
            '只能填 "ask"、"latest"、"full" 或 "baseline"。',
        )

    backend = str(extract.get("backend", "unitypy")).lower()
    if backend not in {"assetstudio", "unitypy"}:
        raise ConfigError(
            f"config.toml 里 backend = \"{backend}\" 不是有效值。",
            '只能填 "assetstudio" 或 "unitypy"。',
        )

    workers = int(download.get("workers", 16))
    if workers < 1:
        raise ConfigError("config.toml 里 workers 至少要是 1。", "建议填 8 到 32 之间。")

    return Config(
        data_dir=data_dir.resolve(),
        first_run=first_run,
        download_assets=bool(download.get("assets", True)),
        download_resources=bool(download.get("resources", True)),
        workers=workers,
        verify_md5=bool(download.get("verify_md5", True)),
        deobfuscate=bool(process.get("deobfuscate", True)),
        extract_images=bool(process.get("extract_images", True)),
        convert_webp=bool(process.get("convert_webp", True)),
        keep_base_copy=bool(process.get("keep_base_copy", False)),
        backend=backend,
        assetstudio_path=str(extract.get("assetstudio_path", "") or "").strip(),
        app_version=str(advanced.get("app_version", "205100")),
        unity_version=str(advanced.get("unity_version", "6000.0.67f1")),
    )


# Settings the web console may edit: (section, key) -> Python type. Anything not
# listed stays hand-edit only.
EDITABLE_FIELDS = {
    ("paths", "data_dir"): str,
    ("update", "first_run"): str,
    ("download", "assets"): bool,
    ("download", "resources"): bool,
    ("download", "workers"): int,
    ("download", "verify_md5"): bool,
    ("process", "deobfuscate"): bool,
    ("process", "extract_images"): bool,
    ("process", "convert_webp"): bool,
    ("process", "keep_base_copy"): bool,
    ("extract", "backend"): str,
    ("extract", "assetstudio_path"): str,
    ("advanced", "app_version"): str,
    ("advanced", "unity_version"): str,
}


def read_raw(path: Path = CONFIG_PATH) -> dict:
    """The editable settings as written in the file, defaults filled in."""
    defaults = tomllib.loads(DEFAULT_CONFIG_TEXT)
    try:
        current = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        current = {}
    values = {}
    for section, key in EDITABLE_FIELDS:
        values.setdefault(section, {})[key] = current.get(section, {}).get(key, defaults[section][key])
    return values


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    # A JSON string is a valid TOML basic string for anything we store here.
    return json.dumps(str(value), ensure_ascii=False)


_ASSIGNMENT = re.compile(r'^(\s*(?P<key>[A-Za-z0-9_]+)\s*=\s*)("(?:[^"\\]|\\.)*"|[^\s#]+)(.*)$')
_SECTION = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*(#.*)?$")


def save_values(updates: dict, path: Path = CONFIG_PATH) -> Config:
    """Write {section: {key: value}} into config.toml, keeping every comment.

    Only the value token on each matching line is replaced, so the user's own
    notes and layout survive. The result is validated before it replaces the
    file; an invalid edit raises ConfigError and leaves the file untouched.
    """
    pending = {}
    for section, keys in updates.items():
        for key, value in keys.items():
            kind = EDITABLE_FIELDS.get((section, key))
            if kind is None:
                raise ConfigError(f"不能修改的配置项：[{section}] {key}")
            try:
                pending[(section, key)] = kind(value) if kind is not bool else bool(value)
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"[{section}] {key} 的值无效：{value!r}") from exc

    ensure_config_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    section = None
    for index, line in enumerate(lines):
        header = _SECTION.match(line)
        if header:
            section = header.group("name").strip()
            continue
        match = _ASSIGNMENT.match(line)
        if match and (section, match.group("key")) in pending:
            value = pending.pop((section, match.group("key")))
            lines[index] = f"{match.group(1)}{_toml_value(value)}{match.group(4)}"

    # Keys missing from a hand-trimmed file go at the end of their section.
    for (section, key), value in pending.items():
        header_index = next(
            (i for i, line in enumerate(lines) if (m := _SECTION.match(line)) and m.group("name").strip() == section),
            None,
        )
        if header_index is None:
            lines += ["", f"[{section}]", f"{key} = {_toml_value(value)}"]
            continue
        insert_at = header_index + 1
        while insert_at < len(lines) and not _SECTION.match(lines[insert_at]):
            insert_at += 1
        while insert_at > header_index + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        lines.insert(insert_at, f"{key} = {_toml_value(value)}")

    text = "\n".join(lines) + "\n"
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    try:
        config = load_config(tmp)
    except ConfigError:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)
    return config
