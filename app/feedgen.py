from __future__ import annotations

from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from .config import GENERATED_AUDIO_DIR, GENERATED_FEED_PATH, podcast_artwork_public_url
from .storage import load_state, topic_variant_title

RFC822 = "%a, %d %b %Y %H:%M:%S GMT"


def _mime_type_for_audio(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix == ".wav":
        return "audio/wav"
    return "application/octet-stream"


def _resolve_audio_file(audio_path: str | None) -> Path | None:
    if not audio_path:
        return None
    stored = Path(audio_path)
    candidates = [stored]
    if stored.name:
        candidates.append(GENERATED_AUDIO_DIR / stored.name)
        if stored.suffix.lower() == ".wav":
            candidates.append(GENERATED_AUDIO_DIR / f"{stored.stem}.mp3")
        elif stored.suffix.lower() == ".mp3":
            candidates.append(GENERATED_AUDIO_DIR / f"{stored.stem}.wav")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _default_title(topic: dict, variant_name: str) -> str:
    return topic_variant_title(topic, variant_name)


def _publish_ready(variant: dict) -> bool:
    publish = variant.get("publish") or {}
    return publish.get("status") == "done" or variant.get("status") == "published"


def _media_url_for_item(base_url: str, variant: dict, audio_file: Path) -> str:
    publish = variant.get("publish") or {}
    public_url = publish.get("public_url")
    if public_url:
        return public_url
    return f"{base_url.rstrip('/')}/audio/{audio_file.name}"


def _published_items(state: dict, base_url: str) -> list[dict]:
    items = []
    for topic in state["topics"]:
        if topic.get("deleted"):
            continue
        for variant_name, variant in topic["variants"].items():
            if not variant["enabled"] or not _publish_ready(variant):
                continue
            audio_path = variant.get("audio_path") or ((variant.get("audio") or {}).get("path"))
            audio_file = _resolve_audio_file(audio_path)
            if not audio_file:
                continue
            publish = variant.get("publish") or {}
            completed_at = publish.get("completed_at") or variant.get("published_at") or topic["updated_at"]
            items.append(
                {
                    "guid": f"{topic['id']}-{variant_name}",
                    "title": variant.get("published_title") or _default_title(topic, variant_name),
                    "description": f"Auto-generated {variant_name.replace('_', ' ')} episode for: {topic['prompt']}",
                    "published_at": completed_at,
                    "audio_file": audio_file,
                    "media_url": _media_url_for_item(base_url, variant, audio_file),
                }
            )
    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items


def regenerate_feed(base_url: str, podcast_config: dict, *, state: dict | None = None, output_path: Path | None = None) -> Path:
    state = state or load_state()
    items = _published_items(state, base_url)
    feed_url = f"{base_url.rstrip('/')}/feed.xml"
    artwork_url = podcast_artwork_public_url({"podcast": podcast_config}, base_url)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">',
        '  <channel>',
        f"    <title>{escape(podcast_config['title'])}</title>",
        f"    <link>{escape(feed_url)}</link>",
        f"    <description>{escape(podcast_config['description'])}</description>",
        f"    <language>{escape(podcast_config.get('language', 'en-us'))}</language>",
        f"    <itunes:author>{escape(podcast_config.get('author', 'Unknown'))}</itunes:author>",
        f"    <itunes:summary>{escape(podcast_config['description'])}</itunes:summary>",
        '    <itunes:explicit>false</itunes:explicit>',
    ]
    if artwork_url:
        parts.extend(
            [
                f'    <itunes:image href="{escape(artwork_url)}" />',
                '    <image>',
                f"      <url>{escape(artwork_url)}</url>",
                f"      <title>{escape(podcast_config['title'])}</title>",
                f"      <link>{escape(feed_url)}</link>",
                '    </image>',
            ]
        )
    for item in items:
        pub_dt = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        audio_file = item["audio_file"]
        mime_type = _mime_type_for_audio(audio_file)
        parts.extend(
            [
                '    <item>',
                f"      <title>{escape(item['title'])}</title>",
                f"      <description>{escape(item['description'])}</description>",
                f"      <pubDate>{pub_dt.strftime(RFC822)}</pubDate>",
                f"      <guid isPermaLink=\"false\">{escape(item['guid'])}</guid>",
                f"      <enclosure url=\"{escape(item['media_url'])}\" length=\"{audio_file.stat().st_size}\" type=\"{mime_type}\" />",
                '    </item>',
            ]
        )
    parts.extend(['  </channel>', '</rss>', ''])
    feed_path = output_path or GENERATED_FEED_PATH
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text("\n".join(parts), encoding="utf-8")
    return feed_path
