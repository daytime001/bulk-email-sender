from __future__ import annotations

import logging
from pathlib import Path
from types import ModuleType

from bulk_email_sender.engine import SendEngine
from bulk_email_sender.models import JobConfig, Sender, SendOptions, SMTPConfig, Template
from bulk_email_sender.recipients_loader import RecipientLoadResult, load_recipients
from bulk_email_sender.sent_store import SentStore
from bulk_email_sender.smtp_client import SMTPClient

logger = logging.getLogger(__name__)


class LegacyConfigError(ValueError):
    """Raised when legacy config.py cannot build a valid job config."""


def ensure_legacy_config_ready(config: ModuleType) -> None:
    if (
        getattr(config, "SENDER_EMAIL", "") == "your_email@126.com"
        or getattr(config, "SENDER_PASSWORD", "") == "your_authorization_code"
    ):
        raise LegacyConfigError("请先在 config.py 中配置您的邮箱信息")


def load_recipients_from_legacy_config(config: ModuleType) -> RecipientLoadResult:
    data_file = Path(
        getattr(config, "TEACHER_DATA_FILE", "examples/recipients/recipients_sample.json")
    )
    return load_recipients(data_file)


def build_job_from_legacy_config(config: ModuleType, *, job_id: str, recipients) -> JobConfig:
    smtp = SMTPConfig(
        host=getattr(config, "SMTP_SERVER", "smtp.126.com"),
        port=int(getattr(config, "SMTP_PORT", 465)),
        username=getattr(config, "SENDER_EMAIL", ""),
        password=getattr(config, "SENDER_PASSWORD", ""),
        use_ssl=True,
        timeout_sec=30,
    )
    sender = Sender(
        email=getattr(config, "SENDER_EMAIL", ""),
        name=getattr(config, "SENDER_NAME", None),
    )
    template = Template(
        subject=getattr(config, "EMAIL_SUBJECT", ""),
        body_text=getattr(config, "EMAIL_CONTENT", ""),
        body_html=None,
    )
    options = SendOptions(
        min_delay_sec=int(getattr(config, "MIN_DELAY", 0)),
        max_delay_sec=int(getattr(config, "MAX_DELAY", 0)),
        randomize_order=bool(getattr(config, "RANDOMIZE_ORDER", False)),
        retry_count=3,
        skip_sent=True,
    )

    log_file = Path(getattr(config, "LOG_FILE", "email_log.txt"))
    sent_store_file = log_file.with_name("sent_records.jsonl")
    sent_store_text_file = log_file
    attachments = [str(path) for path in getattr(config, "ATTACHMENTS", [])]

    return JobConfig(
        job_id=job_id,
        sender=sender,
        smtp=smtp,
        template=template,
        recipients=list(recipients),
        attachments=attachments,
        options=options,
        log_file=log_file,
        sent_store_file=sent_store_file,
        sent_store_text_file=sent_store_text_file,
    )


def create_engine(job: JobConfig) -> SendEngine:
    sent_store = SentStore(job.sent_store_file, text_path=job.sent_store_text_file)
    smtp_client = SMTPClient(job.smtp)
    return SendEngine(smtp_client=smtp_client, sent_store=sent_store)
