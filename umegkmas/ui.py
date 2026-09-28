"""Console helpers. Single Console instance so progress bars and logs interleave.

Every message is also broadcast to registered listeners, which is how the web
console mirrors the terminal without the pipeline knowing it exists.
"""

import threading
import time

from rich import progress as rich_progress
from rich.console import Console

from .errors import UmeError

console = Console()

_listeners = []
_listeners_lock = threading.Lock()
_cancel = threading.Event()


class Cancelled(UmeError):
    def __init__(self):
        super().__init__("已取消。", "下次运行会从断点继续，已下载完整的文件不会重下。")


def add_listener(callback) -> None:
    with _listeners_lock:
        _listeners.append(callback)


def remove_listener(callback) -> None:
    with _listeners_lock:
        if callback in _listeners:
            _listeners.remove(callback)


def emit(kind: str, **data) -> None:
    with _listeners_lock:
        listeners = list(_listeners)
    for callback in listeners:
        try:
            callback({"kind": kind, **data})
        except Exception:
            # A broken listener must never take the pipeline down with it.
            pass


def request_cancel() -> None:
    _cancel.set()


def reset_cancel() -> None:
    _cancel.clear()


def check_cancel() -> None:
    if _cancel.is_set():
        raise Cancelled()


def info(message: str) -> None:
    console.print(f"[bold cyan]>>>[/bold cyan] {message}")
    emit("log", level="info", text=message)


def ok(message: str) -> None:
    console.print(f"[bold green]>>>[/bold green] {message}")
    emit("log", level="ok", text=message)


def warn(message: str) -> None:
    console.print(f"[bold yellow]>>> 注意[/bold yellow] {message}")
    emit("log", level="warn", text=message)


def error(message: str) -> None:
    console.print(f"[bold red]>>> 错误[/bold red] {message}")
    emit("log", level="error", text=message)


def detail(message: str) -> None:
    """An indented follow-up line, e.g. one entry of a failure list."""
    console.print(f"    [red]{message}[/red]", highlight=False)
    emit("log", level="detail", text=message)


def step(message: str) -> None:
    console.rule(f"[bold]{message}[/bold]")
    emit("step", text=message)


class Progress(rich_progress.Progress):
    """rich Progress that also reports its first task to listeners.

    Every stage adds its overall task first (the downloader then adds per-file
    tasks under it), so the first task is the one worth showing elsewhere.
    Updates are also the cancellation point: they happen on every chunk and
    every finished item, so a cancel request lands within moments.
    """

    REPORT_INTERVAL = 0.25

    def __init__(self, *columns, unit: str = "count", **kwargs):
        super().__init__(*columns, **kwargs)
        self._unit = unit
        self._main_task = None
        self._last_report = 0.0

    def add_task(self, description, *args, **kwargs):
        task_id = super().add_task(description, *args, **kwargs)
        if self._main_task is None:
            self._main_task = task_id
            self._report(force=True)
        return task_id

    def update(self, task_id, *args, **kwargs):
        check_cancel()
        super().update(task_id, *args, **kwargs)
        if task_id == self._main_task:
            self._report()

    def advance(self, task_id, advance: float = 1) -> None:
        check_cancel()
        super().advance(task_id, advance)
        if task_id == self._main_task:
            self._report()

    def stop(self) -> None:
        self._report(force=True)
        super().stop()

    def _report(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_report < self.REPORT_INTERVAL:
            return
        self._last_report = now
        task = self._tasks.get(self._main_task)
        if task is None:
            return
        emit(
            "progress",
            text=rich_strip(task.description),
            completed=task.completed,
            total=task.total,
            unit=self._unit,
        )


def rich_strip(text: str) -> str:
    from rich.text import Text

    return Text.from_markup(str(text)).plain


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"
