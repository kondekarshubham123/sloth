"""Look at a folder without opening the door to the internet."""
from __future__ import annotations

import mimetypes
import os
import re
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from . import config

MAX_TEXT = 1400
MAX_DEPTH = 3


@dataclass
class FileRecord:
    id: str
    path: Path
    name: str
    ext: str
    size: int
    modified: str
    kind: str
    text: str = ""
    dims: Optional[Tuple[int, int]] = None
    note: str = ""

    def prompt_view(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "ext": self.ext or "(none)",
            "kind": self.kind,
            "size_kb": max(1, round(self.size / 1024)),
            "modified": self.modified,
        }
        if self.dims:
            d["pixels"] = "%dx%d" % self.dims
        if self.text:
            d["text"] = self.text
        return d

    def ui_view(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "ext": self.ext,
            "size": self.size,
            "modified": self.modified,
            "kind": self.kind,
            "dims": ("%dx%d" % self.dims) if self.dims else "",
        }


def _clean_text(raw: bytes) -> str:
    try:
        s = raw.decode("utf-8", "replace")
    except Exception:
        return ""
    s = s.replace("\x00", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # Keep the signal, drop the bulk.
    return s[:MAX_TEXT]


def _png_dims(head: bytes) -> Optional[Tuple[int, int]]:
    if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            w, h = struct.unpack(">II", head[16:24])
            return int(w), int(h)
        except Exception:
            return None
    return None


def _gif_dims(head: bytes) -> Optional[Tuple[int, int]]:
    if len(head) >= 10 and head[:6] in (b"GIF87a", b"GIF89a"):
        try:
            w, h = struct.unpack("<HH", head[6:10])
            return int(w), int(h)
        except Exception:
            return None
    return None


def _jpeg_dims(head: bytes) -> Optional[Tuple[int, int]]:
    if not head.startswith(b"\xff\xd8"):
        return None
    i = 2
    n = len(head)
    while i + 9 < n:
        if head[i] != 0xFF:
            i += 1
            continue
        marker = head[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > n:
            return None
        seglen = struct.unpack(">H", head[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if i + 9 <= n:
                h, w = struct.unpack(">HH", head[i + 5:i + 9])
                return int(w), int(h)
            return None
        i += 2 + seglen
    return None


def image_dims(path: Path) -> Optional[Tuple[int, int]]:
    try:
        with path.open("rb") as fh:
            head = fh.read(65536)
    except OSError:
        return None
    return _png_dims(head) or _jpeg_dims(head) or _gif_dims(head)


def guess_kind(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        return "unknown"
    return mime


def should_skip_name(name: str) -> bool:
    if name in config.SKIP_NAMES:
        return True
    if name.startswith("."):
        return True
    return any(name.lower().endswith(s) for s in config.SKIP_SUFFIXES)


def scan(root: Path, limit: int = None) -> Tuple[List[FileRecord], List[dict]]:
    """Return files worth tidying plus a list of what we deliberately left alone."""
    limit = limit or config.MAX_FILES
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    records: List[FileRecord] = []
    skipped: List[dict] = []
    counter = 0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and d not in config.NEVER_TOUCH_DIRS
        )
        for name in sorted(filenames):
            if len(records) >= limit:
                break
            p = Path(dirpath) / name
            try:
                if p.is_symlink() or not p.is_file():
                    skipped.append({"name": str(p.relative_to(root)), "reason": "not a regular file"})
                    continue
            except OSError:
                continue
            if should_skip_name(name):
                skipped.append({"name": str(p.relative_to(root)), "reason": "hidden or unfinished"})
                continue
            if p.stat().st_size == 0:
                skipped.append({"name": str(p.relative_to(root)), "reason": "empty file"})
                continue
            counter += 1
            try:
                st = p.stat()
            except OSError:
                continue
            rec = FileRecord(
                id="f%d" % counter,
                path=p,
                name=name,
                ext=p.suffix,
                size=st.st_size,
                modified=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                kind=guess_kind(p),
            )
            if rec.ext.lower() in config.TEXT_EXTS and rec.size <= 2_000_000:
                try:
                    with p.open("rb") as fh:
                        rec.text = _clean_text(fh.read(MAX_TEXT))
                except OSError:
                    pass
            if rec.kind.startswith("image/"):
                rec.dims = image_dims(p)
            records.append(rec)
        if len(records) >= limit or depth >= MAX_DEPTH:
            dirnames[:] = []

    return records, skipped


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%d B" % n
