from __future__ import annotations

import re


class TemplateRenderError(ValueError):
    """Raised when template rendering fails."""


_DOUBLE_BRACE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class _StrictMapping(dict):
    def __missing__(self, key: str) -> str:
        raise KeyError(key)


def _normalize_template_placeholders(template: str) -> str:
    return _DOUBLE_BRACE_PATTERN.sub(r"{\1}", template)


def render_template_text(template: str, variables: dict[str, object]) -> str:
    normalized_template = _normalize_template_placeholders(template)
    try:
        return normalized_template.format_map(_StrictMapping(variables))
    except KeyError as exc:
        missing_key = exc.args[0]
        raise TemplateRenderError(f"Missing template variable: {missing_key}") from exc
    except ValueError as exc:
        raise TemplateRenderError(str(exc)) from exc
