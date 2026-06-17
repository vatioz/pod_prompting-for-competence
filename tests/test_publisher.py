from __future__ import annotations

import importlib
from pathlib import Path


def _write_runtime_fixture(runtime_dir: Path, *, base_url: str, public_base_url: str, auto_publish: bool) -> None:
    (runtime_dir / "config").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "data").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "generated").mkdir(parents=True, exist_ok=True)
    export_dir = runtime_dir / "publish"
    lines = [
        "podcast:",
        "  title: Prompting for Competence",
        "  description: Personal learning podcast feed generated from queued topics.",
        "  author: vatiozs",
        f"  base_url: {base_url}",
        "  language: en-us",
        "worker:",
        "  poll_seconds: 1",
        "research:",
        "  mode: structured_notes",
        "script:",
        "  mode: template",
        "  style: audio_native_explanatory",
        "  overview_target_minutes: 5",
        "  deep_dive_target_minutes: 18",
        "tts:",
        "  provider: sample",
        "publishing:",
        "  target: azure_static",
        f"  public_base_url: {public_base_url}",
        f"  export_dir: {export_dir}",
        f"  auto_publish: {'true' if auto_publish else 'false'}",
        "ui:",
        "  recent_topics_limit: 12",
        "",
    ]
    (runtime_dir / "config" / "podcast.yaml").write_text("\n".join(lines), encoding="utf-8")
    (runtime_dir / "config" / "listener-profile.md").write_text(
        "# Listener Profile\n\n- technically literate software engineer\n",
        encoding="utf-8",
    )
    (runtime_dir / "data" / "topics.yaml").write_text("topics: []\n", encoding="utf-8")


def _reload_modules():
    import app.config as config
    import app.feedgen as feedgen
    import app.publisher as publisher
    import app.research as research
    import app.script_writer as script_writer
    import app.storage as storage
    import app.worker as worker

    modules = [config, storage, feedgen, research, script_writer, publisher, worker]
    for module in modules:
        importlib.reload(module)
    return {
        "config": config,
        "storage": storage,
        "feedgen": feedgen,
        "publisher": publisher,
        "worker": worker,
    }


