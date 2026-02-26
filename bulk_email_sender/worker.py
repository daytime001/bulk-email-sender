from __future__ import annotations

import json
import re
import sys
import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bulk_email_sender.recipients_loader import RecipientLoadError

if TYPE_CHECKING:
    from bulk_email_sender.models import JobConfig, Recipient

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class JsonLineWriter:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self._lock = threading.Lock()

    def write_line(self, payload: dict[str, Any]) -> None:
        text = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            self.stream.write(text + "\n")
            self.stream.flush()


class Worker:
    def __init__(self, writer=None):
        self.writer = writer or JsonLineWriter()
        self._job_thread: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None

    def handle_message(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type", "")).strip()
        payload = message.get("payload", {}) or {}
        try:
            if message_type == "load_recipients":
                self._handle_load_recipients(payload)
            elif message_type == "test_smtp":
                self._handle_test_smtp(payload)
            elif message_type == "start_send":
                self._handle_start_send(payload)
            elif message_type == "cancel":
                self._handle_cancel()
            else:
                self.writer.write_line({"type": "error", "error": f"Unknown message type: {message_type}"})
        except RecipientLoadError as exc:
            self.writer.write_line({"type": "error", "error": str(exc)})
        except Exception as exc:
            self.writer.write_line({"type": "error", "error": str(exc)})

    def _handle_load_recipients(self, payload: dict[str, Any]) -> None:
        from bulk_email_sender.recipients_loader import load_recipients

        path = payload.get("path")
        if not path:
            raise RecipientLoadError("Missing recipient file path")

        result = load_recipients(path, raise_on_invalid=False)
        self.writer.write_line(
            {
                "type": "recipients_loaded",
                "stats": asdict(result.stats),
                "recipients_preview": [asdict(recipient) for recipient in result.recipients[:20]],
            }
        )

    def _handle_test_smtp(self, payload: dict[str, Any]) -> None:
        from bulk_email_sender.models import SMTPConfig
        from bulk_email_sender.smtp_client import SMTPClient

        smtp = SMTPConfig(
            host=str(payload.get("host", "")),
            port=int(payload.get("port", 465)),
            username=str(payload.get("username", "")),
            password=str(payload.get("password", "")),
            use_ssl=bool(payload.get("use_ssl", True)),
            use_starttls=bool(payload.get("use_starttls", False)),
            timeout_sec=int(payload.get("timeout_sec", 30)),
        )
        SMTPClient(smtp).test_connection()
        self.writer.write_line({"type": "smtp_test_succeeded"})

    def _handle_start_send(self, payload: dict[str, Any]) -> None:
        if self._job_thread and self._job_thread.is_alive():
            self.writer.write_line({"type": "error", "error": "Another job is running"})
            return

        job = _build_job_config(payload)
        cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._run_job,
            kwargs={"job": job, "cancel_event": cancel_event},
            daemon=True,
        )
        self._cancel_event = cancel_event
        self._job_thread = thread
        thread.start()
        self.writer.write_line({"type": "job_accepted", "job_id": job.job_id})

    def _handle_cancel(self) -> None:
        if not self._job_thread or not self._job_thread.is_alive() or self._cancel_event is None:
            self.writer.write_line({"type": "error", "error": "No active job"})
            return
        self._cancel_event.set()
        self.writer.write_line({"type": "cancel_requested"})

    def _run_job(self, job: JobConfig, cancel_event: threading.Event) -> None:
        from bulk_email_sender.engine import SendEngine
        from bulk_email_sender.sent_store import SentStore
        from bulk_email_sender.smtp_client import SMTPClient

        smtp_client = SMTPClient(job.smtp)
        with SentStore(job.sent_store_file, text_path=job.sent_store_text_file) as sent_store:
            engine = SendEngine(smtp_client=smtp_client, sent_store=sent_store)
            try:
                for event in engine.send(job, cancel_event=cancel_event):
                    self.writer.write_line(event)
            except Exception as exc:
                self.writer.write_line({"type": "error", "job_id": job.job_id, "error": str(exc)})


