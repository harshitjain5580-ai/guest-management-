import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from email_validator import EmailNotValidError, validate_email
from flask import current_app
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from server.database import SessionLocal
from server.models import PasswordResetToken, User
from server.services.email import send_password_reset_email

RESET_LIFETIME = timedelta(minutes=15)
DUMMY_PASSWORD_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_email(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Enter a valid email address.")
    email = value.strip()
    try:
        normalized = validate_email(email, check_deliverability=False).normalized
    except EmailNotValidError as error:
        raise ValueError("Enter a valid email address.") from error
    if len(normalized) > 254:
        raise ValueError("Email address must be 254 characters or fewer.")
    return normalized.casefold()


def validate_password(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Enter a password.")
    byte_length = len(value.encode("utf-8"))
    if byte_length < 12:
        raise ValueError("Password must be at least 12 characters.")
    if byte_length > 72:
        raise ValueError("Password must be no more than 72 bytes.")
    return value


def create_account(payload: dict) -> User:
    email = normalize_email(payload.get("email"))
    password = validate_password(payload.get("password"))
    try:
        with SessionLocal.begin() as db:
            if db.scalar(select(User.id).where(User.email == email)) is not None:
                raise ValueError("An account with this email already exists.")
            user = User(
                email=email,
                password_hash=bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii"),
                created_at=utcnow(),
            )
            db.add(user)
            db.flush()
            db.expunge(user)
            return user
    except IntegrityError:
        with SessionLocal() as db:
            exists = db.scalar(select(User.id).where(User.email == email)) is not None
        if exists:
            raise ValueError("An account with this email already exists.") from None
        raise


def authenticate(payload: dict) -> User | None:
    try:
        email = normalize_email(payload.get("email"))
    except ValueError:
        email = ""
    password = payload.get("password")
    if not isinstance(password, str):
        password = ""
    encoded = password.encode("utf-8")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email)) if email else None
        stored_hash = user.password_hash.encode("ascii") if user else DUMMY_PASSWORD_HASH
        try:
            password_ok = bcrypt.checkpw(encoded if len(encoded) <= 72 else b"", stored_hash)
        except ValueError:
            password_ok = False
        if not user or not password_ok:
            return None
        db.expunge(user)
        return user


def request_password_reset(email_value: object) -> None:
    email = normalize_email(email_value)
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = utcnow()
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            return
        db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
            .values(used_at=now)
        )
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=now + RESET_LIFETIME,
                created_at=now,
            )
        )
    try:
        send_password_reset_email(email, raw_token)
    except Exception:
        current_app.logger.exception("Could not send a password reset email.")
        with SessionLocal.begin() as db:
            db.execute(
                update(PasswordResetToken)
                .where(PasswordResetToken.token_hash == token_hash, PasswordResetToken.used_at.is_(None))
                .values(used_at=utcnow())
            )
        raise RuntimeError("The password reset email could not be sent. Please try again later.") from None


def reset_password(raw_token: object, password_value: object) -> None:
    if not isinstance(raw_token, str) or not 20 <= len(raw_token) <= 200:
        raise ValueError("This reset link is invalid or has expired.")
    password = validate_password(password_value)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = utcnow()
    encoded_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    with SessionLocal.begin() as db:
        reset = db.scalar(
            select(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash)
            .with_for_update()
        )
        if reset is None or reset.used_at is not None or as_utc(reset.expires_at) <= now:
            raise ValueError("This reset link is invalid or has expired.")
        reset.used_at = now
        user = db.get(User, reset.user_id)
        if user is None:
            raise ValueError("This reset link is invalid or has expired.")
        user.password_hash = encoded_password
        db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.id != reset.id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
