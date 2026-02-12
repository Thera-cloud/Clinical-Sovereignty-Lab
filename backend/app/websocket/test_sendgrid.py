#!/usr/bin/env python3
"""
SendGrid SMTP integration test.
Sends a test email via SMTP using the credentials in .env.

Usage:
  cd backend
  python3 -m app.websocket.test_sendgrid <recipient@email.com>
"""
import asyncio
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# Load env (same as bridge_server)
try:
    from dotenv import load_dotenv
    script_dir = Path(__file__).resolve().parent
    backend_dir = script_dir.parents[2]
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    # Try root .env first, then websocket .env
    master_env = backend_dir / ".env"
    if not master_env.exists():
        master_env = script_dir.parent / ".env"
    if not master_env.exists():
        master_env = script_dir / ".env"
    load_dotenv(dotenv_path=master_env, override=True)
    print(f"Loaded env from: {master_env}")
except ImportError:
    pass

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.sendgrid.net")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "apikey")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "support@sovereignsanctuary.net")
FROM_NAME = os.getenv("FROM_NAME", "Sovereign Sanctuary")


def main():
    to_email = sys.argv[1] if len(sys.argv) > 1 else ""
    if not to_email:
        print("Usage: python3 -m app.websocket.test_sendgrid <recipient@email.com>")
        sys.exit(1)

    if not SMTP_PASSWORD:
        print("ERROR: SMTP_PASSWORD not set in .env")
        sys.exit(1)

    print(f"SMTP Host:     {SMTP_HOST}")
    print(f"SMTP Port:     {SMTP_PORT}")
    print(f"SMTP User:     {SMTP_USER}")
    print(f"SMTP Password: {SMTP_PASSWORD[:8]}...{SMTP_PASSWORD[-4:]}")
    print(f"From:          {FROM_NAME} <{FROM_EMAIL}>")
    print(f"To:            {to_email}")
    print()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "SendGrid SMTP Verification – Sovereign Sanctuary"
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email

    text = "This is a test email from Sovereign Sanctuary to verify SendGrid SMTP integration."
    html = """
    <html><body style="font-family: sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px;">
      <div style="max-width: 500px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 30px; border: 1px solid #334155;">
        <h2 style="color: #C9A962; margin-top: 0;">Sovereign Sanctuary</h2>
        <p>This is a test email to verify SendGrid SMTP integration is working.</p>
        <p style="color: #94a3b8; font-size: 13px; margin-top: 20px;">If you received this, SMTP is configured correctly.</p>
      </div>
    </body></html>
    """
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        print("Connecting to SMTP server...")
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.set_debuglevel(1)  # Show full SMTP conversation
            server.ehlo()
            print("Starting TLS...")
            server.starttls()
            server.ehlo()
            print("Authenticating...")
            server.login(SMTP_USER, SMTP_PASSWORD)
            print("Sending email...")
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
            print()
            print("SUCCESS! Email sent via SMTP.")
            print("Check your inbox (and spam folder).")
    except smtplib.SMTPAuthenticationError as e:
        print(f"\nAUTH ERROR: {e}")
        print("The API key may not have Mail Send permission, or is invalid.")
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
