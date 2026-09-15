"""A local browser UI over the tool surface: `mmk serve`.

The page (`viewer/app.html`) is a layout editor. It reads the layout with
`describe`, looks ids up with `search_catalog` and `list_finishes`, and
changes the file only through `apply_ops`, so the validator has the last
word exactly as it does for the MCP server and the shell. A successful edit
re-exports drawings and the scene, and the page reloads them.

The server is the standard library's: `ThreadingHTTPServer` with a
`SimpleHTTPRequestHandler` that serves the project root (so `out/` and
`examples/` are reachable), the repo's `viewer/` directory, and a JSON API
under `/api/`. It binds to localhost only and has no state of its own.
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import tools
from .edit import is_fixture
from .export import is_stale

VIEWER_DIR = Path(__file__).resolve().parents[2] / "viewer"
APP_PAGE = VIEWER_DIR / "app.html"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8760
LAYOUT_GLOBS = ("*.json", "examples/*.json", "variations/*.json")

Response = tuple[int, dict[str, Any]]


def list_layouts(root: Path) -> dict[str, Any]:
    """Every kitchen file the UI can open: the root, examples/ (fixtures) and variations/."""
    root = root.resolve()
    found = []
    for pattern in LAYOUT_GLOBS:
        for p in sorted(root.glob(pattern)):
            try:
                doc = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(doc, dict) or "runs" not in doc or "room" not in doc:
                continue
            found.append({"path": p.relative_to(root).as_posix(), "name": doc.get("name", p.stem),
                          "fixture": is_fixture(p), "export_stale": is_stale(root / "out", p)})
    return {"ok": True, "layouts": found}


def _num(query: dict[str, str], key: str) -> float | None:
    v = query.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number, not {v!r}") from exc


def _kitchen(query: dict[str, Any]) -> str:
    k = query.get("kitchen")
    if not k or not isinstance(k, str):
        raise ValueError("kitchen (a path relative to the project root) is required")
    return k


def dispatch(root: Path, method: str, path: str, query: dict[str, str], body: dict[str, Any] | None = None) -> Response:
    """Route one API call to the tool surface. Returns (HTTP status, JSON-able body)."""
    try:
        if method == "GET":
            if path == "/api/layouts":
                return 200, list_layouts(root)
            if path == "/api/describe":
                return 200, tools.describe(root, _kitchen(query))
            if path == "/api/catalog":
                lim = _num(query, "limit")
                return 200, tools.search_catalog(root, query.get("kitchen") or None, query.get("kind") or None, query.get("type") or None,
                                                 _num(query, "width_in"), _num(query, "height_in"), query.get("series") or None,
                                                 query.get("text") or None, int(lim) if lim else 50)
            if path == "/api/finishes":
                return 200, tools.list_finishes(query.get("role") or None)
            if path == "/api/validate":
                return 200, tools.validate_kitchen(root, _kitchen(query))
            if path == "/api/bom":
                return 200, tools.bom(root, _kitchen(query))
            if path == "/api/purchase":
                return 200, tools.purchase(root, _kitchen(query))
        elif method == "POST":
            b = body if isinstance(body, dict) else {}
            if path == "/api/apply":
                ops = b.get("ops")
                if not isinstance(ops, list) or not ops:
                    raise ValueError("ops must be a non-empty list of operations")
                return 200, tools.apply_ops(root, _kitchen(b), ops, dry_run=bool(b.get("dry_run")), render=bool(b.get("render")))
            if path == "/api/variation":
                name = b.get("name")
                if not name or not isinstance(name, str):
                    raise ValueError("name is required")
                return 200, tools.start_variation(root, _kitchen(b), name)
            if path == "/api/export":
                return 200, tools.export(root, _kitchen(b), render=bool(b.get("render")), ikea_models=bool(b.get("ikea_models")))
        else:
            return 405, {"ok": False, "error": f"{method} not allowed"}
    except ValueError as exc:
        return 400, {"ok": False, "error": str(exc)}
    return 404, {"ok": False, "error": f"no such route: {method} {path}"}


class Handler(SimpleHTTPRequestHandler):
    """Static files from the project root, the repo's viewer/ at /viewer/, the app at /, and /api/."""

    root: Path = Path(".")
    quiet: bool = True
    protocol_version = "HTTP/1.1"   # keep-alive: the viewer fetches many files

    def __init__(self, *args: Any, root: Path, quiet: bool = True, **kwargs: Any) -> None:
        self.root = root
        self.quiet = quiet
        super().__init__(*args, directory=str(root), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature fixed by the base class
        if not self.quiet:
            super().log_message(format, *args)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        rel = urlsplit(path).path
        if rel == "/viewer" or rel.startswith("/viewer/"):
            target = (VIEWER_DIR / rel[len("/viewer/"):]).resolve()
            if target == VIEWER_DIR or VIEWER_DIR in target.parents:
                return str(target)
        return super().translate_path(path)

    def _send_json(self, status: int, obj: dict[str, Any]) -> None:
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _query(self) -> dict[str, str]:
        return {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def do_GET(self) -> None:  # noqa: N802 - base class naming
        path = urlsplit(self.path).path
        if path in ("/", "/index.html", "/app.html"):
            data = APP_PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith("/api/"):
            status, obj = dispatch(self.root, "GET", path, self._query())
            self._send_json(status, obj)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if not path.startswith("/api/"):
            self._send_json(404, {"ok": False, "error": "POST is only for /api/"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode() or "{}")
        except ValueError:
            self._send_json(400, {"ok": False, "error": "request body must be JSON"})
            return
        status, obj = dispatch(self.root, "POST", path, self._query(), body)
        self._send_json(status, obj)


def make_server(root: Path, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, quiet: bool = True) -> ThreadingHTTPServer:
    root = root.resolve()

    def factory(*args: Any, **kwargs: Any) -> Handler:
        return Handler(*args, root=root, quiet=quiet, **kwargs)

    return ThreadingHTTPServer((host, port), factory)


def serve(root: Path, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, open_browser: bool = True, quiet: bool = True) -> int:
    server = make_server(root, host, port, quiet)
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"millimeter-kitchen UI at {url}  (root {root.resolve()}; Ctrl-C to stop)", file=sys.stderr)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
