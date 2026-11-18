from pathlib import Path

import pytest


def test_dispatch_rejects_unknown_tts_provider(tmp_path):
    from app.tts_dispatch import synthesize_script_to_mp3

    script_path = tmp_path / "script.md"
    script_path.write_text("# Test\n\nHello from the podcast app.", encoding="utf-8")
    output_path = tmp_path / "audio.mp3"

    try:
        synthesize_script_to_mp3(
            script_path=script_path,
            output_path=output_path,
            tts_config={"provider": "mystery_cloud"},
        )
        assert False, "expected unsupported provider to raise"
    except RuntimeError as exc:
        assert "Unsupported tts.provider" in str(exc)
        assert "mystery_cloud" in str(exc)


def test_config_defaults_include_multi_provider_tts_fields():
    from app.config import DEFAULT_CONFIG

    tts = DEFAULT_CONFIG["tts"]

    assert tts["provider"] == "azure_speech"
    assert tts["mode"] == "sync"
    assert "speech_endpoint" in tts
    assert "speech_api_key_env" in tts
    assert "speech_voice" in tts
    assert "speech_output_format" in tts
    assert "speech_sync_max_minutes" in tts
    assert "azure_openai_endpoint" in tts
    assert "azure_openai_api_key_env" in tts
    assert "azure_openai_model" in tts
    assert "azure_openai_voice" in tts
    assert "azure_openai_response_format" in tts
    assert "azure_openai_speed" in tts
    assert "azure_openai_max_chars_per_request" in tts
    assert "ffmpeg_path" in tts


@pytest.mark.parametrize("provider,implementation", [
    (" ElevenLabs ", "synthesize_with_elevenlabs"),
    (" Azure_Speech ", "synthesize_with_azure_speech"),
])
def test_dispatch_forwards_inputs_and_metadata(tmp_path, monkeypatch, provider, implementation):
    from app import tts_dispatch

    config = {"provider": provider, "voice_id": "test-voice"}
    calls = []

    def synthesize(**kwargs):
        calls.append(kwargs)
        return {"provider": provider.strip().lower(), "bytes": 12}

    monkeypatch.setattr(tts_dispatch, implementation, synthesize)
    script, output = tmp_path / "script.md", tmp_path / "audio.mp3"
    assert tts_dispatch.synthesize_script_to_mp3(script, output, config)["bytes"] == 12
    assert calls == [{"script_path": script, "output_path": output, "tts_config": config}]


def test_dispatch_rejects_unimplemented_azure_openai(tmp_path):
    from app.tts_dispatch import synthesize_script_to_mp3

    with pytest.raises(RuntimeError, match="azure_openai.*not implemented"):
        synthesize_script_to_mp3(tmp_path / "script.md", tmp_path / "audio.mp3", {"provider": "azure_openai"})
