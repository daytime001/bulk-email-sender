from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Recipient:
    email: str
    name: str


@dataclass(frozen=True)
class Sender:
    email: str
    name: str | None = None


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    use_ssl: bool = True
    use_starttls: bool = False
    timeout_sec: int = 30


@dataclass(frozen=True)
class Template:
    subject: str
    body_text: str
    body_html: str | None = None


@dataclass(frozen=True)
class SendOptions:
    min_delay_sec: int = 0
    max_delay_sec: int = 0
    randomize_order: bool = False
    retry_count: int = 1
    skip_sent: bool = True


@dataclass(frozen=True)
class JobConfig:
    job_id: str
    sender: Sender
    smtp: SMTPConfig
    template: Template
    recipients: list[Recipient]
    attachments: list[str]
    options: SendOptions
    log_file: Path
    sent_store_file: Path
    sent_store_text_file: Path | None = None
