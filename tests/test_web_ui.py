from __future__ import annotations

import importlib
from pathlib import Path


def _write_runtime_fixture(runtime_dir: Path) -> None:
    (runtime_dir / "config" / "prompts").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "data").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "generated" / "audio").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "generated" / "scripts").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "generated" / "research").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config" / "podcast.yaml").write_text(
        "\n".join(
            [
                "podcast:",
                "  title: Prompting for Competence",
                "  description: Personal learning podcast feed generated from queued topics.",
                "  author: vatioz",
                "  base_url: https://pod.example.com",
                "  language: en-us",
                "worker:",
                "  poll_seconds: 1",
                "research:",
                "  provider: azure_foundry",
                "script:",
                "  provider: azure_foundry",
                "tts:",
                "  provider: elevenlabs",
                "publishing:",
                "  target: app_hosted",
                f"  export_dir: {runtime_dir / 'publish'}",
                "  auto_publish: false",
                "ui:",
                "  recent_topics_limit: 12",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (runtime_dir / "config" / "prompts" / "research_prompt.txt").write_text("Research topic: {topic_prompt}\n", encoding="utf-8")
    (runtime_dir / "config" / "prompts" / "script_overview_prompt.txt").write_text(
        "Overview topic: {topic_prompt}\n{script_steering_block}\nTitle: {script_title}\n{research_markdown}\n",
        encoding="utf-8",
    )
    (runtime_dir / "config" / "prompts" / "script_deep_dive_prompt.txt").write_text(
        "Deep dive topic: {topic_prompt}\n{script_steering_block}\nTitle: {script_title}\n{research_markdown}\n",
        encoding="utf-8",
    )
    (runtime_dir / "data" / "topics.yaml").write_text("topics: []\n", encoding="utf-8")


def _reload_modules():
    import app.app as app_module
    import app.config as config
    import app.feedgen as feedgen
    import app.publisher as publisher
    import app.storage as storage
    import app.worker as worker

    modules = [config, storage, feedgen, publisher, worker, app_module]
    for module in modules:
        importlib.reload(module)
    return {
        "app": app_module,
        "config": config,
        "publisher": publisher,
        "storage": storage,
        "worker": worker,
    }


def _build_test_app(modules):
    modules["worker"].DummyWorker.start = lambda self: None
    app = modules["app"].create_app()
    app.config["TESTING"] = True
    return app


def _create_published_topic(modules, prompt: str = "Remove me from feed") -> dict:
    storage = modules["storage"]
    config = modules["config"]
    publisher = modules["publisher"]

    topic = storage.create_topic(prompt=prompt, overview=True, deep_dive=False)
    audio_path = config.GENERATED_AUDIO_DIR / f"{topic['episode_number']:03d}_{topic['slug']}-overview-{topic['id']}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"ID3web-ui-test")

    def apply(item: dict) -> None:
        item["status"] = "published"
        item["research"]["status"] = "done"
        item["research"]["path"] = str(config.GENERATED_RESEARCH_DIR / f"{topic['episode_number']:03d}_{topic['slug']}-{topic['id']}.md")
        item["variants"]["overview"].update(
            {
                "status": "published",
                "audio_path": str(audio_path),
                "published_title": f"Episode {topic['episode_number']:03d} — {item['prompt']} — Overview",
                "script": {"status": "done", "path": None, "model": "gpt-test", "error": None},
                "audio": {
                    "status": "done",
                    "path": str(audio_path),
                    "provider": "elevenlabs",
                    "voice": "test-voice",
                    "voice_id": "test-voice",
                    "model": "test-model",
                    "segment_count": 1,
                    "duration_seconds": None,
                    "error": None,
                },
                "publish": {
                    "status": "done",
                    "public_url": f"https://pod.example.com/audio/{audio_path.name}",
                    "completed_at": "2026-06-14T00:00:00+00:00",
                    "error": None,
                },
            }
        )

    storage.update_topic(topic["id"], apply)
    publisher.rebuild_publish_outputs(config.load_config())
    return storage.get_topic(topic["id"])


def test_submit_route_creates_topic_with_episode_number_script_steering_and_async_response(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    app = _build_test_app(modules)
    client = app.test_client()

    try:
        response = client.post(
            "/submit",
            data={
                "prompt": "UI refresh topic",
                "variant_overview": "on",
                "script_steering": "Explain like I'm 5, then connect it back to production engineering.",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        body = client.get("/").get_data(as_text=True)
        state = modules["storage"].load_state()
    finally:
        app.config["WORKER"].stop()

    assert response.status_code == 204
    assert len(state["topics"]) == 1
    assert state["topics"][0]["episode_number"] == 1
    assert state["topics"][0]["user_inputs"]["script_steering"] == "Explain like I'm 5, then connect it back to production engineering."
    assert state["topics"][0]["variants"]["overview"]["enabled"] is True
    assert state["topics"][0]["variants"]["deep_dive"]["enabled"] is False
    assert "Episode 001" in body
    assert 'data-topics-url="/ui/topics"' in body


def test_topics_fragment_shows_episode_badge_and_collapsible_markup(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    modules["storage"].create_topic(prompt="Episode list view", overview=True, deep_dive=False)
    app = _build_test_app(modules)
    client = app.test_client()

    try:
        response = client.get("/ui/topics")
        body = response.get_data(as_text=True)
    finally:
        app.config["WORKER"].stop()

    assert response.status_code == 200
    assert '<details class="topic" data-topic-id="' in body
    assert '<summary class="topic-summary">' in body
    assert "Episode 001" in body
    assert "Details" in body


def test_topics_fragment_shows_saved_script_steering_in_details(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    modules["storage"].create_topic(
        prompt="Steer this script",
        overview=True,
        deep_dive=False,
        script_steering="Focus on failure modes and compare it to VPNs.",
    )
    app = _build_test_app(modules)
    client = app.test_client()

    try:
        response = client.get("/ui/topics")
        body = response.get_data(as_text=True)
    finally:
        app.config["WORKER"].stop()

    assert response.status_code == 200
    assert "Script steering" in body
    assert "Focus on failure modes and compare it to VPNs." in body


def test_refresh_script_preserves_open_topic_details(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    topic = modules["storage"].create_topic(prompt="Keep details open", overview=True, deep_dive=False)
    app = _build_test_app(modules)
    client = app.test_client()

    try:
        body = client.get("/ui/topics").get_data(as_text=True)
    finally:
        app.config["WORKER"].stop()

    assert f'data-topic-id="{topic["id"]}"' in body


def test_unpublish_route_hides_topic_from_list_and_feed(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    topic = _create_published_topic(modules)
    app = _build_test_app(modules)
    client = app.test_client()

    try:
        response = client.post(
            f"/topics/{topic['id']}/unpublish",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        updated = modules["storage"].get_topic(topic["id"])
        fragment = client.get("/ui/topics").get_data(as_text=True)
        index_body = client.get("/").get_data(as_text=True)
        feed_text = modules["config"].GENERATED_FEED_PATH.read_text(encoding="utf-8")
    finally:
        app.config["WORKER"].stop()

    assert response.status_code == 204
    assert updated["deleted"] is True
    assert updated["status"] == "unpublished"
    assert topic["prompt"] not in fragment
    assert topic["prompt"] not in index_body
    assert topic["id"] not in feed_text


def test_index_includes_auto_refresh_script_remove_from_feed_action_and_feed_link(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    _create_published_topic(modules, prompt="Refresh me")
    app = _build_test_app(modules)
    client = app.test_client()

    try:
        response = client.get("/")
        body = response.get_data(as_text=True)
    finally:
        app.config["WORKER"].stop()

    assert response.status_code == 200
    assert 'src="/static/app.js"' in body
    assert 'data-refresh-interval-seconds="5"' in body
    assert 'data-async="true"' in body
    assert 'name="script_steering"' in body
    assert 'Optional steering' in body
    assert 'name="variant_overview" checked' in body
    assert 'name="variant_deep_dive"> Deep Dive' in body
    assert 'name="variant_deep_dive" checked' not in body
    assert 'Remove From Feed' in body
    assert 'Feed: <a href="https://pod.example.com/feed.xml">https://pod.example.com/feed.xml</a>' in body
    assert 'Publishing Status' not in body
    assert 'Static Listener Context' not in body


def test_index_hides_internal_debug_details_when_topics_are_rendered(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    topic = _create_published_topic(modules, prompt="Hide debug details")
    app = _build_test_app(modules)
    client = app.test_client()

    try:
        response = client.get("/")
        body = response.get_data(as_text=True)
    finally:
        app.config["WORKER"].stop()

    assert response.status_code == 200
    assert str(modules["config"].GENERATED_RESEARCH_DIR) not in body
    assert str(modules["config"].GENERATED_AUDIO_DIR) not in body
    assert topic["slug"] not in body
    assert 'Publishing Status' not in body
    assert 'Static Listener Context' not in body
