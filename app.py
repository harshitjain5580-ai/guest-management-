"""Production web application for Wedding Guest Manager.

The database uses SQLite locally and Render Postgres when DATABASE_URL is set.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import os
import secrets
from datetime import datetime, timezone

from flask import Flask, jsonify, redirect, request, send_from_directory, session, url_for
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

ROOT = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///wedding_guest_manager.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

EVENT = {"names": "Aria & Kiran", "date": "2026-12-12", "location": "Jaipur", "rsvp_closes": "2026-11-20"}


class Base(DeclarativeBase):
    pass


class Guest(Base):
    __tablename__ = "guests"
    __table_args__ = (CheckConstraint("party_size BETWEEN 0 AND 12", name="party_size_range"), CheckConstraint("status IN ('confirmed', 'declined', 'pending')", name="valid_status"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    household: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reminders: Mapped[list["ReminderLog"]] = relationship(back_populates="guest", cascade="all, delete-orphan")


class ReminderLog(Base):
    __tablename__ = "reminder_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id"), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, default="email")
    guest: Mapped[Guest] = relationship(back_populates="reminders")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def guest_json(guest: Guest) -> dict:
    return {"id": guest.id, "name": guest.name, "household": guest.household, "email": guest.email, "party": guest.party_size, "status": guest.status, "updated": guest.updated_at.isoformat()}


def bootstrap() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Guest)):
            return
        seed = [("Meera Kapoor", "Kapoor family", "meera@example.test", 4, "confirmed"), ("Siddharth Mehta", "Mehta family", "siddharth@example.test", 2, "confirmed"), ("Naina Singh", "Naina Singh", "naina@example.test", 0, "declined"), ("Rohan & Tara Shah", "Shah family", "shah@example.test", 3, "pending"), ("Aditi Bansal", "Bansal family", "aditi@example.test", 2, "pending"), ("Vikram Rao", "Rao family", "vikram@example.test", 2, "confirmed"), ("Ishaan Verma", "Verma family", "ishaan@example.test", 1, "pending")]
        stamp = utcnow()
        db.add_all([Guest(name=name, household=household, email=email, party_size=party, status=status, token_hash=token_hash(secrets.token_urlsafe(32)), created_at=stamp, updated_at=stamp) for name, household, email, party, status in seed])
        db.commit()


def queue_pending_reminders() -> int:
    bootstrap()
    with SessionLocal() as db:
        pending = list(db.scalars(select(Guest).where(Guest.status == "pending")))
        stamp = utcnow()
        db.add_all([ReminderLog(guest_id=guest.id, sent_at=stamp, channel="email") for guest in pending])
        db.commit()
        return len(pending)


app = Flask(__name__, static_folder=ROOT, static_url_path="")
app.config.update(MAX_CONTENT_LENGTH=100_000, JSON_SORT_KEYS=False, SECRET_KEY=os.getenv("APP_SECRET", "local-development-secret-change-before-public-use"), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=os.getenv("RENDER") == "true")


@app.before_request
def ensure_database():
    bootstrap()
    public_endpoints = {"login", "login_submit", "rsvp_page", "rsvp_details", "record_rsvp", "static"}
    if request.endpoint in public_endpoints:
        return None
    if session.get("is_admin"):
        return None
    if request.path.startswith("/api/"):
        return jsonify(error="Authentication required."), 401
    return redirect(url_for("login"))


@app.get("/")
def index():
    return send_from_directory(ROOT, "index.html")


@app.get("/login")
def login():
    return send_from_directory(ROOT, "login.html")


@app.post("/login")
def login_submit():
    configured_password = os.getenv("ADMIN_PASSWORD", "demo-access")
    candidate = request.form.get("password", "")
    if not hmac.compare_digest(candidate, configured_password):
        return redirect(url_for("login", error="1"))
    session.clear(); session["is_admin"] = True
    return redirect(url_for("index"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/api/event")
def event():
    return jsonify(EVENT)


@app.get("/api/dashboard")
def dashboard():
    with SessionLocal() as db:
        guests = list(db.scalars(select(Guest)))
    total = len(guests); confirmed = sum(guest.status == "confirmed" for guest in guests); declined = sum(guest.status == "declined" for guest in guests)
    return jsonify({"total": total, "confirmed": confirmed, "declined": declined, "pending": total - confirmed - declined, "headcount": sum(guest.party_size for guest in guests if guest.status == "confirmed"), "households": len({guest.household for guest in guests})})


@app.get("/api/guests")
def list_guests():
    status = request.args.get("status", "all")
    with SessionLocal() as db:
        statement = select(Guest).order_by(Guest.updated_at.desc(), Guest.id.desc())
        if status in {"confirmed", "declined", "pending"}:
            statement = statement.where(Guest.status == status)
        guests = list(db.scalars(statement))
    return jsonify([guest_json(guest) for guest in guests])


@app.post("/api/guests")
def add_guest():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip(); household = str(payload.get("household", "")).strip() or name; email = str(payload.get("email", "")).strip() or None; status = payload.get("status", "pending")
    try: party = int(payload.get("party", 1))
    except (TypeError, ValueError): party = -1
    if not name or len(name) > 120: return jsonify(error="A guest name of up to 120 characters is required."), 400
    if status not in {"confirmed", "declined", "pending"}: return jsonify(error="Invalid response status."), 400
    if not 1 <= party <= 12: return jsonify(error="Party size must be between 1 and 12."), 400
    raw_token = secrets.token_urlsafe(32); stamp = utcnow()
    guest = Guest(name=name, household=household[:120], email=email, party_size=0 if status == "declined" else party, status=status, token_hash=token_hash(raw_token), created_at=stamp, updated_at=stamp)
    with SessionLocal() as db:
        db.add(guest); db.commit(); db.refresh(guest); result = guest_json(guest)
    result["rsvp_path"] = f"/rsvp/{raw_token}"
    return jsonify(result), 201


@app.post("/api/reminders")
def reminders():
    count = queue_pending_reminders()
    return jsonify(queued=count, message=f"Queued {count} reminder(s). Connect a verified email provider before using real guest contacts.")


@app.get("/api/export.csv")
def export_csv():
    with SessionLocal() as db:
        guests = list(db.scalars(select(Guest).order_by(Guest.name)))
    output = io.StringIO(); writer = csv.writer(output); writer.writerow(["Guest", "Household", "Email", "Party Size", "Response", "Last Updated"])
    writer.writerows([[guest.name, guest.household, guest.email or "", guest.party_size, guest.status, guest.updated_at.isoformat()] for guest in guests])
    return app.response_class(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=wedding-guest-list.csv"})


def find_guest(raw_token: str) -> Guest | None:
    with SessionLocal() as db:
        guest = db.scalar(select(Guest).where(Guest.token_hash == token_hash(raw_token)))
        if guest is not None: db.expunge(guest)
        return guest


@app.get("/rsvp/<raw_token>")
def rsvp_page(raw_token: str):
    if find_guest(raw_token) is None:
        return jsonify(error="This RSVP link is invalid."), 404
    return send_from_directory(ROOT, "rsvp.html")


@app.get("/api/rsvp/<raw_token>")
def rsvp_details(raw_token: str):
    guest = find_guest(raw_token)
    if guest is None: return jsonify(error="This RSVP link is invalid."), 404
    return jsonify(guest={"name": guest.name, "party": guest.party_size, "status": guest.status}, event=EVENT)


@app.post("/api/rsvp/<raw_token>")
def record_rsvp(raw_token: str):
    payload = request.get_json(silent=True) or {}; status = payload.get("status")
    try: party = int(payload.get("party", 1))
    except (TypeError, ValueError): party = -1
    if status not in {"confirmed", "declined"} or not 1 <= party <= 12: return jsonify(error="Please choose a valid response and party size."), 400
    with SessionLocal() as db:
        guest = db.scalar(select(Guest).where(Guest.token_hash == token_hash(raw_token)))
        if guest is None: return jsonify(error="This RSVP link is invalid."), 404
        guest.status = status; guest.party_size = 0 if status == "declined" else party; guest.updated_at = utcnow(); db.commit()
    return jsonify(ok=True)


@app.errorhandler(413)
def too_large(error):
    return jsonify(error="Request is too large."), 413


if __name__ == "__main__":
    bootstrap()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=True)
