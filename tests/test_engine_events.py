from dataclasses import replace
from datetime import datetime
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
        self.messages = []
        self.reset_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def test_connection(self) -> None:
        return None

    def reset_connection(self) -> None:
        self.reset_calls += 1

    def send(self, recipient_email: str, message: object) -> None:
        self.sent_targets.append(recipient_email)
        self.messages.append(message)


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


def test_send_with_retry_resets_connection_on_failure(tmp_path: Path) -> None:
    """After a send failure the engine should reset the persistent connection
    before the next retry so we don't reuse a potentially broken socket."""
    job = _build_job(tmp_path)
    # Need at least 2 attempts for a retry to happen
    job = replace(job, options=replace(job.options, retry_count=2))

    calls = {"count": 0}

    class FailOnceSMTPClient(FakeSMTPClient):
        def send(self, recipient_email: str, message: object) -> None:
            calls["count"] += 1
            if calls["count"] == 1:
                raise ConnectionResetError("simulated disconnect")
            super().send(recipient_email, message)

    smtp_client = FailOnceSMTPClient()
    sent_store = SentStore(job.sent_store_file)
    # Use a no-op sleep so the retry delay doesn't slow the test
    engine = SendEngine(smtp_client=smtp_client, sent_store=sent_store, sleep_func=lambda _: None)

    events = list(engine.send(job))

    finished = events[-1]
    assert finished["type"] == "job_finished"
    assert finished["success"] == 2
    # reset_connection must have been called once (before the second attempt for email 1)
    assert smtp_client.reset_calls == 1


def test_send_engine_waits_full_delay_even_when_send_is_slow(tmp_path: Path, monkeypatch) -> None:
    job = _build_job(tmp_path)
    job = replace(job, options=replace(job.options, min_delay_sec=5, max_delay_sec=5))
    smtp_client = FakeSMTPClient()
    sent_store = SentStore(job.sent_store_file)
    sleep_calls: list[float] = []
    engine = SendEngine(
        smtp_client=smtp_client,
        sent_store=sent_store,
        sleep_func=lambda seconds: sleep_calls.append(seconds),
    )

    tick_values = iter([100.0, 106.0, 200.0])
    monkeypatch.setattr("bulk_email_sender.engine.time.time", lambda: next(tick_values, 200.0))

    list(engine.send(job))

    assert sum(sleep_calls) == 5.0


def test_send_engine_emits_wait_countdown_events(tmp_path: Path) -> None:
    job = _build_job(tmp_path)
    job = replace(job, options=replace(job.options, min_delay_sec=3, max_delay_sec=3))
    smtp_client = FakeSMTPClient()
    sent_store = SentStore(job.sent_store_file)
    sleep_calls: list[float] = []
    engine = SendEngine(
        smtp_client=smtp_client,
        sent_store=sent_store,
        sleep_func=lambda seconds: sleep_calls.append(seconds),
    )

    events = list(engine.send(job))
    wait_events = [event for event in events if event["type"] == "inter_send_wait"]

    assert [event["remaining_sec"] for event in wait_events] == [3, 2, 1]
    assert all(event["delay_sec"] == 3 for event in wait_events)
    assert sum(sleep_calls) == 3.0


def test_send_engine_renders_sender_name_and_send_date_as_signature_block(tmp_path: Path) -> None:
    job = _build_job(tmp_path)
    job = replace(
        job,
        sender=Sender(email="sender@example.com", name="学生张三"),
        template=Template(
            subject="您好 {teacher_name}",
            body_text="尊敬的{teacher_name}：\n\n正文内容\n\n{sender_name}\n{send_date}",
            body_html=None,
        ),
        recipients=[Recipient(email="teacher@example.com", name="魏中信")],
    )
    smtp_client = FakeSMTPClient()
    sent_store = SentStore(job.sent_store_file)
    engine = SendEngine(smtp_client=smtp_client, sent_store=sent_store)

    list(engine.send(job))

    message = smtp_client.messages[0]
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))

    today = datetime.now()
    expected_date = f"{today.year}年{today.month}月{today.day}日"

    assert plain is not None
    plain_text = plain.get_content()
    assert "尊敬的魏中信：" in plain_text
    assert "魏中信老师" not in plain_text
    assert "学生张三" in plain_text
    assert expected_date in plain_text

    assert html is not None
    html_text = html.get_content()
    assert expected_date in html_text
    assert "text-align:right" in html_text
    assert "text-align:center" in html_text


def test_send_engine_does_not_auto_append_signature_when_placeholder_missing(tmp_path: Path) -> None:
    job = _build_job(tmp_path)
    job = replace(
        job,
        sender=Sender(email="sender@example.com", name="学生张三"),
        template=Template(
            subject="您好 {teacher_name}",
            body_text="尊敬的{teacher_name}：\n\n仅正文内容",
            body_html=None,
        ),
        recipients=[Recipient(email="teacher@example.com", name="魏中信")],
    )
    smtp_client = FakeSMTPClient()
    sent_store = SentStore(job.sent_store_file)
    engine = SendEngine(smtp_client=smtp_client, sent_store=sent_store)

    list(engine.send(job))

    message = smtp_client.messages[0]
    plain = message.get_body(preferencelist=("plain",))
    assert plain is not None
    plain_text = plain.get_content()

    today = datetime.now()
    expected_date = f"{today.year}年{today.month}月{today.day}日"

    assert "仅正文内容" in plain_text
    assert "学生张三" not in plain_text
    assert expected_date not in plain_text


def test_send_engine_normalizes_signature_placeholders_to_trailing_block(tmp_path: Path) -> None:
    job = _build_job(tmp_path)
    job = replace(
        job,
        sender=Sender(email="sender@example.com", name="学生张三"),
        template=Template(
            subject="您好 {teacher_name}",
            body_text="第一段\n{sender_name}\n第二段\n{send_date}\n第三段",
            body_html=None,
        ),
        recipients=[Recipient(email="teacher@example.com", name="魏中信")],
    )
    smtp_client = FakeSMTPClient()
    sent_store = SentStore(job.sent_store_file)
    engine = SendEngine(smtp_client=smtp_client, sent_store=sent_store)

    list(engine.send(job))

    message = smtp_client.messages[0]
    plain = message.get_body(preferencelist=("plain",))
    html = message.get_body(preferencelist=("html",))
    assert plain is not None
    assert html is not None

    today = datetime.now()
    expected_date = f"{today.year}年{today.month}月{today.day}日"

    plain_text = plain.get_content()
    assert "第一段" in plain_text
    assert "第二段" in plain_text
    assert "第三段" in plain_text
    assert plain_text.strip().endswith(f"学生张三\n{expected_date}")

    html_text = html.get_content()
    assert "text-align:right" in html_text
    assert "text-align:center" in html_text
    assert html_text.count("学生张三") == 1
    assert html_text.count(expected_date) == 1
