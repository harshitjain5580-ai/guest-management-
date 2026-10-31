from __future__ import annotations

import os

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from server.config import APP_ENV, APP_SECRET, CLIENT_DIR, CORS_ORIGINS, COOKIE_SECURE
from server.database import engine, initialize_database
from server.extensions import limiter
from server.routes.auth import auth
from server.routes.dashboard import dashboard


def create_app() -> Flask:
    application = Flask(__name__, static_folder=None)
    if APP_ENV == "production":
        application.wsgi_app = ProxyFix(application.wsgi_app, x_for=1, x_proto=1, x_host=1)
    application.config.update(
        SECRET_KEY=APP_SECRET,
        MAX_CONTENT_LENGTH=100_000,
        JSON_SORT_KEYS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=COOKIE_SECURE,
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
        RATELIMIT_STORAGE_URI=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        RATELIMIT_HEADERS_ENABLED=True,
    )
    limiter.init_app(application)
    if CORS_ORIGINS:
        CORS(application, origins=CORS_ORIGINS, supports_credentials=True)

    initialize_database()
    application.register_blueprint(auth)
    application.register_blueprint(dashboard)

    @application.after_request
    def apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; "
            "object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:",
        )
        if COOKIE_SECURE:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @application.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found."), 404
        return send_from_directory(CLIENT_DIR, "404.html"), 404

    @application.get("/healthz")
    @application.get("/api/health")
    def health():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return jsonify(status="ok")

    @application.errorhandler(413)
    def request_too_large(error):
        return jsonify(error="Request is too large."), 413

    @application.errorhandler(429)
    def too_many_requests(error):
        return jsonify(error="Too many attempts. Please try again later."), 429

    return application


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")), debug=False)
