from types import SimpleNamespace

import pytest


class _FakeSpeechConfig:
    def __init__(self, subscription=None, endpoint=None, region=None):
        self.subscription = subscription
        self.endpoint = endpoint
        self.region = region
        self.speech_synthesis_voice_name = None
        self.output_format = None

    def set_speech_synthesis_output_format(self, value):
        self.output_format = value


class _FakeAudioOutputConfig:
    def __init__(self, filename):
        self.filename = filename


class _FakeSynthesisResult:
    def __init__(self, reason, cancellation_details=None):
        self.reason = reason
        self.cancellation_details = cancellation_details


class _FakeSpeechSynthesizer:
    last_call = None
    result_reason = 'completed'
    cancellation_details = None

    def __init__(self, speech_config=None, audio_config=None):
        self.speech_config = speech_config
        self.audio_config = audio_config

    def speak_text_async(self, text):
        self.__class__.last_call = {
            'text': text,
            'speech_config': self.speech_config,
            'audio_config': self.audio_config,
        }
        if self.__class__.result_reason == 'completed':
            open(self.audio_config.filename, 'wb').write(b'ID3fake-azure-speech-mp3')
            result = _FakeSynthesisResult(_FakeSpeechSdk.ResultReason.SynthesizingAudioCompleted)
        else:
            result = _FakeSynthesisResult(
                _FakeSpeechSdk.ResultReason.Canceled,
                cancellation_details=self.__class__.cancellation_details,
            )
        return SimpleNamespace(get=lambda: result)


class _FakeSpeechSdk:
    class ResultReason:
        SynthesizingAudioCompleted = 'SynthesizingAudioCompleted'
        Canceled = 'Canceled'

    class SpeechSynthesisOutputFormat:
        Audio24Khz96KBitRateMonoMp3 = 'Audio24Khz96KBitRateMonoMp3'

    SpeechConfig = _FakeSpeechConfig
    SpeechSynthesizer = _FakeSpeechSynthesizer
    audio = SimpleNamespace(AudioOutputConfig=_FakeAudioOutputConfig)


def test_azure_speech_synthesizes_script_to_mp3_via_sdk_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv('AZURE_SPEECH_KEY', 'speech-test-key')
    from app import tts_azure_speech

    monkeypatch.setattr(tts_azure_speech, '_load_speechsdk', lambda: _FakeSpeechSdk)

    script_path = tmp_path / 'script.md'
    script_path.write_text(
        '# Overview\n\nHello and welcome to the podcast. Today we are exploring Model Context Protocol in practical engineering terms.',
        encoding='utf-8',
    )
    output_path = tmp_path / 'audio.mp3'

    meta = tts_azure_speech.synthesize_script_to_mp3(
        script_path=script_path,
        output_path=output_path,
        tts_config={
            'provider': 'azure_speech',
            'mode': 'sync',
            'speech_endpoint': 'https://example-speech-resource.cognitiveservices.azure.com/',
            'speech_api_key_env': 'AZURE_SPEECH_KEY',
            'speech_voice': 'en-US-Ava:DragonHDLatestNeural',
            'speech_output_format': 'audio-24khz-96kbitrate-mono-mp3',
            'speech_sync_max_minutes': 9.5,
        },
    )

    assert output_path.exists()
    assert output_path.read_bytes() == b'ID3fake-azure-speech-mp3'
    assert meta['provider'] == 'azure_speech'
    assert meta['voice'] == 'en-US-Ava:DragonHDLatestNeural'
    assert meta['voice_id'] == 'en-US-Ava:DragonHDLatestNeural'
    assert meta['model'] == 'speech_sync'
    assert meta['segment_count'] == 1

    call = _FakeSpeechSynthesizer.last_call
    assert call['speech_config'].subscription == 'speech-test-key'
    assert call['speech_config'].endpoint == 'https://example-speech-resource.cognitiveservices.azure.com'
    assert call['speech_config'].region is None
    assert call['speech_config'].speech_synthesis_voice_name == 'en-US-Ava:DragonHDLatestNeural'
    assert call['speech_config'].output_format == 'Audio24Khz96KBitRateMonoMp3'


