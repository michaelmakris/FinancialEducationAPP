"""
Outgoing email: verification links, password reset links, security notices.

Backends (BFF_EMAIL_BACKEND):
  outbox  dev default -- each message is written to BFF_OUTBOX_DIR as a .eml file
          (open it, click the link); nothing leaves the machine
  smtp    any SMTP server or provider relay (BFF_SMTP_HOST/PORT/USER/PASSWORD,
          BFF_SMTP_SECURITY=starttls|ssl|none)

Sending happens in a FastAPI background task after the response is written, so
"account exists" and "no such account" take the same time to answer.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from prometheus_client import Counter

from .config import settings

log = logging.getLogger("bff.mailer")
SENT = Counter("bff_emails_total", "Emails handed to the email backend", ["kind", "outcome"])


def build(to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="investment-lab.local")
    msg.set_content(body)
    return msg


class OutboxSender:
    def send(self, msg: EmailMessage) -> None:
        folder = Path(settings.outbox_dir)
        folder.mkdir(parents=True, exist_ok=True)
        safe_to = "".join(ch if ch.isalnum() else "_" for ch in str(msg["To"]))[:60]
        path = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}-{safe_to}.eml"  # sorts in send order
        path.write_bytes(bytes(msg))
        log.info("email to %s written to %s", msg["To"], path)


class SmtpSender:
    def send(self, msg: EmailMessage) -> None:
        if not settings.smtp_host:
            raise RuntimeError("BFF_SMTP_HOST is not set")
        ctx = ssl.create_default_context()
        if settings.smtp_security == "ssl":
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with server:
            if settings.smtp_security == "starttls":
                server.starttls(context=ctx)
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)


class MemorySender:
    """Tests: keeps messages in a list."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, msg: EmailMessage) -> None:
        self.sent.append(msg)


_sender = None


def sender():
    global _sender
    if _sender is None:
        _sender = SmtpSender() if settings.email_backend == "smtp" else OutboxSender()
    return _sender


def set_sender(s) -> None:
    global _sender
    _sender = s


def deliver(kind: str, to: str, subject: str, body: str) -> None:
    """Never raises: a mail outage must not turn into a 500 for the customer (it is
    counted in bff_emails_total{outcome="failed"} and alerted on instead)."""
    try:
        sender().send(build(to, subject, body))
        SENT.labels(kind, "sent").inc()
    except Exception:
        SENT.labels(kind, "failed").inc()
        log.exception("could not send %s email", kind)


# ---------------------------------------------------------------- messages
_FOOTER = "\n\n--\nInvestment Lab\nWe will never ask for your password by email or phone."


def verify_email(name: str, token: str) -> tuple[str, str]:
    link = f"{settings.public_url}/?action=verify-email&token={token}"
    return ("Confirm your email address",
            f"Hello {name},\n\nPlease confirm your email address to activate your account:\n\n{link}\n\n"
            f"The link is valid for {settings.verify_token_hours} hours. If you did not create an account, ignore this email." + _FOOTER)


def already_registered(name: str) -> tuple[str, str]:
    return ("Someone tried to register with your email",
            f"Hello {name},\n\nSomeone (maybe you) tried to create a new account with this email address, "
            f"but you already have one.\n\nSign in: {settings.public_url}/\n"
            f"Forgot your password? Reset it from the sign-in page.\n\nIf this wasn't you, no action is needed." + _FOOTER)


def password_reset(name: str, token: str) -> tuple[str, str]:
    link = f"{settings.public_url}/?action=reset-password&token={token}"
    return ("Reset your password",
            f"Hello {name},\n\nUse this link to choose a new password:\n\n{link}\n\n"
            f"The link is valid for {settings.reset_token_minutes} minutes and works once. "
            f"If you did not ask for this, ignore this email; your password stays the same." + _FOOTER)


def security_notice(name: str, what: str) -> tuple[str, str]:
    return (f"Security notice: {what}",
            f"Hello {name},\n\n{what} on your account just now.\n\n"
            f"If this was you, no action is needed. If it wasn't, reset your password immediately from "
            f"{settings.public_url}/ and contact support." + _FOOTER)
