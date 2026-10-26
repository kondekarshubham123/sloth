"""Command line: sloth scan / apply / undo / ui / night / doctor."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import config, netguard, store
from .llm import LocalModel, ModelUnavailable
from .planner import Planner

TTY = sys.stdout.isatty()


def c(text: str, code: str) -> str:
    return "\033[%sm%s\033[0m" % (code, text) if TTY else text


BOLD = lambda s: c(s, "1")
DIM = lambda s: c(s, "2")
MOSS = lambda s: c(s, "38;5;65")
CLAY = lambda s: c(s, "38;5;173")


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%d B" % n


def _progress(event: dict) -> None:
    stage = event.get("stage")
    msg = event.get("message", "")
    if stage in ("scan", "wake"):
        print("  " + DIM(msg))
    elif stage == "read":
        print("  " + DIM(msg))
    elif stage == "sort":
        done, total = event.get("done", 0), event.get("total", 0)
        print("  " + MOSS("·") + " reading files %d–%d of %d" % (
            done + 1, min(done + len(event.get("names", [])), total), total
        ))
    elif stage == "warn":
        print("  " + CLAY("! " + msg))
    elif stage == "progress" and event.get("done") == event.get("total"):
        print("  " + DIM("done thinking"))


def _show_plan(plan: dict) -> None:
    stats = plan["stats"]
    print()
    print("  " + BOLD(plan.get("note") or "A plan is ready."))
    print()
    if not plan.get("model_used"):
        print("  " + CLAY("Sorted with careful rules (no local model was used)."))
        if plan.get("model_error"):
            print("  " + DIM(plan["model_error"].splitlines()[0]))
        print()
    by_bucket = {}
    for f in plan["files"]:
        by_bucket.setdefault(f["bucket"], []).append(f)
    for bucket in config.BUCKETS:
        files = by_bucket.get(bucket)
        if not files:
            continue
        print("  " + MOSS(bucket) + DIM("  (%d)" % len(files)))
        for f in files:
            flag = " *" if f["flagged"] else ""
            old = f["name"]
            new = f["new_name"]
            name = "%s → %s" % (old, new) if old != new else new
            print("    " + name + DIM("  %s" % _size(f["size"])) + (CLAY(flag) if flag else ""))
        print()
    print("  " + DIM(
        "%d files · %d piles · %s · %d need a look%s" % (
            stats["files"], stats["buckets"], _size(stats["bytes"]), stats["flagged"],
            (" · LLM %.1fs" % plan["llm_seconds"]) if plan.get("llm_seconds") else "",
        )
    ))
    print("  " + DIM("Plan: %s" % (config.PLANS_DIR / (plan["id"] + ".json"))))
    print()
    print("  Tuck them away:  " + BOLD("./sloth apply %s --yes" % plan["id"]))
    print("  Change your mind: " + BOLD("./sloth apply %s" % plan["id"]) + DIM(" (review first)"))
    print()


def _pick_plan(plan_id: str = None) -> dict:
    if plan_id and plan_id != "last":
        return store.load_plan(plan_id)
    plans = [p for p in store.list_plans(20) if p.get("status") == "preview"]
    if not plans:
        raise SystemExit("No preview plan waiting. Run ./sloth scan first.")
    return store.load_plan(plans[0]["id"])


def cmd_scan(args) -> int:
    netguard.install()
    root = Path(args.folder).expanduser() if args.folder else config.demo_root()
    if not root.exists():
        print("  That folder does not exist: %s" % root)
        return 2
    print()
    print("  " + BOLD("Sloth") + DIM("  ·  sorting %s" % root))
    print()
    model = LocalModel(autostart=not args.no_model)
    planner = Planner(model=model, use_model=not args.no_model, on_event=_progress)
    try:
        plan = planner.build(root, limit=args.limit)
    except ModelUnavailable as e:
        print("\n  " + CLAY(str(e)))
        return 3
    finally:
        if model.proc:
            model.stop()
    store.save_plan(plan)
    _show_plan(plan)
    if args.json:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


def cmd_apply(args) -> int:
    plan = _pick_plan(args.plan_id)
    if plan.get("status") != "preview":
        print("  That plan is %s, not waiting to be applied." % plan.get("status"))
        return 2
    pending = [f for f in plan["files"] if f.get("status") in ("pending", "preview")]
    if not pending:
        print("  Nothing pending in that plan.")
        return 2
    print("\n  %s" % BOLD(plan.get("note") or "Ready to tidy."))
    print("  %d files will move into %s/" % (len(pending), config.SORTED_DIR))
    print()
    if not args.yes:
        if not sys.stdin.isatty():
            print("  Not a terminal. Re-run with --yes to apply.")
            return 2
        answer = input("  Tuck them away? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("  Left everything exactly where it was.")
            return 0
    run = store.apply_plan(plan)
    print("  " + MOSS("Done.") + " %d files tucked into %d piles." % (
        len(run["moves"]), len({m["bucket"] for m in run["moves"]})
    ))
    if run["skipped"]:
        print("  " + DIM("%d skipped." % len(run["skipped"])))
    print("  Undo any time: " + BOLD("./sloth undo"))
    print("  Morning note:  " + DIM(str(config.BRIEFINGS_DIR)))
    print()
    return 0


def cmd_undo(args) -> int:
    result = store.undo(args.run_id or "last")
    if result.get("error"):
        print("  " + result["error"])
        return 2
    print("  Put %d files back." % result["restored"])
    if result.get("conflicts"):
        print("  " + DIM("%d could not be restored." % len(result["conflicts"])))
    return 0


def cmd_ui(args) -> int:
    from .server import serve
    serve(port=args.port, open_browser=args.open)
    return 0


def _next_run(at: str) -> datetime:
    try:
        hh, mm = [int(x) for x in at.split(":")]
    except Exception:
        hh, mm = 3, 0
    now = datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def cmd_night(args) -> int:
    netguard.install()
    root = Path(args.folder).expanduser() if args.folder else config.demo_root()
    if not root.exists():
        print("  That folder does not exist: %s" % root)
        return 2
    while True:
        if args.once:
            print("\n  " + BOLD("Sloth night shift") + DIM("  ·  %s" % root))
        else:
            target = _next_run(args.at)
            secs = (target - datetime.now()).total_seconds()
            print("\n  Next quiet pass: %s (in %s). Ctrl-C to wake me." % (
                target.strftime("%Y-%m-%d %H:%M"), str(timedelta(seconds=int(secs)))
            ))
            time.sleep(secs)
        model = LocalModel()
        planner = Planner(model=model, on_event=_progress)
        try:
            plan = planner.build(root, limit=args.limit)
            store.save_plan(plan)
            if args.apply:
                run = store.apply_plan(plan)
                print("  " + MOSS("Tidied %d files while you were away." % len(run["moves"])))
                print("  " + DIM(str(config.BRIEFINGS_DIR)))
            else:
                print("  " + DIM("Plan saved for review: %s" % plan["id"]))
        except Exception as e:
            print("  " + CLAY("Night shift stumbled: %s" % e))
        finally:
            if model.proc:
                model.stop()
        if args.once:
            return 0
        if not args.repeat:
            return 0


def cmd_doctor(args) -> int:
    netguard.install()
    print()
    print("  " + BOLD("Sloth doctor"))
    print()
    ok = True
    checks = []
    checks.append(("Python", "%d.%d.%d" % sys.version_info[:3], True))
    checks.append(("Home", str(config.HOME), True))

    model = LocalModel()
    info = model.info()
    checks.append(("Weights", "%s (%s GB)" % (info["model"], info["model_gb"]),
                   config.MODEL_PATH.exists()))
    checks.append(("Engine", "%s (%s)" % (info["engine"], info["backend"]),
                   config.LLAMA_SERVER.exists()))
    checks.append(("Checksum", info["sha"], info["sha"] not in ("missing",)))
    checks.append(("Server", info["endpoint"] + (" awake" if info["healthy"] else " asleep"),
                   True))
    checks.append(("Airgap", "outbound connections blocked" if netguard.status()["active"] else "off",
                   netguard.status()["active"]))
    test_dir = config.HOME
    try:
        probe = test_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        checks.append(("Writable", str(test_dir), True))
    except Exception:
        checks.append(("Writable", str(test_dir), False))
        ok = False

    for label, value, good in checks:
        mark = MOSS("✓") if good else CLAY("✗")
        if not good:
            ok = False
        print("    %s  %-9s %s" % (mark, label, value))
    print()
    if not config.MODEL_PATH.exists() or not config.LLAMA_SERVER.exists():
        print("  " + CLAY("Run ./setup.sh to build llama.cpp and fetch the model."))
    else:
        print("  " + DIM("Offline check: every byte above is on this machine."))
    print()
    return 0 if ok else 1


def cmd_demo(args) -> int:
    import subprocess
    script = config.REPO / "demo" / "make_demo.py"
    if not script.exists():
        print("  Demo script missing: %s" % script)
        return 2
    subprocess.run([sys.executable, str(script), "--force"])
    print("  Demo folder: %s" % config.demo_root())
    print("  Try: ./sloth scan")
    return 0


def cmd_models(args) -> int:
    print("\n  Running on:")
    print(json.dumps(LocalModel().info(), indent=2))
    print("\n  Swap the weights by setting SLOTH_MODEL=/path/to/other.gguf")
    print("  Any llama.cpp-compatible GGUF works.\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sloth",
        description="A quiet, offline file tidier. Slow on purpose.",
    )
    p.add_argument("--version", action="version", version="sloth 1.0")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("scan", help="look at a folder and draft a plan")
    s.add_argument("folder", nargs="?", help="folder to tidy (default: demo folder)")
    s.add_argument("--limit", type=int, default=config.MAX_FILES)
    s.add_argument("--no-model", action="store_true", help="use careful rules only")
    s.add_argument("--json", action="store_true", help="also print the plan as JSON")
    s.set_defaults(func=cmd_scan)

    a = sub.add_parser("apply", help="move the files in a plan")
    a.add_argument("plan_id", nargs="?", default="last")
    a.add_argument("--yes", action="store_true")
    a.set_defaults(func=cmd_apply)

    u = sub.add_parser("undo", help="put the last run back")
    u.add_argument("run_id", nargs="?", default="last")
    u.set_defaults(func=cmd_undo)

    ui = sub.add_parser("ui", help="open the local dashboard")
    ui.add_argument("--port", type=int, default=config.UI_PORT)
    ui.add_argument("--open", action="store_true")
    ui.set_defaults(func=cmd_ui)

    n = sub.add_parser("night", help="tidy on a schedule, like a sleepy housemaid")
    n.add_argument("--at", default="03:00", help="HH:MM local time")
    n.add_argument("--folder", default=None)
    n.add_argument("--limit", type=int, default=config.MAX_FILES)
    n.add_argument("--apply", action="store_true", help="move files without asking")
    n.add_argument("--once", action="store_true", help="run once now")
    n.add_argument("--repeat", action="store_true", help="keep running nightly")
    n.set_defaults(func=cmd_night)

    d = sub.add_parser("doctor", help="check the local pieces")
    d.set_defaults(func=cmd_doctor)

    m = sub.add_parser("demo", help="rebuild the messy demo folder")
    m.set_defaults(func=cmd_demo)

    mo = sub.add_parser("models", help="show the local model and how to swap it")
    mo.set_defaults(func=cmd_models)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    config.ensure_dirs()
    return args.func(args) or 0
