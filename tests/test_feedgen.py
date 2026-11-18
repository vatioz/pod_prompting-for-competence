from copy import deepcopy
from xml.etree import ElementTree

import pytest

from app import config, feedgen, storage


@pytest.mark.parametrize("suffix,mime", [(".mp3", "audio/mpeg"), (".m4a", "audio/mp4"), (".wav", "audio/wav"), (".raw", "application/octet-stream")])
def test_feed_enclosures_use_audio_mime_type(tmp_path, suffix, mime):
    topic = storage.create_topic("Escaping & ordering", True, False)
    audio = tmp_path / f"001_audio{suffix}"
    audio.write_bytes(b"audio")
    topic["variants"]["overview"].update(status="published", audio_path=str(audio))
    path = feedgen.regenerate_feed("https://example.com/", {"title": "Title & more", "description": "Description <detail>"},
                                   state={"topics": [topic]}, output_path=tmp_path / "feed.xml")
    channel = ElementTree.parse(path).getroot().find("channel")
    assert channel.findtext("title") == "Title & more"
    item = channel.find("item")
    assert item.findtext("title") == storage.topic_variant_title(topic, "overview")
    assert item.find("enclosure").attrib == {"url": f"https://example.com/audio/{audio.name}", "length": "5", "type": mime}


@pytest.mark.parametrize("stored_suffix,actual_suffix", [(".mp3", ".mp3"), (".wav", ".mp3"), (".mp3", ".wav")])
def test_feed_resolves_relocated_and_legacy_audio(tmp_path, stored_suffix, actual_suffix):
    config.ensure_runtime_dirs()
    actual = config.GENERATED_AUDIO_DIR / f"relocated{actual_suffix}"
    actual.write_bytes(b"media")
    assert feedgen._resolve_audio_file(str(tmp_path / "old" / f"relocated{stored_suffix}")) == actual


def test_feed_omits_deleted_and_missing_media_topics(tmp_path):
    topic = storage.create_topic("feed filtering", True, False)
    variant = topic["variants"]["overview"]
    variant.update(status="published", audio_path=None)
    assert feedgen._published_items({"topics": [topic]}, "https://example.com") == []
    variant["audio_path"] = str(tmp_path / "missing.mp3")
    assert feedgen._published_items({"topics": [topic]}, "https://example.com") == []
    media = tmp_path / "present.mp3"
    media.write_bytes(b"audio")
    variant["audio_path"] = str(media)
    topic["deleted"] = True
    assert feedgen._published_items({"topics": [topic]}, "https://example.com") == []


def test_feed_sorts_newest_first_and_honors_explicit_media_url(tmp_path):
    topic = storage.create_topic("feed ordering", True, False)
    media = tmp_path / "audio.mp3"
    media.write_bytes(b"audio")
    older = deepcopy(topic)
    newer = deepcopy(topic)
    older["id"], newer["id"] = "older", "newer"
    for row, date in [(older, "2025-01-01T00:00:00Z"), (newer, "2025-01-02T00:00:00Z")]:
        row["variants"]["overview"].update(audio_path=str(media), publish={"status": "done", "completed_at": date,
                                                                         "public_url": "https://cdn.example.com/media.mp3"})
    items = feedgen._published_items({"topics": [older, newer]}, "https://preview.example.com")
    assert [item["guid"] for item in items] == ["newer-overview", "older-overview"]
    assert all(item["media_url"] == "https://cdn.example.com/media.mp3" for item in items)
