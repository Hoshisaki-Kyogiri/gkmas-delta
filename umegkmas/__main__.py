"""CLI entry point.

No arguments = read config.toml and do the sensible thing (incremental update).
Flags exist for the cases the config can't express per-run.
"""

import argparse
import multiprocessing
import sys
from pathlib import Path

from .config import CONFIG_PATH, ensure_config_file, load_config
from .errors import UmeError
from .pipeline import run
from .ui import console, error, human_size, info, warn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="umegkmas",
        description="学园偶像大师 资源更新工具。不加任何参数就是「检查并下载更新」。",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="下载完整资源（60 GB 以上）")
    mode.add_argument("--latest", action="store_true", help="下载最新一个版本的更新内容")
    mode.add_argument("--baseline", action="store_true", help="只记录当前版本号，不下载")
    mode.add_argument("--status", action="store_true", help="显示本地记录的版本和服务器最新版本")
    mode.add_argument("--web", action="store_true", help="打开本地网页控制台")

    parser.add_argument("--local-cache", type=Path, default=None, help="改用本地 octocacheevai 文件")
    parser.add_argument("--force", action="store_true", help="即使版本号没变也重新处理一次")
    parser.add_argument("--workers", type=int, default=None, help="临时覆盖下载线程数")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="指定配置文件路径")
    parser.add_argument("--no-pause", action="store_true", help="结束后不等待回车（用于计划任务）")
    parser.add_argument("--port", type=int, default=None, help="网页控制台端口（默认 8765，被占用时自动换）")
    parser.add_argument("--no-browser", action="store_true", help="启动网页控制台但不自动打开浏览器")
    return parser


def show_status(config) -> int:
    from .status import local_status, server_status

    local = local_status(config)
    console.print()
    if local["has_baseline"]:
        console.print(f"  本地版本：[bold]v{local['revision']}[/bold]（{local['updated_at'] or '未知时间'}）")
    else:
        console.print("  本地版本：[yellow]尚未记录[/yellow]")
    console.print(f"  游戏版本：{config.app_version}")
    console.print(f"  数据目录：{config.paths.data_dir}")

    try:
        remote = server_status(config)
    except UmeError as exc:
        warn(exc.message)
        return 1

    console.print(f"  服务器版本：[bold]v{remote['server_revision']}[/bold]")
    pending = remote["pending"]
    if pending:
        console.print(
            f"  待更新：[bold green]{pending['bundles']} 个 Asset / {pending['files']} 个 Resource，"
            f"共 {human_size(pending['bytes'])}[/bold green]"
        )
    elif local["has_baseline"] and not local["app_version_changed"]:
        console.print("  [green]已是最新。[/green]")
    console.print()
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if ensure_config_file(args.config):
        info(f"已生成默认配置文件：{args.config}")

    try:
        config = load_config(args.config)
        if args.workers:
            config.workers = args.workers

        if args.status:
            return show_status(config)

        if args.web:
            from .web import serve

            return serve(args.config, port=args.port, open_browser=not args.no_browser)

        mode = None
        if args.full:
            mode = "full"
        elif args.latest:
            mode = "latest"
        elif args.baseline:
            mode = "baseline"

        return run(config, requested_mode=mode, local_cache=args.local_cache, force=args.force)

    except UmeError as exc:
        console.print()
        error(exc.message)
        if exc.hint:
            console.print(f"    [yellow]{exc.hint}[/yellow]")
        console.print()
        return 1
    except KeyboardInterrupt:
        console.print()
        warn("已中断。下次运行会从断点继续。")
        return 130


def cli() -> int:
    # Required so the ProcessPoolExecutor in deobfuscate.py works under a frozen
    # or embedded Python build on Windows.
    multiprocessing.freeze_support()
    # The web console runs until the window is closed; nothing to pause for.
    no_pause = "--no-pause" in sys.argv or "--web" in sys.argv
    code = main()
    if not no_pause:
        try:
            input("\n按回车键退出...")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(cli())
