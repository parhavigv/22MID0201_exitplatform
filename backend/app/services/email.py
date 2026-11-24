"""
Outbound email.

Phase 8 swaps `LogSender` for `SMTPSender` against the company relay. Nothing
that sends a message imports a provider directly — they take an `EmailSender`,
so that swap is a one-line change in `get_sender()` and touches no caller.

Until then every "sent" message is written to the in-app notifications table,
which is the part users actually see in the pilot.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    def send(self, message: Message) -> None: ...


class LogSender:
    """Development default. Records the message without delivering it."""

    def send(self, message: Message) -> None:
        log.info("EMAIL (not sent) to=%s subject=%s", message.to, message.subject)


class SMTPSender:
    """Phase 8. Needs the company relay's host, port, and credentials."""

    def __init__(self, host: str, port: int, username: str, password: str, sender: str):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender

    def send(self, message: Message) -> None:
        email = EmailMessage()
        email["From"] = self._sender
        email["To"] = message.to
        email["Subject"] = message.subject
        email.set_content(message.body)

        with smtplib.SMTP(self._host, self._port, timeout=20) as smtp:
            smtp.starttls()
            if self._username:
                smtp.login(self._username, self._password)
            smtp.send_message(email)


def get_sender() -> EmailSender:
    settings = get_settings()
    host = getattr(settings, "smtp_host", "")
    if not host:
        return LogSender()
    return SMTPSender(
        host=host,
        port=getattr(settings, "smtp_port", 587),
        username=getattr(settings, "smtp_username", ""),
        password=getattr(settings, "smtp_password", ""),
        sender=getattr(settings, "smtp_from", "exit-process@example.com"),
    )
