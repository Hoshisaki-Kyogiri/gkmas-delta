"""Parallel downloader.

Two behaviours carried over from the previous toolkit because they matter on
this CDN: a single global connection budget shared by cross-file workers and
per-file range segments, and multi-connection range fetches for large files so
one ~900 MB video can't leave the link idle on a single slow socket.

New here: an existing file is only trusted when its md5 matches the manifest.
Resources keep their real name, so an updated file (same name, new md5) would
otherwise be skipped forever.
"""

import hashlib
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from .errors import DiskSpaceError
from .ui import console, human_size, info, warn

CHUNK_SIZE = 256 * 1024
REQUEST_TIMEOUT = (10, 60)
LARGE_FILE_THRESHOLD = 16 * 1024 * 1024
SEGMENT_RETRIES = 3
MD5_CHUNK = 1024 * 1024

_thread_local = threading.local()
_conn_sema = threading.Semaphore(16)
_segment_connections = 16


def _session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


def _parse_size(value):
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    return size if size > 0 else None


def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(MD5_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ranged_get(url, headers=None):
    _conn_sema.acquire()
    try:
        response = _session().get(url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response
    except Exception:
        _conn_sema.release()
        raise


def _release(response):
    try:
        response.close()
    finally:
        _conn_sema.release()


def _download_single(url, temp_path, task_id, overall_id, progress):
    response = _ranged_get(url)
    try:
        header_size = response.headers.get("Content-Length")
        if header_size and header_size.isdigit():
            progress.update(task_id, total=int(header_size))
        with open(temp_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                handle.write(chunk)
                progress.update(task_id, advance=len(chunk))
                progress.update(overall_id, advance=len(chunk))
    finally:
        _release(response)


def _download_segment(url, temp_path, start, end, task_id, overall_id, progress):
    last_exc = None
    for attempt in range(SEGMENT_RETRIES):
        written = 0
        try:
            response = _ranged_get(url, headers={"Range": f"bytes={start}-{end}"})
            try:
                with open(temp_path, "r+b") as handle:
                    handle.seek(start)
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        written += len(chunk)
                        progress.update(task_id, advance=len(chunk))
                        progress.update(overall_id, advance=len(chunk))
            finally:
                _release(response)
            return
        except Exception as exc:
            last_exc = exc
            # Undo this attempt's progress so a retry doesn't double-count bytes.
            if written:
                progress.update(task_id, advance=-written)
                progress.update(overall_id, advance=-written)
            if attempt < SEGMENT_RETRIES - 1:
                time.sleep(0.3 * (attempt + 1))
    raise last_exc


def _download_ranged(url, temp_path, size, task_id, overall_id, progress):
    segments = min(
        _segment_connections,
        max(1, (size + LARGE_FILE_THRESHOLD - 1) // LARGE_FILE_THRESHOLD),
    )
    if segments <= 1:
        _download_single(url, temp_path, task_id, overall_id, progress)
        return

    # Pre-size the target so each segment seeks to its own offset and writes in place.
    with open(temp_path, "wb") as handle:
        handle.truncate(size)

    span = (size + segments - 1) // segments
    ranges = [(i * span, min((i + 1) * span - 1, size - 1)) for i in range(segments)]
    with ThreadPoolExecutor(max_workers=segments) as executor:
        futures = [
            executor.submit(_download_segment, url, temp_path, start, end, task_id, overall_id, progress)
            for start, end in ranges
        ]
        for future in as_completed(futures):
            future.result()


def _download_one(job, progress, overall_id, state, lock):
    label = "资源包" if job["is_asset"] else "文件"
    size = _parse_size(job["size"])
    task_id = progress.add_task(f"[cyan]{label} {job['name']}", total=size, start=False)
    temp_path = job["path"] + ".part"

    try:
        progress.start_task(task_id)
        if size is not None and size >= LARGE_FILE_THRESHOLD:
            _download_ranged(job["url"], temp_path, size, task_id, overall_id, progress)
        else:
            _download_single(job["url"], temp_path, task_id, overall_id, progress)
        os.replace(temp_path, job["path"])

        with lock:
            state["done"] += 1
            progress.update(
                overall_id,
                description=f"[magenta]总进度 ({state['done']}/{state['total']} 个文件)",
            )
        progress.remove_task(task_id)
        return True
    except Exception as exc:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        with lock:
            state["failed"].append((job["name"], str(exc)))
        progress.update(task_id, description=f"[red]{label} {job['name']} 失败")
        progress.stop_task(task_id)
        return False


def _needs_download(path: Path, expected_md5: str, expected_size, verify_md5: bool) -> bool:
    if not path.exists():
        return True
    size = _parse_size(expected_size)
    if size is not None and path.stat().st_size != size:
        return True
    if verify_md5 and expected_md5:
        return file_md5(path) != expected_md5
    return False


def build_jobs(manifest, paths, download_assets, download_resources, verify_md5):
    """Turn a manifest into the list of files actually missing locally."""
    url_format = manifest.get("urlFormat") or "https://object.asset.game-gakuen-idolmaster.jp/{o}"
    jobs = []
    skipped = 0

    groups = []
    if download_assets:
        # Assets are stored under their md5, so an update lands as a new file.
        groups.append((manifest.get("assetBundleList", []), paths.assets, True, "md5"))
    if download_resources:
        # Resources keep their real filename; md5 is the only way to spot an update.
        groups.append((manifest.get("resourceList", []), paths.resources, False, "name"))

    for entries, target_dir, is_asset, name_key in groups:
        if not entries:
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            filename = entry.get(name_key)
            object_name = entry.get("objectName")
            if not filename or not object_name:
                continue
            path = target_dir / filename
            if not _needs_download(path, entry.get("md5", ""), entry.get("size"), verify_md5):
                skipped += 1
                continue
            jobs.append(
                {
                    "url": url_format.replace("{o}", object_name),
                    "path": str(path),
                    "name": entry["name"],
                    "is_asset": is_asset,
                    "size": entry.get("size"),
                }
            )
    return jobs, skipped


def check_disk_space(jobs, target: Path) -> None:
    needed = sum(size for size in (_parse_size(job["size"]) for job in jobs) if size)
    if not needed:
        return
    target.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(target).free
    # Deobfuscation and extraction write further copies, so ask for headroom.
    required = int(needed * 1.2)
    if free < required:
        raise DiskSpaceError(
            f"磁盘空间不够：大约需要 {human_size(required)}，可用只有 {human_size(free)}。",
            "腾出空间，或在 config.toml 的 [paths] 里把 data_dir 指到别的盘。",
        )


def download(jobs, workers: int):
    global _conn_sema, _segment_connections
    _conn_sema = threading.Semaphore(workers)
    _segment_connections = workers

    if not jobs:
        info("没有需要下载的文件。")
        return 0, []

    total = sum(size for size in (_parse_size(job["size"]) for job in jobs) if size)
    state = {"done": 0, "total": len(jobs), "failed": []}
    lock = threading.Lock()

    info(f"开始下载 {len(jobs)} 个文件，共 {human_size(total)}。")

    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        refresh_per_second=10,
    ) as progress:
        overall_id = progress.add_task(
            f"[magenta]总进度 (0/{len(jobs)} 个文件)", total=total or None
        )
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(_download_one, job, progress, overall_id, state, lock)
                for job in jobs
            ]
            for future in as_completed(futures):
                future.result()

    if state["failed"]:
        warn(f"{len(state['failed'])} 个文件下载失败：")
        for name, reason in state["failed"][:10]:
            console.print(f"    [red]{name}[/red] — {reason}")
        if len(state["failed"]) > 10:
            console.print(f"    ... 另有 {len(state['failed']) - 10} 个")
    return state["done"], state["failed"]
