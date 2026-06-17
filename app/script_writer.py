from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib import error, request

from .config import GENERATED_SCRIPTS_DIR, SCRIPT_DEEP_DIVE_PROMPT_PATH, SCRIPT_OVERVIEW_PROMPT_PATH
from .prompt_loader import load_prompt_template, render_prompt_template
from .storage import topic_artifact_stem, topic_variant_title


def generate_script_markdown(
    topic: dict,
    variant_name: str,
    research_markdown: str,
    output_dir: Path = GENERATED_SCRIPTS_DIR,
    script_config: dict | None = None,
) -> Path:
    config = dict(script_config or {})
    script_text = build_script_markdown_with_foundry(
        topic=topic,
        variant_name=variant_name,
        research_markdown=research_markdown,
        script_config=config,
    )
    validate_script_markdown(script_text)
    output_dir.mkdir(parents=True, exist_ok=True)
    script_path = output_dir / f"{topic_artifact_stem(topic, variant_name)}.md"
    script_path.write_text(script_text, encoding="utf-8")
    return script_path


def build_script_markdown_with_foundry(
    topic: dict,
    variant_name: str,
    research_markdown: str,
    script_config: dict,
) -> str:
    response = _call_foundry_script(
        topic=topic,
        variant_name=variant_name,
        research_markdown=research_markdown,
        script_config=script_config,
    )
    text = _extract_output_text(response).strip()
    if not text:
        raise RuntimeError("Azure Foundry script response did not include output text")
    return _normalize_script_markdown(text, topic=topic, variant_name=variant_name)


def validate_script_markdown(script_markdown: str) -> None:
    stripped = script_markdown.strip()
    if len(stripped) < 250:
        raise ValueError(f"Script artifact is too short to be useful (got {len(stripped)} chars)")
    if not stripped.startswith("# "):
        raise ValueError("Script artifact must start with a markdown title")
    if sum(1 for line in stripped.splitlines() if line.strip()) < 4:
        raise ValueError("Script artifact must contain multiple spoken paragraphs")


def spoken_text_from_markdown(script_markdown: str) -> str:
    lines = []
    for raw_line in script_markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^[-*]\s+", "", line)
        lines.append(line)
    return re.sub(r"\s+", " ", "\n\n".join(lines)).strip()


def _call_foundry_script(topic: dict, variant_name: str, research_markdown: str, script_config: dict) -> dict:
    endpoint = (script_config.get("endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
    model = (
        script_config.get("model")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_MODEL")
        or ""
    ).strip()
    api_key_env = (script_config.get("api_key_env") or "AZURE_OPENAI_API_KEY").strip()
    api_key = (script_config.get("api_key") or os.getenv(api_key_env) or os.getenv("AZURE_OPENAI_API_KEY") or "").strip()

    if not endpoint:
        raise RuntimeError("Script generation requires script.endpoint or AZURE_OPENAI_ENDPOINT")
    if not model:
        raise RuntimeError("Script generation requires script.model or AZURE_OPENAI_DEPLOYMENT")
    if not api_key:
        raise RuntimeError(f"Script generation requires API key in env var {api_key_env}")

    payload = {
        "model": model,
        "input": _foundry_script_prompt(
            topic=topic,
            variant_name=variant_name,
            research_markdown=research_markdown,
            script_config=script_config,
        ),
    }
    effort = script_config.get("reasoning_effort") or script_config.get("effort")
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
    timeout = float(script_config.get("timeout_seconds") or 90)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure Foundry script request failed with HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Azure Foundry script request failed: {exc.reason}") from exc


def _foundry_script_prompt(topic: dict, variant_name: str, research_markdown: str, script_config: dict) -> str:
    is_overview = variant_name == "overview"
    target_minutes = int(script_config.get("overview_target_minutes") or 5) if is_overview else int(script_config.get("deep_dive_target_minutes") or 18)
    template_path = SCRIPT_OVERVIEW_PROMPT_PATH if is_overview else SCRIPT_DEEP_DIVE_PROMPT_PATH
    template = load_prompt_template(template_path)
    return render_prompt_template(
        template,
        {
            "topic_prompt": str(topic["prompt"]).strip(),
            "variant_label": "overview" if is_overview else "deep dive",
            "target_minutes": target_minutes,
            "script_title": topic_variant_title(topic, variant_name),
            "script_steering_block": _script_steering_block(topic),
            "research_markdown": research_markdown.strip(),
        },
    )


def _normalize_script_markdown(text: str, topic: dict, variant_name: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        stripped = raw_line.rstrip()
        if stripped.startswith("- "):
            stripped = stripped[2:]
        if stripped.startswith("* "):
            stripped = stripped[2:]
        lines.append(stripped)

    cleaned = "\n".join(lines).strip()
    expected_title = f"# {topic_variant_title(topic, variant_name)}"
    if not cleaned.startswith("# "):
        cleaned = expected_title + "\n\n" + cleaned
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"
    return cleaned


def _responses_url(endpoint: str) -> str:
    cleaned = endpoint.strip()
    if cleaned.endswith("/responses"):
        return cleaned
    return cleaned.rstrip("/") + "/responses"


def _extract_output_text(response: dict) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    return ""



def _script_steering_block(topic: dict) -> str:
    steering = str((topic.get("user_inputs") or {}).get("script_steering") or "").strip()
    if not steering:
        return "Additional script steering: none"
    return f"Additional script steering:\n{steering}"
