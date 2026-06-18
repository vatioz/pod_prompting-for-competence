from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import tempfile
import uuid

import yaml

from .config import TOPICS_PATH

DEFAULT_STATE = {"topics": []}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


EPISODE_NUMBER_WIDTH = 3
EPISODE_NUMBER_RE = re.compile(r"(?<!\d)(\d{3,})(?=_)")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or f"topic-{uuid.uuid4().hex[:8]}"


def format_episode_number(value: int) -> str:
    number = int(value)
    if number < 1:
        raise ValueError("Episode numbers must be positive integers")
    return f"{number:0{EPISODE_NUMBER_WIDTH}d}"


def topic_episode_label(topic: dict) -> str:
    return f"Episode {format_episode_number(_topic_episode_number(topic))}"


def topic_variant_title(topic: dict, variant_name: str) -> str:
    label = "Overview" if variant_name == "overview" else "Deep Dive"
    return f"{topic_episode_label(topic)} — {topic['prompt']} — {label}"


def topic_artifact_stem(topic: dict, variant_name: str | None = None) -> str:
    prefix = f"{format_episode_number(_topic_episode_number(topic))}_{topic['slug']}"
    return f"{prefix}-{variant_name}-{topic['id']}" if variant_name else f"{prefix}-{topic['id']}"


def load_state() -> dict:
    if not TOPICS_PATH.exists():
        return deepcopy(DEFAULT_STATE)
    with TOPICS_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if "topics" not in data or not isinstance(data["topics"], list):
        data["topics"] = []
    data["topics"] = _normalize_topics(data["topics"])
    return data


