import io
import json
from contextlib import contextmanager
from urllib.error import HTTPError, URLError

import pytest

from app import config, research, script_writer, storage


@pytest.fixture
def topic():
    config.ensure_runtime_dirs()
    return storage.create_topic("Mechanisms and tradeoffs", True, True, "Use concrete examples")


@pytest.mark.parametrize("module", [research, script_writer])
def test_foundry_request_and_environment_fallbacks(module, topic, monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.com/openai/v1/")
    monkeypatch.setenv("AZURE_OPENAI_MODEL", "model-test")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key")
    calls = []

    @contextmanager
    def urlopen(req, timeout):
        calls.append((req, timeout))
        yield io.BytesIO(json.dumps({"output_text": "response"}).encode())

    monkeypatch.setattr(module.request, "urlopen", urlopen)
    settings = {"effort": "low", "timeout_seconds": 12, "api_key_env": "UNSET_TEST_KEY"}
    if module is research:
        settings.update(allowed_domains=["example.com", ""], blocked_domains=["blocked.example.com"], user_location={"country": "US"})
        result = module._call_foundry_research(topic, settings)
    else:
        result = module._call_foundry_script(topic, "deep_dive", "Research input", settings)
    req, timeout = calls[0]
    payload = json.loads(req.data)
    assert result == {"output_text": "response"}
    assert req.full_url == "https://example.com/openai/v1/responses"
    assert req.method == "POST"
    assert req.get_header("Api-key") == "fake-key"
    assert timeout == 12
    assert payload["model"] == "model-test"
    assert payload["reasoning"] == {"effort": "low"}
    assert topic["prompt"] in payload["input"]
    if module is research:
        assert payload["include"] == ["web_search_call.action.sources"]
        assert payload["tools"][0]["filters"] == {"allowed_domains": ["example.com"], "blocked_domains": ["blocked.example.com"]}
        assert payload["tools"][0]["user_location"] == {"country": "US"}
    else:
        assert "Research input" in payload["input"]
        assert "Use concrete examples" in payload["input"]
        assert "tools" not in payload


@pytest.mark.parametrize("module", [research, script_writer])
@pytest.mark.parametrize("missing", ["endpoint", "model", "api_key"])
def test_foundry_missing_settings(module, topic, missing):
    settings = {"endpoint": "https://example.com", "model": "test", "api_key": "fake"}
    del settings[missing]
    with pytest.raises(RuntimeError, match="requires"):
        if module is research:
            module._call_foundry_research(topic, settings)
        else:
            module._call_foundry_script(topic, "overview", "Research", settings)


@pytest.mark.parametrize("module", [research, script_writer])
@pytest.mark.parametrize("failure", ["http", "url"])
def test_foundry_transport_failure_details(module, topic, monkeypatch, failure):
    error = HTTPError("https://example.com", 429, "rate limit", {}, io.BytesIO(b"retry later")) if failure == "http" else URLError("offline")

    def urlopen(*args, **kwargs):
        raise error

    monkeypatch.setattr(module.request, "urlopen", urlopen)
    settings = {"endpoint": "https://example.com", "model": "test", "api_key": "fake"}
    with pytest.raises(RuntimeError, match="HTTP 429: retry later" if failure == "http" else "offline") as exc:
        if module is research:
            module._call_foundry_research(topic, settings)
        else:
            module._call_foundry_script(topic, "overview", "Research", settings)
    assert exc.value.__cause__ is error


@pytest.mark.parametrize("module", [research, script_writer])
def test_response_content_fallback_and_empty_error(module, topic, monkeypatch):
    response = {"output_text": " ", "output": [{"content": [{"type": "other", "text": "ignore"}, {"type": "output_text", "text": "nested"}]}]}
    assert module._extract_output_text(response) == "nested"
    assert module._responses_url(" https://example.com/responses ") == "https://example.com/responses"
    assert module._extract_output_text({}) == ""
    if module is research:
        monkeypatch.setattr(module, "_call_foundry_research", lambda **kwargs: {})
        call = lambda: module.build_research_markdown_with_foundry(topic, {})
    else:
        monkeypatch.setattr(module, "_call_foundry_script", lambda **kwargs: {})
        call = lambda: module.build_script_markdown_with_foundry(topic, "overview", "Research", {})
    with pytest.raises(RuntimeError, match="did not include output text"):
        call()


def test_research_artifact_and_source_note_replacement(topic, tmp_path, monkeypatch):
    text = "# Research\n\n" + "\n\n".join(heading + "\n" + "Useful explanation. " * 5 for heading in research.REQUIRED_HEADINGS)
    response = {"output_text": text, "output": [
        {"type": "web_search_call", "action": {"sources": [{"url": " https://example.com/a "}, {"url": "https://example.com/b", "title": "B"}, {"url": ""}]}},
        {"content": [{"annotations": [{"type": "ignore"}, {"type": "url_citation", "url": "https://example.com/a", "title": "A"}, {"type": "url_citation", "url": "https://example.com/c"}]}]},
    ]}
    monkeypatch.setattr(research, "_call_foundry_research", lambda **kwargs: response)
    path = research.generate_research_markdown(topic, tmp_path)
    written = path.read_text(encoding="utf-8")
    assert path.name == storage.topic_artifact_stem(topic) + ".md"
    assert "## Source Notes\n- A: https://example.com/a\n- B: https://example.com/b\n- https://example.com/c\n" in written
    assert "## Unresolved Questions" in written
    assert research._inject_source_notes(text, {}) == text
    assert research._replace_section_body("# No sources", "## Source Notes", ["- source"]) == "# No sources\n\n## Source Notes\n- source\n"
    with pytest.raises(ValueError, match="too short"):
        research.validate_research_markdown("short")
    with pytest.raises(ValueError, match="missing required headings"):
        research.validate_research_markdown("long enough " * 50)


def test_script_artifact_normalizes_bullets_and_missing_title(topic, tmp_path, monkeypatch):
    text = "- First mechanism. " + "detail " * 30 + "\n\n\n* Second mechanism.\n\nFinal tradeoff."
    monkeypatch.setattr(script_writer, "_call_foundry_script", lambda **kwargs: {"output_text": text})
    path = script_writer.generate_script_markdown(topic, "deep_dive", "Research", tmp_path)
    written = path.read_text(encoding="utf-8")
    assert path.name == storage.topic_artifact_stem(topic, "deep_dive") + ".md"
    assert written.startswith("# " + storage.topic_variant_title(topic, "deep_dive") + "\n\nFirst mechanism.")
    assert "\n* " not in written and "\n- " not in written and "\n\n\n" not in written
    assert "Second mechanism." in script_writer.spoken_text_from_markdown(written)
    assert script_writer._script_steering_block({}) == "Additional script steering: none"


@pytest.mark.parametrize("text,message", [
    ("short", "too short"),
    ("words " * 50, "markdown title"),
    ("# Title\n" + "words " * 50, "multiple spoken paragraphs"),
])
def test_script_validation_errors(text, message):
    with pytest.raises(ValueError, match=message):
        script_writer.validate_script_markdown(text)
