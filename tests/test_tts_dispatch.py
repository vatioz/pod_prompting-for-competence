from pathlib import Path


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
