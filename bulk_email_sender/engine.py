from __future__ import annotations

import random
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from bulk_email_sender.message_builder import build_email_message
from bulk_email_sender.models import JobConfig, Recipient
from bulk_email_sender.sent_store import SentStore
from bulk_email_sender.smtp_client import SMTPClient
from bulk_email_sender.template import render_template_text


class SendEngine:
    def __init__(
        self,
        *,
        smtp_client: SMTPClient,
        sent_store: SentStore,
        sleep_func=time.sleep,
        randomizer: random.Random | None = None,
    ):
        self.smtp_client = smtp_client
        self.sent_store = sent_store
        self.sleep_func = sleep_func
        self.randomizer = randomizer or random.Random()

    def send(self, job: JobConfig, cancel_event: threading.Event | None = None) -> Iterator[dict[str, Any]]:
        self._validate_attachments(job.attachments)
        recipients = list(job.recipients)
        if job.options.randomize_order:
            self.randomizer.shuffle(recipients)

        success = 0
        failed = 0
        skipped = 0
        failures: list[dict[str, str]] = []

        yield {
            "type": "job_started",
            "job_id": job.job_id,
            "total": len(recipients),
        }

        # Reuse SMTP connection across the whole batch
        with self.smtp_client:
            for index, recipient in enumerate(recipients, start=1):
                if cancel_event and cancel_event.is_set():
                    yield {
                        "type": "job_cancelled",
                        "job_id": job.job_id,
                        "success": success,
                        "failed": failed,
                        "skipped": skipped,
                        "total": len(recipients),
                    }
                    return

                if job.options.skip_sent and self.sent_store.is_sent(recipient.email):
                    skipped += 1
                    yield {
                        "type": "recipient_skipped",
                        "job_id": job.job_id,
                        "index": index,
                        "email": recipient.email,
                        "name": recipient.name,
                        "reason": "already_sent",
                    }
                    continue

                teacher_name = _decorate_teacher_name(recipient, job.options.add_teacher_suffix)
                yield {
                    "type": "recipient_started",
                    "job_id": job.job_id,
                    "index": index,
                    "email": recipient.email,
                    "name": teacher_name,
                }

                try:
                    message = self._build_message(job, recipient, teacher_name)
                    self._send_with_retry(
                        recipient_email=recipient.email,
                        message=message,
                        retry_count=job.options.retry_count,
                    )
                    self.sent_store.append(
                        email=recipient.email,
                        teacher_name=teacher_name,
                        job_id=job.job_id,
                    )
                    success += 1
                    yield {
                        "type": "recipient_sent",
                        "job_id": job.job_id,
                        "index": index,
                        "email": recipient.email,
                        "name": teacher_name,
                    }
                except Exception as exc:
                    failed += 1
                    failures.append({"email": recipient.email, "name": teacher_name, "error": str(exc)})
                    yield {
                        "type": "recipient_failed",
                        "job_id": job.job_id,
                        "index": index,
                        "email": recipient.email,
                        "name": teacher_name,
                        "error": str(exc),
                    }

                if index < len(recipients):
                    delay = self._pick_delay(job.options.min_delay_sec, job.options.max_delay_sec)
                    self._sleep_with_cancel(delay, cancel_event)

        yield {
            "type": "job_finished",
            "job_id": job.job_id,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "total": len(recipients),
            "failures": failures,
        }

    def _build_message(self, job: JobConfig, recipient: Recipient, teacher_name: str):
        variables = {
            "teacher_name": teacher_name,
            "teacher_email": recipient.email,
            "sender_name": job.sender.name or "",
        }

        subject = render_template_text(job.template.subject, variables)
        body_text = render_template_text(job.template.body_text, variables)
        body_html = None
        if job.template.body_html:
            body_html = render_template_text(job.template.body_html, variables)

        return build_email_message(
            sender=job.sender,
            recipient_email=recipient.email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachments=job.attachments,
        )

    def _send_with_retry(self, *, recipient_email: str, message, retry_count: int) -> None:
        retries = max(retry_count, 1)
        last_error: Exception | None = None
        for _ in range(retries):
            try:
                self.smtp_client.send(recipient_email, message)
                return
            except Exception as exc:
                last_error = exc
                continue
        assert last_error is not None
        raise last_error

    def _pick_delay(self, min_delay_sec: int, max_delay_sec: int) -> int:
        if min_delay_sec < 0 or max_delay_sec < 0:
            return 0
        if max_delay_sec < min_delay_sec:
            min_delay_sec, max_delay_sec = max_delay_sec, min_delay_sec
        return self.randomizer.randint(min_delay_sec, max_delay_sec)

    def _sleep_with_cancel(self, delay_sec: int, cancel_event: threading.Event | None) -> None:
        if delay_sec <= 0:
            return
        if cancel_event is not None:
            cancel_event.wait(timeout=delay_sec)
        else:
            self.sleep_func(delay_sec)

    def _validate_attachments(self, attachments: list[str]) -> None:
        for raw_path in attachments:
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"Attachment not found: {path}")


def _decorate_teacher_name(recipient: Recipient, add_teacher_suffix: bool) -> str:
    if not add_teacher_suffix:
        return recipient.name
    if recipient.name.endswith("老师"):
        return recipient.name
    return f"{recipient.name}老师"
