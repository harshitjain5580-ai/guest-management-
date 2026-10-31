import csv
import hashlib
import io
import secrets
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request, send_from_directory, session
from sqlalchemy import select

from server.config import CLIENT_DIR
from server.database import SessionLocal
from server.middleware.auth import login_required
from server.models import Guest, ReminderLog

dashboard = Blueprint("dashboard", __name__)
EVENT = {"name": "", "date": "", "location": "", "rsvp_closes": ""}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def guest_json(guest: Guest) -> dict:
    return {
        "id": guest.id,
        "name": guest.name,
        "household": guest.household,
        "email": guest.email,
        "party": guest.party_size,
        "status": guest.status,
        "updated": guest.updated_at.isoformat(),
    }


@dashboard.get("/")
@login_required
def home():
    return send_from_directory(CLIENT_DIR, "index.html")


@dashboard.get("/<path:filename>")
def public_asset(filename: str):
    allowed_root_assets = {"styles.css", "app.js", "rsvp.js"}
    allowed_client_assets = {"auth.css", "auth.js", "brand.js", "login.css", "dashboard.css"}
    if filename in allowed_root_assets:
        return send_from_directory(CLIENT_DIR.parent, filename)
    if filename.startswith("client/") and filename.removeprefix("client/") in allowed_client_assets:
        return send_from_directory(CLIENT_DIR, filename.removeprefix("client/"))
    from flask import abort

    abort(404)


@dashboard.get("/api/event")
@login_required
def event():
    return jsonify(EVENT)


@dashboard.get("/api/dashboard")
@login_required
def dashboard_stats():
    owner_id = request_user_id()
    with SessionLocal() as db:
        guests = list(db.scalars(select(Guest).where(Guest.user_id == owner_id)))
    total = len(guests)
    confirmed = sum(guest.status == "confirmed" for guest in guests)
    declined = sum(guest.status == "declined" for guest in guests)
    return jsonify(
        {
            "total": total,
            "confirmed": confirmed,
            "declined": declined,
            "pending": total - confirmed - declined,
            "headcount": sum(guest.party_size for guest in guests if guest.status == "confirmed"),
            "households": len({guest.household for guest in guests}),
        }
    )


@dashboard.get("/api/guests")
@login_required
def list_guests():
    owner_id = request_user_id()
    status = request.args.get("status", "all")
    statement = select(Guest).where(Guest.user_id == owner_id).order_by(Guest.updated_at.desc(), Guest.id.desc())
    if status in {"confirmed", "declined", "pending"}:
        statement = statement.where(Guest.status == status)
    with SessionLocal() as db:
        guests = list(db.scalars(statement))
    return jsonify([guest_json(guest) for guest in guests])


@dashboard.post("/api/guests")
@login_required
def add_guest():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Enter valid guest details."), 400
    name = payload.get("name")
    household = payload.get("household", "")
    email = payload.get("email", "")
    status = payload.get("status", "pending")
    try:
        party = int(payload.get("party", 1))
    except (TypeError, ValueError):
        party = -1
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        return jsonify(error="A guest name of up to 120 characters is required."), 400
    if not isinstance(household, str) or not isinstance(email, str):
        return jsonify(error="Enter valid guest details."), 400
    if email and (len(email) > 254 or "@" not in email):
        return jsonify(error="Enter a valid guest email address."), 400
    if status not in {"confirmed", "declined", "pending"}:
        return jsonify(error="Invalid response status."), 400
    if not 1 <= party <= 12:
        return jsonify(error="Party size must be between 1 and 12."), 400
    raw_token = secrets.token_urlsafe(32)
    stamp = utcnow()
    guest = Guest(
        user_id=request_user_id(),
        name=name.strip(),
        household=household.strip()[:120] or name.strip(),
        email=email.strip() or None,
        party_size=0 if status == "declined" else party,
        status=status,
        token_hash=token_hash(raw_token),
        created_at=stamp,
        updated_at=stamp,
    )
    with SessionLocal.begin() as db:
        db.add(guest)
        db.flush()
        result = guest_json(guest)
    result["rsvp_path"] = f"/rsvp/{raw_token}"
    return jsonify(result), 201


@dashboard.post("/api/reminders")
@login_required
def reminders():
    owner_id = request_user_id()
    with SessionLocal.begin() as db:
        pending = list(db.scalars(select(Guest).where(Guest.user_id == owner_id, Guest.status == "pending")))
        stamp = utcnow()
        db.add_all([ReminderLog(guest_id=guest.id, sent_at=stamp, channel="email") for guest in pending])
    return jsonify(queued=len(pending), message=f"Queued {len(pending)} reminder(s).")


@dashboard.get("/api/export.csv")
@login_required
def export_csv():
    owner_id = request_user_id()
    with SessionLocal() as db:
        guests = list(
            db.scalars(select(Guest).where(Guest.user_id == owner_id).order_by(Guest.name))
        )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Guest", "Household", "Email", "Party Size", "Response", "Last Updated"])
    writer.writerows(
        [[guest.name, guest.household, guest.email or "", guest.party_size, guest.status, guest.updated_at.isoformat()] for guest in guests]
    )
    return current_app.response_class(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=guest-list.csv"},
    )


def request_user_id() -> int:
    return int(session["user_id"])


def find_guest(raw_token: str) -> Guest | None:
    with SessionLocal() as db:
        guest = db.scalar(select(Guest).where(Guest.token_hash == token_hash(raw_token)))
        if guest is not None:
            db.expunge(guest)
        return guest


@dashboard.get("/rsvp/<raw_token>")
def rsvp_page(raw_token: str):
    if find_guest(raw_token) is None:
        from flask import abort

        abort(404)
    return send_from_directory(CLIENT_DIR, "rsvp.html")


@dashboard.get("/api/rsvp/<raw_token>")
def rsvp_details(raw_token: str):
    guest = find_guest(raw_token)
    if guest is None:
        return jsonify(error="This RSVP link is invalid."), 404
    return jsonify(guest={"name": guest.name, "party": guest.party_size, "status": guest.status}, event=EVENT)


@dashboard.post("/api/rsvp/<raw_token>")
def record_rsvp(raw_token: str):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Please choose a valid response and party size."), 400
    status = payload.get("status")
    try:
        party = int(payload.get("party", 1))
    except (TypeError, ValueError):
        party = -1
    if status not in {"confirmed", "declined"} or not 1 <= party <= 12:
        return jsonify(error="Please choose a valid response and party size."), 400
    with SessionLocal.begin() as db:
        guest = db.scalar(select(Guest).where(Guest.token_hash == token_hash(raw_token)))
        if guest is None:
            return jsonify(error="This RSVP link is invalid."), 404
        guest.status = status
        guest.party_size = 0 if status == "declined" else party
        guest.updated_at = utcnow()
    return jsonify(ok=True)
