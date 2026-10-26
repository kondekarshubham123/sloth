"""Turn a messy folder into a calm, reviewable plan.

The model does the reading. A small rule engine keeps it honest: local models are
wonderful and occasionally confident nonsense, so objective signals (file types,
"screenshot" in the name) and strong semantic clues get the final say. Every
override is visible in the "why" line.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from . import config, scanner
from .llm import LocalModel, ModelUnavailable

EXT_BUCKETS = {
    "Images": {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif", ".raw", ".svg"},
    "Audio": {".mp3", ".m4a", ".wav", ".aiff", ".flac", ".ogg", ".aac", ".opus", ".mid"},
    "Video": {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".wmv", ".flv"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".dmg", ".iso"},
    "Code": {".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".rb", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".css", ".html", ".sql", ".ipynb"},
    "Finance": {".xlsx", ".xls", ".csv", ".numbers", ".ofx", ".qif"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".pages", ".odt", ".tex", ".epub"},
}

# Objective signals. If a file is an audio file, it is Audio, whatever the model thinks.
HARD_BUCKETS = {"Images", "Screenshots", "Audio", "Video", "Archives", "Code"}
SEMANTIC_BUCKETS = {"Finance", "Travel", "Health", "School"}

NAME_HINTS = [
    ("Screenshots", ("screenshot", "screen shot", "screen capture", "cleanshot")),
    ("Finance", ("invoice", "receipt", "tax", "statement", "budget", "paystub", "w-2", "1099", "bank", "rent")),
    ("Travel", ("boarding", "flight", "itinerary", "booking", "hotel", "airbnb", "train", "ticket", "visa", "trip")),
    ("Health", ("prescription", "medical", "lab result", "doctor", " dr ", "dentist", "blood test",
                "insurance claim", "workout", "gym", "health", "therapy")),
    ("School", ("lecture", "assignment", "homework", "syllabus", "course", "exam", "thesis",
                "semester", "university", "school", "study notes")),
    ("Code", ("dockerfile", "makefile", "package.json", "requirements.txt")),
]

HINT_WHY = {
    "Screenshots": "name says it is a screen capture",
    "Images": "image file",
    "Audio": "audio file",
    "Video": "video file",
    "Archives": "archive file",
    "Code": "source or project file",
    "Finance": "name points to money or paperwork",
    "Travel": "name points to a trip or booking",
    "Health": "name points to health or medical",
    "School": "name points to coursework",
    "Documents": "document file",
    "Unsorted": "no clear signal",
}


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def _clean_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"(?i)\b(final|copy|new|backup|v\d+|\(\d+\)|download(ed)?)\b", " ", stem)
    stem = re.sub(r"(?i)^(img|dsc|pxl|scan)[-_ ]?(\d+).*$", r"\1-\2", stem)
    return _slug(stem)


def _fallback_name(rec: scanner.FileRecord) -> str:
    slug = _clean_stem(rec.name)
    if len(slug) < 3:
        slug = "untitled"
    return slug[:60] + rec.ext.lower()


def hint_bucket(rec: scanner.FileRecord) -> str:
    lower = " %s " % rec.name.lower()
    for bucket, words in NAME_HINTS:
        if any(w in lower for w in words):
            # Screenshot beats the generic image extension below.
            return bucket
    ext = rec.ext.lower()
    for bucket, exts in EXT_BUCKETS.items():
        if ext in exts:
            return bucket
    return "Unsorted"


def fallback_suggestion(rec: scanner.FileRecord) -> dict:
    bucket = hint_bucket(rec)
    return {
        "id": rec.id,
        "bucket": bucket,
        "new_name": _fallback_name(rec),
        "why": HINT_WHY.get(bucket, "matched by file type"),
        "confidence": 0.62 if bucket != "Unsorted" else 0.25,
        "source": "rules",
    }


def sanitize_name(raw: str, rec: scanner.FileRecord) -> str:
    if not raw or not isinstance(raw, str):
        return rec.name
    raw = raw.strip().strip("\"'`")
    raw = raw.replace("\\", "/").split("/")[-1]
    stem = raw
    if rec.ext and stem.lower().endswith(rec.ext.lower()):
        stem = stem[: -len(rec.ext)]
    else:
        stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", stem)
    stem = _slug(stem)[:64]
    if not stem:
        stem = _clean_stem(rec.name)[:64] or "untitled"
    return stem + rec.ext.lower()


def drop_bogus_date(name: str, rec: scanner.FileRecord) -> str:
    """A small model loves stamping today's date on everything. Don't let it."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})-(.+)$", name)
    if not m:
        return name
    date, rest = m.group(0)[:10], m.group(4)
    compact = date.replace("-", "")
    name_digits = re.sub(r"[^0-9]", "", rec.name)
    if compact in name_digits or date == rec.modified:
        return name
    return rest


