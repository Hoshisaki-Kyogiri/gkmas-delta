"""Build the green (portable) package.

Produces a folder the user unzips and double-clicks - no Python install, no .NET
runtime, no pip step. The embedded interpreter is downloaded from python.org and
dependencies are installed into it as wheels only: the embeddable distribution
has no setuptools, so anything falling back to a source build would fail.

    python tools/build_green.py [--version 3.13.7] [--keep-pip]
"""

import argparse
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
EMBED_URL = "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# Files and folders that make up the shipped app.
APP_ITEMS = ("umegkmas", "umegkmas.bat", "启动.bat", "说明.txt", "README.md", "requirements.txt")
# Dropped from the bundled interpreter: build tooling the user never invokes.
PIP_LEFTOVERS = ("pip", "setuptools", "wheel", "pkg_resources")


def log(message: str) -> None:
    print(f">>> {message}", flush=True)


def fetch(url: str, target: Path) -> Path:
    if target.exists():
        log(f"已存在，跳过下载：{target.name}")
        return target
    log(f"下载 {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    log(f"  -> {target.name} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
    return target


def prepare_interpreter(version: str, dest: Path) -> Path:
    archive = fetch(EMBED_URL.format(v=version), BUILD / f"python-{version}-embed.zip")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)

    tag = "python" + "".join(version.split(".")[:2])
    pth = dest / f"{tag}._pth"
    if not pth.exists():
        raise SystemExit(f"找不到 {pth.name}，嵌入式包结构可能变了。")
    # `..` puts the distribution root (holding the umegkmas package) on sys.path;
    # `import site` is what makes site-packages searchable at all.
    pth.write_text(f"{tag}.zip\n.\n..\nLib\\site-packages\n\nimport site\n", encoding="ascii")
    log(f"已配置 {pth.name}")
    return dest / "python.exe"


def install_dependencies(python_exe: Path, extra: list) -> None:
    get_pip = fetch(GET_PIP_URL, BUILD / "get-pip.py")
    log("引导 pip...")
    subprocess.run([str(python_exe), str(get_pip), "-q", "--no-warn-script-location"], check=True)

    log("安装依赖（仅 wheel，嵌入式环境无法源码编译）...")
    subprocess.run(
        [
            str(python_exe), "-m", "pip", "install", "-q", "--no-warn-script-location",
            # Without this, a package preferring an sdist dies on missing setuptools.
            "--only-binary=:all:",
            "-r", str(ROOT / "requirements.txt"), *extra,
        ],
        check=True,
    )


def verify(python_exe: Path) -> None:
    log("验证所有模块可加载...")
    modules = [
        "requests", "Crypto.Cipher.AES", "rich", "google.protobuf", "PIL.Image",
        "UnityPy", "astc_encoder", "etcpak", "texture2ddecoder", "tomllib",
    ]
    script = (
        "import sys\n"
        f"mods = {modules!r}\n"
        "bad = []\n"
        "for m in mods:\n"
        "    try:\n"
        "        __import__(m)\n"
        "    except Exception as e:\n"
        "        bad.append(f'{m}: {e}')\n"
        "print('FAIL:' + '; '.join(bad) if bad else 'ALLOK')\n"
    )
    result = subprocess.run([str(python_exe), "-c", script], capture_output=True, text=True)
    output = (result.stdout or "").strip()
    if "ALLOK" not in output:
        raise SystemExit(f"依赖验证失败：{output}\n{result.stderr}")
    log("  全部模块加载正常")


def strip_build_tooling(python_dir: Path) -> None:
    site_packages = python_dir / "Lib" / "site-packages"
    for entry in site_packages.iterdir():
        name = entry.name.lower()
        if any(name == item or name.startswith(item + "-") for item in PIP_LEFTOVERS):
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    for cache in python_dir.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    log("已移除 pip / setuptools 等构建工具")


def copy_app(dest: Path) -> None:
    for item in APP_ITEMS:
        source = ROOT / item
        if not source.exists():
            raise SystemExit(f"缺少 {item}")
        target = dest / item
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, target)
    log(f"已复制程序文件：{', '.join(APP_ITEMS)}")


def folder_size(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024 / 1024


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="3.13.7", help="嵌入式 Python 版本")
    parser.add_argument("--keep-pip", action="store_true", help="保留 pip（便于用户自行装包）")
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()

    dist = BUILD / "umegkmas"
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)

    python_exe = prepare_interpreter(args.version, dist / "python")
    install_dependencies(python_exe, ["UnityPy"])
    verify(python_exe)
    if not args.keep_pip:
        strip_build_tooling(dist / "python")
    copy_app(dist)

    log(f"包体积：{folder_size(dist):.1f} MB")

    if not args.no_zip:
        archive = BUILD / "umegkmas-green-win64"
        if archive.with_suffix(".zip").exists():
            archive.with_suffix(".zip").unlink()
        log("打包 zip...")
        shutil.make_archive(str(archive), "zip", root_dir=dist.parent, base_dir=dist.name)
        size = archive.with_suffix(".zip").stat().st_size / 1024 / 1024
        log(f"完成：{archive.with_suffix('.zip')} ({size:.1f} MB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
