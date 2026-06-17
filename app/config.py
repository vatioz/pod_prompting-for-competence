from __future__ import annotations

import logging
import os
import shutil
from copy import deepcopy
from pathlib import Path

import yaml


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(os.environ.get("POD_RUNTIME_DIR", str(BASE_DIR))).resolve()
CONFIG_PATH = Path(os.environ.get("POD_CONFIG_PATH", str(RUNTIME_DIR / "config" / "podcast.yaml"))).resolve()
TOPICS_PATH = Path(os.environ.get("POD_TOPICS_PATH", str(RUNTIME_DIR / "data" / "topics.yaml"))).resolve()
GENERATED_DIR = Path(os.environ.get("POD_GENERATED_DIR", str(RUNTIME_DIR / "generated"))).resolve()
GENERATED_AUDIO_DIR = GENERATED_DIR / "audio"
GENERATED_SCRIPTS_DIR = GENERATED_DIR / "scripts"
GENERATED_RESEARCH_DIR = GENERATED_DIR / "research"
GENERATED_IMAGES_DIR = GENERATED_DIR / "images"
GENERATED_FEED_PATH = GENERATED_DIR / "feed.xml"

DEFAULT_PROMPTS_DIR = BASE_DIR / "config" / "prompts"
PROMPTS_DIR = Path(os.environ.get("POD_PROMPTS_DIR", str(RUNTIME_DIR / "config" / "prompts"))).resolve()
RESEARCH_PROMPT_PATH = Path(
    os.environ.get("POD_RESEARCH_PROMPT_PATH", str(PROMPTS_DIR / "research_prompt.txt"))
).resolve()
SCRIPT_OVERVIEW_PROMPT_PATH = Path(
    os.environ.get("POD_SCRIPT_OVERVIEW_PROMPT_PATH", str(PROMPTS_DIR / "script_overview_prompt.txt"))
).resolve()
SCRIPT_DEEP_DIVE_PROMPT_PATH = Path(
    os.environ.get("POD_SCRIPT_DEEP_DIVE_PROMPT_PATH", str(PROMPTS_DIR / "script_deep_dive_prompt.txt"))
).resolve()

DEFAULT_CONFIG = {
    "podcast": {
        "title": "Prompting for Competence",
        "description": "Personal learning podcast feed generated from queued topics.",
        "author": "Vatioz",
        "base_url": "http://127.0.0.1:6001",
        "language": "en-us",
        "artwork": {
            "source_path": "",
            "public_url": "",
            "alt_text": "",
        },
    },
    "worker": {"poll_seconds": 3},
    "research": {
        "minimum_characters": 500,
        "provider": "azure_foundry",
        "endpoint": "",
        "model": "",
        "api_key_env": "AZURE_OPENAI_API_KEY",
        "timeout_seconds": 90,
        "include_search_sources": True,
        "allowed_domains": [],
        "blocked_domains": [],
        "reasoning_effort": "",
    },
    "script": {
        "provider": "azure_foundry",
        "style": "audio_native_explanatory",
        "overview_target_minutes": 5,
        "deep_dive_target_minutes": 18,
        "endpoint": "",
        "model": "",
        "api_key_env": "AZURE_OPENAI_API_KEY",
        "timeout_seconds": 90,
        "reasoning_effort": "",
    },
    "tts": {
        "provider": "azure_speech",
        "mode": "sync",
        "timeout_seconds": 90,
        "ffmpeg_path": "ffmpeg",
        "speech_endpoint": "",
        "speech_region": "",
        "speech_api_key_env": "AZURE_SPEECH_KEY",
        "speech_voice": "",
        "speech_output_format": "audio-24khz-96kbitrate-mono-mp3",
        "speech_sync_max_minutes": 9.5,
        "azure_openai_endpoint": "",
        "azure_openai_api_key_env": "AZURE_OPENAI_API_KEY",
        "azure_openai_model": "tts-1-hd",
        "azure_openai_voice": "alloy",
        "azure_openai_response_format": "mp3",
        "azure_openai_speed": 1.0,
        "azure_openai_max_chars_per_request": 3500,
        "voice_id": "",
        "model_id": "eleven_multilingual_v2",
        "output_format": "mp3_44100_128",
        "base_url": "https://api.elevenlabs.io",
        "stability": 0.45,
        "similarity_boost": 0.75,
        "style": 0.2,
        "use_speaker_boost": True,
    },
    "publishing": {
        "target": "azure_static",
        "public_base_url": "",
        "export_dir": str(RUNTIME_DIR / "publish"),
        "auto_publish": False,
        "deploy_enabled": False,
        "azure_container": "$web",
        "azure_path_prefix": "",
        "azure_delete_stale": True,
        "azure_allow_root_delete": False,
        "azure_credential_mode": "connection_string",
        "azure_connection_string_env": "AZURE_STORAGE_CONNECTION_STRING",
        "azure_account_url": "",
    },
    "ui": {"recent_topics_limit": 12},
}


