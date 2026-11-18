import io
import json
from urllib.error import HTTPError, URLError

import pytest

from app import tts_elevenlabs


@pytest.mark.parametrize("custom", [False, True])
def test_elevenlabs_request_and_atomic_audio_output(tmp_path, monkeypatch, custom):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "env-key")
    config = {"voice_id": " voice ", "base_url": "https://example.com"}
    if custom:
        config.update(api_key="explicit-key", base_url="https://tts.example.com/", output_format="mp3_22050_32",
                      timeout_seconds="15", model_id="custom-model", stability="0.1", similarity_boost="0.2",
                      style="0.3", use_speaker_boost=False)
    script = tmp_path / "script.md"
    script.write_text("# Episode\n\nHello   world.\nSecond paragraph.", encoding="utf-8")
    output = tmp_path / "nested" / "audio.mp3"
    output.parent.mkdir()
    output.write_bytes(b"previous")
    calls = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(b"ID3unit-audio")

    monkeypatch.setattr(tts_elevenlabs, "urlopen", urlopen)
    meta = tts_elevenlabs.synthesize_script_to_mp3(script, output, config)
    request, timeout = calls[0]
    assert request.full_url == ("https://tts.example.com/v1/text-to-speech/voice?output_format=mp3_22050_32" if custom
                                else "https://example.com/v1/text-to-speech/voice?output_format=mp3_44100_128")
    assert request.method == "POST"
    assert request.get_header("Xi-api-key") == ("explicit-key" if custom else "env-key")
    assert request.get_header("Accept") == "audio/mpeg"
    assert request.get_header("Content-type") == "application/json"
    assert timeout == (15 if custom else 90)
    payload = json.loads(request.data)
    assert payload == {"text": "Episode Hello world. Second paragraph.",
                       "model_id": "custom-model" if custom else "eleven_multilingual_v2",
                       "voice_settings": {"stability": 0.1 if custom else 0.45,
                                          "similarity_boost": 0.2 if custom else 0.75,
                                          "style": 0.3 if custom else 0.2, "use_speaker_boost": not custom}}
    assert meta == {"provider": "elevenlabs", "voice": "voice", "voice_id": "voice",
                    "model": payload["model_id"], "segment_count": 1, "bytes": len(b"ID3unit-audio"), "path": str(output)}
    assert output.read_bytes() == b"ID3unit-audio"
    assert not output.with_suffix(".mp3.tmp").exists()


@pytest.mark.parametrize("config,text,message", [
    ({"voice_id": "voice"}, "hello", "API key"),
    ({"api_key": "key", "voice_id": " "}, "hello", "voice_id"),
    ({"api_key": "key", "voice_id": "voice"}, " \n\t ", "empty script"),
])
def test_elevenlabs_invalid_inputs_do_not_make_requests(tmp_path, monkeypatch, config, text, message):
    monkeypatch.setattr(tts_elevenlabs, "urlopen", lambda *args, **kwargs: pytest.fail("invalid request sent"))
    with pytest.raises(RuntimeError, match=message):
        tts_elevenlabs.synthesize_text_to_mp3(text, tmp_path / "audio.mp3", config)
    assert not (tmp_path / "audio.mp3").exists()


@pytest.mark.parametrize("error", [HTTPError("https://example.com", 429, "limit", {}, None), URLError("offline")])
def test_elevenlabs_propagates_provider_errors_without_overwriting_audio(tmp_path, monkeypatch, error):
    output = tmp_path / "audio.mp3"
    output.write_bytes(b"original")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(tts_elevenlabs, "urlopen", fail)
    with pytest.raises(type(error)) as exc:
        tts_elevenlabs.synthesize_text_to_mp3("hello", output, {"api_key": "key", "voice_id": "voice"})
    assert exc.value is error
    assert output.read_bytes() == b"original"


def test_elevenlabs_empty_response_does_not_publish_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(tts_elevenlabs, "urlopen", lambda *args, **kwargs: io.BytesIO())
    with pytest.raises(RuntimeError, match="empty audio response"):
        tts_elevenlabs.synthesize_text_to_mp3("hello", tmp_path / "nested" / "audio.mp3", {"api_key": "key", "voice_id": "voice"})
    assert not (tmp_path / "nested").exists()