def save_state(state: dict) -> None:
    normalized = {"topics": _normalize_topics(state.get("topics", []))}
    TOPICS_PATH.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(prefix=f".{TOPICS_PATH.name}.", suffix=".tmp", dir=str(TOPICS_PATH.parent))
    temp_file = Path(temp_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(normalized, handle, sort_keys=False, allow_unicode=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_file, TOPICS_PATH)
    except Exception:
        if temp_file.exists():
            temp_file.unlink()
        raise


def list_topics(limit: int | None = None, *, include_deleted: bool = False) -> list[dict]:
    state = load_state()
    topics = list(reversed(state["topics"]))
    if not include_deleted:
        topics = [topic for topic in topics if not topic.get("deleted")]
    return topics[:limit] if limit else topics


def get_topic(topic_id: str) -> dict | None:
    state = load_state()
    for topic in state["topics"]:
        if topic["id"] == topic_id:
            return topic
    return None


def create_topic(prompt: str, overview: bool, deep_dive: bool, script_steering: str = "") -> dict:
    cleaned = prompt.strip()
    if not cleaned:
        raise ValueError("Prompt is required")
    if not overview and not deep_dive:
        raise ValueError("Select at least one episode variant")

    state = load_state()
    next_episode_number = max((int(item["episode_number"]) for item in state["topics"]), default=0) + 1
    topic = {
        "id": uuid.uuid4().hex[:10],
        "episode_number": next_episode_number,
        "slug": slugify(cleaned)[:80],
        "prompt": cleaned,
        "user_inputs": {"script_steering": script_steering},
        "status": "queued",
        "deleted": False,
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "last_error": None,
        "research": {
            "status": "queued",
            "path": None,
            "error": None,
        },
        "variants": {
            "overview": _new_variant_state(enabled=overview),
            "deep_dive": _new_variant_state(enabled=deep_dive),
        },
    }
    normalized = _normalize_topic(topic)
    state["topics"].append(normalized)
    save_state(state)
    return normalized


def update_topic(topic_id: str, updater) -> dict | None:
    state = load_state()
    for idx, topic in enumerate(state["topics"]):
        if topic["id"] == topic_id:
            topic_copy = deepcopy(topic)
            updater(topic_copy)
            topic_copy["updated_at"] = utc_now_iso()
            topic_copy = _normalize_topic(topic_copy)
            state["topics"][idx] = topic_copy
            save_state(state)
            return topic_copy
    return None


def retry_topic(topic_id: str) -> dict | None:
    def apply(topic: dict) -> None:
        topic["status"] = "queued"
        topic["last_error"] = None
        topic["research"]["status"] = "queued"
        topic["research"]["path"] = None
        topic["research"]["error"] = None
        for variant in topic["variants"].values():
            if not variant["enabled"]:
                variant["status"] = "disabled"
                continue
            variant["status"] = "queued"
            variant["script_path"] = None
            variant["audio_path"] = None
            variant["published_title"] = None
            variant["published_at"] = None
            variant.setdefault("script", {})
            variant["script"]["status"] = "queued"
            variant["script"]["path"] = None
            variant["script"]["model"] = None
            variant["script"]["error"] = None
            variant.setdefault("audio", {})
            variant["audio"]["status"] = "queued"
            variant["audio"]["path"] = None
            variant["audio"]["provider"] = None
            variant["audio"]["voice"] = None
            variant["audio"]["voice_id"] = None
            variant["audio"]["model"] = None
            variant["audio"]["segment_count"] = None
            variant["audio"]["duration_seconds"] = None
            variant["audio"]["error"] = None
            variant.setdefault("publish", {})
            variant["publish"]["status"] = "queued"
            variant["publish"]["public_url"] = None
            variant["publish"]["completed_at"] = None
            variant["publish"]["error"] = None

    return update_topic(topic_id, apply)


def unpublish_topic(topic_id: str) -> dict | None:
    def apply(topic: dict) -> None:
        topic["deleted"] = True
        topic["status"] = "unpublished"

    return update_topic(topic_id, apply)


def recompute_topic_status(topic: dict) -> str:
    if (topic.get("research") or {}).get("status") == "failed":
        return "failed"
    variants = [variant for variant in topic.get("variants", {}).values() if variant.get("enabled")]
    if not variants:
        return topic.get("status", "queued")
    statuses = [variant.get("status") for variant in variants]
    if any(status == "failed" for status in statuses):
        return "failed"
    if all(status == "published" for status in statuses):
        return "published"
    if all(status in {"exported", "published"} for status in statuses):
        return "exported" if any(status == "exported" for status in statuses) else "published"
    if all(status in {"generated", "exported", "published"} for status in statuses):
        return "generated" if any(status == "generated" for status in statuses) else "processing"
    if any(status == "processing" for status in statuses) or (topic.get("research") or {}).get("status") == "processing":
        return "processing"
    if all(status == "queued" for status in statuses) and (topic.get("research") or {}).get("status") == "queued":
        return "queued"
    return topic.get("status", "queued")


def _normalize_topic(topic: dict) -> dict:
    topic = deepcopy(topic)
    topic["user_inputs"] = _normalize_user_inputs(topic.get("user_inputs"))
    topic.setdefault("episode_number", None)
    topic.setdefault("status", "queued")
    topic.setdefault("deleted", False)
    topic.setdefault("created_at", utc_now_iso())
    topic.setdefault("updated_at", topic["created_at"])
    topic.setdefault("last_error", None)
    topic["research"] = _normalize_research(topic.get("research"))
    topic.setdefault("variants", {})
    for variant_name in ("overview", "deep_dive"):
        topic["variants"][variant_name] = _normalize_variant(topic["variants"].get(variant_name))
    if topic["status"] not in {"failed", "processing", "unpublished"}:
        topic["status"] = recompute_topic_status(topic)
    return topic


def _normalize_topics(topics: list[dict]) -> list[dict]:
    normalized = [_normalize_topic(topic) for topic in topics]
    _assign_missing_episode_numbers(normalized)
    return normalized


def _assign_missing_episode_numbers(topics: list[dict]) -> None:
    used_numbers: set[int] = set()
    unresolved: list[dict] = []

    for topic in topics:
        explicit = _coerce_episode_number(topic.get("episode_number"))
        if explicit and explicit not in used_numbers:
            topic["episode_number"] = explicit
            used_numbers.add(explicit)
        else:
            topic["episode_number"] = None
            unresolved.append(topic)

    still_unresolved: list[dict] = []
    for topic in unresolved:
        inferred = next((value for value in _topic_episode_number_candidates(topic) if value not in used_numbers), None)
        if inferred is not None:
            topic["episode_number"] = inferred
            used_numbers.add(inferred)
        else:
            still_unresolved.append(topic)

    next_number = 1
    for topic in still_unresolved:
        while next_number in used_numbers:
            next_number += 1
        topic["episode_number"] = next_number
        used_numbers.add(next_number)
        next_number += 1


def _topic_episode_number(topic: dict) -> int:
    explicit = _coerce_episode_number(topic.get("episode_number"))
    if explicit is not None:
        return explicit
    candidates = _topic_episode_number_candidates(topic)
    if candidates:
        return candidates[0]
    return 1


def _coerce_episode_number(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _topic_episode_number_candidates(topic: dict) -> list[int]:
    candidates: list[int] = []

    def add_candidate(raw_value) -> None:
        number = _extract_episode_number(raw_value)
        if number is not None and number not in candidates:
            candidates.append(number)

    add_candidate((topic.get("research") or {}).get("path"))
    for variant in (topic.get("variants") or {}).values():
        add_candidate(variant.get("script_path"))
        add_candidate(variant.get("audio_path"))
        add_candidate((variant.get("script") or {}).get("path"))
        add_candidate((variant.get("audio") or {}).get("path"))
        add_candidate((variant.get("publish") or {}).get("public_url"))
    return candidates


def _extract_episode_number(raw_value) -> int | None:
    if not raw_value:
        return None
    match = EPISODE_NUMBER_RE.search(str(raw_value))
    if not match:
        return None
    return int(match.group(1))


def _normalize_user_inputs(user_inputs: dict | None) -> dict:
    normalized = deepcopy(user_inputs or {})
    normalized["script_steering"] = _normalize_script_steering(normalized.get("script_steering"))
    return normalized


def _normalize_script_steering(raw_value) -> str:
    value = str(raw_value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:1000]


def _normalize_research(research: dict | None) -> dict:
    research = deepcopy(research or {})
    research.setdefault("status", "queued")
    research.setdefault("path", None)
    research.setdefault("error", None)
    return research


def _normalize_variant(variant: dict | None) -> dict:
    variant = deepcopy(variant or {})
    enabled = bool(variant.get("enabled", False))
    status = variant.get("status") or ("queued" if enabled else "disabled")
    script_path = variant.get("script_path") or ((variant.get("script") or {}).get("path"))
    audio_path = variant.get("audio_path") or ((variant.get("audio") or {}).get("path"))
    publish_info = deepcopy(variant.get("publish") or {})

    script = deepcopy(variant.get("script") or {})
    script.setdefault("status", _artifact_stage_status(status, enabled, script_path))
    script.setdefault("path", script_path)
    script.setdefault("model", None)
    script.setdefault("error", None)

    audio = deepcopy(variant.get("audio") or {})
    audio.setdefault("status", _artifact_stage_status(status, enabled, audio_path))
    audio.setdefault("path", audio_path)
    audio.setdefault("provider", None)
    if not audio.get("voice") and audio.get("voice_id"):
        audio["voice"] = audio.get("voice_id")
    if not audio.get("voice_id") and audio.get("voice"):
        audio["voice_id"] = audio.get("voice")
    audio.setdefault("voice", None)
    audio.setdefault("voice_id", None)
    audio.setdefault("model", None)
    audio.setdefault("segment_count", None)
    audio.setdefault("duration_seconds", None)
    audio.setdefault("error", None)

    publish_info.setdefault("status", _publish_stage_status(status, enabled, publish_info.get("public_url")))
    publish_info.setdefault("public_url", None)
    publish_info.setdefault("completed_at", variant.get("published_at"))
    publish_info.setdefault("error", None)

    normalized = {
        "enabled": enabled,
        "status": status,
        "script_path": script["path"],
        "audio_path": audio["path"],
        "published_title": variant.get("published_title"),
        "published_at": variant.get("published_at"),
        "script": script,
        "audio": audio,
        "publish": publish_info,
    }
    if not enabled:
        normalized["status"] = "disabled"
        normalized["script"]["status"] = "disabled"
        normalized["audio"]["status"] = "disabled"
        normalized["publish"]["status"] = "disabled"
    return normalized


def _artifact_stage_status(variant_status: str, enabled: bool, artifact_path: str | None) -> str:
    if not enabled:
        return "disabled"
    if artifact_path and variant_status in {"generated", "exported", "published"}:
        return "done"
    if variant_status == "failed":
        return "failed"
    if variant_status == "processing":
        return "processing"
    return "queued"


def _publish_stage_status(variant_status: str, enabled: bool, public_url: str | None) -> str:
    if not enabled:
        return "disabled"
    if public_url or variant_status in {"exported", "published"}:
        return "done"
    if variant_status == "failed":
        return "failed"
    if variant_status == "processing":
        return "processing"
    return "queued"


def _new_variant_state(*, enabled: bool) -> dict:
    status = "queued" if enabled else "disabled"
    return {
        "enabled": enabled,
        "status": status,
        "script_path": None,
        "audio_path": None,
        "published_title": None,
        "published_at": None,
        "script": {
            "status": status,
            "path": None,
            "model": None,
            "error": None,
        },
        "audio": {
            "status": status,
            "path": None,
            "provider": None,
            "voice": None,
            "voice_id": None,
            "model": None,
            "segment_count": None,
            "duration_seconds": None,
            "error": None,
        },
        "publish": {
            "status": status,
            "public_url": None,
            "completed_at": None,
            "error": None,
        },
    }
