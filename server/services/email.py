import smtplib
import ssl
from email.message import EmailMessage

from server.config import (
    CLIENT_URL,
    SMTP_FROM_EMAIL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    SMTP_USERNAME,
)


def send_password_reset_email(email: str, token: str) -> None:
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        raise RuntimeError("SMTP_HOST and SMTP_FROM_EMAIL must be configured before sending email.")

    reset_link = f"{CLIENT_URL}/reset-password?token={token}"
    message = EmailMessage()
    message["Subject"] = "Reset your password"
    message["From"] = SMTP_FROM_EMAIL
    message["To"] = email
    message.set_content(
        "A password reset was requested for your account.\n\n"
        f"Use this link within 15 minutes to set a new password:\n{reset_link}\n\n"
        "If you did not request this change, you can ignore this email."
    )

    context = ssl.create_default_context()
    with (
        smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=15)
        if SMTP_USE_SSL
        else smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15)
    ) as smtp:
        if not SMTP_USE_SSL and SMTP_USE_TLS:
            smtp.starttls(context=context)
        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        smtp.send_message(message)
