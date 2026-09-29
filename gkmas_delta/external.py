"""Third-party command-line tools: vgmstream (CRI audio) and ffmpeg (USM video).

Both are fetched from pinned URLs and checked against a pinned SHA-256 before
anything is unpacked. vgmstream is small and ships with the release zip; ffmpeg
is ~30 MB and only downloaded the first time someone opens a video.

Only the standard library is used here so tools/build.py can import this module
without the app's dependencies installed.
"""

import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .errors import UmeError
from .paths import APP_DIR

BIN_DIR = APP_DIR / "bin"
DOWNLOAD_CHUNK = 256 * 1024


@dataclass(frozen=True)
class Tool:
    name: str
    label: str
    url: str
    sha256: str
    size_mb: float
    exe: str
    # Archive members to keep: a prefix to strip and a glob inside it.
    member_prefix: str
    member_glob: str
    path_names: tuple  # what to look for on PATH outside Windows builds
    license_note: str


TOOLS = {
    "vgmstream": Tool(
        name="vgmstream",
        label="vgmstream（CRI 音频解码）",
        url="https://github.com/vgmstream/vgmstream/releases/download/r2117/vgmstream-win64.zip",
        sha256="6c4a8a3813864fefed081bbd337dbc0ad93bf88e0b92f5db98d7ab258b22dc6c",
        size_mb=4.3,
        exe="vgmstream-cli.exe",
        member_prefix="",
        member_glob="*",
        path_names=("vgmstream-cli",),
        license_note="vgmstream r2117, ISC-style license (see bin/vgmstream/COPYING)",
    ),
    "ffmpeg": Tool(
        name="ffmpeg",
        label="ffmpeg（视频转换）",
        # The imageio-ffmpeg wheel carries a single static ffmpeg 7.1 build and
        # PyPI is reachable (and mirrored) where GitHub downloads often aren't.
        url=(
            "https://files.pythonhosted.org/packages/2c/c6/"
            "fa760e12a2483469e2bf5058c5faff664acf66cadb4df2ad6205b016a73d/"
            "imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl"
        ),
        sha256="02fa47c83703c37df6bfe4896aab339013f62bf02c5ebf2dce6da56af04ffc0a",
        size_mb=29.8,
        exe="ffmpeg.exe",
        member_prefix="imageio_ffmpeg/binaries/",
        member_glob="ffmpeg-*.exe",
        path_names=("ffmpeg",),
        license_note="ffmpeg 7.1 static build from imageio-ffmpeg 0.6.0 (GPL)",
    ),
}


class ToolMissingError(UmeError):
    def __init__(self, tool: Tool):
        super().__init__(
            f"需要先下载 {tool.label}，约 {tool.size_mb:g} MB。",
            "下载一次就会保存在程序目录的 bin 文件夹里。",
        )
        self.tool = tool


def locate(name: str) -> Path | None:
    tool = TOOLS[name]
    bundled = BIN_DIR / name / tool.exe
    if bundled.is_file():
        return bundled
    for candidate in tool.path_names:
        found = shutil.which(candidate)
        if found:
            return Path(found)
    return None


def require(name: str) -> Path:
    path = locate(name)
    if path is None:
        raise ToolMissingError(TOOLS[name])
    return path


def status() -> dict:
    return {
        name: {"installed": locate(name) is not None, "label": tool.label, "size_mb": tool.size_mb}
        for name, tool in TOOLS.items()
    }


def _download(tool: Tool, target: Path, report=None) -> None:
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(tool.url, timeout=60) as response, target.open("wb") as handle:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(DOWNLOAD_CHUNK):
                handle.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if report:
                    report(done, total)
    except OSError as exc:
        raise UmeError(f"{tool.label} 下载失败：{exc}", "检查网络后重试。") from exc
    if digest.hexdigest() != tool.sha256:
        # Never unpack something that isn't the file we pinned.
        raise UmeError(f"{tool.label} 的校验值不对，已丢弃。", "可能是网络被劫持或下载不完整，重试一次。")


def install(name: str, dest_root: Path = BIN_DIR, report=None) -> Path:
    """Download, verify and unpack one tool into dest_root/<name>/. Returns the executable."""
    if sys.platform != "win32" and dest_root == BIN_DIR:
        raise UmeError(
            "自动下载只提供 Windows 版本。",
            f"请用系统的包管理器安装 {' / '.join(TOOLS[name].path_names)}。",
        )
    tool = TOOLS[name]
    dest = dest_root / name
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "download.zip"
        _download(tool, archive, report)
        staging = Path(tmp) / "unpacked"
        staging.mkdir()
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if member.endswith("/") or not member.startswith(tool.member_prefix):
                    continue
                relative = member[len(tool.member_prefix) :]
                # Top-level files only: no nested paths, so nothing can escape staging.
                if "/" in relative or not Path(relative).match(tool.member_glob):
                    continue
                with zf.open(member) as src, (staging / relative).open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        if name == "ffmpeg":
            # The wheel names the binary after its version; give it a stable name.
            (binary,) = staging.glob(tool.member_glob)
            binary.rename(staging / tool.exe)
        if not (staging / tool.exe).is_file():
            raise UmeError(f"{tool.label} 的压缩包里没找到 {tool.exe}。", "下载地址可能变了，请反馈这个问题。")
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(dest))
    return dest / tool.exe
