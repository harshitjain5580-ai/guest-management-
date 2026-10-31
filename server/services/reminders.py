from datetime import datetime, timezone

from sqlalchemy import select

from server.database import SessionLocal, initialize_database
from server.models import Guest, ReminderLog


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
from server.routes.dashboard import utcnow


def queue_pending_reminders() -> int:
    initialize_database()
    with SessionLocal.begin() as db:
        pending = list(
            db.scalars(
                select(Guest).where(
                    Guest.user_id.is_not(None),
                    Guest.status == "pending",
                )
            )
        )
        stamp = utcnow()
        db.add_all(
            [ReminderLog(guest_id=guest.id, sent_at=stamp, channel="email") for guest in pending]
        )
    return len(pending)
