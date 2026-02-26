from __future__ import annotations

import random
import re
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from html import escape
from math import ceil
from pathlib import Path
from typing import Any

from bulk_email_sender.message_builder import build_email_message
from bulk_email_sender.models import JobConfig, Recipient
from bulk_email_sender.sent_store import SentStore
from bulk_email_sender.smtp_client import SMTPClient
from bulk_email_sender.template import render_template_text

SENDER_NAME_TOKEN = "__BULK_EMAIL_SENDER_NAME__"
SEND_DATE_TOKEN = "__BULK_EMAIL_SEND_DATE__"
SENDER_NAME_TEMPLATE_TOKEN = "{sender_name}"
SEND_DATE_TEMPLATE_TOKEN = "{send_date}"
SIGNATURE_TOKENS_PATTERN = re.compile(
    rf"{re.escape(SENDER_NAME_TOKEN)}(?:\r\n|\r|\n|<br\\s*/?>|[ \t]|&nbsp;|&#10;|&#13;)+{re.escape(SEND_DATE_TOKEN)}",
    flags=re.IGNORECASE,
)


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

            teacher_name = recipient.name
            yield {
                "type": "recipient_started",
                "job_id": job.job_id,
                "index": index,
                "email": recipient.email,
                "name": teacher_name,
            }

            try:
                message = self._build_message(job, recipient, teacher_name)
                # Use a fresh connection per email: avoids idle-timeout reconnect
                # penalties caused by SMTP servers silently dropping connections
                # during the inter-message delay.
                with self.smtp_client:
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
                cancelled = False
                remaining = float(delay)
                while remaining > 0:
                    if cancel_event and cancel_event.is_set():
                        cancelled = True
                        break
                    yield {
                        "type": "inter_send_wait",
                        "job_id": job.job_id,
                        "index": index,
                        "next_index": index + 1,
                        "delay_sec": delay,
                        "remaining_sec": int(ceil(remaining)),
                    }
                    chunk = min(1.0, remaining)
                    if self._sleep_with_cancel(chunk, cancel_event):
                        cancelled = True
                        break
                    remaining -= chunk
                if cancelled:
                    yield {
                        "type": "job_cancelled",
                        "job_id": job.job_id,
                        "success": success,
                        "failed": failed,
                        "skipped": skipped,
                        "total": len(recipients),
                    }
                    return

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
        send_date = _format_send_date(datetime.now())
        signature_name = _resolve_signature_name(job)
        normalized_body_text_template = _normalize_signature_tokens_in_template(job.template.body_text)
        variables = {
            "teacher_name": teacher_name,
            "teacher_email": recipient.email,
            "sender_name": signature_name,
            "signature_name": signature_name,
            "send_date": send_date,
        }

        subject = render_template_text(job.template.subject, variables)
        body_text = render_template_text(normalized_body_text_template, variables)

        body_html = _build_body_html(
            body_text_template=normalized_body_text_template,
            body_html_template=job.template.body_html,
            variables=variables,
            signature_name=signature_name,
            send_date=send_date,
        )

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
        for attempt in range(retries):
            try:
                self.smtp_client.send(recipient_email, message)
                return
            except Exception as exc:
                last_error = exc
                if attempt < retries - 1:
                    # Reset the persistent connection before next retry so we
                    # don't waste timeout_sec discovering a broken socket.
                    self.smtp_client.reset_connection()
                    self.sleep_func(1)  # brief pause to avoid hammering the server
        assert last_error is not None
        raise last_error

    def _pick_delay(self, min_delay_sec: int, max_delay_sec: int) -> int:
        if min_delay_sec < 0 or max_delay_sec < 0:
            return 0
        if max_delay_sec < min_delay_sec:
            min_delay_sec, max_delay_sec = max_delay_sec, min_delay_sec
        return self.randomizer.randint(min_delay_sec, max_delay_sec)

    def _sleep_with_cancel(self, delay_sec: float, cancel_event: threading.Event | None) -> bool:
        if delay_sec <= 0:
            return False
        if cancel_event is not None:
            return cancel_event.wait(timeout=delay_sec)
        self.sleep_func(delay_sec)
        return False

    def _validate_attachments(self, attachments: list[str]) -> None:
        for raw_path in attachments:
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"Attachment not found: {path}")


