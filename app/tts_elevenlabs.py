from __future__ import annotations

from pathlib import Path
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .script_writer import spoken_text_from_markdown


def synthesize_script_to_mp3(script_path: Path, output_path: Path, tts_config: dict) -> dict:
    script_markdown = script_path.read_text(encoding="utf-8")
    spoken_text = spoken_text_from_markdown(script_markdown)
    return synthesize_text_to_mp3(spoken_text=spoken_text, output_path=output_path, tts_config=tts_config)


def synthesize_text_to_mp3(spoken_text: str, output_path: Path, tts_config: dict) -> dict:
    api_key = tts_config.get("api_key") or os.environ.get("ELEVENLABS_API_KEY")
    voice_id = (tts_config.get("voice_id") or "").strip()
    if not api_key:
        raise RuntimeError("ElevenLabs API key (ELEVENLABS_API_KEY) is required when tts.provider is set to elevenlabs")
    if not voice_id:
        raise RuntimeError("tts.voice_id is required when tts.provider is set to elevenlabs")
    cleaned_text = " ".join(spoken_text.split())
    if not cleaned_text:
        raise RuntimeError("Cannot send empty script text to ElevenLabs")

    base_url = (tts_config.get("base_url") or "https://api.elevenlabs.io").rstrip("/")
    output_format = tts_config.get("output_format") or "mp3_44100_128"
    timeout_seconds = int(tts_config.get("timeout_seconds") or 90)

    voice_settings = {
        "stability": float(tts_config.get("stability", 0.45)),
        "similarity_boost": float(tts_config.get("similarity_boost", 0.75)),
        "style": float(tts_config.get("style", 0.2)),
        "use_speaker_boost": bool(tts_config.get("use_speaker_boost", True)),
    }
    query = urlencode({"output_format": output_format})
    url = f"{base_url}/v1/text-to-speech/{voice_id}?{query}"
    payload = {
        "text": cleaned_text,
        "model_id": tts_config.get("model_id") or "eleven_multilingual_v2",
        "voice_settings": voice_settings,
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        audio_bytes = response.read()
    if not audio_bytes:
        raise RuntimeError("ElevenLabs returned an empty audio response")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_bytes(audio_bytes)
    temp_path.replace(output_path)
    return {
        "provider": "elevenlabs",
        "voice": voice_id,
        "voice_id": voice_id,
        "model": tts_config.get("model_id") or "eleven_multilingual_v2",
        "segment_count": 1,
        "bytes": len(audio_bytes),
        "path": str(output_path),
    }
