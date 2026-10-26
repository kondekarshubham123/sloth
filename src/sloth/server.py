"""A tiny local web UI. Bound to 127.0.0.1, no framework, no network."""
from __future__ import annotations

import json
import mimetypes
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import config, netguard, store
from .llm import LocalModel, ModelUnavailable
from .planner import Planner

UI_DIR = Path(__file__).resolve().parent / "ui"
_infer_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "Sloth/1.0"

    def log_message(self, fmt, *args):  # keep the terminal calm
        return

    # -- helpers ----------------------------------------------------------
    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _stream_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _stream(self, event: dict) -> None:
        try:
            self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise

    # -- static -----------------------------------------------------------
    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (UI_DIR / rel).resolve()
        if UI_DIR not in target.parents and target != UI_DIR:
            self._json(403, {"error": "no"})
            return
        if not target.is_file():
            self._json(404, {"error": "not found"})
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # -- routes -----------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/status":
                model = LocalModel()
                info = model.info()
                info["settings"] = {
                    "demo_root": str(config.demo_root()),
                    "home": str(config.HOME),
                    "sorted_dir": config.SORTED_DIR,
                    "max_files": config.MAX_FILES,
                    "batches": config.BATCH_SIZE,
                }
                self._json(200, info)
                return
            if path == "/api/state":
                payload = store.state()
                payload["status"] = LocalModel().info()
                self._json(200, payload)
                return
            if path.startswith("/api/plan/"):
                plan_id = path.rsplit("/", 1)[-1]
                self._json(200, store.load_plan(plan_id))
                return
            self._static(path)
        except FileNotFoundError as e:
            self._json(404, {"error": str(e)})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._read_body()
            if path == "/api/scan":
                self._scan(body)
                return
            if path == "/api/apply":
                plan = store.load_plan(body.get("plan_id", ""))
                run = store.apply_plan(plan, ids=body.get("ids"))
                self._json(200, {
                    "ok": True,
                    "run": {k: v for k, v in run.items() if k != "moves"},
                    "moved": len(run["moves"]),
                    "briefing": store.latest_briefing(),
                })
                return
            if path == "/api/undo":
                result = store.undo(body.get("run_id") or "last")
                self._json(200, result)
                return
            self._json(404, {"error": "not found"})
        except Exception as e:
            self._json(500, {"error": str(e), "trace": traceback.format_exc(limit=3)})

    def _scan(self, body: dict) -> None:
        raw = (body.get("path") or "").strip()
        root = Path(raw).expanduser() if raw else config.demo_root()
        if not root.exists():
            root = Path.home() / "Downloads"
        try:
            limit = max(1, min(200, int(body.get("limit") or config.MAX_FILES)))
        except (TypeError, ValueError):
            limit = config.MAX_FILES
        use_model = bool(body.get("use_model", True))

        self._stream_start()
        sent_lock = threading.Lock()

        def emit(event: dict) -> None:
            with sent_lock:
                self._stream(event)

        try:
            planner = Planner(use_model=use_model, on_event=emit)
            with _infer_lock:
                plan = planner.build(root, limit=limit)
            store.save_plan(plan)
            self._stream({"stage": "saved", "plan_id": plan["id"]})
        except ModelUnavailable as e:
            self._stream({"stage": "error", "message": str(e)})
        except Exception as e:
            self._stream({"stage": "error", "message": str(e)})


def serve(port: int = None, open_browser: bool = False) -> None:
    netguard.install()
    port = int(port or config.UI_PORT)
    httpd = ThreadingHTTPServer((config.HOST, port), Handler)
    httpd.daemon_threads = True
    url = "http://%s:%d" % (config.HOST, port)
    print("\n  Sloth is awake (quietly).")
    print("  %s\n" % url)
    print("  Local model: %s" % config.MODEL_PATH)
    print("  Airgap: on — outbound connections blocked\n")
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Sloth is going back to sleep.")
    finally:
        httpd.server_close()
