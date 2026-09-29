"""Extraction backend dispatch."""

from pathlib import Path

from ..errors import BackendMissingError


# Bundles named img_* hold the 2D art (cards, portraits, UI). Everything else
# (mdl_, env_, eff_, ...) carries material textures, several times as many files.
IMG_PREFIX = "img_"


def run(
    backend: str,
    input_dir: Path,
    output_dir: Path,
    unity_version: str,
    cli_path: str = "",
    workers: int = 8,
    scope: str = "img",
) -> bool:
    if not input_dir.exists():
        return False
    only_img = scope == "img"

    if backend == "unitypy":
        from . import unitypy

        return unitypy.extract(input_dir, output_dir, unity_version, workers=workers, only_img=only_img)

    if backend == "assetstudio":
        from . import assetstudio

        return assetstudio.extract(input_dir, output_dir, unity_version, cli_path=cli_path, only_img=only_img)

    raise BackendMissingError(
        f"未知的抽图后端 \"{backend}\"。",
        'config.toml 的 [extract] backend 只能填 "assetstudio" 或 "unitypy"。',
    )
