from __future__ import annotations

import os
from pathlib import Path
from urllib import parse

from .script_writer import spoken_text_from_markdown

_DEFAULT_WORDS_PER_MINUTE = 150.0
_OUTPUT_FORMAT_ENUMS = {
    "audio-16khz-32kbitrate-mono-mp3": "Audio16Khz32KBitRateMonoMp3",
    "audio-16khz-64kbitrate-mono-mp3": "Audio16Khz64KBitRateMonoMp3",
    "audio-24khz-48kbitrate-mono-mp3": "Audio24Khz48KBitRateMonoMp3",
    "audio-24khz-96kbitrate-mono-mp3": "Audio24Khz96KBitRateMonoMp3",
    "audio-48khz-192kbitrate-mono-mp3": "Audio48Khz192KBitRateMonoMp3",
    "riff-16khz-16bit-mono-pcm": "Riff16Khz16BitMonoPcm",
    "riff-24khz-16bit-mono-pcm": "Riff24Khz16BitMonoPcm",
}


def synthesize_script_to_mp3(script_path: Path, output_path: Path, tts_config: dict) -> dict:
    script_markdown = script_path.read_text(encoding="utf-8")
    spoken_text = spoken_text_from_markdown(script_markdown)
    return synthesize_text_to_mp3(spoken_text=spoken_text, output_path=output_path, tts_config=tts_config)


def synthesize_text_to_mp3(spoken_text: str, output_path: Path, tts_config: dict) -> dict:
    mode = (tts_config.get("mode") or "sync").strip().lower()
    if mode != "sync":
        raise RuntimeError(f"Azure Speech tts.mode '{mode}' is not implemented yet; use sync for now")

    endpoint = _base_endpoint(tts_config.get("speech_endpoint") or "")
    region = (tts_config.get("speech_region") or "").strip()
    api_key_env = (tts_config.get("speech_api_key_env") or "AZURE_SPEECH_KEY").strip()
    api_key = (tts_config.get("speech_api_key") or os.getenv(api_key_env) or "").strip()
    voice = (tts_config.get("speech_voice") or "").strip()
    output_format = (tts_config.get("speech_output_format") or "audio-24khz-96kbitrate-mono-mp3").strip()

    if not endpoint and not region:
        raise RuntimeError("Either tts.speech_endpoint or tts.speech_region is required when tts.provider is set to azure_speech")
    if not api_key:
        raise RuntimeError(f"Azure Speech API key is required in env var {api_key_env} when tts.provider is set to azure_speech")
    if not voice:
        raise RuntimeError("tts.speech_voice is required when tts.provider is set to azure_speech")

    cleaned_text = " ".join(spoken_text.split())
    if not cleaned_text:
        raise RuntimeError("Cannot send empty script text to Azure Speech")

    estimated_minutes = estimate_duration_minutes(cleaned_text)
    max_minutes = float(tts_config.get("speech_sync_max_minutes") or 9.5)
    if estimated_minutes > max_minutes:
        raise RuntimeError(
            f"Azure Speech sync estimated duration {estimated_minutes:.1f} minutes exceeds speech_sync_max_minutes={max_minutes:g}. Shorten the script or use a future batch mode."
        )

    speechsdk = _load_speechsdk()
    speech_config = _create_speech_config(speechsdk=speechsdk, api_key=api_key, endpoint=endpoint, region=region)
    speech_config.speech_synthesis_voice_name = voice
    output_enum = _resolve_output_format_enum(speechsdk, output_format)
    if output_enum is not None:
        speech_config.set_speech_synthesis_output_format(output_enum)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(output_path))
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = synthesizer.speak_text_async(cleaned_text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        if not output_path.exists():
            raise RuntimeError("Azure Speech reported success but no audio file was written")
        audio_bytes = output_path.read_bytes()
        if not audio_bytes:
            raise RuntimeError("Azure Speech wrote an empty audio file")
        return {
            "provider": "azure_speech",
            "voice": voice,
            "voice_id": voice,
            "model": "speech_sync",
            "segment_count": 1,
            "bytes": len(audio_bytes),
            "path": str(output_path),
        }

    if result.reason == speechsdk.ResultReason.Canceled:
        details = result.cancellation_details
        reason = getattr(details, "reason", "unknown")
        error_details = getattr(details, "error_details", "")
        extra = f": {error_details}" if error_details else ""
        raise RuntimeError(f"Azure Speech synthesis canceled ({reason}){extra}")

    raise RuntimeError(f"Azure Speech synthesis failed with unexpected result reason: {result.reason}")


def estimate_duration_minutes(spoken_text: str) -> float:
    words = len([part for part in spoken_text.split() if part])
    return words / _DEFAULT_WORDS_PER_MINUTE if words else 0.0


def _load_speechsdk():
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError as exc:
        raise RuntimeError(
            "Azure Speech SDK is not installed. Add azure-cognitiveservices-speech to requirements and rebuild the app container."
        ) from exc
    return speechsdk


def _create_speech_config(*, speechsdk, api_key: str, endpoint: str, region: str):
    if endpoint:
        return speechsdk.SpeechConfig(subscription=api_key, endpoint=endpoint)
    return speechsdk.SpeechConfig(subscription=api_key, region=region)


def _resolve_output_format_enum(speechsdk, output_format: str):
    enum_name = _OUTPUT_FORMAT_ENUMS.get((output_format or "").strip().lower())
    if not enum_name:
        return None
    return getattr(speechsdk.SpeechSynthesisOutputFormat, enum_name, None)


def _base_endpoint(endpoint: str) -> str:
    cleaned = (endpoint or "").strip().rstrip("/")
    if not cleaned:
        return ""
    parsed = parse.urlparse(cleaned)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return cleaned
