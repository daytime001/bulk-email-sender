import pytest

from bulk_email_sender.template import TemplateRenderError, render_template_text


def test_render_template_supports_single_brace_placeholders() -> None:
    rendered = render_template_text(
        "您好 {teacher_name}，邮箱 {teacher_email}",
        {"teacher_name": "张老师", "teacher_email": "teacher@example.com"},
    )
    assert rendered == "您好 张老师，邮箱 teacher@example.com"


def test_render_template_supports_double_brace_placeholders() -> None:
    rendered = render_template_text(
        "您好 {{teacher_name}}",
        {"teacher_name": "张老师"},
    )
    assert rendered == "您好 张老师"


def test_render_template_raises_when_required_variable_missing() -> None:
    with pytest.raises(TemplateRenderError):
        render_template_text("您好 {teacher_name}", {})
