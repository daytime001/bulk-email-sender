from email.message import EmailMessage

import pytest

from bulk_email_sender.models import SMTPConfig
from bulk_email_sender.smtp_client import SMTPClient


class FakeSMTPServer:
    def __init__(self) -> None:
        self.login_calls: list[tuple[str, str]] = []
        self.starttls_calls = 0
        self.send_calls = 0

    def login(self, username: str, password: str) -> None:
        self.login_calls.append((username, password))

    def starttls(self) -> None:
        self.starttls_calls += 1

    def send_message(self, _message: EmailMessage) -> dict[str, str]:
        self.send_calls += 1
        return {}

    def quit(self) -> None:
        pass

    def __enter__(self) -> "FakeSMTPServer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def _sample_message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "teacher@example.com"
    message["Subject"] = "test"
    message.set_content("hello")
    return message


def test_smtp_client_uses_ssl_transport_and_login(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeSMTPServer()

    def fake_smtp_ssl(host: str, port: int, timeout: int):
        assert host == "smtp.example.com"
        assert port == 465
        assert timeout == 20
        return server

    monkeypatch.setattr("smtplib.SMTP_SSL", fake_smtp_ssl)

    client = SMTPClient(
        SMTPConfig(
            host="smtp.example.com",
            port=465,
            username="sender@example.com",
            password="auth-code",
            use_ssl=True,
            timeout_sec=20,
        )
    )

    client.send("teacher@example.com", _sample_message())

    assert server.login_calls == [("sender@example.com", "auth-code")]
    assert server.send_calls == 1
    assert server.starttls_calls == 0


def test_smtp_client_uses_starttls_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeSMTPServer()

    def fake_smtp(host: str, port: int, timeout: int):
        assert host == "smtp.example.com"
        assert port == 587
        assert timeout == 30
        return server

    monkeypatch.setattr("smtplib.SMTP", fake_smtp)

    client = SMTPClient(
        SMTPConfig(
            host="smtp.example.com",
            port=587,
            username="sender@example.com",
            password="auth-code",
            use_ssl=False,
            use_starttls=True,
            timeout_sec=30,
        )
    )

    client.test_connection()

    assert server.starttls_calls == 1
    assert server.login_calls == [("sender@example.com", "auth-code")]


def test_smtp_client_skips_login_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeSMTPServer()

    def fake_smtp(host: str, port: int, timeout: int):
        assert host == "localhost"
        assert port == 1025
        assert timeout == 10
        return server

    monkeypatch.setattr("smtplib.SMTP", fake_smtp)

    client = SMTPClient(
        SMTPConfig(
            host="localhost",
            port=1025,
            username="",
            password="",
            use_ssl=False,
            use_starttls=False,
            timeout_sec=10,
        )
    )

    client.send("teacher@example.com", _sample_message())

    assert server.login_calls == []
    assert server.starttls_calls == 0
    assert server.send_calls == 1
