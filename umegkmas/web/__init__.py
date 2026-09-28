"""Local web console.

A small stdlib HTTP server bound to 127.0.0.1, so the green package gains a GUI
without a single extra dependency. The page drives the same pipeline as the CLI;
everything the pipeline reports through `ui` is mirrored to the browser over
Server-Sent Events, and the terminal window keeps showing the rich output too.

Only one job runs at a time: two pipelines writing the same data directory and
state.json would race each other.
"""

import json
import mimetypes
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .. import __version__, pipeline
from ..config import load_config, read_raw, save_values
from ..errors import UmeError
from ..status import local_status, server_status
from ..ui import Cancelled, add_listener, console, emit, error, request_cancel, reset_cancel, warn

DEFAULT_PORT = 8765
PORT_ATTEMPTS = 20
PAGE = Path(__file__).with_name("index.html")
IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}
GALLERY_PAGE_SIZE = 200
# Pipeline modes the page may start. None = "whatever the next sensible run is".
MODES = {"update": None, "latest": "latest", "full": "full", "baseline": "baseline"}

mimetypes.add_type("image/webp", ".webp")


class EventHub:
    """Fan-out of ui events to any number of SSE clients.

    Logs are kept (bounded) so a reloaded page shows what already happened.
    Progress is too chatty to keep; only the latest one is held for new clients.
    """

    HISTORY = 2000

    def __init__(self):
        self._cond = threading.Condition()
        self._seq = 0
        self._history = deque(maxlen=self.HISTORY)
        self._progress = None

    def publish(self, event: dict) -> None:
        with self._cond:
            self._seq += 1
            event = {**event, "id": self._seq, "time": time.time()}
            if event["kind"] == "progress":
                self._progress = event
            else:
                self._history.append(event)
                if event["kind"] == "step":
                    # A new stage starts with no progress bar until it adds one.
                    self._progress = None
            self._cond.notify_all()

    def since(self, last_id: int, timeout: float) -> list:
        with self._cond:
            if self._seq <= last_id:
                self._cond.wait(timeout)
            events = [event for event in self._history if event["id"] > last_id]
            if self._progress and self._progress["id"] > last_id:
                events.append(self._progress)
            return events

    @property
    def last_id(self) -> int:
        return self._seq


class JobRunner:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._lock = threading.Lock()
        self.current = None
        self.last = None

    def snapshot(self) -> dict:
        return {"running": self.current, "last": self.last}

    def start(self, mode_key: str, force: bool) -> None:
        if mode_key not in MODES:
            raise UmeError(f"未知的操作：{mode_key}")
        with self._lock:
            if self.current:
                raise UmeError("已有任务在运行。", "等它结束，或先点「取消」。")
            self.current = {"mode": mode_key, "force": force, "started_at": time.time()}
        reset_cancel()
        threading.Thread(target=self._run, args=(mode_key, force), daemon=True).start()

    def _run(self, mode_key: str, force: bool) -> None:
        emit("job", state="running", **self.current)
        result = "error"
        try:
            config = load_config(self.config_path)
            code = pipeline.run(config, requested_mode=MODES[mode_key], force=force, interactive=False)
            result = "ok" if code == 0 else "failed"
        except Cancelled as exc:
            warn(f"{exc.message}{exc.hint}")
            result = "cancelled"
        except UmeError as exc:
            error(exc.message)
            if exc.hint:
                warn(exc.hint)
        except Exception as exc:
            console.print_exception()
            error(f"程序出错：{exc!r}")
            emit("log", level="detail", text=traceback.format_exc(limit=6))
        finally:
            with self._lock:
                self.last = {**self.current, "result": result, "finished_at": time.time()}
                self.current = None
            emit("job", state="idle", **self.last)


