"""PNG -> lossless WebP conversion for the two atlas sizes that ship squashed.

The game stores these portraits at a compressed aspect ratio; resizing to the
paired target restores the intended proportions. Anything else is left alone.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

from .ui import Cancelled, check_cancel, detail, emit, info, warn

ALLOWED_SIZES = {
    (1024, 2048): (1152, 2048),
    (2048, 1024): (2048, 1152),
}
# Lossless WebP "method" is compression effort, not quality: decoded pixels are
# identical at any method. These are viewed locally, so trade size for speed.
WEBP_METHOD = 0


def _convert_one(path: Path, input_dir: Path, output_dir: Path) -> str:
    try:
        with Image.open(path) as image:
            if image.size not in ALLOWED_SIZES:
                return "skipped"
            resized = image.resize(ALLOWED_SIZES[image.size], resample=Image.LANCZOS)

        # Preserve the source's sub-directory layout so grouped output stays grouped.
        relative = path.relative_to(input_dir).parent
        target_dir = output_dir / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        resized.save(target_dir / f"{path.stem}.webp", format="webp", lossless=True, method=WEBP_METHOD)
        return "processed"
    except Exception as exc:
        return f"failed:{exc}"


def convert(input_dir: Path, output_dir: Path, workers: int | None = None) -> tuple[int, int]:
    if not input_dir.exists():
        warn(f"找不到图片目录 {input_dir}，跳过转换。")
        return 0, 0

    files = list(input_dir.rglob("*.png"))
    if not files:
        info("没有找到需要转换的 PNG。")
        return 0, 0

    output_dir.mkdir(parents=True, exist_ok=True)
    workers = workers or os.cpu_count() or 4
    info(f"扫描 {len(files)} 张 PNG，{workers} 线程转换 webp...")

    processed = skipped = failed = 0
    done = 0
    lock = threading.Lock()

    # libwebp releases the GIL while encoding, so threads scale near-linearly
    # without a process pool's spawn cost.
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {executor.submit(_convert_one, path, input_dir, output_dir): path for path in files}
        for future in as_completed(futures):
            check_cancel()
            result = future.result()
            with lock:
                done += 1
            if result == "processed":
                processed += 1
            elif result == "skipped":
                skipped += 1
            else:
                failed += 1
                if failed <= 5:
                    detail(f"{futures[future].name} {result}")
            if done % 50 == 0 or done == len(files):
                emit("progress", text="转换 webp", completed=done, total=len(files), unit="count")
    except Cancelled:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    executor.shutdown(wait=True)

    info(f"转换完成：{processed} 张，跳过 {skipped} 张" + (f"，失败 {failed} 张" if failed else "。"))
    return processed, skipped
