from copy import deepcopy
from pathlib import Path

import pytest

from app import config, storage
from app.prompt_loader import render_prompt_template


def test_bind_settings_and_absolute_artwork(monkeypatch, tmp_path):
    assert config.get_bind_host() == "0.0.0.0"
    assert config.get_bind_port() == 6001
    monkeypatch.setenv("POD_HOST", "127.0.0.1")
    monkeypatch.setenv("POD_PORT", "8080")
    assert (config.get_bind_host(), config.get_bind_port()) == ("127.0.0.1", 8080)
    monkeypatch.setenv("POD_PORT", "invalid")
    with pytest.raises(ValueError):
        config.get_bind_port()
    cover = tmp_path / "cover.PNG"
    cover.write_bytes(b"image")
    settings = {"podcast": {"artwork": {"source_path": str(cover)}}}
    assert config.resolve_podcast_artwork_source(settings) == cover.resolve()
    assert config.podcast_artwork_public_url(settings, "https://example.com/") == "https://example.com/images/podcast-cover.png"
    cover.unlink()
    assert config.podcast_artwork_public_url(settings, "https://example.com") == ""


def test_prompt_nested_key_failure_preserves_cause():
    with pytest.raises(RuntimeError, match="missing value for placeholder: missing") as exc:
        render_prompt_template("{person[missing]}", {"person[missing]": "unused", "person": {}})
    assert isinstance(exc.value.__cause__, KeyError)


def test_missing_malformed_and_empty_state(tmp_path, monkeypatch):
    path = tmp_path / "topics.yaml"
    monkeypatch.setattr(storage, "TOPICS_PATH", path)
    state = storage.load_state()
    state["topics"].append({"id": "not-persisted"})
    assert storage.load_state() == {"topics": []}
    for contents in ("", "other: value\n", "topics: invalid\n"):
        path.write_text(contents, encoding="utf-8")
        assert storage.load_state()["topics"] == []


def test_topic_lookup_order_deleted_and_missing_updates():
    first = storage.create_topic("first", True, False)
    second = storage.create_topic("second", True, False)
    storage.unpublish_topic(first["id"])
    assert [topic["id"] for topic in storage.list_topics()] == [second["id"]]
    assert [topic["id"] for topic in storage.list_topics(include_deleted=True)] == [second["id"], first["id"]]
    assert storage.get_topic("missing") is None
    assert storage.update_topic("missing", lambda _: pytest.fail("updater must not run")) is None
    with pytest.raises(ValueError, match="positive"):
        storage.format_episode_number(0)


@pytest.mark.parametrize("stage", ["script", "legacy", "none"])
def test_retry_script_and_full_fallback_reset(stage):
    topic = storage.create_topic("retry", True, False)

    def fail(item):
        item["research"].update(status="done", path="research.md", error=None)
        variant = item["variants"]["overview"]
        variant["status"] = "failed" if stage == "legacy" else "generated"
        variant["script"].update(status="failed" if stage == "script" else "done", path="script.md", error="bad script" if stage == "script" else None)
        variant["audio"].update(status="done", path="audio.mp3", voice="voice")
        variant["publish"].update(status="done", public_url="https://example.com/audio.mp3")

    storage.update_topic(topic["id"], fail)
    updated = storage.retry_topic(topic["id"])
    if stage == "none":
        assert updated["status"] == "queued"
    assert updated["research"]["status"] == ("queued" if stage == "none" else "done")
    for name in ("script", "audio", "publish"):
        assert updated["variants"]["overview"][name]["status"] == "queued"
        assert updated["variants"]["overview"][name]["error"] is None
    assert updated["variants"]["deep_dive"]["status"] == "disabled"


def test_research_retry_keeps_disabled_variant_disabled():
    topic = storage.create_topic("research retry", True, False)
    storage.update_topic(topic["id"], lambda item: item["research"].update(status="failed", error="bad research"))
    updated = storage.retry_topic(topic["id"])
    assert updated["research"] == {"status": "queued", "path": None, "error": None}
    assert updated["variants"]["deep_dive"]["status"] == "disabled"


@pytest.mark.parametrize("statuses,research,expected", [
    ([], "done", "original"),
    (["failed"], "done", "failed"),
    (["published", "exported"], "done", "exported"),
    (["processing", "queued"], "done", "processing"),
    (["queued"], "processing", "processing"),
    (["queued"], "queued", "queued"),
    (["generated", "queued"], "done", "original"),
    (["published"], "failed", "failed"),
])
def test_derived_topic_status(statuses, research, expected):
    topic = {"status": "original", "research": {"status": research}, "variants": {
        str(index): {"enabled": True, "status": status} for index, status in enumerate(statuses)
    }}
    assert storage.recompute_topic_status(topic) == expected


def test_episode_number_conflicts_inference_and_fallback():
    topics = [
        {"episode_number": 1}, {"episode_number": 3},
        {"episode_number": 1, "research": {"path": "003_taken.md"}},
        {"research": {"path": "007_inferred.md"}},
        {},
    ]
    storage._assign_missing_episode_numbers(topics)
    assert [item["episode_number"] for item in topics] == [1, 3, 2, 7, 4]
    assert storage.topic_episode_label({"research": {"path": "007_inferred.md"}}) == "Episode 007"
    assert storage.topic_episode_label({}) == "Episode 001"


@pytest.mark.parametrize("voice_field", ["voice", "voice_id"])
def test_legacy_audio_voice_normalization_does_not_mutate_input(voice_field):
    raw = {"enabled": True, "status": "generated", "audio": {"path": "audio.mp3", voice_field: "legacy"}}
    original = deepcopy(raw)
    result = storage._normalize_variant(raw)
    assert result["audio"]["voice_id"] == "legacy"
    assert result["audio"]["voice"] == "legacy"
    assert result["audio"]["status"] == "done"
    assert raw == original
