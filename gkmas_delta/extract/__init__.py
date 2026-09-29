"""Extraction backend dispatch."""

from pathlib import Path

from ..errors import BackendMissingError


def run(backend: str, input_dir: Path, output_dir: Path, unity_version: str, cli_path: str = "", workers: int = 8) -> bool:
    if not input_dir.exists():
        return False

    if backend == "unitypy":
        from . import unitypy

        return unitypy.extract(input_dir, output_dir, unity_version, workers=workers)

    if backend == "assetstudio":
        from . import assetstudio

        return assetstudio.extract(input_dir, output_dir, unity_version, cli_path=cli_path)

    raise BackendMissingError(
        f"未知的抽图后端 \"{backend}\"。",
        'config.toml 的 [extract] backend 只能填 "assetstudio" 或 "unitypy"。',
    )
