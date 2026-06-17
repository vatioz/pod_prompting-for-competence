from __future__ import annotations

from pathlib import Path

from .tts_azure_speech import synthesize_script_to_mp3 as synthesize_with_azure_speech
from .tts_elevenlabs import synthesize_script_to_mp3 as synthesize_with_elevenlabs


def synthesize_script_to_mp3(script_path: Path, output_path: Path, tts_config: dict) -> dict:
    provider = (tts_config.get("provider") or "").strip().lower()
    if provider == "elevenlabs":
        return synthesize_with_elevenlabs(script_path=script_path, output_path=output_path, tts_config=tts_config)
    if provider == "azure_speech":
        return synthesize_with_azure_speech(script_path=script_path, output_path=output_path, tts_config=tts_config)
    if provider == "azure_openai":
        raise RuntimeError("tts.provider 'azure_openai' is not implemented yet")
    raise RuntimeError(
        f"Unsupported tts.provider: {provider or '<empty>'}. Supported providers: elevenlabs, azure_speech, azure_openai"
    )