def _open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - local folder chosen from a fixed list
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _revision_dirs(config) -> list:
    """Every revision that has extracted images, newest first."""
    paths = config.paths
    found = {}
    for source, root in (("png", paths.images), ("webp", paths.converted)):
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit():
                found.setdefault(int(child.name[1:]), []).append(source)
    return [{"revision": rev, "sources": sorted(found[rev])} for rev in sorted(found, reverse=True)]


def _gallery_dir(config, revision: int, source: str) -> Path:
    paths = config.paths
    return paths.revision_converted(revision) if source == "webp" else paths.revision_images(revision)


def _list_images(config, revision: int, source: str, query: str, offset: int) -> dict:
    root = _gallery_dir(config, revision, source)
    if not root.is_dir():
        return {"total": 0, "items": []}
    query = query.lower()
    files = sorted(
        path
        for path in root.rglob("*")
        if path.suffix.lower() in IMAGE_SUFFIXES and (not query or query in path.as_posix().lower())
    )
    data_dir = config.paths.data_dir
    items = [
        {
            "path": path.relative_to(data_dir).as_posix(),
            "name": path.name,
            "group": path.parent.relative_to(root).as_posix(),
        }
        for path in files[offset : offset + GALLERY_PAGE_SIZE]
    ]
    return {"total": len(files), "items": items}


