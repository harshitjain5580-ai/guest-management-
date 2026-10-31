from functools import wraps

from flask import jsonify, redirect, request, session, url_for


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("user_id"):
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify(error="Please log in to continue."), 401
        return redirect(url_for("auth.login_page", next=request.full_path.rstrip("?")))

    return wrapped
