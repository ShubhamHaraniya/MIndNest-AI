"""Outgoing email. Development sends to Mailpit; swap SmtpMailer for a provider later."""

import logging
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib
from mindnest_core.settings import Settings

logger = logging.getLogger("mindnest.mail")


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, to: str, subject: str, body: str) -> None:
        """Send one message. A mail failure is logged, never raised: the account action that
        triggered it has already succeeded, and the user can ask for another email."""
        message = EmailMessage()
        message["From"] = self._settings.mail_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            await aiosmtplib.send(
                message,
                hostname=self._settings.smtp_host,
                port=self._settings.smtp_port,
                username=self._settings.smtp_user or None,
                password=self._settings.smtp_password or None,
                start_tls=self._settings.smtp_security == "starttls",
                use_tls=self._settings.smtp_security == "tls",
                timeout=10,
            )
        except Exception:
            logger.warning("Could not send email to %s", to, exc_info=True)


def verification_message(link: str) -> tuple[str, str]:
    return (
        "Verify your email for MindNest AI",
        "Welcome to MindNest AI.\n\n"
        f"Confirm your email address by opening this link:\n{link}\n\n"
        "The link works once and expires in 48 hours. "
        "If you did not create an account, you can ignore this message.\n",
    )


def reset_message(link: str) -> tuple[str, str]:
    return (
        "Reset your MindNest AI password",
        "Someone asked to reset the password for this MindNest AI account.\n\n"
        f"Choose a new password here:\n{link}\n\n"
        "The link works once and expires in 60 minutes. "
        "If this was not you, ignore this message; your password has not changed.\n",
    )
