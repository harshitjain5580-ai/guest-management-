# Wedding Guest Manager

This is a public-deployment-ready full-stack application with the same interface as the supplied prototype.

## Start it

From this folder, install the production dependencies and run:

```powershell
& "C:\Users\LENOVO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m pip install -r .\requirements.txt
& "C:\Users\LENOVO\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" .\app.py
```

Open `http://127.0.0.1:8000` in a browser.

The local demo password is `demo-access`. Before public deployment, set a strong `ADMIN_PASSWORD` in Render. It protects the private organizer dashboard; shareable RSVP links stay public.

## What is implemented

- SQLite locally and PostgreSQL in production
- Organizer dashboard calculated from stored data
- Guest creation with validation and a unique RSVP token
- Guest RSVP API endpoint (`POST /api/rsvp/{token}`)
- Daily Render cron job for pending reminders (no external messages are sent until an email provider is connected)
- CSV export

The local database file is created automatically on first run. Render uses the managed PostgreSQL database specified in `render.yaml`; do not use SQLite for public production data.

## Deploy on Render

1. Push this project to a private GitHub repository.
2. In Render, select **New > Blueprint** and select that repository.
3. Render reads the root-level `render.yaml`, provisions the web service, PostgreSQL database, and daily reminder cron job, then gives you an `onrender.com` URL.
4. Render prompts for `ADMIN_PASSWORD`. Choose a unique, strong value and do not commit it to the repository.
5. Before importing real guest data, configure an approved transactional-email provider and set its keys as Render secrets.