def make_handler(config_path: Path, hub: EventHub, jobs: JobRunner):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"umegkmas/{__version__}"

        def log_message(self, *args):
            # Request lines would drown the pipeline's own output in the terminal.
            pass

        # -- plumbing ---------------------------------------------------------

        def _host_ok(self) -> bool:
            # Rejecting foreign Host headers blocks DNS-rebinding pages from
            # reaching this server through a hostname they control.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in {"127.0.0.1", "localhost", "::1"}

        def _send_json(self, payload, status=HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, exc: UmeError, status=HTTPStatus.BAD_REQUEST) -> None:
            self._send_json({"error": exc.message, "hint": exc.hint}, status)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise UmeError("请求内容不是有效的 JSON。") from exc

        def _config(self):
            return load_config(config_path)

        # -- routing ----------------------------------------------------------

        def do_GET(self):
            if not self._host_ok():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            url = urlparse(self.path)
            query = parse_qs(url.query)
            try:
                if url.path in ("/", "/index.html"):
                    self._serve_file(PAGE, cache=False)
                elif url.path == "/api/ping":
                    self._send_json({"app": "umegkmas", "version": __version__})
                elif url.path == "/api/state":
                    self._send_json({"local": local_status(self._config()), "job": jobs.snapshot()})
                elif url.path == "/api/server":
                    self._send_json(server_status(self._config()))
                elif url.path == "/api/config":
                    self._send_json({"values": read_raw(config_path), "path": str(config_path)})
                elif url.path == "/api/gallery":
                    self._send_json({"revisions": _revision_dirs(self._config())})
                elif url.path == "/api/images":
                    self._send_json(
                        _list_images(
                            self._config(),
                            int(query.get("revision", ["0"])[0]),
                            query.get("source", ["png"])[0],
                            query.get("q", [""])[0],
                            max(0, int(query.get("offset", ["0"])[0])),
                        )
                    )
                elif url.path == "/api/events":
                    self._stream_events()
                elif url.path.startswith("/data/"):
                    self._serve_data(unquote(url.path[len("/data/") :]))
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except UmeError as exc:
                self._send_error(exc)
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self):
            # A custom header can't be set cross-origin without a CORS preflight,
            # which this server never approves - so other sites can't drive it.
            if not self._host_ok() or self.headers.get("X-Umegkmas") != "1":
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            url = urlparse(self.path)
            try:
                body = self._read_json()
                if url.path == "/api/run":
                    jobs.start(str(body.get("mode", "update")), bool(body.get("force", False)))
                    self._send_json(jobs.snapshot())
                elif url.path == "/api/cancel":
                    if jobs.current:
                        request_cancel()
                        warn("正在取消，等当前文件处理完...")
                    self._send_json(jobs.snapshot())
                elif url.path == "/api/config":
                    config = save_values(body.get("values", {}), config_path)
                    emit("log", level="ok", text="配置已保存。")
                    self._send_json({"values": read_raw(config_path), "data_dir": str(config.paths.data_dir)})
                elif url.path == "/api/open":
                    self._open(body)
                    self._send_json({"ok": True})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except UmeError as exc:
                self._send_error(exc)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        # -- handlers ---------------------------------------------------------

        def _open(self, body: dict) -> None:
            config = self._config()
            target = body.get("target")
            if target == "data":
                _open_folder(config.paths.data_dir)
            elif target == "config":
                _open_folder(config_path.parent)
            elif target == "images":
                revision = int(body.get("revision") or 0)
                source = body.get("source", "png")
                _open_folder(_gallery_dir(config, revision, source) if revision else config.paths.images)
            else:
                raise UmeError(f"未知的目录：{target}")

        def _serve_file(self, path: Path, cache: bool = True) -> None:
            try:
                data = path.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if content_type.startswith("text/"):
                content_type += "; charset=utf-8"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _serve_data(self, relative: str) -> None:
            root = self._config().paths.data_dir.resolve()
            target = (root / relative).resolve()
            # Only image files inside the data directory, never anything above it.
            if not target.is_relative_to(root) or target.suffix.lower() not in IMAGE_SUFFIXES:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            self._serve_file(target)

        def _stream_events(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            # EventSource resends the last id on reconnect, so a dropped
            # connection resumes instead of replaying the whole log.
            last_id = int(self.headers.get("Last-Event-ID") or 0)
            if last_id > hub.last_id:
                last_id = 0  # the server restarted; the page's ids are stale
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            while True:
                events = hub.since(last_id, timeout=15)
                if not events:
                    self.wfile.write(b": keepalive\n\n")
                for event in events:
                    last_id = max(last_id, event["id"])
                    payload = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"id: {event['id']}\ndata: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # SO_REUSEADDR on Windows lets a second process bind a port that is already
    # taken, which would split the console across two servers and two pipelines.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _existing_console(port: int) -> bool:
    """True when our own console already answers on this port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as response:
            return json.load(response).get("app") == "umegkmas"
    except Exception:
        return False


def _bind(handler, port: int | None):
    candidates = [port] if port else range(DEFAULT_PORT, DEFAULT_PORT + PORT_ATTEMPTS)
    for candidate in candidates:
        try:
            return _Server(("127.0.0.1", candidate), handler)
        except OSError:
            if _existing_console(candidate):
                return candidate
    raise UmeError(
        "找不到可用的端口来启动网页控制台。",
        "用 --port 指定一个没被占用的端口，例如 --port 9000。",
    )


def serve(config_path: Path, port: int | None = None, open_browser: bool = True) -> int:
    # Fail early on a broken config.toml rather than serving a page that can't load.
    load_config(config_path)

    hub = EventHub()
    jobs = JobRunner(config_path)
    add_listener(hub.publish)

    server = _bind(make_handler(config_path, hub, jobs), port)
    if isinstance(server, int):
        # A second double-click just brings the running console to the front;
        # two pipelines on one data directory would corrupt each other's state.
        url = f"http://127.0.0.1:{server}/"
        console.print(f"[bold green]>>>[/bold green] 控制台已经在运行：{url}")
        if open_browser:
            webbrowser.open(url)
        return 0

    url = f"http://127.0.0.1:{server.server_address[1]}/"
    console.print()
    console.print(f"[bold green]>>>[/bold green] 网页控制台已启动：[bold underline]{url}[/bold underline]")
    console.print("    浏览器没自动打开的话，把上面的地址复制到浏览器里。")
    console.print("    [dim]关闭这个窗口 = 退出程序。[/dim]")
    console.print()
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if jobs.current:
            request_cancel()
        console.print()
        warn("控制台已关闭。")
    finally:
        server.server_close()
    return 0
