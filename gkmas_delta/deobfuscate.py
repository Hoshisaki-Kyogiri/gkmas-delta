"""Assetbundle header de-obfuscation.

Downloaded bundles have their first 256 bytes XORed with a mask derived from the
bundle's own name. Undo that and the file becomes a normal Unity bundle.

Worker functions are module-level and take only picklable arguments so they can
run in a ProcessPoolExecutor.
"""

import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from rich.progress import (
    BarColumn,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from .ui import Cancelled, Progress, console, info, warn

PROCESS_POOL_THRESHOLD = 32
COPY_BUFFER_SIZE = 1024 * 1024
UNITY_SIGNATURE = b"\x55\x6e\x69\x74\x79"
HEADER_LENGTH = 256


def _string_to_mask_bytes(mask_string: str, mask_len: int, byte_len: int) -> bytes:
    mask = bytearray(byte_len)
    if mask_len >= 1:
        i, j, k = 0, 0, byte_len - 1
        while mask_len != j:
            char = ord(mask_string[j])
            j += 1
            mask[i] = char
            i += 2
            mask[k] = ~char & 0xFF
            k -= 2

    checksum = 0x9B
    pointer = 0
    remaining = byte_len
    while remaining:
        value = mask[pointer]
        pointer += 1
        remaining -= 1
        checksum = (((checksum & 1) << 7) | (checksum >> 1)) ^ value

    for index in range(byte_len):
        mask[index] ^= checksum
    return bytes(mask)


def _crypt_by_string(data: bytes, mask_string: str, offset: int, stream_pos: int, header_length: int) -> bytes:
    mask_len = len(mask_string)
    byte_len = mask_len << 1
    buffer = bytearray(data)
    mask = _string_to_mask_bytes(mask_string, mask_len, byte_len)

    count = min(header_length - stream_pos, max(len(buffer) - offset, 0))
    for i in range(count):
        buffer[offset + i] ^= mask[(stream_pos + i) % byte_len]
    return bytes(buffer)


def _copy_to_many(src, destinations) -> None:
    while True:
        chunk = src.read(COPY_BUFFER_SIZE)
        if not chunk:
            break
        for dst in destinations:
            dst.write(chunk)


def _worker(task):
    source, name, type_dir, out_dirs = task
    source = Path(source)
    try:
        targets = []
        for out_dir in out_dirs:
            folder = Path(out_dir) / type_dir
            folder.mkdir(parents=True, exist_ok=True)
            targets.append(folder / (name + ".unity3d"))

        header_size = max(HEADER_LENGTH, len(UNITY_SIGNATURE))
        with source.open("rb") as src:
            handles = [target.open("wb") for target in targets]
            try:
                header = src.read(header_size)
                if header[0:5] == UNITY_SIGNATURE:
                    # Already plain; some bundles ship unobfuscated.
                    for handle in handles:
                        handle.write(header)
                    _copy_to_many(src, handles)
                    return True

                decoded = _crypt_by_string(header, name, 0, 0, HEADER_LENGTH)
                if decoded[0:5] != UNITY_SIGNATURE:
                    return False
                for handle in handles:
                    handle.write(decoded)
                _copy_to_many(src, handles)
                return True
            finally:
                for handle in handles:
                    handle.close()
    except Exception:
        return False


def _copy_worker(task):
    source, name, type_dir, out_dirs = task
    try:
        with Path(source).open("rb") as src:
            handles = []
            try:
                for out_dir in out_dirs:
                    folder = Path(out_dir) / type_dir
                    folder.mkdir(parents=True, exist_ok=True)
                    handles.append((folder / name).open("wb"))
                _copy_to_many(src, handles)
            finally:
                for handle in handles:
                    handle.close()
        return True
    except Exception:
        return False


def _build_tasks(entries, source_dir: Path, out_dirs, file_key: str):
    tasks = []
    for entry in entries:
        key = entry.get(file_key)
        if not key:
            continue
        source = source_dir / key
        if not source.is_file():
            continue
        tasks.append((str(source), entry["name"], entry["type"], out_dirs))
    return tasks


def _run(tasks, worker, description: str) -> int:
    errors = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(description, total=len(tasks))
        if len(tasks) < PROCESS_POOL_THRESHOLD:
            for task in tasks:
                if not worker(task):
                    errors += 1
                progress.update(task_id, advance=1)
        else:
            executor = ProcessPoolExecutor()
            try:
                futures = [executor.submit(worker, task) for task in tasks]
                for future in as_completed(futures):
                    if not future.result():
                        errors += 1
                    progress.update(task_id, advance=1)
            except Cancelled:
                executor.shutdown(wait=True, cancel_futures=True)
                raise
            executor.shutdown(wait=True)
    return errors


def _out_dirs(paths, revision: int, keep_base_copy: bool):
    dirs = [str(paths.revision_unobfuscated(revision))]
    if keep_base_copy:
        # A merged view of every revision. Doubles disk usage, so opt-in.
        dirs.append(str(paths.unobfuscated / "base"))
    return dirs


def deobfuscate_assets(manifest: dict, paths, keep_base_copy: bool = False) -> int:
    entries = manifest.get("assetBundleList", [])
    revision = manifest["revision"]
    if not entries:
        info("本次没有需要解混淆的 Asset。")
        return 0
    if not paths.assets.exists():
        warn(f"找不到目录 {paths.assets}，跳过解混淆。")
        return 0

    tasks = _build_tasks(entries, paths.assets, _out_dirs(paths, revision, keep_base_copy), "md5")
    if not tasks:
        warn("没有找到可解混淆的 Asset 文件。")
        return 0

    errors = _run(tasks, _worker, f"[cyan]解混淆 Asset (v{revision})...")
    if errors:
        warn(f"解混淆完成，{errors} 个文件失败。")
    else:
        info(f"解混淆完成，共 {len(tasks)} 个文件。")
    return len(tasks) - errors


def rename_resources(manifest: dict, paths, keep_base_copy: bool = False) -> int:
    """Resources are not obfuscated; this just files them by type per revision."""
    entries = manifest.get("resourceList", [])
    revision = manifest["revision"]
    if not entries or not paths.resources.exists():
        return 0

    tasks = _build_tasks(entries, paths.resources, _out_dirs(paths, revision, keep_base_copy), "name")
    if not tasks:
        return 0
    errors = _run(tasks, _copy_worker, f"[magenta]整理 Resource (v{revision})...")
    if errors:
        warn(f"整理完成，{errors} 个文件失败。")
    return len(tasks) - errors