def _format_send_date(timestamp: datetime) -> str:
    return f"{timestamp.year}年{timestamp.month}月{timestamp.day}日"


def _resolve_signature_name(job: JobConfig) -> str:
    sender_name = (job.sender.name or "").strip()
    if sender_name:
        return sender_name
    return job.sender.email


def _normalize_signature_tokens_in_template(body_text_template: str) -> str:
    normalized = body_text_template.replace("\r\n", "\n").replace("\r", "\n")
    if SENDER_NAME_TEMPLATE_TOKEN not in normalized or SEND_DATE_TEMPLATE_TOKEN not in normalized:
        return normalized

    content_without_tokens = normalized.replace(SENDER_NAME_TEMPLATE_TOKEN, "").replace(SEND_DATE_TEMPLATE_TOKEN, "")
    content_lines = [line.rstrip() for line in content_without_tokens.split("\n")]

    while content_lines and content_lines[-1].strip() == "":
        content_lines.pop()

    if content_lines:
        content_lines.append("")
    content_lines.extend([SENDER_NAME_TEMPLATE_TOKEN, SEND_DATE_TEMPLATE_TOKEN])
    return "\n".join(content_lines)


def _render_plain_text_as_html(content: str) -> str:
    escaped = escape(content)
    return f'<div style="white-space: pre-wrap; line-height: 1.8;">{escaped}</div>'


def _build_signature_block_html(signature_name: str, send_date: str) -> str:
    safe_name = escape(signature_name)
    safe_date = escape(send_date)
    return (
        '<div style="margin-top:24px; display:flex; justify-content:flex-end; text-align:right;">'
        '<table role="presentation" cellspacing="0" cellpadding="0" '
        'style="border-collapse:collapse; text-align:center;">'
        f'<tr><td style="padding: 0 0 6px 0;">{safe_name}</td></tr>'
        f'<tr><td style="padding: 0;">{safe_date}</td></tr>'
        "</table>"
        "</div>"
    )


def _build_body_html(
    *,
    body_text_template: str,
    body_html_template: str | None,
    variables: dict[str, str],
    signature_name: str,
    send_date: str,
) -> str:
    signature_html = _build_signature_block_html(signature_name, send_date)
    if body_html_template:
        rendered_html = render_template_text(
            body_html_template,
            {
                **variables,
                "sender_name": SENDER_NAME_TOKEN,
                "send_date": SEND_DATE_TOKEN,
            },
        )
        return _inject_signature_block_by_tokens(
            rendered_html,
            signature_html=signature_html,
            sender_name=signature_name,
            send_date=send_date,
        )

    rendered_text_for_html = render_template_text(
        body_text_template,
        {
            **variables,
            "sender_name": SENDER_NAME_TOKEN,
            "send_date": SEND_DATE_TOKEN,
        },
    )
    rendered_text_html = _render_plain_text_as_html(rendered_text_for_html)
    return _inject_signature_block_by_tokens(
        rendered_text_html,
        signature_html=signature_html,
        sender_name=signature_name,
        send_date=send_date,
    )


def _inject_signature_block_by_tokens(
    content_html: str,
    *,
    signature_html: str,
    sender_name: str,
    send_date: str,
) -> str:
    composed = SIGNATURE_TOKENS_PATTERN.sub(signature_html, content_html)
    return (
        composed.replace(SENDER_NAME_TOKEN, escape(sender_name))
        .replace(SEND_DATE_TOKEN, escape(send_date))
    )
