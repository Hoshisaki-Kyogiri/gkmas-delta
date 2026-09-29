"""The update pipeline.

Three ways to pick a manifest:

  update  (default)  ask the server for everything changed since our recorded
                     revision. One HTTP call, ~13 KB, only the changed files.
  full               the entire catalogue (~15 GB of downloads).
  baseline           record the current revision without downloading anything,
                     so future runs are incremental from here on.

The server does the diffing, so incremental mode needs no local manifest history
- just the revision number in state.json.
"""

from . import convert, deobfuscate, extract, octo
from .downloader import build_jobs, check_disk_space, download
from .errors import UmeError
from .state import State
from .ui import check_cancel, human_size, info, ok, step, warn


def _summarise(manifest: dict) -> str:
    return (
        f"{len(manifest.get('assetBundleList', []))} 个 Asset / "
        f"{len(manifest.get('resourceList', []))} 个 Resource"
    )


def _prompt_first_run() -> str:
    print()
    print("  这是第一次运行，还没有本地记录。请选择：")
    print()
    print("    [1] 下载最新一个版本的更新内容  （推荐，通常几十到几百 MB）")
    print("    [2] 下载整个游戏资源            （60 GB 以上，很慢）")
    print("    [3] 退出")
    print()
    while True:
        choice = input("  请输入 1 / 2 / 3 后回车： ").strip()
        if choice == "1":
            return "latest"
        if choice == "2":
            return "full"
        if choice == "3":
            return "quit"
        print("  只能输入 1、2 或 3。")


def resolve_mode(config, state: State, requested: str | None, interactive: bool = True) -> str:
    """Decide between baseline / full / update."""
    if requested:
        return requested

    if not state.has_baseline:
        choice = config.first_run
        if choice == "ask":
            if not interactive:
                raise UmeError("还没有本地记录，需要先选择首次下载方式。", "在控制台里选一种首次运行方式。")
            choice = _prompt_first_run()
        return choice if choice in {"latest", "full", "baseline", "quit"} else "latest"

    if not state.matches_app_version(config.app_version):
        # Revision numbers are scoped to the app version in the octo URL, so an
        # old number would silently request the wrong lineage.
        warn(
            f"app_version 已从 {state.app_version} 变成 {config.app_version}，"
            "上次的版本号不再适用，本次按全量清单处理。"
        )
        return "full"

    return "update"


def _base_revision(config, state: State, mode: str) -> int:
    """Which revision to diff against. 0 means "give me the whole catalogue"."""
    if mode == "update":
        return state.last_revision

    if mode == "latest":
        # First run, no local history: ask what the newest revision is (a 54-byte
        # probe) and take just that one revision's changes.
        newest = octo.latest_revision(config.app_version, config.unity_version)
        info(f"服务器最新版本 v{newest}。")
        return max(newest - 1, 0)

    return 0


def fetch_manifest(config, state: State, mode: str, local_cache=None):
    """Returns (manifest dict, raw proto bytes, base revision or None)."""
    if local_cache is not None:
        info(f"从本地缓存读取清单：{local_cache}")
        database, proto_bytes = octo.decrypt_local_cache(local_cache)
        return octo.to_dict(database), proto_bytes, None

    base = _base_revision(config, state, mode)
    if base:
        info(f"向服务器索取 v{base} 之后的更新...")
    else:
        info("获取完整清单（约 5 MB）...")

    database, proto_bytes = octo.fetch(base, config.app_version, config.unity_version)
    return octo.to_dict(database), proto_bytes, (base or None)


def run(
    config, requested_mode: str | None = None, local_cache=None, force: bool = False, interactive: bool = True
) -> int:
    paths = config.paths
    paths.ensure()
    state = State.load(paths.state_file)

    mode = "full" if local_cache is not None else resolve_mode(config, state, requested_mode, interactive)
    if mode == "quit":
        info("已取消。")
        return 0

    step("获取清单")
    manifest, proto_bytes, base = fetch_manifest(config, state, mode, local_cache)
    revision = manifest["revision"]

    if mode == "baseline":
        octo.save_manifest(manifest, proto_bytes, paths.manifests, revision, f"v{revision}")
        state.record(config.app_version, revision, "baseline")
        ok(f"已记录当前版本 v{revision}（{_summarise(manifest)}），没有下载任何文件。")
        info("以后每次运行都只会下载新增和变动的内容。")
        return 0

    if mode == "update" and revision == state.last_revision and not force:
        ok(f"已经是最新版本 v{revision}，没有更新。")
        return 0

    # `base` is set for every incremental fetch, whether it came from local state
    # (update) or from the newest-revision probe (latest).
    label = f"diff_v{base}_v{revision}" if base else f"v{revision}"

    manifest, deleted = octo.drop_deleted(manifest)
    if deleted:
        info(f"清单中有 {deleted} 个已删除条目，已跳过。")

    if not manifest["assetBundleList"] and not manifest["resourceList"]:
        octo.save_manifest(manifest, proto_bytes, paths.manifests, revision, label)
        state.record(config.app_version, revision, mode)
        ok(f"版本已更新到 v{revision}，但没有需要下载的内容。")
        return 0

    manifest_path = octo.save_manifest(manifest, proto_bytes, paths.manifests, revision, label)
    if base:
        ok(f"v{base} → v{revision}：{_summarise(manifest)}，共 {human_size(octo.total_bytes(manifest))}")
    else:
        ok(f"完整清单 v{revision}：{_summarise(manifest)}，共 {human_size(octo.total_bytes(manifest))}")
    info(f"清单已保存到 {manifest_path}")

    step("下载")
    jobs, skipped = build_jobs(
        manifest, paths, config.download_assets, config.download_resources, config.verify_md5
    )
    if skipped:
        info(f"{skipped} 个文件本地已是最新，跳过。")
    check_disk_space(jobs, paths.data_dir)
    _, failed = download(jobs, config.workers)
    check_cancel()

    if config.deobfuscate:
        step("解混淆")
        deobfuscate.deobfuscate_assets(manifest, paths, config.keep_base_copy)

    check_cancel()
    extracted = False
    if config.extract_images and manifest["assetBundleList"]:
        step("抽取贴图")
        try:
            extracted = extract.run(
                config.backend,
                paths.revision_unobfuscated(revision),
                paths.revision_images(revision),
                config.unity_version,
                cli_path=config.assetstudio_path,
                workers=config.workers,
            )
        except UmeError as exc:
            # A missing extraction backend must not lose the downloads or the
            # revision bookkeeping that already succeeded.
            warn(exc.message)
            if exc.hint:
                warn(exc.hint)

    check_cancel()
    if config.convert_webp and extracted:
        step("转换 webp")
        convert.convert(paths.revision_images(revision), paths.revision_converted(revision), config.workers)

    if failed:
        warn(
            f"本次有 {len(failed)} 个文件下载失败，版本号仍停留在 v{state.last_revision}。"
            "再运行一次会自动补下缺失的文件。"
        )
        return 1

    state.record(config.app_version, revision, mode)
    step("完成")
    ok(f"已更新到 v{revision}。")
    info(f"文件在：{paths.data_dir}")
    return 0
