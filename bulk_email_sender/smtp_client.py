from __future__ import annotations

import contextlib
import smtplib
import time
from email.message import EmailMessage
from types import TracebackType
from typing import Callable

from bulk_email_sender.models import SMTPConfig


class SMTPClient:
    """SMTP client with optional connection reuse.

    Usage (single shot – backward compatible):
        client.send(email, msg)

    Usage (one connection per email – recommended for bulk sending with delays):
        for email, msg in batch:
            with client:
                client.send(email, msg)
            time.sleep(interval)

    Usage (connection reuse for rapid batches with no delays):
        with client:
            for email, msg in batch:
                client.send(email, msg)
    """

    def __init__(self, smtp_config: SMTPConfig):
        self.smtp_config = smtp_config
        self._persistent_server: smtplib.SMTP | None = None

    # -- context manager for connection reuse ----------------------------------

    def __enter__(self) -> SMTPClient:
        """Establish SMTP connection, retrying once after 2 s on transient errors.

        Some SMTP servers (e.g. 163.com / 126.com) implement greylisting
        (RFC 6647): the first connection attempt from an unfamiliar client
        receives a temporary ``421`` rejection.  Legitimate senders are
        expected to retry; bots typically do not.  A single 2-second pause
        before the retry covers this case without masking real auth errors.

        With the current architecture each email gets its own ``with`` block
        (fresh connection), so this retry is hit at most once per
        cold-start session — subsequent emails arrive within the server's
        greylisting window and are accepted on the first attempt.
        """
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                self._persistent_server = self._connect()
                return self
            except (OSError, smtplib.SMTPException) as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(2)
        raise last_error  # type: ignore[misc]

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._close_persistent()

    def reset_connection(self) -> None:
        """Close the persistent connection so the next send() will reconnect."""
        self._close_persistent()

    # -- public API ------------------------------------------------------------

    def test_connection(self) -> None:
        self._with_server(lambda _: None)

    def send(self, recipient_email: str, message: EmailMessage) -> None:
        def _send(server: smtplib.SMTP) -> None:
            refused = server.send_message(message)
            if recipient_email in refused:
                raise smtplib.SMTPRecipientsRefused(refused)

        if self._persistent_server is not None:
            try:
                _send(self._persistent_server)
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPException, OSError):
                # Reconnect on disconnect or any connection-level error, then retry once.
                self._persistent_server = self._connect()
                _send(self._persistent_server)
        else:
            self._with_server(_send)

    def noop(self) -> None:
        """Send a NOOP to verify the persistent connection is still alive.

        Resets ``_persistent_server`` to None if the connection is dead so the
        next :meth:`send` call will reconnect immediately instead of timing out.
        """
        if self._persistent_server is None:
            return
        try:
            self._persistent_server.noop()
        except (smtplib.SMTPException, OSError):
            self._close_persistent()

    # -- internals -------------------------------------------------------------

    def _connect(self) -> smtplib.SMTP:
        if self.smtp_config.use_ssl and self.smtp_config.use_starttls:
            raise ValueError("SMTP 配置冲突：use_ssl 与 use_starttls 不能同时开启")

        if self.smtp_config.use_ssl:
            server = smtplib.SMTP_SSL(
                self.smtp_config.host,
                self.smtp_config.port,
                timeout=self.smtp_config.timeout_sec,
            )
        else:
            server = smtplib.SMTP(
                self.smtp_config.host,
                self.smtp_config.port,
                timeout=self.smtp_config.timeout_sec,
            )
            if self.smtp_config.use_starttls:
                server.starttls()

        self._login_if_needed(server)
        return server

    def _close_persistent(self) -> None:
        server = self._persistent_server
        self._persistent_server = None
        if server is not None:
            with contextlib.suppress(smtplib.SMTPException):
                server.quit()

    def _with_server(self, callback: Callable[[smtplib.SMTP], None]) -> None:
        server = self._connect()
        try:
            callback(server)
        finally:
            with contextlib.suppress(smtplib.SMTPException):
                server.quit()

    def _login_if_needed(self, server: smtplib.SMTP) -> None:
        if not self.smtp_config.username or not self.smtp_config.password:
            return
        server.login(self.smtp_config.username, self.smtp_config.password)
