"""A dependency-free local app for the Wedding Guest Manager prototype.

Run with: python server.py
Then open: http://127.0.0.1:8000
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent
DB_PATH = ROOT / "wedding_guest_manager.db"
EVENT = {"names": "Aria & Kiran", "date": "2026-12-12", "location": "Jaipur", "rsvp_closes": "2026-11-20"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connection() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def initialize() -> None:
    db = connection()
    db.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS guests (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          household TEXT NOT NULL,
          email TEXT,
          party_size INTEGER NOT NULL DEFAULT 1 CHECK(party_size BETWEEN 0 AND 12),
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('confirmed','declined','pending')),
          token_hash TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reminder_log (
          id INTEGER PRIMARY KEY,
          guest_id INTEGER NOT NULL REFERENCES guests(id),
          sent_at TEXT NOT NULL,
          channel TEXT NOT NULL DEFAULT 'email'
        );
        """
    )
    has_rows = db.execute("SELECT 1 FROM guests LIMIT 1").fetchone()
    if not has_rows:
        seed = [
            ("Meera Kapoor", "Kapoor family", "meera@example.test", 4, "confirmed"),
            ("Siddharth Mehta", "Mehta family", "siddharth@example.test", 2, "confirmed"),
            ("Naina Singh", "Naina Singh", "naina@example.test", 0, "declined"),
            ("Rohan & Tara Shah", "Shah family", "shah@example.test", 3, "pending"),
            ("Aditi Bansal", "Bansal family", "aditi@example.test", 2, "pending"),
            ("Vikram Rao", "Rao family", "vikram@example.test", 2, "confirmed"),
            ("Ishaan Verma", "Verma family", "ishaan@example.test", 1, "pending"),
        ]
        stamp = now()
        db.executemany(
            "INSERT INTO guests(name, household, email, party_size, status, token_hash, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            [(name, household, email, party, status, hashlib.sha256(secrets.token_urlsafe(24).encode()).hexdigest(), stamp, stamp) for name, household, email, party, status in seed],
        )
    db.commit(); db.close()


def safe_guest(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"], "household": row["household"], "email": row["email"], "party": row["party_size"], "status": row["status"], "updated": row["updated_at"]}


class App(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 100_000: raise ValueError("Request is too large")
        try: return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as error: raise ValueError("Invalid JSON") from error

    def send_json(self, payload, code=HTTPStatus.OK):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/event": return self.send_json(EVENT)
        if path == "/api/dashboard": return self.dashboard()
        if path == "/api/guests": return self.list_guests()
        if path == "/api/export.csv": return self.export_csv()
        if path.startswith("/rsvp/"):
            return self.serve_rsvp(path.rsplit("/", 1)[-1])
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/guests": return self.add_guest(payload)
            if path == "/api/reminders": return self.queue_reminders()
            if path.startswith("/api/rsvp/"): return self.record_rsvp(path.rsplit("/", 1)[-1], payload)
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def dashboard(self):
        db = connection()
        rows = db.execute("SELECT status, party_size, household FROM guests").fetchall(); db.close()
        total = len(rows); confirmed = sum(r["status"] == "confirmed" for r in rows); declined = sum(r["status"] == "declined" for r in rows); pending = total - confirmed - declined
        self.send_json({"total": total, "confirmed": confirmed, "declined": declined, "pending": pending, "headcount": sum(r["party_size"] for r in rows if r["status"] == "confirmed"), "households": len({r["household"] for r in rows})})

    def list_guests(self):
        params = parse_qs(urlparse(self.path).query); status = params.get("status", ["all"])[0]
        db = connection(); query = "SELECT * FROM guests"; values = []
        if status in ("confirmed", "declined", "pending"): query += " WHERE status=?"; values.append(status)
        rows = db.execute(query + " ORDER BY updated_at DESC, id DESC", values).fetchall(); db.close()
        self.send_json([safe_guest(row) for row in rows])

    def add_guest(self, payload):
        name = str(payload.get("name", "")).strip(); household = str(payload.get("household", "")).strip() or name
        email = str(payload.get("email", "")).strip(); status = payload.get("status", "pending")
        try: party = int(payload.get("party", 1))
        except (ValueError, TypeError): party = -1
        if not name or len(name) > 120: raise ValueError("A guest name of up to 120 characters is required")
        if status not in ("confirmed", "declined", "pending"): raise ValueError("Invalid response status")
        if party < 1 or party > 12: raise ValueError("Party size must be between 1 and 12")
        if status == "declined": party = 0
        stamp = now(); raw_token = secrets.token_urlsafe(24); token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        db = connection(); cursor = db.execute("INSERT INTO guests(name, household, email, party_size, status, token_hash, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)", (name, household, email, party, status, token_hash, stamp, stamp)); db.commit(); row = db.execute("SELECT * FROM guests WHERE id=?", (cursor.lastrowid,)).fetchone(); db.close()
        guest = safe_guest(row); guest["rsvp_path"] = f"/rsvp/{raw_token}"; self.send_json(guest, HTTPStatus.CREATED)

    def queue_reminders(self):
        db = connection(); rows = db.execute("SELECT id FROM guests WHERE status='pending'").fetchall(); stamp = now()
        db.executemany("INSERT INTO reminder_log(guest_id, sent_at) VALUES(?,?)", [(row["id"], stamp) for row in rows]); db.commit(); db.close()
        self.send_json({"queued": len(rows), "message": f"Queued {len(rows)} reminder(s). This local demo logs sends but does not email real contacts."})

    def export_csv(self):
        db = connection(); rows = db.execute("SELECT name, household, email, party_size, status, updated_at FROM guests ORDER BY name").fetchall(); db.close()
        output = io.StringIO(); writer = csv.writer(output); writer.writerow(["Guest", "Household", "Email", "Party Size", "Response", "Last Updated"])
        writer.writerows([[r["name"], r["household"], r["email"], r["party_size"], r["status"], r["updated_at"]] for r in rows]); data = output.getvalue().encode("utf-8")
        self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "text/csv; charset=utf-8"); self.send_header("Content-Disposition", 'attachment; filename="wedding-guest-list.csv"'); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def guest_from_token(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest(); db = connection(); row = db.execute("SELECT * FROM guests WHERE token_hash=?", (digest,)).fetchone(); db.close(); return row

    def serve_rsvp(self, token):
        row = self.guest_from_token(token)
        if not row: return self.send_json({"error": "This RSVP link is invalid."}, HTTPStatus.NOT_FOUND)
        self.send_json({"guest": {"name": row["name"], "party": row["party_size"], "status": row["status"]}, "event": EVENT})

    def record_rsvp(self, token, payload):
        row = self.guest_from_token(token)
        if not row: return self.send_json({"error": "This RSVP link is invalid."}, HTTPStatus.NOT_FOUND)
        status = payload.get("status");
        try: party = int(payload.get("party", 1))
        except (ValueError, TypeError): party = -1
        if status not in ("confirmed", "declined") or party < 1 or party > 12: raise ValueError("Please choose a valid response and party size")
        if status == "declined": party = 0
        db = connection(); db.execute("UPDATE guests SET status=?, party_size=?, updated_at=? WHERE id=?", (status, party, now(), row["id"])); db.commit(); db.close(); self.send_json({"ok": True})


if __name__ == "__main__":
    initialize(); print("Wedding Guest Manager running at http://127.0.0.1:8000"); ThreadingHTTPServer(("127.0.0.1", 8000), App).serve_forever()