def test_azure_speech_supports_region_only_config(tmp_path, monkeypatch):
    monkeypatch.setenv('AZURE_SPEECH_KEY', 'speech-test-key')
    from app import tts_azure_speech

    monkeypatch.setattr(tts_azure_speech, '_load_speechsdk', lambda: _FakeSpeechSdk)

    output_path = tmp_path / 'audio.mp3'
    meta = tts_azure_speech.synthesize_text_to_mp3(
        spoken_text='Hello from Azure Speech.',
        output_path=output_path,
        tts_config={
            'provider': 'azure_speech',
            'mode': 'sync',
            'speech_region': 'swedencentral',
            'speech_api_key_env': 'AZURE_SPEECH_KEY',
            'speech_voice': 'en-US-Ava:DragonHDLatestNeural',
            'speech_output_format': 'audio-24khz-96kbitrate-mono-mp3',
            'speech_sync_max_minutes': 9.5,
        },
    )

    assert meta['provider'] == 'azure_speech'
    call = _FakeSpeechSynthesizer.last_call
    assert call['speech_config'].endpoint is None
    assert call['speech_config'].region == 'swedencentral'


def test_azure_speech_fails_clearly_when_required_config_is_missing(tmp_path):
    from app.tts_azure_speech import synthesize_script_to_mp3

    script_path = tmp_path / 'script.md'
    script_path.write_text('# Overview\n\nHello there.', encoding='utf-8')
    output_path = tmp_path / 'audio.mp3'

    try:
        synthesize_script_to_mp3(
            script_path=script_path,
            output_path=output_path,
            tts_config={'provider': 'azure_speech', 'mode': 'sync'},
        )
        assert False, 'expected missing config to raise'
    except RuntimeError as exc:
        message = str(exc)
        assert 'speech_endpoint' in message or 'speech_region' in message or 'AZURE_SPEECH_KEY' in message or 'speech_voice' in message


def test_azure_speech_blocks_when_estimated_duration_exceeds_sync_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('AZURE_SPEECH_KEY', 'speech-test-key')
    from app import tts_azure_speech

    monkeypatch.setattr(tts_azure_speech, '_load_speechsdk', lambda: _FakeSpeechSdk)

    output_path = tmp_path / 'audio.mp3'

    try:
        tts_azure_speech.synthesize_text_to_mp3(
            spoken_text='word ' * 1800,
            output_path=output_path,
            tts_config={
                'provider': 'azure_speech',
                'mode': 'sync',
                'speech_region': 'swedencentral',
                'speech_api_key_env': 'AZURE_SPEECH_KEY',
                'speech_voice': 'en-US-Ava:DragonHDLatestNeural',
                'speech_output_format': 'audio-24khz-96kbitrate-mono-mp3',
                'speech_sync_max_minutes': 9.5,
            },
        )
        assert False, 'expected estimated duration guard to raise'
    except RuntimeError as exc:
        assert 'estimated duration' in str(exc).lower()
        assert 'sync' in str(exc).lower()


def test_azure_speech_surfaces_sdk_cancellation_details(tmp_path, monkeypatch):
    monkeypatch.setenv('AZURE_SPEECH_KEY', 'speech-test-key')
    from app import tts_azure_speech

    monkeypatch.setattr(tts_azure_speech, '_load_speechsdk', lambda: _FakeSpeechSdk)
    _FakeSpeechSynthesizer.result_reason = 'canceled'
    _FakeSpeechSynthesizer.cancellation_details = SimpleNamespace(reason='Error', error_details='Resource not found')

    try:
        tts_azure_speech.synthesize_text_to_mp3(
            spoken_text='Hello from Azure Speech.',
            output_path=tmp_path / 'audio.mp3',
            tts_config={
                'provider': 'azure_speech',
                'mode': 'sync',
                'speech_endpoint': 'https://example-speech-resource.cognitiveservices.azure.com/',
                'speech_api_key_env': 'AZURE_SPEECH_KEY',
                'speech_voice': 'en-US-Ava:DragonHDLatestNeural',
                'speech_output_format': 'audio-24khz-96kbitrate-mono-mp3',
                'speech_sync_max_minutes': 9.5,
            },
        )
        assert False, 'expected sdk cancellation to raise'
    except RuntimeError as exc:
        assert 'Resource not found' in str(exc)
    finally:
        _FakeSpeechSynthesizer.result_reason = 'completed'
        _FakeSpeechSynthesizer.cancellation_details = None


