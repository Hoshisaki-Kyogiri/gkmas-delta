"""Texture extraction via AssetStudioModCLI.

Known-good backend, but framework-dependent: the shipped build needs the .NET 9
runtime on the machine. That's the main reason a pure-Python backend exists
alongside it.
"""

import subprocess
from pathlib import Path

from ..errors import BackendMissingError
from ..paths import APP_DIR
from ..ui import info, warn

SEARCH_PATHS = (
    Path("AssetStudioModCLI") / "AssetStudioModCLI.exe",
    Path("tools") / "AssetStudioModCLI" / "AssetStudioModCLI.exe",
    Path("AssetStudioModCLI_net9_win64") / "AssetStudioModCLI.exe",
)


def locate(explicit: str = "") -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path
        raise BackendMissingError(
            f"config.toml 里指定的 AssetStudio 路径不存在：{path}",
            "改成正确的 AssetStudioModCLI.exe 路径，或把 backend 改成 \"unitypy\"。",
        )

    for candidate in SEARCH_PATHS:
        path = APP_DIR / candidate
        if path.is_file():
            return path

    raise BackendMissingError(
        "找不到 AssetStudioModCLI.exe。",
        "把它放到程序目录下的 AssetStudioModCLI 文件夹里，"
        "或者把 config.toml 的 [extract] backend 改成 \"unitypy\"（不需要额外程序）。",
    )


def extract(input_dir: Path, output_dir: Path, unity_version: str, cli_path: str = "") -> bool:
    exe = locate(cli_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [
        str(exe),
        str(input_dir),
        "-o",
        str(output_dir),
        "-t",
        "tex2d",
        "--image-format",
        "png",
        "--unity-version",
        unity_version,
        "-g",
        "container",
    ]

    info(f"调用 AssetStudio 抽取贴图：{input_dir} -> {output_dir}")
    try:
        process = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise BackendMissingError(
            "AssetStudioModCLI 无法启动，可能缺少 .NET 9 运行时。",
            "安装 .NET 9 Desktop Runtime，或把 config.toml 的 backend 改成 \"unitypy\"。",
        ) from exc
    except subprocess.CalledProcessError as exc:
        warn(f"AssetStudio 退出码 {exc.returncode}。")
        if exc.stdout:
            warn(exc.stdout[-2000:])
        if exc.stderr:
            warn(exc.stderr[-2000:])
        return False

    # The CLI prints one line per exported asset; keep only the summary lines.
    for line in (process.stdout or "").splitlines():
        line = line.strip()
        if line and not line.startswith(("Exported [", "Loading ", "Preparing")):
            info(line)
    return True
