import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from bulk_email_sender.recipients_loader import RecipientLoadError, load_recipients


def test_load_json_map_format(tmp_path: Path) -> None:
    recipients_path = tmp_path / "teachers.json"
    recipients_path.write_text(
        json.dumps({"teacher1@example.com": "张教授", "teacher2@example.com": "李教授"}),
        encoding="utf-8",
    )

    result = load_recipients(recipients_path)

    assert [recipient.email for recipient in result.recipients] == [
        "teacher1@example.com",
        "teacher2@example.com",
    ]
    assert result.stats.total_rows == 2
    assert result.stats.valid_rows == 2


def test_load_xlsx_with_headers_and_duplicate_rows(tmp_path: Path) -> None:
    recipients_path = tmp_path / "teachers.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["邮箱", "姓名"])
    sheet.append(["teacher1@example.com", "张教授"])
    sheet.append(["teacher1@example.com", "张教授重复"])
    sheet.append(["teacher2@example.com", "李教授"])
    workbook.save(recipients_path)

    result = load_recipients(recipients_path)

    assert [recipient.email for recipient in result.recipients] == [
        "teacher1@example.com",
        "teacher2@example.com",
    ]
    assert result.stats.duplicate_rows == 1
    assert result.stats.invalid_rows == 0


def test_load_xlsx_without_headers_uses_ab_columns(tmp_path: Path) -> None:
    recipients_path = tmp_path / "teachers-no-header.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["teacher3@example.com", "王教授"])
    workbook.save(recipients_path)

    result = load_recipients(recipients_path)

    assert len(result.recipients) == 1
    assert result.recipients[0].name == "王教授"


def test_invalid_rows_raise_error_with_details(tmp_path: Path) -> None:
    recipients_path = tmp_path / "teachers-invalid.json"
    recipients_path.write_text(
        json.dumps(
            [
                {"email": "not-an-email", "name": "坏数据"},
                {"email": "good@example.com", "name": "好数据"},
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(RecipientLoadError) as exc_info:
        load_recipients(recipients_path)

    assert "not-an-email" in str(exc_info.value)


def test_load_json_lenient_stats_include_sendable_invalid_and_missing_name(tmp_path: Path) -> None:
    recipients_path = tmp_path / "teachers-lenient.json"
    recipients_path.write_text(
        json.dumps(
            [
                {"email": "good1@example.com", "name": "张教授"},
                {"email": "bad-email", "name": "坏邮箱"},
                {"email": "good2@example.com", "name": ""},
                {"email": "good1@example.com", "name": "重复但可发"},
                {"email": "", "name": ""},
            ]
        ),
        encoding="utf-8",
    )

    result = load_recipients(recipients_path, raise_on_invalid=False)

    assert result.stats.total_rows == 5
    assert result.stats.sendable_rows == 2
    assert result.stats.invalid_email_rows == 1
    assert result.stats.missing_name_rows == 1
