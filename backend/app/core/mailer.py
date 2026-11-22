"""Plain-text e-mail through the standard `smtplib` (DEC-108, DEC-140).

In dev and demo the SMTP server is Mailpit, which only catches mail. The
message body may contain a one-time link: it is never logged.
"""

import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    body: str = field(repr=False)


def send_email(message: OutgoingEmail) -> bool:
    """Send synchronously; True on success. Failures are logged without
    the body or recipient so that tokens and addresses stay out of logs."""
    settings = get_settings()
    email = EmailMessage()
    email["From"] = settings.smtp_from
    email["To"] = message.to
    email["Subject"] = message.subject
    email.set_content(message.body)
    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
        ) as smtp:
            smtp.send_message(email)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("E-mail could not be sent (%s)", type(exc).__name__)
        return False
    return True
