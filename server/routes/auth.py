from flask import Blueprint, jsonify, redirect, request, session, send_from_directory, url_for

from server.config import CLIENT_DIR
from server.controllers.auth import authenticate, create_account, request_password_reset, reset_password
from server.database import SessionLocal
from server.extensions import limiter
from server.middleware.auth import login_required
from server.models import User

auth = Blueprint("auth", __name__)


def json_payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


@auth.get("/login")
def login_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard.home"))
    return send_from_directory(CLIENT_DIR, "login.html")


@auth.get("/signup")
def signup_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard.home"))
    return send_from_directory(CLIENT_DIR, "signup.html")


@auth.get("/forgot-password")
def forgot_password_page():
    if session.get("user_id"):
        return redirect(url_for("dashboard.home"))
    return send_from_directory(CLIENT_DIR, "forgot-password.html")


@auth.get("/reset-password")
def reset_password_page():
    return send_from_directory(CLIENT_DIR, "reset-password.html")


@auth.post("/api/auth/signup")
@limiter.limit("5 per hour")
def signup():
    try:
        user = create_account(json_payload())
    except ValueError as error:
        return jsonify(error=str(error)), 400
    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    return jsonify(message="Your account has been created."), 201


@auth.post("/api/auth/login")
@limiter.limit("5 per minute")
def login_submit():
    user = authenticate(json_payload())
    if user is None:
        return jsonify(error="Email or password is incorrect."), 401
    session.clear()
    session.permanent = True
    session["user_id"] = user.id
    return jsonify(message="You are logged in.")


@auth.post("/api/auth/forgot-password")
@limiter.limit("3 per hour")
def forgot_password_submit():
    try:
        request_password_reset(json_payload().get("email"))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except RuntimeError as error:
        return jsonify(error=str(error)), 503
    return jsonify(message="If an account exists for that email, a password reset link has been sent.")


@auth.post("/api/auth/reset-password")
@limiter.limit("5 per hour")
def reset_password_submit():
    payload = json_payload()
    try:
        reset_password(payload.get("token"), payload.get("password"))
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return jsonify(message="Your password has been reset. You can now log in.")


@auth.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("auth.login_page"))


@auth.get("/api/auth/me")
@login_required
def current_user():
    with SessionLocal() as db:
        user = db.get(User, session["user_id"])
        if user is None:
            session.clear()
            return jsonify(error="Please log in to continue."), 401
        return jsonify(email=user.email)
