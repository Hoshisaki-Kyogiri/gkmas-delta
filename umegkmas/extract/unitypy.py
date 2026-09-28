"""Texture extraction via UnityPy.

Pure Python, so it needs no .NET runtime and works off a plain pip install.
Kept behind a config switch until the A/B check against AssetStudio passes.

Output layout mirrors AssetStudio's `-g container`: each image goes under the
directory part of its container path, falling back to the bundle's own folder
name when a container is missing.
"""

import os
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.progress import BarColumn, SpinnerColumn, TaskProgressColumn, TextColumn, TimeRemainingColumn

from ..errors import BackendMissingError
from ..ui import Cancelled, Progress, console, detail, info, warn

# Windows reserved characters plus the ones a container path legitimately uses.
_UNSAFE = '<>:"|?*\\/'


def _require_unitypy():
    try:
        import UnityPy  # noqa: F401
    except ImportError as exc:
        raise BackendMissingError(
            "没有安装 UnityPy。",
            "运行 pip install UnityPy，或把 config.toml 的 backend 改回 \"assetstudio\"。",
        ) from exc
    return UnityPy


def _safe_name(name: str) -> str:
    cleaned = "".join("_" if ch in _UNSAFE else ch for ch in name).strip().strip(".")
    return cleaned or "unnamed"


def _container_dir(container: str) -> str:
    """assets/.../foo.png -> the directory chain, matching AssetStudio grouping."""
    if not container:
        return ""
    parts = [p for p in container.replace("\\", "/").split("/")[:-1] if p]
    return "/".join(_safe_name(p) for p in parts)


def _claim_path(base: Path) -> Path:
    """Reserve an unused filename, appending _#N on collisions like AssetStudio.

    The claim is made by creating the file with O_EXCL rather than by testing
    exists(), because bundles are extracted concurrently and two threads hitting
    the same texture name would otherwise both pass the check and one would
    silently overwrite the other.
    """
    for index in range(0, 10000):
        candidate = base if index == 0 else base.with_name(f"{base.stem}_#{index}{base.suffix}")
        try:
            os.close(os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError(f"无法为 {base.name} 找到可用文件名")


def _extract_bundle(bundle_path: Path, output_dir: Path, unity_version: str) -> tuple[int, str]:
    import UnityPy

    written = 0
    try:
        env = UnityPy.load(str(bundle_path))
        for obj in env.objects:
            if obj.type.name not in ("Texture2D", "Sprite"):
                continue
            try:
                data = obj.read()
                image = data.image
                if image is None:
                    continue
                name = _safe_name(getattr(data, "m_Name", "") or bundle_path.stem)
                sub_dir = _container_dir(getattr(obj, "container", "") or "")
                target_dir = output_dir / sub_dir if sub_dir else output_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                image.save(_claim_path(target_dir / f"{name}.png"))
                written += 1
            except Exception:
                # One bad object must not abort a whole bundle.
                continue
    except Exception as exc:
        return written, f"{bundle_path.name}: {exc}"
    return written, ""


def extract(input_dir: Path, output_dir: Path, unity_version: str, workers: int = 8) -> bool:
    UnityPy = _require_unitypy()
    # These bundles carry no version string, so the fallback is not optional -
    # and it must be set globally before load(), not on the env afterwards.
    UnityPy.config.FALLBACK_UNITY_VERSION = unity_version
    # Every bundle then warns that it fell back, which is the expected path here.
    warnings.filterwarnings("ignore", category=UnityPy.exceptions.UnityVersionFallbackWarning)
    output_dir.mkdir(parents=True, exist_ok=True)

    bundles = sorted(input_dir.rglob("*.unity3d"))
    if not bundles:
        warn(f"{input_dir} 下没有找到 .unity3d 文件。")
        return False

    info(f"UnityPy 抽取贴图：{len(bundles)} 个资源包 -> {output_dir}")
    total_images = 0
    failures = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("[cyan]抽取贴图...", total=len(bundles))
        executor = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {
                executor.submit(_extract_bundle, bundle, output_dir, unity_version): bundle
                for bundle in bundles
            }
            for future in as_completed(futures):
                written, error = future.result()
                total_images += written
                if error:
                    failures.append(error)
                progress.update(task_id, advance=1)
        except Cancelled:
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        executor.shutdown(wait=True)

    if failures:
        warn(f"{len(failures)} 个资源包抽取失败，例如：")
        for line in failures[:5]:
            detail(line)
    info(f"共抽出 {total_images} 张图片。")
    return total_images > 0