def _clean_suggestion(rec: scanner.FileRecord, sug: dict) -> dict:
    bucket = str(sug.get("bucket") or "").strip()
    if bucket not in config.BUCKETS:
        bucket = hint_bucket(rec)
    name = drop_bogus_date(sanitize_name(str(sug.get("new_name") or ""), rec), rec)
    why = str(sug.get("why") or "").strip()
    why = re.sub(r"\s+", " ", why)[:90]
    try:
        conf = float(sug.get("confidence", 0.6))
    except (TypeError, ValueError):
        conf = 0.6
    conf = max(0.0, min(1.0, conf))
    return {
        "id": rec.id,
        "bucket": bucket,
        "new_name": name,
        "why": why,
        "confidence": conf,
        "source": "model",
    }


def reconcile(rec: scanner.FileRecord, sug: dict) -> dict:
    """Let the rules correct the model only where the evidence is objective."""
    hint = hint_bucket(rec)
    if hint == sug["bucket"]:
        # Agreement is reassuring, and objective evidence is stronger than a guess.
        if hint in HARD_BUCKETS or hint in SEMANTIC_BUCKETS:
            sug = dict(sug)
            sug["confidence"] = max(sug["confidence"], 0.9 if hint in HARD_BUCKETS else 0.8)
        return sug
    if hint == "Unsorted":
        return sug
    if hint in HARD_BUCKETS:
        sug = dict(sug)
        sug["bucket"] = hint
        sug["why"] = HINT_WHY[hint]
        sug["confidence"] = max(sug["confidence"], 0.92)
        sug["source"] = "rules+model"
        return sug
    if hint in SEMANTIC_BUCKETS and (
        sug["bucket"] in ("Documents", "Unsorted") or sug["confidence"] < 0.6
    ):
        sug = dict(sug)
        sug["bucket"] = hint
        sug["why"] = HINT_WHY[hint]
        sug["confidence"] = max(sug["confidence"], 0.78)
        sug["source"] = "rules+model"
    return sug


def _unique(bucket: str, name: str, root: Path, taken: set) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    else:
        ext = "." + ext
    candidate = name
    n = 2
    while (bucket, candidate.lower()) in taken or (
        root / config.SORTED_DIR / bucket / candidate
    ).exists():
        candidate = "%s-%d%s" % (stem, n, ext)
        n += 1
    taken.add((bucket, candidate.lower()))
    return candidate


