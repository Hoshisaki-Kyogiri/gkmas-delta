"""A/B harness: AssetStudioModCLI vs UnityPy.

Compares coverage, pixel content and wall time on the same input directory so
the extraction backend can be switched on evidence rather than hope.

    python tools/ab_extract.py <unobfuscated_dir> [--out <workdir>]

Pixel hashes are used instead of file hashes because the two encoders write
different PNG bytes for identical pixels.
"""

import argparse
import collections
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gkmas_delta.extract import assetstudio, unitypy  # noqa: E402
from gkmas_delta.ui import console, info, ok, warn  # noqa: E402


def index_images(root: Path) -> dict:
    """{stem: (width, height, pixel_md5, path)} - keyed by stem so grouping
    differences between the two backends don't count as mismatches."""
    from PIL import Image

    index = {}
    for path in sorted(root.rglob("*.png")):
        try:
            with Image.open(path) as image:
                image = image.convert("RGBA")
                digest = hashlib.md5(image.tobytes()).hexdigest()
                index[path.stem] = (image.width, image.height, digest, path)
        except Exception as exc:
            warn(f"读取失败 {path.name}: {exc}")
    return index


DEDUP_SUFFIX = re.compile(r"_#\d+$")


def group_by_base(index: dict) -> dict:
    """Collapse backend-specific dedup suffixes so the same texture lines up."""
    groups = collections.defaultdict(list)
    for stem, entry in index.items():
        groups[DEDUP_SUFFIX.sub("", stem)].append(entry)
    return groups


def max_channel_diff(path_a: Path, path_b: Path) -> int:
    """Worst per-channel delta. Block-compression decoders legitimately differ by
    1, so only a larger delta means the two backends really disagree."""
    from PIL import Image, ImageChops

    with Image.open(path_a) as image_a, Image.open(path_b) as image_b:
        diff = ImageChops.difference(image_a.convert("RGBA"), image_b.convert("RGBA"))
        return max(high for _, high in diff.getextrema())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="解混淆后的 .unity3d 目录")
    parser.add_argument("--out", type=Path, default=Path("ab_out"))
    parser.add_argument("--unity-version", default="6000.0.67f1")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-assetstudio", action="store_true")
    parser.add_argument("--compare-only", action="store_true", help="不重新抽取，只比对已有产出")
    parser.add_argument("--tolerance", type=int, default=1, help="可接受的最大通道差，默认 1")
    args = parser.parse_args()

    if not args.input.exists():
        warn(f"输入目录不存在：{args.input}")
        return 1

    as_dir = args.out / "assetstudio"
    up_dir = args.out / "unitypy"
    timings = {}

    if not args.skip_assetstudio and not args.compare_only:
        info("跑 AssetStudio...")
        start = time.perf_counter()
        assetstudio.extract(args.input, as_dir, args.unity_version)
        timings["assetstudio"] = time.perf_counter() - start

    if not args.compare_only:
        info("跑 UnityPy...")
        start = time.perf_counter()
        unitypy.extract(args.input, up_dir, args.unity_version, workers=args.workers)
        timings["unitypy"] = time.perf_counter() - start

    info("比对结果...")
    a = index_images(as_dir) if as_dir.exists() else {}
    b = index_images(up_dir)

    # The two backends disambiguate duplicate names differently - AssetStudio
    # appends the Unity pathID (_#20035), UnityPy a running counter (_#1) - so
    # compare by base name and count, not by the decorated stem.
    group_a = group_by_base(a)
    group_b = group_by_base(b)

    only_a = sorted(set(group_a) - set(group_b))
    only_b = sorted(set(group_b) - set(group_a))
    shared = sorted(set(group_a) & set(group_b))

    count_mismatch = [
        (base, len(group_a[base]), len(group_b[base]))
        for base in shared
        if len(group_a[base]) != len(group_b[base])
    ]

    size_mismatch, rounding, real, ambiguous = [], [], [], 0
    for base in shared:
        items_a, items_b = group_a[base], group_b[base]
        if len(items_a) != 1 or len(items_b) != 1:
            # Duplicated names can't be paired reliably; coverage is checked by count.
            ambiguous += 1
            continue
        entry_a, entry_b = items_a[0], items_b[0]
        if entry_a[:2] != entry_b[:2]:
            size_mismatch.append(base)
            continue
        if entry_a[2] == entry_b[2]:
            continue
        try:
            delta = max_channel_diff(entry_a[3], entry_b[3])
        except Exception as exc:
            real.append((base, f"比对失败: {exc}"))
            continue
        (rounding if delta <= args.tolerance else real).append((base, delta))

    identical = len(shared) - ambiguous - len(size_mismatch) - len(rounding) - len(real)

    console.print()
    console.rule("[bold]A/B 结果")
    console.print(f"  AssetStudio 产出： {len(a)} 张 / {len(group_a)} 个名字   耗时 {timings.get('assetstudio', 0):.1f}s")
    console.print(f"  UnityPy 产出：     {len(b)} 张 / {len(group_b)} 个名字   耗时 {timings.get('unitypy', 0):.1f}s")
    console.print(f"  逐位一致：         {identical}")
    console.print(f"  [green]仅舍入差(≤{args.tolerance})：   {len(rounding)}（视觉一致）[/green]")
    console.print(f"  [dim]同名多张无法配对： {ambiguous}（只核对张数）[/dim]")
    console.print(f"  [yellow]仅 AssetStudio 有：{len(only_a)}[/yellow]")
    console.print(f"  [dim]仅 UnityPy 有：    {len(only_b)}（多抽出的）[/dim]")
    console.print(f"  [red]张数不一致：       {len(count_mismatch)}[/red]")
    console.print(f"  [red]尺寸不一致：       {len(size_mismatch)}[/red]")
    console.print(f"  [red]真实像素差异：     {len(real)}[/red]")
    for base, count_a, count_b in count_mismatch[:10]:
        console.print(f"      [red]{base}[/red]  AssetStudio={count_a} UnityPy={count_b}")
    for key, delta in real[:15]:
        console.print(f"      [red]{key}[/red]  maxdiff={delta}")
    console.print()

    # Missing output and real disagreement block a switch; extra output and
    # decoder rounding do not.
    verdict = not only_a and not size_mismatch and not real and not count_mismatch
    if verdict:
        ok("UnityPy 覆盖 AssetStudio 的全部产出，差异仅为解码舍入，可以切换。")
    else:
        warn("存在实质差异，先看下面的报告再决定是否切换。")

    report = args.out / "ab_report.json"
    report.write_text(
        json.dumps(
            {
                "timings": timings,
                "tolerance": args.tolerance,
                "counts": {
                    "assetstudio_files": len(a),
                    "unitypy_files": len(b),
                    "assetstudio_names": len(group_a),
                    "unitypy_names": len(group_b),
                    "shared_names": len(shared),
                    "identical": identical,
                    "rounding_only": len(rounding),
                    "ambiguous": ambiguous,
                    "real_mismatch": len(real),
                },
                "count_mismatch": count_mismatch,
                "only_assetstudio": only_a,
                "only_unitypy": only_b,
                "size_mismatch": size_mismatch,
                "real_mismatch": [[k, str(v)] for k, v in real],
                "verdict_can_switch": verdict,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    info(f"详细报告：{report}")
    return 0 if verdict else 2


if __name__ == "__main__":
    raise SystemExit(main())
