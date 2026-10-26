"""Talk to a local llama.cpp server. Nothing else.

The engine and the weights are both open source, both on disk, both ours.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import platform
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from . import config, netguard


class ModelUnavailable(RuntimeError):
    pass


def _post(url: str, payload: dict, timeout: int = 240) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str, timeout: int = 3) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_json(text: str):
    """Pull the first complete JSON value out of a chatty model reply."""
    if not text:
        raise ValueError("empty model reply")
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    start = None
    for i, ch in enumerate(text):
        if ch in "[{":
            start = i
            break
    if start is None:
        raise ValueError("no JSON found in reply")
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                blob = text[start:i + 1]
                try:
                    return json.loads(blob)
                except Exception:
                    cleaned = re.sub(r",\s*([}\]])", r"\1", blob)
                    try:
                        return json.loads(cleaned)
                    except Exception:
                        return ast.literal_eval(cleaned)
    raise ValueError("unterminated JSON in reply")


class LocalModel:
    def __init__(
        self,
        model_path: Path = None,
        server_bin: Path = None,
        port: int = None,
        autostart: bool = True,
    ):
        self.model_path = Path(model_path or config.MODEL_PATH)
        self.server_bin = Path(server_bin or config.LLAMA_SERVER)
        self.port = int(port or config.MODEL_PORT)
        self.autostart = autostart
        self.proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._sha: Optional[str] = None
        self.last_error = ""

    # -- server lifecycle -------------------------------------------------
    @property
    def base(self) -> str:
        return "http://%s:%d" % (config.HOST, self.port)

    def health(self, timeout: float = 1.5) -> bool:
        try:
            with urllib.request.urlopen(self.base + "/health", timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def ensure(self, progress=None) -> None:
        with self._lock:
            if self.health():
                return
            if not self.autostart:
                raise ModelUnavailable("No local model is running at %s." % self.base)
            if not self.model_path.exists():
                raise ModelUnavailable(
                    "Model weights missing: %s\nRun ./setup.sh to fetch them." % self.model_path
                )
            if not self.server_bin.exists():
                raise ModelUnavailable(
                    "llama.cpp server missing: %s\nRun ./setup.sh to build it." % self.server_bin
                )
            if progress:
                progress("Waking the sloth (loading weights into memory)...")
            log_path = config.CACHE_DIR / "llama-server.log"
            config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            log = open(str(log_path), "ab", buffering=0)
            threads = max(2, min(10, (os.cpu_count() or 4) - 2))
            cmd = [
                str(self.server_bin),
                "-m", str(self.model_path),
                "--host", config.HOST,
                "--port", str(self.port),
                "-c", str(config.CTX),
                "-np", "1",
                "--jinja",
                "-ngl", "99",
                "-t", str(threads),
            ]
            self.proc = subprocess.Popen(
                cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL
            )
            deadline = time.time() + 180
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    tail = ""
                    try:
                        tail = log_path.read_text(errors="replace")[-1200:]
                    except Exception:
                        pass
                    raise ModelUnavailable(
                        "The local engine exited while starting.\n%s" % tail
                    )
                if self.health(timeout=1.0):
                    return
                time.sleep(0.4)
            raise ModelUnavailable("Timed out waiting for the local model to load.")

    def stop(self) -> None:
        with self._lock:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=8)
                except Exception:
                    self.proc.kill()
            self.proc = None

    # -- inference --------------------------------------------------------
    def chat(self, messages: List[dict], max_tokens: int = 900, temperature: float = 0.15) -> str:
        self.ensure()
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
            "repeat_penalty": 1.05,
            "stream": False,
            "response_format": {"type": "json_object"},
            "cache_prompt": True,
        }
        try:
            out = _post(self.base + "/v1/chat/completions", payload)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            # Older builds may not understand response_format; try once without it.
            if e.code in (400, 422):
                payload.pop("response_format", None)
                try:
                    out = _post(self.base + "/v1/chat/completions", payload)
                except Exception as e2:
                    raise ModelUnavailable("Local model error: %s %s" % (e2, body))
            else:
                raise ModelUnavailable("Local model error: %s %s" % (e, body))
        except urllib.error.URLError as e:
            raise ModelUnavailable("Could not reach the local model: %s" % e)
        try:
            return out["choices"][0]["message"]["content"] or ""
        except Exception:
            raise ModelUnavailable("Unexpected reply from the local model.")

    def complete_json(self, system: str, user: str, max_tokens: int = 900) -> dict:
        content = self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        parsed = extract_json(content)
        if not isinstance(parsed, dict):
            raise ValueError("model did not return a JSON object")
        return parsed

    # -- facts for the UI -------------------------------------------------
    def sha(self) -> str:
        if self._sha is None:
            cached = config.CACHE_DIR / "model.sha256"
            key = "%s:%s" % (self.model_path, self.model_path.stat().st_size if self.model_path.exists() else 0)
            if cached.exists():
                try:
                    old_key, old_sha = cached.read_text().strip().split(" ", 1)
                    if old_key == key:
                        self._sha = old_sha
                        return self._sha
                except Exception:
                    pass
            if not self.model_path.exists():
                return "missing"
            h = hashlib.sha256()
            with self.model_path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
            self._sha = h.hexdigest()[:16]
            try:
                config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cached.write_text("%s %s\n" % (key, self._sha))
            except Exception:
                pass
        return self._sha

    def info(self) -> dict:
        size = self.model_path.stat().st_size if self.model_path.exists() else 0
        return {
            "model": self.model_path.name,
            "model_path": str(self.model_path),
            "model_gb": round(size / (1024 ** 3), 2) if size else 0,
            "sha": self.sha(),
            "engine": "llama.cpp",
            "engine_path": str(self.server_bin),
            "backend": "Metal" if platform.system() == "Darwin" and platform.machine() == "arm64" else "CPU",
            "endpoint": self.base,
            "healthy": self.health(),
            "netguard": netguard.status(),
        }
