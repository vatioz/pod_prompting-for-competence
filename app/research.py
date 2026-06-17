from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib import error, request

from .config import GENERATED_RESEARCH_DIR, RESEARCH_PROMPT_PATH
from .prompt_loader import load_prompt_template, render_prompt_template
from .storage import topic_artifact_stem

REQUIRED_HEADINGS = (
    "## Topic Statement",
    "## Key Concepts",
    "## Why It Matters",
    "## Practical Examples",
    "## Tradeoffs / Caveats",
    "## Glossary / Jargon Expansion",
    "## Source Notes",
    "## Unresolved Questions",
)


def generate_research_markdown(
    topic: dict,
    output_dir: Path = GENERATED_RESEARCH_DIR,
    research_config: dict | None = None,
) -> Path:
    config = dict(research_config or {})
    text = build_research_markdown_with_foundry(topic=topic, research_config=config)
    validate_research_markdown(text, minimum_characters=int(config.get("minimum_characters") or 500))
    output_dir.mkdir(parents=True, exist_ok=True)
    research_path = output_dir / f"{topic_artifact_stem(topic)}.md"
    research_path.write_text(text, encoding="utf-8")
    return research_path


def build_research_markdown_with_foundry(topic: dict, research_config: dict) -> str:
    response = _call_foundry_research(topic=topic, research_config=research_config)
    text = _extract_output_text(response).strip()
    if not text:
        raise RuntimeError("Azure Foundry research response did not include output text")
    return _inject_source_notes(text, response)


def validate_research_markdown(text: str, minimum_characters: int = 500) -> None:
    stripped = text.strip()
    if len(stripped) < minimum_characters:
        raise ValueError(f"Research artifact is too short to be useful (got {len(stripped)} chars, need {minimum_characters})")
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in stripped]
    if missing:
        raise ValueError(f"Research artifact missing required headings: {', '.join(missing)}")


def _call_foundry_research(topic: dict, research_config: dict) -> dict:
    endpoint = (research_config.get("endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
    model = (
        research_config.get("model")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_MODEL")
        or ""
    ).strip()
    api_key_env = (research_config.get("api_key_env") or "AZURE_OPENAI_API_KEY").strip()
    api_key = (research_config.get("api_key") or os.getenv(api_key_env) or os.getenv("AZURE_OPENAI_API_KEY") or "").strip()

    if not endpoint:
        raise RuntimeError("Research requires research.endpoint or AZURE_OPENAI_ENDPOINT")
    if not model:
        raise RuntimeError("Research requires research.model or AZURE_OPENAI_DEPLOYMENT")
    if not api_key:
        raise RuntimeError(f"Research requires API key in env var {api_key_env}")

    tool = {"type": "web_search"}
    filters: dict[str, list[str]] = {}
    allowed_domains = [item for item in research_config.get("allowed_domains", []) if item]
    blocked_domains = [item for item in research_config.get("blocked_domains", []) if item]
    if allowed_domains:
        filters["allowed_domains"] = allowed_domains
    if blocked_domains:
        filters["blocked_domains"] = blocked_domains
    if filters:
        tool["filters"] = filters
    if research_config.get("user_location"):
        tool["user_location"] = research_config["user_location"]

    payload = {
        "model": model,
        "input": _foundry_research_prompt(topic=topic),
        "tools": [tool],
        "tool_choice": "auto",
    }
    if research_config.get("include_search_sources", True):
        payload["include"] = ["web_search_call.action.sources"]
    effort = research_config.get("reasoning_effort") or research_config.get("effort")
    if effort:
        payload["reasoning"] = {"effort": effort}

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        _responses_url(endpoint),
        data=body,
        headers={
            "Content-Type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )
    timeout = float(research_config.get("timeout_seconds") or 90)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure Foundry research request failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Azure Foundry research request failed: {exc.reason}") from exc


def _responses_url(endpoint: str) -> str:
    cleaned = endpoint.strip()
    if cleaned.endswith("/responses"):
        return cleaned
    return cleaned.rstrip("/") + "/responses"


def _foundry_research_prompt(topic: dict) -> str:
    template = load_prompt_template(RESEARCH_PROMPT_PATH)
    return render_prompt_template(
        template,
        {
            "topic_prompt": str(topic["prompt"]).strip(),
        },
    )


def _extract_output_text(response: dict) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    return ""


def _inject_source_notes(text: str, response: dict) -> str:
    normalized_notes = _normalized_source_note_lines(response)
    if not normalized_notes:
        return text
    return _replace_section_body(text, "## Source Notes", normalized_notes)


def _normalized_source_note_lines(response: dict) -> list[str]:
    by_url: dict[str, str] = {}
    for item in response.get("output", []):
        if item.get("type") == "web_search_call":
            for source in ((item.get("action") or {}).get("sources") or []):
                url = (source.get("url") or "").strip()
                if url and url not in by_url:
                    by_url[url] = source.get("title") or ""
        for content in item.get("content", []) or []:
            for annotation in content.get("annotations", []) or []:
                if annotation.get("type") != "url_citation":
                    continue
                url = (annotation.get("url") or "").strip()
                if url and url not in by_url:
                    by_url[url] = annotation.get("title") or ""
                elif url and annotation.get("title") and not by_url[url]:
                    by_url[url] = annotation["title"]

    lines = []
    for url, title in by_url.items():
        lines.append(f"- {title}: {url}" if title else f"- {url}")
    return lines


def _replace_section_body(text: str, heading: str, body_lines: list[str]) -> str:
    pattern = re.compile(rf"{re.escape(heading)}\n(?:.*?)(?=\n## |\Z)", flags=re.DOTALL)
    replacement = heading + "\n" + "\n".join(body_lines) + "\n"
    if pattern.search(text):
        return pattern.sub(replacement, text, count=1).strip() + "\n"
    return text.rstrip() + "\n\n" + replacement

