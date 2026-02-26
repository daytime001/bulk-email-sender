from __future__ import annotations

import json
from datetime import datetime, timezone
from io import TextIOWrapper
from pathlib import Path
from types import TracebackType


class SentStore:
    """Append-only JSONL store for sent email records.

    Supports context-manager mode for batch writes (keeps file handle open):
        with SentStore(path) as store:
            store.append(...)
    """

    def __init__(self, path: str | Path, text_path: str | Path | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.text_path = Path(text_path) if text_path else None
        if self.text_path is not None:
            self.text_path.parent.mkdir(parents=True, exist_ok=True)
        self._emails = self._load_emails()
        self._handle: TextIOWrapper | None = None
        self._text_handle: TextIOWrapper | None = None
        self._text_header_written = bool(
            self.text_path and self.text_path.exists() and self.text_path.stat().st_size > 0
        )

    # -- context manager for batch writes --------------------------------------

    def __enter__(self) -> SentStore:
        self._handle = self.path.open("a", encoding="utf-8")
        if self.text_path is not None:
            self._text_handle = self.text_path.open("a", encoding="utf-8")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            handle.flush()
            handle.close()
        text_handle = self._text_handle
        self._text_handle = None
        if text_handle is not None:
            text_handle.flush()
            text_handle.close()

    # -- public API ------------------------------------------------------------

    def _load_emails(self) -> set[str]:
        emails: set[str] = set()
        if not self.path.exists():
            return emails

        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                email = str(payload.get("email", "")).strip().lower()
                if email:
                    emails.add(email)
        return emails

    def is_sent(self, email: str) -> bool:
        return email.strip().lower() in self._emails

    def append(self, email: str, teacher_name: str, job_id: str) -> None:
        normalized_email = email.strip().lower()
        sent_at = datetime.now(timezone.utc)
        payload = {
            "email": normalized_email,
            "teacher_name": teacher_name,
            "job_id": job_id,
            "sent_at": sent_at.isoformat(),
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"

        if self._handle is not None:
            self._handle.write(line)
            self._handle.flush()
        else:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)

        self._append_text_line(
            email=normalized_email,
            teacher_name=teacher_name,
            job_id=job_id,
            sent_at=sent_at,
        )
        self._emails.add(normalized_email)

    def _append_text_line(self, *, email: str, teacher_name: str, job_id: str, sent_at: datetime) -> None:
        if self.text_path is None:
            return

        local_time = sent_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{local_time}] 发送成功 | 姓名: {teacher_name} | 邮箱: {email} | 任务: {job_id}\n"

        if self._text_handle is not None:
            if not self._text_header_written:
                self._text_handle.write("# Bulk-Email-Sender 发送记录（可读版）\n")
                self._text_handle.write("# 格式: 时间 | 姓名 | 邮箱 | 任务ID\n")
                self._text_header_written = True
            self._text_handle.write(line)
            self._text_handle.flush()
            return

        with self.text_path.open("a", encoding="utf-8") as handle:
            if not self._text_header_written:
                handle.write("# Bulk-Email-Sender 发送记录（可读版）\n")
                handle.write("# 格式: 时间 | 姓名 | 邮箱 | 任务ID\n")
                self._text_header_written = True
            handle.write(line)
