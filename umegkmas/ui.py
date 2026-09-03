"""Console helpers. Single Console instance so progress bars and logs interleave."""

from rich.console import Console

console = Console()


def info(message: str) -> None:
    console.print(f"[bold cyan]>>>[/bold cyan] {message}")


def ok(message: str) -> None:
    console.print(f"[bold green]>>>[/bold green] {message}")


def warn(message: str) -> None:
    console.print(f"[bold yellow]>>> 注意[/bold yellow] {message}")


def error(message: str) -> None:
    console.print(f"[bold red]>>> 错误[/bold red] {message}")


def step(message: str) -> None:
    console.rule(f"[bold]{message}[/bold]")


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"
