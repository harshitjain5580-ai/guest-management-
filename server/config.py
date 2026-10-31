import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIR = ROOT / "client"
load_dotenv(ROOT / ".env")

BRAND_NAME = "Guest Manager"
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
APP_SECRET = os.getenv("APP_SECRET")
if not APP_SECRET:
    if APP_ENV == "production":
        raise RuntimeError("APP_SECRET must be set in production.")
    APP_SECRET = secrets.token_urlsafe(48)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'wedding_guest_manager.db').as_posix()}")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() == "true" or APP_ENV == "production"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
RENDER_SITE_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}" if RENDER_EXTERNAL_HOSTNAME else ""
CLIENT_URL = os.getenv("CLIENT_URL", RENDER_SITE_URL or PUBLIC_BASE_URL).strip().rstrip("/")
if not CLIENT_URL:
    CLIENT_URL = RENDER_SITE_URL or PUBLIC_BASE_URL
CORS_ORIGINS = [CLIENT_URL]
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", SMTP_USERNAME).strip()
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() == "true"
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").strip().lower() == "true"
if SMTP_USE_TLS and SMTP_USE_SSL:
    raise RuntimeError("Enable either SMTP_USE_TLS or SMTP_USE_SSL, not both.")
if APP_ENV == "production" and not CLIENT_URL.startswith("https://"):
    raise RuntimeError("CLIENT_URL must use HTTPS in production.")
if "*" in CORS_ORIGINS:
    raise RuntimeError("CORS_ORIGINS must list trusted origins; wildcard origins are not allowed.")