class Planner:
    def __init__(self, model: Optional[LocalModel] = None, use_model: bool = True,
                 on_event: Optional[Callable[[dict], None]] = None):
        self.model = model or LocalModel()
        self.use_model = use_model
        self.on_event = on_event or (lambda e: None)
        self.model_used = False
        self.model_error = ""
        self.llm_seconds = 0.0

    def _emit(self, stage: str, message: str, **extra) -> None:
        event = {"stage": stage, "message": message}
        event.update(extra)
        self.on_event(event)

    def _sort_batch(self, records: List[scanner.FileRecord]) -> List[dict]:
        """One model call per small batch; split and retry rather than give up."""
        files = []
        for r in records:
            view = r.prompt_view()
            view["hint"] = hint_bucket(r)
            files.append(view)
        payload = {
            "today": datetime.now().strftime("%Y-%m-%d"),
            "files": files,
        }
        system = config.SYSTEM_PROMPT.format(buckets=", ".join(config.BUCKETS))
        user = (
            "Sort these %d files. Return JSON only.\n\n%s"
            % (len(records), json.dumps(payload, ensure_ascii=False))
        )
        t0 = time.time()
        try:
            out = self.model.complete_json(system, user, max_tokens=450 + 110 * len(records))
            self.llm_seconds += time.time() - t0
            self.model_used = True
        except Exception as e:
            self.model_error = str(e)
            if len(records) > 2:
                mid = len(records) // 2
                return self._sort_batch(records[:mid]) + self._sort_batch(records[mid:])
            self._emit("warn", "Model stumbled on one batch; using careful rules.")
            return [fallback_suggestion(r) for r in records]

        by_id = {}
        items = out.get("files")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    by_id[str(item["id"])] = item

        suggestions = []
        for rec in records:
            sug = by_id.get(rec.id)
            if sug:
                suggestions.append(_clean_suggestion(rec, sug))
            else:
                suggestions.append(fallback_suggestion(rec))
        return suggestions

    def build(self, root: Path, limit: int = None) -> dict:
        root = Path(root).expanduser().resolve()
        self._emit("scan", "Looking around %s" % root)
        records, skipped = scanner.scan(root, limit=limit)
        if not records:
            raise ValueError("Nothing to tidy in %s." % root)

        self._emit("read", "Found %d files. Reading the room." % len(records),
                   total=len(records), done=0)

        effective = "model" if self.use_model else "rules"
        if self.use_model:
            try:
                self.model.ensure(progress=lambda m: self._emit("wake", m))
            except ModelUnavailable as e:
                effective = "rules"
                self.model_error = str(e)
                self._emit("warn", "No local model available, so I'll use careful rules.")

        suggestions: List[dict] = []
        if effective == "model":
            for i in range(0, len(records), config.BATCH_SIZE):
                batch = records[i:i + config.BATCH_SIZE]
                self._emit(
                    "sort",
                    "Considering %d of %d..." % (min(i + len(batch), len(records)), len(records)),
                    done=i, total=len(records),
                    names=[r.name for r in batch],
                )
                suggestions.extend(self._sort_batch(batch))
                self._emit("progress", "Sorted %d of %d" % (i + len(batch), len(records)),
                           done=i + len(batch), total=len(records))
        else:
            for rec in records:
                suggestions.append(fallback_suggestion(rec))
                self._emit("progress", "Sorted %d of %d" % (len(suggestions), len(records)),
                           done=len(suggestions), total=len(records))

        sug_by_id = {s["id"]: s for s in suggestions}
        taken = set()
        files = []
        for rec in records:
            sug = reconcile(rec, sug_by_id.get(rec.id, fallback_suggestion(rec)))
            final_name = _unique(sug["bucket"], sug["new_name"], root, taken)
            flagged = sug["confidence"] < 0.55 or sug["bucket"] == "Unsorted"
            files.append({
                "id": rec.id,
                "path": str(rec.path),
                "name": rec.name,
                "size": rec.size,
                "modified": rec.modified,
                "kind": rec.kind,
                "bucket": sug["bucket"],
                "new_name": final_name,
                "why": sug["why"],
                "confidence": round(sug["confidence"], 2),
                "source": sug["source"],
                "flagged": flagged,
                "status": "pending",
            })

        stats = {
            "files": len(files),
            "buckets": len({f["bucket"] for f in files}),
            "bytes": sum(f["size"] for f in files),
            "flagged": sum(1 for f in files if f["flagged"]),
            "skipped": len(skipped),
        }
        plan = {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4],
            "created": datetime.now().isoformat(timespec="seconds"),
            "root": str(root),
            "files": files,
            "skipped": skipped[:20],
            "stats": stats,
            "status": "preview",
            "model_used": effective == "model",
            "model_error": self.model_error,
            "llm_seconds": round(self.llm_seconds, 1),
            "model": self.model.info(),
            "note": self._note(files, stats),
        }
        self._emit("done", plan["note"], plan=plan)
        return plan

    def _note(self, files: List[dict], stats: dict) -> str:
        counts = {}
        for f in files:
            counts[f["bucket"]] = counts.get(f["bucket"], 0) + 1
        many = "%d files tucked into %d piles" % (stats["files"], stats["buckets"])
        if not counts:
            return many + "."
        high = max(counts.values())
        tops = [b for b, n in counts.items() if n == high]
        named = " and ".join(tops[:2])
        verb = "were" if len(tops) > 1 else "was"
        if stats["flagged"]:
            return "%s. %s %s the busiest, and %d are still asking for a second look." % (
                many, named, verb, stats["flagged"]
            )
        return "%s. %s %s the busiest. Nothing is asking for you right now." % (many, named, verb)
