"""Plans on disk, moves you can undo, and a morning note."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import config


def _write_json(path: Path, data: dict) -> None:
    config.ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def save_plan(plan: dict) -> Path:
    config.ensure_dirs()
    path = config.PLANS_DIR / ("%s.json" % plan["id"])
    _write_json(path, plan)
    return path


def load_plan(plan_id: str) -> dict:
    path = config.PLANS_DIR / ("%s.json" % plan_id)
    if not path.exists():
        raise FileNotFoundError("No such plan: %s" % plan_id)
    return json.loads(path.read_text(encoding="utf-8"))


def list_plans(limit: int = 8) -> List[dict]:
    config.ensure_dirs()
    out = []
    for p in sorted(config.PLANS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "id": d.get("id"),
                "created": d.get("created"),
                "root": d.get("root"),
                "status": d.get("status"),
                "stats": d.get("stats"),
                "note": d.get("note"),
                "model_used": d.get("model_used"),
            })
        except Exception:
            continue
    return out


def _journal_path() -> Path:
    config.ensure_dirs()
    return config.HOME / "journal.jsonl"


def append_journal(entry: dict) -> None:
    config.ensure_dirs()
    with _journal_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_journal() -> List[dict]:
    path = _journal_path()
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except Exception:
            continue
    return entries


def _safe_destination(root: Path, bucket: str, name: str) -> Path:
    dest = (root / config.SORTED_DIR / bucket / name).resolve()
    if root.resolve() not in dest.parents:
        raise ValueError("Refusing to write outside the folder being tidied.")
    return dest


def apply_plan(plan: dict, ids: Optional[List[str]] = None) -> dict:
    root = Path(plan["root"]).resolve()
    chosen = set(ids) if ids else None
    moves = []
    skipped = []
    taken = set()

    for f in plan["files"]:
        if chosen is not None and f["id"] not in chosen:
            continue
        if f.get("status") not in ("pending", "preview"):
            continue
        src = Path(f["path"])
        if not src.exists() or not src.is_file():
            skipped.append({"name": f["name"], "reason": "moved since the plan was made"})
            continue
        dest = _safe_destination(root, f["bucket"], f["new_name"])
        if dest.exists():
            stem, dot, ext = f["new_name"].rpartition(".")
            n = 2
            while dest.exists():
                candidate = "%s-%d.%s" % (stem, n, ext) if dot else "%s-%d" % (f["new_name"], n)
                dest = _safe_destination(root, f["bucket"], candidate)
                n += 1
            f["new_name"] = dest.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(dest))
            moves.append({
                "from": str(src),
                "to": str(dest),
                "bucket": f["bucket"],
                "name": f["name"],
                "new_name": dest.name,
                "size": f.get("size", 0),
            })
            f["status"] = "moved"
            taken.add(dest)
        except OSError as e:
            skipped.append({"name": f["name"], "reason": str(e)})

    piles = len({m["bucket"] for m in moves})
    left = sum(1 for f in plan["files"] if f.get("status") == "pending")
    note = "%d files tucked into %d %s." % (len(moves), piles, "pile" if piles == 1 else "piles")
    if left:
        note += " %d left exactly where they were." % left
    run = {
        "type": "apply",
        "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4],
        "plan_id": plan["id"],
        "at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "moves": moves,
        "skipped": skipped,
        "note": note,
        "model_used": plan.get("model_used", False),
    }
    if moves:
        append_journal(run)
        plan["status"] = "applied"
        plan["applied_at"] = run["at"]
        plan["run_id"] = run["id"]
        save_plan(plan)
        write_briefing(plan, run)
    return run


def write_briefing(plan: dict, run: dict) -> Path:
    config.ensure_dirs()
    now = datetime.now()
    path = config.BRIEFINGS_DIR / ("%s.md" % now.strftime("%Y-%m-%d-%H%M"))
    piles: Dict[str, List[str]] = {}
    for m in run["moves"]:
        piles.setdefault(m["bucket"], []).append(m["new_name"])
    lines = [
        "# A quieter folder",
        "",
        "_%s · %s_" % (now.strftime("%A, %d %B %Y, %H:%M"), plan["root"]),
        "",
        run.get("note", ""),
        "",
    ]
    for bucket in sorted(piles):
        lines.append("## %s" % bucket)
        for name in piles[bucket]:
            lines.append("- %s" % name)
        lines.append("")
    if plan.get("stats", {}).get("flagged"):
        lines.append(
            "> %d files were marked for a second look and left where they were. "
            "Nothing is lost; they can wait." % plan["stats"]["flagged"]
        )
        lines.append("")
    lines.append("_Sorted locally by %s. No file left this laptop._" % (
        "Qwen2.5 + llama.cpp" if plan.get("model_used") else "careful rules"
    ))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def latest_briefing() -> Optional[dict]:
    config.ensure_dirs()
    files = sorted(config.BRIEFINGS_DIR.glob("*.md"), reverse=True)
    if not files:
        return None
    p = files[0]
    return {"name": p.name, "at": p.stat().st_mtime, "text": p.read_text(encoding="utf-8")}


def undo(run_id: str = "last") -> dict:
    entries = read_journal()
    applies = [e for e in entries if e.get("type") == "apply"]
    undone = {e.get("undo_of") for e in entries if e.get("type") == "undo"}
    available = [e for e in applies if e["id"] not in undone]
    if not available:
        return {"restored": 0, "conflicts": [], "error": "Nothing to undo."}
    if run_id in ("last", "", None):
        target = available[-1]
    else:
        target = next((e for e in available if e["id"] == run_id), None)
        if not target:
            return {"restored": 0, "conflicts": [], "error": "That run is already undone or unknown."}

    restored = 0
    conflicts = []
    for move in reversed(target.get("moves", [])):
        src = Path(move["from"])
        dst = Path(move["to"])
        if not dst.exists():
            conflicts.append({"name": move["new_name"], "reason": "already moved elsewhere"})
            continue
        if src.exists():
            conflicts.append({"name": move["new_name"], "reason": "a file with the old name exists"})
            continue
        try:
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(src))
            restored += 1
        except OSError as e:
            conflicts.append({"name": move["new_name"], "reason": str(e)})

    # Tidy up empty bucket folders.
    for folder in sorted(
        (Path(target["root"]) / config.SORTED_DIR).rglob("*"), key=lambda p: len(p.parts), reverse=True
    ):
        try:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            pass
    sorted_root = Path(target["root"]) / config.SORTED_DIR
    try:
        if sorted_root.is_dir() and not any(sorted_root.iterdir()):
            sorted_root.rmdir()
    except OSError:
        pass

    entry = {
        "type": "undo",
        "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4],
        "undo_of": target["id"],
        "at": datetime.now().isoformat(timespec="seconds"),
        "restored": restored,
        "conflicts": conflicts,
    }
    append_journal(entry)
    try:
        plan = load_plan(target["plan_id"])
        plan["status"] = "undone"
        for f in plan["files"]:
            if f.get("status") == "moved":
                f["status"] = "pending"
        save_plan(plan)
    except Exception:
        pass
    return {"restored": restored, "conflicts": conflicts, "run_id": target["id"]}


def state() -> dict:
    entries = read_journal()
    undone = {e.get("undo_of") for e in entries if e.get("type") == "undo"}
    runs = []
    for e in entries:
        if e.get("type") != "apply":
            continue
        runs.append({
            "id": e["id"],
            "at": e["at"],
            "root": e["root"],
            "moved": len(e.get("moves", [])),
            "undone": e["id"] in undone,
            "note": e.get("note", ""),
        })
    return {
        "plans": list_plans(6),
        "runs": runs[-6:][::-1],
        "briefing": latest_briefing(),
    }
