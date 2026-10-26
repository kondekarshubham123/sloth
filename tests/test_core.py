"""Fast tests for the parts that touch your files. No model needed."""
from __future__ import annotations

import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sloth import config, netguard, scanner, store  # noqa: E402
from sloth.llm import extract_json  # noqa: E402
from sloth.planner import fallback_suggestion, sanitize_name, _unique  # noqa: E402


class TempHome(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (config.HOME, config.PLANS_DIR, config.RUNS_DIR, config.BRIEFINGS_DIR, config.CACHE_DIR)
        config.HOME = Path(self.tmp.name) / ".sloth"
        config.PLANS_DIR = config.HOME / "plans"
        config.RUNS_DIR = config.HOME / "runs"
        config.BRIEFINGS_DIR = config.HOME / "briefings"
        config.CACHE_DIR = config.HOME / "cache"
        config.ensure_dirs()
        self.root = Path(self.tmp.name) / "messy"
        self.root.mkdir()

    def tearDown(self):
        (config.HOME, config.PLANS_DIR, config.RUNS_DIR, config.BRIEFINGS_DIR, config.CACHE_DIR) = self.old
        self.tmp.cleanup()


class ParsingTests(unittest.TestCase):
    def test_fenced_json(self):
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_json_with_prose_and_trailing_comma(self):
        text = 'Sure! Here is the plan:\n{"files":[{"id":"f1",},],}\nHope that helps.'
        self.assertEqual(extract_json(text)["files"][0]["id"], "f1")

    def test_no_json(self):
        with self.assertRaises(ValueError):
            extract_json("I would rather nap.")


class NamingTests(TempHome):
    def test_sanitize(self):
        rec = scanner.FileRecord("f1", Path("/tmp/x.pdf"), "x.pdf", ".pdf", 10, "2026-01-01", "application/pdf")
        self.assertEqual(
            sanitize_name("../../Invoices/Acme Invoice #8842.PDF", rec),
            "acme-invoice-8842.pdf",
        )

    def test_sanitize_keeps_original_ext(self):
        rec = scanner.FileRecord("f1", Path("/tmp/x.heic"), "x.heic", ".heic", 10, "2026-01-01", "image/heic")
        self.assertEqual(sanitize_name("holiday snap.jpg", rec), "holiday-snap.heic")

    def test_unique_name(self):
        (self.root / "Sloth Sorted" / "Images").mkdir(parents=True)
        (self.root / "Sloth Sorted" / "Images" / "cat.png").write_bytes(b"x")
        taken = set()
        one = _unique("Images", "cat.png", self.root, taken)
        two = _unique("Images", "cat.png", self.root, taken)
        self.assertEqual(one, "cat-2.png")
        self.assertEqual(two, "cat-3.png")


class ScannerTests(TempHome):
    def test_scan_skips_the_right_things(self):
        (self.root / "hello.txt").write_text("A note about a dentist appointment.", encoding="utf-8")
        (self.root / ".hidden").write_text("no", encoding="utf-8")
        (self.root / "half.part").write_bytes(b"x")
        (self.root / "empty.txt").write_bytes(b"")
        (self.root / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"\x00\x00\x05\xa0\x00\x00\x03\x20")
        try:
            (self.root / "link.txt").symlink_to(self.root / "hello.txt")
        except OSError:
            pass
        records, skipped = scanner.scan(self.root)
        names = {r.name for r in records}
        self.assertIn("hello.txt", names)
        self.assertIn("shot.png", names)
        self.assertNotIn(".hidden", names)
        self.assertNotIn("half.part", names)
        self.assertNotIn("empty.txt", names)
        self.assertNotIn("link.txt", names)
        hello = next(r for r in records if r.name == "hello.txt")
        self.assertIn("dentist", hello.text)
        shot = next(r for r in records if r.name == "shot.png")
        self.assertEqual(shot.dims, (1440, 800))
        self.assertGreaterEqual(len(skipped), 4)


class FallbackTests(unittest.TestCase):
    def test_bucket_by_name_and_type(self):
        cases = [
            ("invoice acme.pdf", ".pdf", "Finance"),
            ("Screenshot 2026.png", ".png", "Screenshots"),
            ("flight to rome.txt", ".txt", "Travel"),
            ("main.py", ".py", "Code"),
            ("mystery.bin", ".bin", "Unsorted"),
        ]
        for name, ext, expected in cases:
            rec = scanner.FileRecord("f", Path("/tmp") / name, name, ext, 10, "2026-01-01", "application/octet-stream")
            self.assertEqual(fallback_suggestion(rec)["bucket"], expected, name)


class ApplyUndoTests(TempHome):
    def _plan(self, files):
        return {
            "id": "test-plan",
            "root": str(self.root),
            "files": files,
            "note": "test note",
            "model_used": False,
            "stats": {"files": len(files), "buckets": 1, "bytes": 10, "flagged": 0, "skipped": 0},
        }

    def test_move_then_undo(self):
        a = self.root / "a.txt"
        b = self.root / "b.txt"
        a.write_text("alpha")
        b.write_text("beta")
        files = [
            {"id": "f1", "path": str(a), "name": "a.txt", "bucket": "Documents",
             "new_name": "alpha-note.txt", "status": "pending", "size": 5,
             "why": "note", "confidence": 0.9, "source": "rules", "flagged": False},
            {"id": "f2", "path": str(b), "name": "b.txt", "bucket": "Documents",
             "new_name": "beta-note.txt", "status": "pending", "size": 4,
             "why": "note", "confidence": 0.9, "source": "rules", "flagged": False},
        ]
        plan = self._plan(files)
        store.save_plan(plan)
        run = store.apply_plan(plan)
        self.assertEqual(len(run["moves"]), 2)
        self.assertTrue((self.root / "Sloth Sorted" / "Documents" / "alpha-note.txt").exists())
        self.assertFalse(a.exists())
        self.assertIsNotNone(store.latest_briefing())

        result = store.undo("last")
        self.assertEqual(result["restored"], 2)
        self.assertTrue(a.exists() and b.exists())
        self.assertFalse((self.root / "Sloth Sorted").exists())
        self.assertTrue(any(r["undone"] for r in store.state()["runs"]))

    def test_apply_is_idempotent(self):
        a = self.root / "a.txt"
        a.write_text("alpha")
        plan = self._plan([{
            "id": "f1", "path": str(a), "name": "a.txt", "bucket": "Documents",
            "new_name": "alpha.txt", "status": "pending", "size": 5,
            "why": "note", "confidence": 0.9, "source": "rules", "flagged": False,
        }])
        store.save_plan(plan)
        first = store.apply_plan(plan)
        second = store.apply_plan(plan)
        self.assertEqual(len(first["moves"]), 1)
        self.assertEqual(len(second["moves"]), 0)

    def test_refuses_to_escape_root(self):
        a = self.root / "a.txt"
        a.write_text("alpha")
        plan = self._plan([{
            "id": "f1", "path": str(a), "name": "a.txt", "bucket": "../../etc",
            "new_name": "passwd", "status": "pending", "size": 5,
            "why": "evil", "confidence": 0.9, "source": "model", "flagged": False,
        }])
        with self.assertRaises(ValueError):
            store.apply_plan(plan)
        self.assertTrue(a.exists())


class AirgapTests(unittest.TestCase):
    def test_external_connections_are_blocked(self):
        netguard.install()
        with self.assertRaises(PermissionError):
            socket.create_connection(("93.184.216.34", 80), timeout=0.2)
        # Loopback is still allowed (connection refused, not forbidden).
        with self.assertRaises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", 9), timeout=0.2)
        self.assertGreaterEqual(netguard.status()["blocked"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