def test_publish_generated_variant_exports_bundle_and_updates_state(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(
        runtime_dir,
        base_url="https://preview.example.com",
        public_base_url="https://public.example.com/podcast",
        auto_publish=False,
    )
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    storage = modules["storage"]
    config = modules["config"]
    publisher = modules["publisher"]

    topic = storage.create_topic(prompt="Deterministic build systems", overview=True, deep_dive=False)
    audio_path = config.GENERATED_AUDIO_DIR / f"{topic['slug']}-overview-{topic['id']}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"ID3export-test")

    def apply(item: dict) -> None:
        item["status"] = "generated"
        item["research"]["status"] = "done"
        item["variants"]["overview"].update(
            {
                "status": "generated",
                "audio_path": str(audio_path),
                "published_title": "Deterministic build systems — Overview",
                "script": {"status": "done", "path": None, "model": "template"},
                "audio": {
                    "status": "done",
                    "path": str(audio_path),
                    "provider": "sample",
                    "voice_id": None,
                    "duration_seconds": None,
                },
                "publish": {"status": "queued", "public_url": None},
            }
        )

    storage.update_topic(topic["id"], apply)

    result = publisher.publish_topic_variant(topic_id=topic["id"], variant_name="overview", config=config.load_config())
    state = storage.load_state()
    updated_topic = state["topics"][0]
    variant = updated_topic["variants"]["overview"]
    export_dir = Path(config.load_config()["publishing"]["export_dir"]) / "current"
    exported_audio = export_dir / "audio" / audio_path.name
    exported_feed = export_dir / "feed.xml"

    assert result["bundle_dir"] == str(export_dir)
    assert variant["status"] == "exported"
    assert variant["publish"]["status"] == "done"
    assert variant["publish"]["public_url"] == f"https://public.example.com/podcast/audio/{audio_path.name}"
    assert exported_audio.exists()
    assert exported_audio.read_bytes() == b"ID3export-test"
    assert exported_feed.exists()
    assert f"https://public.example.com/podcast/audio/{audio_path.name}" in exported_feed.read_text(encoding="utf-8")


def test_worker_auto_publish_separates_generated_from_exported_state(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(
        runtime_dir,
        base_url="https://preview.example.com",
        public_base_url="https://public.example.com/podcast",
        auto_publish=True,
    )
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    storage = modules["storage"]
    config = modules["config"]
    worker_module = modules["worker"]

    def _fake_generate_research_markdown(topic, output_dir, research_config):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{topic['slug']}-{topic['id']}.md"
        path.write_text(
            "\n".join(
                [
                    "# Research Notes",
                    "## Topic Statement",
                    "A practical summary.",
                    "## Key Concepts",
                    "- Concept A",
                    "## Why It Matters",
                    "It reduces integration friction.",
                    "## Practical Examples",
                    "- Example",
                    "## Tradeoffs / Caveats",
                    "- More moving parts.",
                    "## Glossary / Jargon Expansion",
                    "- MCP: Model Context Protocol.",
                    "## Source Notes",
                    "- https://example.com",
                    "## Unresolved Questions",
                    "- Open question.",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def _fake_generate_script_markdown(topic, variant_name, research_markdown, output_dir, script_config):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{topic['slug']}-{variant_name}-{topic['id']}.md"
        path.write_text("# Hermetic build pipelines — Overview\n\nA concise practical script.", encoding="utf-8")
        return path

    def _fake_synthesize_script_to_mp3(script_path, output_path, tts_config):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ID3publisher-test")
        return {
            "provider": "elevenlabs",
            "voice": "test-voice",
            "voice_id": "test-voice",
            "model": "eleven_multilingual_v2",
            "segment_count": 1,
            "duration_seconds": None,
        }

    worker_module.generate_research_markdown = _fake_generate_research_markdown
    worker_module.generate_script_markdown = _fake_generate_script_markdown
    worker_module.synthesize_script_to_mp3 = _fake_synthesize_script_to_mp3

    storage.create_topic(prompt="Hermetic build pipelines", overview=True, deep_dive=False)
    worker = worker_module.DummyWorker(config.load_config())

    assert worker.process_once() is True

    state = storage.load_state()
    topic = state["topics"][0]
    variant = topic["variants"]["overview"]
    audio_name = Path(variant["audio"]["path"]).name
    export_feed = Path(config.load_config()["publishing"]["export_dir"]) / "current" / "feed.xml"

    assert topic["status"] == "exported"
    assert variant["status"] == "exported"
    assert variant["script"]["status"] == "done"
    assert variant["audio"]["status"] == "done"
    assert variant["publish"]["status"] == "done"
    assert variant["publish"]["public_url"] == f"https://public.example.com/podcast/audio/{audio_name}"
    assert export_feed.exists()
    assert f"https://public.example.com/podcast/audio/{audio_name}" in export_feed.read_text(encoding="utf-8")



def test_worker_uses_episode_number_in_artifact_names_and_feed_titles(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(
        runtime_dir,
        base_url="https://preview.example.com",
        public_base_url="https://public.example.com/podcast",
        auto_publish=True,
    )
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    storage = modules["storage"]
    config = modules["config"]
    worker_module = modules["worker"]

    def _fake_generate_research_markdown(topic, output_dir, research_config):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{topic['episode_number']:03d}_{topic['slug']}-{topic['id']}.md"
        path.write_text(
            "\n".join(
                [
                    "# Research Notes",
                    "## Topic Statement",
                    "A practical summary.",
                    "## Key Concepts",
                    "- Concept A",
                    "## Why It Matters",
                    "It reduces integration friction.",
                    "## Practical Examples",
                    "- Example",
                    "## Tradeoffs / Caveats",
                    "- More moving parts.",
                    "## Glossary / Jargon Expansion",
                    "- MCP: Model Context Protocol.",
                    "## Source Notes",
                    "- https://example.com",
                    "## Unresolved Questions",
                    "- Open question.",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def _fake_generate_script_markdown(topic, variant_name, research_markdown, output_dir, script_config):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{topic['episode_number']:03d}_{topic['slug']}-{variant_name}-{topic['id']}.md"
        path.write_text("# Episode numbering for sorting — Overview\n\nA concise practical script.\n\nMore detail here.\n", encoding="utf-8")
        return path

    def _fake_synthesize_script_to_mp3(script_path, output_path, tts_config):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ID3episode-numbering")
        return {
            "provider": "elevenlabs",
            "voice": "test-voice",
            "voice_id": "test-voice",
            "model": "eleven_multilingual_v2",
            "segment_count": 1,
            "duration_seconds": None,
        }

    worker_module.generate_research_markdown = _fake_generate_research_markdown
    worker_module.generate_script_markdown = _fake_generate_script_markdown
    worker_module.synthesize_script_to_mp3 = _fake_synthesize_script_to_mp3

    topic = storage.create_topic(prompt="Episode numbering for sorting", overview=True, deep_dive=False)
    worker = worker_module.DummyWorker(config.load_config())

    assert worker.process_once() is True

    state = storage.load_state()
    updated_topic = state["topics"][0]
    variant = updated_topic["variants"]["overview"]
    audio_name = Path(variant["audio"]["path"]).name
    script_name = Path(variant["script"]["path"]).name
    research_name = Path(updated_topic["research"]["path"]).name
    feed_text = (Path(config.load_config()["publishing"]["export_dir"]) / "current" / "feed.xml").read_text(encoding="utf-8")

    assert topic["episode_number"] == 1
    assert updated_topic["episode_number"] == 1
    assert research_name.startswith("001_")
    assert script_name.startswith("001_")
    assert audio_name.startswith("001_")
    assert variant["published_title"] == "Episode 001 — Episode numbering for sorting — Overview"
    assert "Episode 001 — Episode numbering for sorting — Overview" in feed_text
