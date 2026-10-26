#!/usr/bin/env python3
"""Create a pleasantly messy folder so you can try Sloth without touching your own files."""
from __future__ import annotations

import argparse
import os
import random
import shutil
import struct
import zlib
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "messy Downloads"
random.seed(7)


def png_bytes(w: int, h: int, top: tuple, bottom: tuple) -> bytes:
    rows = bytearray()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        rows.append(0)
        rows.extend(bytes((r, g, b)) * w)
    raw = zlib.compress(bytes(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def jpeg_bytes(w: int, h: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
           + struct.pack(">HH", h, w) + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01")
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


FILES = [
    # name, content, days_ago, kind
    ("notes for dr patel.txt",
     "Appointment moved to Tuesday 4:30pm. Bring the blood test results from March. "
     "Ask about the new prescription and whether the dizziness is normal.", 9, "text"),
    ("flight confirmation BA 249.txt",
     "British Airways BA249\nLondon Heathrow -> Rio de Janeiro\n12 March 2026, 21:40\n"
     "Seat 42A. Booking reference K7P2QN. Baggage: 1 x 23kg.", 160, "text"),
    ("hotel booking lisbon.txt",
     "Hotel Alegria, Lisbon. Check-in 4 June 2026, check-out 8 June 2026. "
     "Booking 8812-44. Breakfast included. Free cancellation until 30 May.", 130, "text"),
    ("chemistry lecture notes.txt",
     "CHEM 201 — Week 6. Entropy and Gibbs free energy. dG = dH - T dS. "
     "Practice problems 4, 5, 9 for next seminar. Exam covers chapters 3-6.", 40, "text"),
    ("syllabus - cs101.pdf",
     "Course outline. Weekly labs, two projects, final exam. Office hours Thursday.", 210, "pdf"),
    ("thesis draft v7.pdf",
     "Chapter 3 draft with supervisor comments in the margins. Still needs a conclusion.", 24, "pdf"),
    ("client contract - acme - signed.pdf",
     "Master services agreement between Acme Studio and the client. Signed 2 Feb 2026.", 80, "pdf"),
    ("invoice-8842.pdf",
     "Acme Studio invoice 8842. Design retainer, March 2026. Amount due 4,200.00. "
     "Payment terms 14 days. Tax ID on file.", 30, "pdf"),
    ("rent receipt march.pdf",
     "Receipt for apartment rent, March 2026. Paid by bank transfer on the 1st.", 25, "pdf"),
    ("insurance claim form.pdf",
     "Health insurance claim for the physiotherapy sessions in January. "
     "Policy number redacted. Attach receipts and referral letter.", 55, "pdf"),
    ("boarding-pass-berlin.pdf",
     "Lufthansa LH 1947, Munich to Berlin, 19 September 2026, gate B12, seat 14C.", 8, "pdf"),
    ("scan0001.pdf",
     "Black and white scan, no useful header.", 300, "pdf"),
    ("resume 2026.docx", "Updated CV, two pages, last edited in January.", 120, "doc"),
    ("assignment 2 final.docx", "CS101 assignment 2: recursion and big-O. Submitted version.", 18, "doc"),
    ("client-contract-v2.docx", "Editable contract with tracked changes.", 79, "doc"),
    ("q3 budget final FINAL v3.xlsx", "Sheet1: rent, groceries, transport, savings.", 14, "xlsx"),
    ("tax stuff 2025.zip", "Archived tax documents for the 2025 filing.", 200, "zip"),
    ("download.zip", "Compressed folder from a colleague.", 12, "zip"),
    ("tax-receipts-2025.csv",
     "date,vendor,amount,currency\n2025-01-14,Office Depot,42.90,EUR\n"
     "2025-02-03,Adobe,59.99,EUR\n2025-03-11,Bahn,88.40,EUR\n", 70, "text"),
    ("bank statement feb.csv",
     "date,description,amount\n2026-02-01,rent,-1400.00\n2026-02-03,salary,3200.00\n"
     "2026-02-14,bookshop,-24.50\n", 34, "text"),
    ("main (1).py",
     "import json\n\n\ndef load(path):\n    with open(path) as fh:\n        return json.load(fh)\n\n\n"
     "if __name__ == '__main__':\n    print(load('data.json'))\n", 45, "text"),
    ("app_backup.js",
     "const express = require('express');\nconst app = express();\n"
     "app.get('/health', (req, res) => res.send('ok'));\napp.listen(3000);\n", 47, "text"),
    ("Dockerfile copy", "FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\nRUN pip install -r requirements.txt\n"
     "CMD [\"python\", \"main.py\"]\n", 44, "text"),
    ("logo-final.svg",
     "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
     "<circle cx='50' cy='50' r='40' fill='#56684b'/></svg>", 60, "text"),
    ("logo-final-v2.svg",
     "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
     "<rect x='15' y='15' width='70' height='70' rx='18' fill='#b06f4c'/></svg>", 58, "text"),
    ("data export (3).json", '{"exported_at":"2026-04-02","rows":184,"status":"complete"}', 52, "text"),
    ("recipe - banana bread.txt",
     "3 ripe bananas, 2 eggs, 180g flour, 100g sugar, 80g butter, 1 tsp baking soda. "
     "Bake at 175C for 55 minutes. Add walnuts if we have them.", 100, "text"),
    ("gym plan.txt", "Mon: legs. Wed: push. Fri: pull. Saturday: long walk, no phone.", 66, "text"),
    ("prescription refill.txt", "Refill request sent to the pharmacy. Pick up Thursday after 10am.", 11, "text"),
    ("todo.txt", "call mum\nfix the bike light\nbook dentist\ncancel that trial\nwater the plants", 3, "text"),
    ("Screenshot 2026-03-14 at 10.22.31.png", "", 30, "shot-wide"),
    ("Screenshot_2026-06-01.png", "", 6, "shot-phone"),
    ("Screenshot 2026-05-20 at 18.04.12.png", "", 17, "shot-wide"),
    ("IMG_4821.HEIC", "", 120, "heic"),
    ("IMG_20250912_143322.jpg", "", 95, "jpg"),
    ("headshot.jpg", "", 210, "jpg"),
    ("IMG_5501.MOV", "", 42, "video"),
    ("voice memo 4.m4a", "", 22, "audio"),
    ("podcast-ep12.mp3", "", 12, "audio"),
]

SKIPPED = [
    (".DS_Store", b"\x00\x00\x00\x01Bud1"),
    ("movie.mp4.crdownload", b"partial download"),
    ("empty.txt", b""),
    (".hidden-notes.txt", b"not for the sloth"),
]


def write(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    now = datetime.now()

    for name, content, days_ago, kind in FILES:
        path = root / name
        mtime = (now - timedelta(days=days_ago, hours=random.randint(0, 12))).timestamp()
        if kind == "text":
            path.write_text(content, encoding="utf-8")
        elif kind in ("pdf", "doc", "xlsx", "zip"):
            header = {
                "pdf": b"%PDF-1.4\n",
                "doc": b"PK\x03\x04",
                "xlsx": b"PK\x03\x04",
                "zip": b"PK\x03\x04",
            }[kind]
            body = content.encode("utf-8")
            path.write_bytes(header + body + b"\n" + os.urandom(1200))
        elif kind == "shot-wide":
            path.write_bytes(png_bytes(1440, 900, (238, 234, 222), (205, 214, 196)))
        elif kind == "shot-phone":
            path.write_bytes(png_bytes(1170, 2532, (250, 248, 240), (30, 34, 30)))
        elif kind == "heic":
            path.write_bytes(b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + os.urandom(2400))
        elif kind == "jpg":
            path.write_bytes(jpeg_bytes(4032, 3024) + os.urandom(1800))
        elif kind == "video":
            path.write_bytes(b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  " + os.urandom(6000))
        elif kind == "audio":
            path.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + os.urandom(2200))
        os.utime(path, (mtime, mtime))

    for name, data in SKIPPED:
        path = root / name
        path.write_bytes(data)
        if name != ".DS_Store":
            mtime = (now - timedelta(days=5)).timestamp()
            os.utime(path, (mtime, mtime))

    # A symlink the sloth must refuse to follow.
    try:
        (root / "shortcut to notes").symlink_to(root / "notes for dr patel.txt")
    except OSError:
        pass

    # A nested folder, because mess is recursive.
    nested = root / "old phone backup"
    nested.mkdir()
    for i, label in enumerate(("IMG_0031.jpg", "IMG_0032.jpg", "notes.txt")):
        p = nested / label
        if label.endswith(".txt"):
            p.write_text("Old phone notes: wifi password was on the fridge. Taxi number 555-0142.", encoding="utf-8")
        else:
            p.write_bytes(jpeg_bytes(3024, 4032) + os.urandom(900))
        mtime = (now - timedelta(days=400 + i)).timestamp()
        os.utime(p, (mtime, mtime))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="replace an existing demo folder")
    args = parser.parse_args()
    if ROOT.exists() and not args.force:
        print("Demo folder already exists: %s" % ROOT)
        print("Use --force to rebuild it.")
        return
    write(ROOT)
    count = sum(1 for p in ROOT.rglob("*") if p.is_file() or p.is_symlink())
    size = sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file())
    print("Built a messy demo folder with %d entries (%.1f MB)." % (count, size / 1e6))
    print(ROOT)


if __name__ == "__main__":
    main()
