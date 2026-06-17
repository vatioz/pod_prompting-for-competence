from __future__ import annotations

import importlib
from pathlib import Path


def _write_runtime_fixture(
    runtime_dir: Path,
    *,
    target: str = "azure_static",
    deploy_enabled: bool = True,
    public_base_url: str = "https://public.example.com/podcast",
) -> None:
    (runtime_dir / "config").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "data").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "generated").mkdir(parents=True, exist_ok=True)
    export_dir = runtime_dir / "publish"
    (runtime_dir / "config" / "podcast.yaml").write_text(
        "\n".join(
            [
                "podcast:",
                "  title: Prompting for Competence",
                "  description: Personal learning podcast feed generated from queued topics.",
                "  author: vatioz",
                "  base_url: https://preview.example.com",
                "  language: en-us",
                "worker:",
                "  poll_seconds: 1",
                "research:",
                "  provider: azure_foundry",
                "script:",
                "  provider: azure_foundry",
                "tts:",
                "  provider: sample",
                "publishing:",
                f"  target: {target}",
                f"  public_base_url: {public_base_url}",
                f"  export_dir: {export_dir}",
                "  auto_publish: false",
                f"  deploy_enabled: {'true' if deploy_enabled else 'false'}",
                "  azure_container: $web",
                "  azure_path_prefix: podcast",
                "  azure_delete_stale: true",
                "  azure_allow_root_delete: false",
                "  azure_credential_mode: connection_string",
                "  azure_connection_string_env: AZURE_STORAGE_CONNECTION_STRING",
                "ui:",
                "  recent_topics_limit: 12",
                "",
            ]
        ),
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

    for module in [config, storage, feedgen, publisher, worker, app_module]:
        importlib.reload(module)
    return {
        "app": app_module,
        "config": config,
        "publisher": publisher,
        "storage": storage,
        "worker": worker,
    }


def _mark_topic_as_generated(modules, topic):
    storage = modules["storage"]
    config = modules["config"]
    audio_path = config.GENERATED_AUDIO_DIR / f"{topic['episode_number']:03d}_{topic['slug']}-overview-{topic['id']}.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"ID3azure-publisher")

    def apply(item: dict) -> None:
        item["status"] = "generated"
        item["research"]["status"] = "done"
        item["variants"]["overview"].update(
            {
                "status": "generated",
                "audio_path": str(audio_path),
                "published_title": f"Episode {item['episode_number']:03d} — {item['prompt']} — Overview",
                "script": {"status": "done", "path": None, "model": "template"},
                "audio": {"status": "done", "path": str(audio_path), "provider": "sample"},
                "publish": {"status": "queued", "public_url": None, "error": None},
            }
        )

    storage.update_topic(topic["id"], apply)
    return audio_path


def test_publish_calls_azure_deploy_when_enabled(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, deploy_enabled=True)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    topic = modules["storage"].create_topic(prompt="Azure deploy", overview=True, deep_dive=False)
    audio_path = _mark_topic_as_generated(modules, topic)

    calls = []

    def fake_deploy(bundle_dir, publishing_config):
        calls.append((str(bundle_dir), publishing_config["azure_path_prefix"]))
        return {
            "uploaded": ["podcast/feed.xml"],
            "deleted": [],
            "uploaded_count": 1,
            "deleted_count": 0,
            "remote_feed_url": "https://public.example.com/podcast/feed.xml",
            "container": "$web",
            "prefix": "podcast",
        }

    modules["publisher"].deploy_directory_to_azure_static = fake_deploy
    result = modules["publisher"].publish_topic_variant(topic["id"], "overview", modules["config"].load_config())

    assert calls == [(str(Path(runtime_dir / "publish" / "current")), "podcast")]
    assert result["deploy"]["deployed"] is True
    assert result["public_url"] == f"https://public.example.com/podcast/audio/{audio_path.name}"


def test_unpublish_rebuild_triggers_azure_deploy(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, deploy_enabled=True)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    topic = modules["storage"].create_topic(prompt="Azure unpublish", overview=True, deep_dive=False)
    audio_path = _mark_topic_as_generated(modules, topic)

    modules["storage"].update_topic(
        topic["id"],
        lambda item: item["variants"]["overview"]["publish"].update(
            {
                "status": "done",
                "public_url": f"https://public.example.com/podcast/audio/{audio_path.name}",
                "completed_at": "2026-06-14T00:00:00+00:00",
                "error": None,
            }
        ),
    )
    modules["storage"].unpublish_topic(topic["id"])

    calls = []

    def fake_deploy(bundle_dir, publishing_config):
        calls.append(str(bundle_dir))
        return {
            "uploaded": ["podcast/feed.xml"],
            "deleted": [f"podcast/audio/{audio_path.name}"],
            "uploaded_count": 1,
            "deleted_count": 1,
            "remote_feed_url": "https://public.example.com/podcast/feed.xml",
            "container": "$web",
            "prefix": "podcast",
        }

    modules["publisher"].deploy_directory_to_azure_static = fake_deploy
    outputs = modules["publisher"].rebuild_publish_outputs_and_maybe_deploy(modules["config"].load_config(), deploy=True)

    assert calls == [str(Path(runtime_dir / "publish" / "current"))]
    assert outputs["deploy"]["deleted"] == [f"podcast/audio/{audio_path.name}"]


def test_create_app_startup_does_not_remote_deploy(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, deploy_enabled=True)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    modules["worker"].DummyWorker.start = lambda self: None

    def fail_deploy(*args, **kwargs):
        raise AssertionError("startup should not deploy")

    modules["publisher"].deploy_directory_to_azure_static = fail_deploy
    app = modules["app"].create_app()
    try:
        assert app.config["APP_CONFIG"]["publishing"]["deploy_enabled"] is True
    finally:
        app.config["WORKER"].stop()
