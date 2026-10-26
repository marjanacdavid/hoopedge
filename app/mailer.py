"""Slanje emailova preko SMTP-a (env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_SECURITY).

SMTP_SECURITY: 'ssl' (port 465), 'starttls' (port 587, zadano), ili 'none'.
Ako SMTP nije podesen, poruka se NE salje, nego se link upise u log (journalctl) -- za testiranje.
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

log = logging.getLogger("hoopedge.mail")


def configured() -> bool:
    return bool(os.getenv("SMTP_HOST"))


def send_mail(to: str, subject: str, text: str, html: str = "") -> bool:
    host = os.getenv("SMTP_HOST", "")
    if not host:
        log.warning("SMTP nije podesen; email za %s NIJE poslan. Sadrzaj:\n%s", to, text)
        return False
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    pw = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", user)
    mode = os.getenv("SMTP_SECURITY", "ssl" if port == 465 else "starttls").lower()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("HOOPEDGE", sender))
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        ctx = ssl.create_default_context()
        if mode == "ssl":
            s = smtplib.SMTP_SSL(host, port, timeout=15, context=ctx)
        else:
            s = smtplib.SMTP(host, port, timeout=15)
            if mode == "starttls":
                s.starttls(context=ctx)
        with s:
            if user:
                s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception as e:   # lozinka se nikad ne upisuje u log
        log.error("Slanje emaila za %s nije uspjelo: %s: %s", to, type(e).__name__, e)
        return False


def reset_email(link: str):
    text = ("We received a request to reset your HOOPEDGE password.\n\nChoose a new password here:\n\n"
            f"{link}\n\nThe link is valid for 1 hour and works once. If you did not ask for this, ignore this email: "
            "your password stays the same.\n")
    html = ("<div style=\"font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:24px\">"
            "<h2 style=\"margin:0 0 12px\">Reset your password</h2>"
            "<p>We received a request to reset your HOOP<b>EDGE</b> password.</p>"
            f"<p><a href=\"{link}\" style=\"display:inline-block;background:#19a866;color:#fff;text-decoration:none;"
            "padding:12px 20px;border-radius:8px;font-weight:bold\">Choose a new password</a></p>"
            f"<p style=\"font-size:12px;color:#666\">Or paste this link into your browser:<br>{link}</p>"
            "<p style=\"font-size:12px;color:#666\">Valid for 1 hour, works once. If you didn't ask for this, ignore this email.</p></div>")
    return "Reset your HOOPEDGE password", text, html


def verification_email(link: str):
    text = ("Welcome to HOOPEDGE!\n\nConfirm your email address to activate your account:\n\n"
            f"{link}\n\nThe link is valid for 24 hours. If you did not create this account, you can ignore this email.\n")
    html = ("<div style=\"font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:24px\">"
            "<h2 style=\"margin:0 0 12px\">Welcome to HOOP<span style=\"color:#19a866\">EDGE</span></h2>"
            "<p>Confirm your email address to activate your account.</p>"
            f"<p><a href=\"{link}\" style=\"display:inline-block;background:#19a866;color:#fff;text-decoration:none;"
            "padding:12px 20px;border-radius:8px;font-weight:bold\">Confirm email</a></p>"
            f"<p style=\"font-size:12px;color:#666\">Or paste this link into your browser:<br>{link}</p>"
            "<p style=\"font-size:12px;color:#666\">Valid for 24 hours. If you didn't sign up, ignore this email.</p></div>")
    return "Confirm your HOOPEDGE email", text, html
