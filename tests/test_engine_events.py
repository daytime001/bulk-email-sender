from pathlib import Path

from bulk_email_sender.engine import SendEngine
from bulk_email_sender.models import (
    JobConfig,
    Recipient,
    Sender,
    SendOptions,
    SMTPConfig,
    Template,
)
from bulk_email_sender.sent_store import SentStore


class FakeSMTPClient:
    def __init__(self) -> None:
        self.sent_targets = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def test_connection(self) -> None:
        return None

    def send(self, recipient_email: str, message: object) -> None:
        self.sent_targets.append(recipient_email)


def _build_job(tmp_path: Path) -> JobConfig:
    return JobConfig(
        job_id="job-1",
        sender=Sender(email="sender@example.com", name="发件人"),
        smtp=SMTPConfig(
            host="smtp.126.com",
            port=465,
            username="sender@example.com",
            password="auth-code",
            use_ssl=True,
            timeout_sec=30,
        ),
        template=Template(
            subject="您好 {teacher_name}",
            body_text="正文 {teacher_name}",
            body_html=None,
        ),
        recipients=[
            Recipient(email="teacher1@example.com", name="张教授"),
            Recipient(email="teacher2@example.com", name="李教授"),
        ],
        attachments=[],
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


def test_send_engine_emits_expected_summary(tmp_path: Path) -> None:
    job = _build_job(tmp_path)
    smtp_client = FakeSMTPClient()
    sent_store = SentStore(job.sent_store_file)
    engine = SendEngine(smtp_client=smtp_client, sent_store=sent_store)

    events = list(engine.send(job))

    assert events[0]["type"] == "job_started"
    assert events[-1]["type"] == "job_finished"
    assert events[-1]["success"] == 2
    assert smtp_client.sent_targets == ["teacher1@example.com", "teacher2@example.com"]


def test_send_engine_skips_previously_sent_recipients(tmp_path: Path) -> None:
    job = _build_job(tmp_path)
    sent_store = SentStore(job.sent_store_file)
    sent_store.append(email="teacher1@example.com", teacher_name="张教授", job_id="before")
    smtp_client = FakeSMTPClient()
    engine = SendEngine(smtp_client=smtp_client, sent_store=sent_store)

    events = list(engine.send(job))
    skipped_events = [event for event in events if event["type"] == "recipient_skipped"]

    assert len(skipped_events) == 1
    assert skipped_events[0]["email"] == "teacher1@example.com"
    assert smtp_client.sent_targets == ["teacher2@example.com"]


def test_send_engine_fails_fast_when_attachment_missing(tmp_path: Path) -> None:
    job = _build_job(tmp_path)
    job.attachments.append(str(tmp_path / "missing.pdf"))
    smtp_client = FakeSMTPClient()
    sent_store = SentStore(job.sent_store_file)
    engine = SendEngine(smtp_client=smtp_client, sent_store=sent_store)

    try:
        list(engine.send(job))
    except FileNotFoundError as exc:
        assert "missing.pdf" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError for missing attachment")

    assert smtp_client.sent_targets == []
