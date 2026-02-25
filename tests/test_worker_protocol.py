import json
import threading
from pathlib import Path

from bulk_email_sender.models import JobConfig, Recipient, Sender, SendOptions, SMTPConfig, Template
from bulk_email_sender.worker import Worker


class DummyWriter:
    def __init__(self) -> None:
        self.lines = []

    def write_line(self, payload):
        self.lines.append(payload)


def test_worker_load_recipients_command(tmp_path: Path) -> None:
    recipients_path = tmp_path / "teachers.json"
    recipients_path.write_text(
        json.dumps({"teacher1@example.com": "张教授"}),
        encoding="utf-8",
    )

    writer = DummyWriter()
    worker = Worker(writer=writer)
    worker.handle_message(
        {
            "type": "load_recipients",
            "protocol": 1,
            "payload": {"path": str(recipients_path)},
        }
    )

    assert writer.lines[-1]["type"] == "recipients_loaded"
    assert writer.lines[-1]["stats"]["valid_rows"] == 1


def test_worker_unknown_command_returns_error() -> None:
    writer = DummyWriter()
    worker = Worker(writer=writer)
    worker.handle_message({"type": "unknown", "protocol": 1, "payload": {}})

    assert writer.lines[-1]["type"] == "error"


def test_worker_run_job_emits_error_on_unexpected_exception(tmp_path: Path) -> None:
    writer = DummyWriter()
    worker = Worker(writer=writer)
    job = JobConfig(
        job_id="job-error",
        sender=Sender(email="sender@example.com", name="发件人"),
        smtp=SMTPConfig(
            host="smtp.example.com",
            port=465,
            username="sender@example.com",
            password="secret",
            use_ssl=True,
            timeout_sec=5,
        ),
        template=Template(
            subject="hello",
            body_text="world",
            body_html=None,
        ),
        recipients=[Recipient(email="teacher@example.com", name="张教授")],
        attachments=[str(tmp_path / "missing.pdf")],
        options=SendOptions(
            min_delay_sec=0,
            max_delay_sec=0,
            randomize_order=False,
            retry_count=1,
            add_teacher_suffix=False,
            skip_sent=True,
        ),
        log_file=tmp_path / "email.log",
        sent_store_file=tmp_path / "sent_records.jsonl",
    )

    worker._run_job(job=job, cancel_event=threading.Event())

    assert writer.lines[-1]["type"] == "error"
    assert "missing.pdf" in writer.lines[-1]["error"]


def test_worker_start_send_requires_sender_email() -> None:
    writer = DummyWriter()
    worker = Worker(writer=writer)
    worker.handle_message(
        {
            "type": "start_send",
            "protocol": 1,
            "payload": {
                "sender": {"email": "", "name": "发件人"},
                "smtp": {
                    "host": "127.0.0.1",
                    "port": 1,
                    "username": "",
                    "password": "",
                    "use_ssl": False,
                    "use_starttls": False,
                    "timeout_sec": 1,
                },
                "template": {"subject": "hi", "body_text": "hello"},
                "recipients": [{"email": "teacher@example.com", "name": "张教授"}],
                "attachments": [],
                "options": {"retry_count": 1},
                "paths": {"log_file": "email.log", "sent_store_file": "sent_records.jsonl"},
            },
        }
    )

    assert writer.lines[0]["type"] == "error"
    assert "发件邮箱" in writer.lines[0]["error"]


def test_worker_start_send_requires_non_empty_recipients() -> None:
    writer = DummyWriter()
    worker = Worker(writer=writer)
    worker.handle_message(
        {
            "type": "start_send",
            "protocol": 1,
            "payload": {
                "sender": {"email": "sender@example.com", "name": "发件人"},
                "smtp": {
                    "host": "127.0.0.1",
                    "port": 1,
                    "username": "sender@example.com",
                    "password": "secret",
                    "use_ssl": False,
                    "use_starttls": False,
                    "timeout_sec": 1,
                },
                "template": {"subject": "hi", "body_text": "hello"},
                "recipients": [],
                "attachments": [],
                "options": {"retry_count": 1},
                "paths": {"log_file": "email.log", "sent_store_file": "sent_records.jsonl"},
            },
        }
    )

    assert writer.lines[0]["type"] == "error"
    assert "收件人" in writer.lines[0]["error"]


def test_worker_start_send_rejects_invalid_recipient_email() -> None:
    writer = DummyWriter()
    worker = Worker(writer=writer)
    worker.handle_message(
        {
            "type": "start_send",
            "protocol": 1,
            "payload": {
                "sender": {"email": "sender@example.com", "name": "发件人"},
                "smtp": {
                    "host": "127.0.0.1",
                    "port": 1,
                    "username": "sender@example.com",
                    "password": "secret",
                    "use_ssl": False,
                    "use_starttls": False,
                    "timeout_sec": 1,
                },
                "template": {"subject": "hi", "body_text": "hello"},
                "recipients": [{"email": "not-an-email", "name": "张教授"}],
                "attachments": [],
                "options": {"retry_count": 1},
                "paths": {"log_file": "email.log", "sent_store_file": "sent_records.jsonl"},
            },
        }
    )

    assert writer.lines[0]["type"] == "error"
    assert "格式不正确" in writer.lines[0]["error"]


def test_worker_start_send_requires_smtp_host() -> None:
    writer = DummyWriter()
    worker = Worker(writer=writer)
    worker.handle_message(
        {
            "type": "start_send",
            "protocol": 1,
            "payload": {
                "sender": {"email": "sender@example.com", "name": "发件人"},
                "smtp": {
                    "host": "",
                    "port": 465,
                    "username": "sender@example.com",
                    "password": "secret",
                    "use_ssl": True,
                    "use_starttls": False,
                    "timeout_sec": 10,
                },
                "template": {"subject": "hi", "body_text": "hello"},
                "recipients": [{"email": "teacher@example.com", "name": "张教授"}],
                "attachments": [],
                "options": {"retry_count": 1},
                "paths": {"log_file": "email.log", "sent_store_file": "sent_records.jsonl"},
            },
        }
    )

    assert writer.lines[0]["type"] == "error"
    assert "SMTP 主机" in writer.lines[0]["error"]


def test_worker_start_send_rejects_ssl_starttls_conflict() -> None:
    writer = DummyWriter()
    worker = Worker(writer=writer)
    worker.handle_message(
        {
            "type": "start_send",
            "protocol": 1,
            "payload": {
                "sender": {"email": "sender@example.com", "name": "发件人"},
                "smtp": {
                    "host": "smtp.example.com",
                    "port": 465,
                    "username": "sender@example.com",
                    "password": "secret",
                    "use_ssl": True,
                    "use_starttls": True,
                    "timeout_sec": 10,
                },
                "template": {"subject": "hi", "body_text": "hello"},
                "recipients": [{"email": "teacher@example.com", "name": "张教授"}],
                "attachments": [],
                "options": {"retry_count": 1},
                "paths": {"log_file": "email.log", "sent_store_file": "sent_records.jsonl"},
            },
        }
    )

    assert writer.lines[0]["type"] == "error"
    assert "配置冲突" in writer.lines[0]["error"]
