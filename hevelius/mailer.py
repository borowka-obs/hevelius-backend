"""Minimal SMTP email sender for account-related notifications.

Uses the `smtp` config section (host/port/username/password/use-tls/from-addr).
When no host is configured (e.g. dev/test), the message is logged instead of sent
so the rest of the flow (token issuance) still works without mail infrastructure.
"""

import logging
import smtplib
from email.message import EmailMessage

from hevelius.config import load_config

logger = logging.getLogger(__name__)


def send_email(to_addr: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True if actually sent over SMTP."""
    cfg = load_config().get("smtp") or {}
    host = cfg.get("host")

    if not host or not to_addr:
        logger.info(
            "SMTP not configured (or no recipient); email not sent. To=%s Subject=%s\n%s",
            to_addr, subject, body,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("from-addr") or "noreply@hevelius.local"
    msg["To"] = to_addr
    msg.set_content(body)

    port = int(cfg.get("port") or 587)
    username = cfg.get("username")
    password = cfg.get("password")
    use_tls = cfg.get("use-tls", True)

    with smtplib.SMTP(host, port, timeout=10) as server:
        if use_tls:
            server.starttls()
        if username:
            server.login(username, password or "")
        server.send_message(msg)

    return True


def send_password_reset_email(to_addr: str, reset_url: str) -> bool:
    subject = "Hevelius password reset"
    body = (
        "A password reset was requested for your Hevelius account.\n\n"
        f"Reset your password using this link (valid for 1 hour):\n{reset_url}\n\n"
        "If you did not request this, you can safely ignore this email."
    )
    return send_email(to_addr, subject, body)