@pytest.mark.parametrize("overrides,text,message", [
    ({"mode": "batch"}, "hello", "not implemented"),
    ({"speech_api_key": ""}, "hello", "API key is required"),
    ({"speech_voice": " "}, "hello", "speech_voice is required"),
    ({}, " \n\t ", "empty script"),
])
def test_azure_speech_validates_before_loading_sdk(tmp_path, monkeypatch, overrides, text, message):
    from app import tts_azure_speech

    config = {"speech_region": "westus", "speech_api_key": "unit-key", "speech_voice": "unit-voice", **overrides}
    monkeypatch.setattr(tts_azure_speech, "_load_speechsdk", lambda: pytest.fail("invalid request reached SDK"))
    with pytest.raises(RuntimeError, match=message):
        tts_azure_speech.synthesize_text_to_mp3(text, tmp_path / "audio.mp3", config)
    assert not (tmp_path / "audio.mp3").exists()


@pytest.mark.parametrize("reason,content,details,message", [
    (_FakeSpeechSdk.ResultReason.SynthesizingAudioCompleted, None, None, "no audio file"),
    (_FakeSpeechSdk.ResultReason.SynthesizingAudioCompleted, b"", None, "empty audio file"),
    (_FakeSpeechSdk.ResultReason.Canceled, None, SimpleNamespace(), "canceled \\(unknown\\)"),
    ("unexpected", None, None, "unexpected result reason: unexpected"),
])
def test_azure_speech_rejects_unsuccessful_sdk_results(tmp_path, monkeypatch, reason, content, details, message):
    from app import tts_azure_speech

    output = tmp_path / "audio.mp3"

    def speak(self, text):
        if content is not None:
            output.write_bytes(content)
        return SimpleNamespace(get=lambda: _FakeSynthesisResult(reason, details))

    monkeypatch.setattr(_FakeSpeechSynthesizer, "speak_text_async", speak)
    monkeypatch.setattr(tts_azure_speech, "_load_speechsdk", lambda: _FakeSpeechSdk)
    with pytest.raises(RuntimeError, match=message):
        tts_azure_speech.synthesize_text_to_mp3("hello", output, {
            "speech_region": "westus", "speech_api_key": "unit-key", "speech_voice": "unit-voice",
        })


def test_azure_speech_exact_duration_limit_and_unknown_output_format(tmp_path, monkeypatch):
    from app import tts_azure_speech

    monkeypatch.setattr(tts_azure_speech, "_load_speechsdk", lambda: _FakeSpeechSdk)
    config = {"speech_region": "westus", "speech_api_key": "unit-key", "speech_voice": "unit-voice",
              "speech_sync_max_minutes": 1, "speech_output_format": "sdk-default"}
    output = tmp_path / "audio.mp3"
    meta = tts_azure_speech.synthesize_text_to_mp3("word " * 150, output, config)
    assert meta["bytes"] == len(output.read_bytes())
    assert _FakeSpeechSynthesizer.last_call["speech_config"].output_format is None
    with pytest.raises(RuntimeError, match="exceeds speech_sync_max_minutes=1"):
        tts_azure_speech.synthesize_text_to_mp3("word " * 151, output, config)


def test_azure_speech_sdk_load_and_missing_dependency(monkeypatch):
    import sys
    from app import tts_azure_speech

    assert tts_azure_speech._load_speechsdk().SpeechConfig is not None
    monkeypatch.setitem(sys.modules, "azure.cognitiveservices.speech", None)
    with pytest.raises(RuntimeError, match="SDK is not installed") as exc:
        tts_azure_speech._load_speechsdk()
    assert isinstance(exc.value.__cause__, ImportError)


def test_azure_speech_accepts_non_url_endpoint(tmp_path, monkeypatch):
    from app import tts_azure_speech

    monkeypatch.setattr(tts_azure_speech, "_load_speechsdk", lambda: _FakeSpeechSdk)
    tts_azure_speech.synthesize_text_to_mp3("hello", tmp_path / "audio.mp3", {
        "speech_endpoint": " local-endpoint/ ", "speech_api_key": "unit-key", "speech_voice": "unit-voice",
    })
    assert _FakeSpeechSynthesizer.last_call["speech_config"].endpoint == "local-endpoint"
