from pathlib import Path

from bulk_email_sender.sent_store import SentStore


def test_sent_store_writes_human_readable_records(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "sent_records.jsonl"
    txt_path = tmp_path / "sent_records.txt"

    store = SentStore(jsonl_path, text_path=txt_path)
    store.append(email="Teacher1@Example.com", teacher_name="张教授", job_id="job-1")
    store.append(email="teacher2@example.com", teacher_name="李教授", job_id="job-2")

    text = txt_path.read_text(encoding="utf-8")
    assert "发送记录（可读版）" in text
    assert "teacher1@example.com" in text
    assert "teacher2@example.com" in text
    assert "张教授" in text
    assert "李教授" in text
    assert "job-1" in text
    assert "job-2" in text