def _build_job_config(payload: dict[str, Any]) -> JobConfig:
    from bulk_email_sender.models import JobConfig, Sender, SendOptions, SMTPConfig, Template

    job_id = str(payload.get("job_id") or uuid.uuid4().hex)
    sender_payload = payload.get("sender", {})
    smtp_payload = payload.get("smtp", {})
    template_payload = payload.get("template", {})
    options_payload = payload.get("options", {})
    paths_payload = payload.get("paths", {})

    sender_email = _validate_email(
        str(sender_payload.get("email", smtp_payload.get("username", ""))).strip(),
        field_name="发件邮箱",
    )
    smtp_host = str(smtp_payload.get("host", "")).strip()
    if not smtp_host:
        raise ValueError("SMTP 主机不能为空")
    smtp_port = _parse_int(
        smtp_payload.get("port", 465),
        field_name="SMTP 端口",
        minimum=1,
        maximum=65535,
    )
    use_ssl = _parse_bool(smtp_payload.get("use_ssl", True), field_name="SMTP use_ssl")
    use_starttls = _parse_bool(smtp_payload.get("use_starttls", False), field_name="SMTP use_starttls")
    if use_ssl and use_starttls:
        raise ValueError("SMTP 配置冲突：use_ssl 与 use_starttls 不能同时开启")
    timeout_sec = _parse_int(
        smtp_payload.get("timeout_sec", 30),
        field_name="SMTP 超时时间",
        minimum=1,
    )
    sender_name = str(sender_payload.get("name", "")).strip()
    if not sender_name:
        raise ValueError("发件人姓名不能为空")
    sender = Sender(
        email=sender_email,
        name=sender_name,
    )

    smtp = SMTPConfig(
        host=smtp_host,
        port=smtp_port,
        username=str(smtp_payload.get("username", "")),
        password=str(smtp_payload.get("password", "")),
        use_ssl=use_ssl,
        use_starttls=use_starttls,
        timeout_sec=timeout_sec,
    )
    template = Template(
        subject=str(template_payload.get("subject", "")),
        body_text=str(template_payload.get("body_text", "")),
        body_html=template_payload.get("body_html"),
    )
    options = SendOptions(
        min_delay_sec=_parse_int(
            options_payload.get("min_delay_sec", 0),
            field_name="最小延迟",
            minimum=0,
        ),
        max_delay_sec=_parse_int(
            options_payload.get("max_delay_sec", 0),
            field_name="最大延迟",
            minimum=0,
        ),
        randomize_order=_parse_bool(
            options_payload.get("randomize_order", False),
            field_name="randomize_order",
        ),
        retry_count=_parse_int(
            options_payload.get("retry_count", 1),
            field_name="重试次数",
            minimum=1,
        ),
        skip_sent=_parse_bool(
            options_payload.get("skip_sent", True),
            field_name="skip_sent",
        ),
    )
    attachments = [str(path) for path in payload.get("attachments", [])]

    recipients = _resolve_recipients(payload)
    if not recipients:
        raise RecipientLoadError("收件人列表不能为空")
    log_file = Path(paths_payload.get("log_file", "email_log.txt"))
    sent_store_file = Path(paths_payload.get("sent_store_file", "sent_records.jsonl"))
    sent_store_text_file_raw = paths_payload.get("sent_store_text_file")
    if sent_store_text_file_raw:
        sent_store_text_file = Path(sent_store_text_file_raw)
    else:
        sent_store_text_file = sent_store_file.with_suffix(".txt")

    return JobConfig(
        job_id=job_id,
        sender=sender,
        smtp=smtp,
        template=template,
        recipients=recipients,
        attachments=attachments,
        options=options,
        log_file=log_file,
        sent_store_file=sent_store_file,
        sent_store_text_file=sent_store_text_file,
    )


def _resolve_recipients(payload: dict[str, Any]) -> list[Recipient]:
    from bulk_email_sender.models import Recipient
    from bulk_email_sender.recipients_loader import load_recipients

    if "recipients" in payload and payload["recipients"] is not None:
        recipients: list[Recipient] = []
        for index, item in enumerate(payload["recipients"], start=1):
            if not isinstance(item, dict):
                raise RecipientLoadError(f"Invalid recipients[{index}] payload")
            email = _validate_email(str(item.get("email", "")).strip(), field_name=f"recipients[{index}].email")
            name = str(item.get("name", "")).strip()
            if not name:
                raise RecipientLoadError(f"Invalid recipients[{index}] data")
            recipients.append(Recipient(email=email, name=name))
        return recipients

    recipients_file = payload.get("recipients_file")
    if recipients_file:
        return load_recipients(str(recipients_file).strip()).recipients

    raise RecipientLoadError("Missing recipients or recipients_file")


def _validate_email(email: str, *, field_name: str) -> str:
    normalized = email.strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空")
    if not EMAIL_RE.match(normalized):
        raise ValueError(f"{field_name} 格式不正确")
    return normalized


def _parse_int(value: Any, *, field_name: str, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是整数") from exc

    if minimum is not None and parsed < minimum:
        raise ValueError(f"{field_name} 必须 >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{field_name} 必须 <= {maximum}")
    return parsed


def _parse_bool(value: Any, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    raise ValueError(f"{field_name} 必须是布尔值")


def main() -> None:
    worker = Worker()
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            worker.writer.write_line({"type": "error", "error": f"Invalid JSON: {exc}"})
            continue
        worker.handle_message(message)
    # Wait for any in-flight job thread so all events are flushed before exit.
    if worker._job_thread is not None and worker._job_thread.is_alive():
        worker._job_thread.join()


if __name__ == "__main__":
    main()
