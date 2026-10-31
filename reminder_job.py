"""Scheduled reminder queue entry point."""

from server.services.reminders import queue_pending_reminders


if __name__ == "__main__":
    print(f"Recorded {queue_pending_reminders()} pending reminder(s).")
