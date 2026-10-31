"""Compatibility entry point for running the authenticated Flask application."""

import os

from app import app


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")), debug=False)
