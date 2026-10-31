"""Render Cron Job entry point.

This currently records pending guests for follow-up. Add a verified email/SMS provider
before enabling real message delivery.
"""
from app import queue_pending_reminders

if __name__ == "__main__":
    print(f"Queued {queue_pending_reminders()} pending reminder(s).")
