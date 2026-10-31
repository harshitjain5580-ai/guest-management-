import os
import random
import secrets
import unittest
from datetime import datetime, timedelta, timezone
import hashlib
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_SECRET"] = secrets.token_urlsafe(48)

from app import app  # noqa: E402
from server.database import Base, SessionLocal, engine, initialize_database  # noqa: E402
from server.models import PasswordResetToken, User  # noqa: E402
from server.config import CLIENT_URL  # noqa: E402
from sqlalchemy import select  # noqa: E402


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        initialize_database()
        self.client = app.test_client()
        self.client.environ_base["REMOTE_ADDR"] = f"10.30.{random.randrange(1, 254)}.{random.randrange(1, 254)}"

    def signup(self, email="person@example.com", password="correct-horse-battery"):
        return self.client.post(
            "/api/auth/signup",
            json={"email": email, "password": password},
        )

    def login(self, email="person@example.com", password="correct-horse-battery"):
        return self.client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )

    def request_reset(self, email="person@example.com"):
        return self.client.post("/api/auth/forgot-password", json={"email": email})

    def test_dashboard_redirects_and_api_requires_login(self):
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)

    def test_sqlite_enforces_foreign_keys(self):
        if engine.dialect.name == "sqlite":
            with engine.connect() as connection:
                self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one(), 1)

    def test_signup_validation_and_duplicate_email(self):
        self.assertEqual(
            self.client.post(
                "/api/auth/signup",
                json={"email": "not-an-email", "password": "short"},
            ).status_code,
            400,
        )
        self.assertEqual(self.signup(email="Person@example.com").status_code, 201)
        self.assertEqual(self.signup(email="person@example.com").status_code, 400)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "person@example.com"))
            self.assertTrue(user.password_hash.startswith("$2"))

    def test_login_password_reset_expiry_and_single_use(self):
        self.assertEqual(self.signup().status_code, 201)
        self.assertEqual(self.login(password="incorrect-password").status_code, 401)
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/login").status_code, 302)
        reset_page = self.client.get("/reset-password?token=reset-token")
        self.assertEqual(reset_page.status_code, 200)
        reset_page.close()
        with self.client.session_transaction() as browser_session:
            self.assertTrue(browser_session["user_id"])
        self.assertTrue(self.client.get_cookie("session").http_only)
        self.assertEqual(self.client.get_cookie("session").same_site, "Lax")
        self.assertEqual(self.client.get("/api/dashboard").json["total"], 0)

        sent_tokens = []
        with patch(
            "server.controllers.auth.send_password_reset_email",
            side_effect=lambda email, token: sent_tokens.append(token),
        ):
            self.assertEqual(self.request_reset().status_code, 200)
        self.assertEqual(len(sent_tokens), 1)
        with SessionLocal() as db:
            reset = db.scalar(select(PasswordResetToken))
            self.assertEqual(reset.token_hash, hashlib.sha256(sent_tokens[0].encode()).hexdigest())
            self.assertNotEqual(reset.token_hash, sent_tokens[0])

        token = sent_tokens[0]
        self.assertEqual(
            self.client.post(
                "/api/auth/reset-password",
                json={"token": token, "password": "new-correct-password"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/auth/reset-password",
                json={"token": token, "password": "another-correct-password"},
            ).status_code,
            400,
        )
        self.assertEqual(self.login(password="correct-horse-battery").status_code, 401)
        self.assertEqual(self.login(password="new-correct-password").status_code, 200)

    def test_expired_reset_token_is_rejected(self):
        self.assertEqual(self.signup().status_code, 201)
        sent_tokens = []
        with patch(
            "server.controllers.auth.send_password_reset_email",
            side_effect=lambda email, token: sent_tokens.append(token),
        ):
            self.assertEqual(self.request_reset().status_code, 200)
        with SessionLocal.begin() as db:
            reset = db.scalar(select(PasswordResetToken))
            reset.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        response = self.client.post(
            "/api/auth/reset-password",
            json={"token": sent_tokens[0], "password": "new-correct-password"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("expired", response.json["error"])

    def test_reset_request_does_not_disclose_unknown_accounts(self):
        with patch("server.controllers.auth.send_password_reset_email") as send_email:
            response = self.request_reset("unknown@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn("If an account exists", response.json["message"])
        send_email.assert_not_called()

    def test_guest_data_is_scoped_to_each_account_and_logout_protects_dashboard(self):
        self.assertEqual(self.signup().status_code, 201)
        added = self.client.post(
            "/api/guests",
            json={"name": "Guest", "party": 2, "status": "pending"},
        )
        self.assertEqual(added.status_code, 201)
        self.assertEqual(self.client.get("/api/guests").json[0]["name"], "Guest")
        rsvp_path = added.json["rsvp_path"]
        token = rsvp_path.rsplit("/", 1)[-1]
        rsvp_page = self.client.get(rsvp_path)
        self.assertEqual(rsvp_page.status_code, 200)
        rsvp_page.close()
        self.assertEqual(
            self.client.post(
                f"/api/rsvp/{token}",
                json={"status": "confirmed", "party": 3},
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/dashboard").json["headcount"], 3)

        other_client = app.test_client()
        other_client.environ_base["REMOTE_ADDR"] = "10.30.254.1"
        self.assertEqual(
            other_client.post(
                "/api/auth/signup",
                json={"email": "other@example.com", "password": "another-correct-password"},
            ).status_code,
            201,
        )
        self.assertEqual(other_client.get("/api/guests").json, [])
        self.assertEqual(self.client.post("/logout").status_code, 302)
        self.assertEqual(self.client.get("/api/guests").status_code, 401)

    def test_login_is_rate_limited(self):
        for _ in range(5):
            self.assertEqual(self.login(password="incorrect-password").status_code, 401)
        limited = self.login(password="incorrect-password")
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Too many attempts", limited.json["error"])

    def test_password_reset_endpoint_is_rate_limited(self):
        invalid_reset = {
            "token": "invalid-reset-token-value",
            "password": "new-correct-password",
        }
        for _ in range(5):
            self.assertEqual(
                self.client.post("/api/auth/reset-password", json=invalid_reset).status_code,
                400,
            )
        limited = self.client.post("/api/auth/reset-password", json=invalid_reset)
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Too many attempts", limited.json["error"])

    def test_not_found_page_and_security_headers(self):
        response = self.client.get("/missing-page")
        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Page not found", response.data)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        response.close()

    def test_readiness_endpoint_checks_database(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_cors_is_limited_to_the_configured_client_origin(self):
        allowed = self.client.get("/api/health", headers={"Origin": CLIENT_URL})
        self.assertEqual(allowed.headers.get("Access-Control-Allow-Origin"), CLIENT_URL)
        rejected = self.client.get("/api/health", headers={"Origin": "https://untrusted.example"})
        self.assertIsNone(rejected.headers.get("Access-Control-Allow-Origin"))


if __name__ == "__main__":
    unittest.main()
