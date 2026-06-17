from __future__ import annotations

from pathlib import Path
from string import Formatter


def load_prompt_template(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"Prompt template file is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"Prompt template file is empty: {path}")
    return text


def render_prompt_template(template: str, values: dict[str, object]) -> str:
    required_names = {
        field_name
        for _, field_name, _, _ in Formatter().parse(template)
        if field_name
    }
    missing_names = sorted(name for name in required_names if name not in values)
    if missing_names:
        raise RuntimeError(f"Prompt template is missing values for placeholders: {', '.join(missing_names)}")
    try:
        return template.format(**values)
    except KeyError as exc:
        raise RuntimeError(f"Prompt template is missing value for placeholder: {exc.args[0]}") from exc
