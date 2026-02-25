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

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._emails = self._load_emails()
        self._handle: TextIOWrapper | None = None

    # -- context manager for batch writes --------------------------------------

    def __enter__(self) -> SentStore:
        self._handle = self.path.open("a", encoding="utf-8")
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
        payload = {
            "email": normalized_email,
            "teacher_name": teacher_name,
            "job_id": job_id,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"

        if self._handle is not None:
            self._handle.write(line)
            self._handle.flush()
        else:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)

        self._emails.add(normalized_email)