def load_config() -> dict:
    config = deepcopy(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        _deep_merge(config, loaded)
    _normalize_loaded_config(config)
    return config


def _deep_merge(target: dict, source: dict) -> dict:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def _normalize_loaded_config(config: dict) -> dict:
    podcast = config.setdefault("podcast", {})
    if podcast.get("base_url"):
        podcast["base_url"] = str(podcast["base_url"]).strip().rstrip("/")
    artwork = podcast.setdefault("artwork", {})
    artwork["source_path"] = str(artwork.get("source_path") or "").strip()
    artwork["public_url"] = str(artwork.get("public_url") or "").strip()
    artwork["alt_text"] = str(artwork.get("alt_text") or "").strip()

    publishing = config.setdefault("publishing", {})
    publishing["public_base_url"] = str(publishing.get("public_base_url") or "").strip().rstrip("/")
    publishing["export_dir"] = str(Path(str(publishing.get("export_dir") or (RUNTIME_DIR / "publish"))).expanduser())
    publishing["azure_container"] = str(publishing.get("azure_container") or "$web").strip() or "$web"
    publishing["azure_path_prefix"] = normalize_publish_path_prefix(publishing.get("azure_path_prefix"))
    publishing["azure_connection_string_env"] = str(
        publishing.get("azure_connection_string_env") or "AZURE_STORAGE_CONNECTION_STRING"
    ).strip() or "AZURE_STORAGE_CONNECTION_STRING"
    publishing["azure_credential_mode"] = str(publishing.get("azure_credential_mode") or "connection_string").strip().lower()
    publishing["azure_account_url"] = str(publishing.get("azure_account_url") or "").strip().rstrip("/")
    publishing["auto_publish"] = bool(publishing.get("auto_publish"))
    publishing["deploy_enabled"] = bool(publishing.get("deploy_enabled"))
    publishing["azure_delete_stale"] = bool(publishing.get("azure_delete_stale", True))
    publishing["azure_allow_root_delete"] = bool(publishing.get("azure_allow_root_delete"))
    return config


def normalize_publish_path_prefix(value: str | None) -> str:
    return str(value or "").strip().strip("/")


def get_bind_host() -> str:
    return os.environ.get("POD_HOST", "0.0.0.0")


def get_bind_port() -> int:
    return int(os.environ.get("POD_PORT", "6001"))


def ensure_runtime_dirs() -> None:
    for path in [
        CONFIG_PATH.parent,
        PROMPTS_DIR,
        TOPICS_PATH.parent,
        GENERATED_DIR,
        GENERATED_AUDIO_DIR,
        GENERATED_SCRIPTS_DIR,
        GENERATED_RESEARCH_DIR,
        GENERATED_IMAGES_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    _seed_if_missing(BASE_DIR / "config" / "podcast.yaml", CONFIG_PATH)
    _seed_if_missing(BASE_DIR / "data" / "topics.yaml", TOPICS_PATH)
    _seed_if_missing(DEFAULT_PROMPTS_DIR / "research_prompt.txt", RESEARCH_PROMPT_PATH)
    _seed_if_missing(DEFAULT_PROMPTS_DIR / "script_overview_prompt.txt", SCRIPT_OVERVIEW_PROMPT_PATH)
    _seed_if_missing(DEFAULT_PROMPTS_DIR / "script_deep_dive_prompt.txt", SCRIPT_DEEP_DIVE_PROMPT_PATH)


def _seed_if_missing(source: Path, destination: Path) -> None:
    if destination.exists() or not source.exists() or source.resolve() == destination.resolve():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def resolve_podcast_artwork_source(config: dict) -> Path | None:
    artwork = config.get("podcast", {}).get("artwork", {})
    source_path = str(artwork.get("source_path") or "").strip()
    if not source_path:
        return None
    path = Path(source_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (RUNTIME_DIR / path).resolve()


def podcast_artwork_public_url(config: dict, base_url: str) -> str:
    artwork = config.get("podcast", {}).get("artwork", {})
    explicit = str(artwork.get("public_url") or "").strip()
    if explicit:
        return explicit
    source = resolve_podcast_artwork_source(config)
    if not source or not source.suffix:
        return ""
    if not source.exists():
        logger.warning("Configured podcast artwork file does not exist: %s", source)
        return ""
    return f"{base_url.rstrip('/')}/images/podcast-cover{source.suffix.lower()}"


def podcast_artwork_publish_name(config: dict) -> str:
    source = resolve_podcast_artwork_source(config)
    suffix = source.suffix.lower() if source and source.suffix else ".jpg"
    return f"podcast-cover{suffix}"
