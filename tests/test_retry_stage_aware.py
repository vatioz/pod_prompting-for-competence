from __future__ import annotations

import importlib
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _write_runtime_fixture(runtime_dir: Path) -> None:
    (runtime_dir / "config" / "prompts").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "data").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "generated").mkdir(parents=True, exist_ok=True)
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


def _reload_storage():
    import app.config as config
    import app.storage as storage

    importlib.reload(config)
    importlib.reload(storage)
    return storage


def _seed_topic(storage, *, deep_dive: bool = True):
    return storage.create_topic(prompt="Retry semantics", overview=True, deep_dive=deep_dive)


def test_retry_publish_failure_only_requeues_publish_stage(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
    storage = _reload_storage()

    topic = _seed_topic(storage)
    script_path = f"/tmp/{topic['id']}-overview-script.md"
    audio_path = f"/tmp/{topic['id']}-overview-audio.mp3"
    sibling_audio_path = f"/tmp/{topic['id']}-deep-dive-audio.mp3"

    def apply(item: dict) -> None:
        item["status"] = "failed"
        item["last_error"] = "publish failed"
        item["research"]["status"] = "done"
        item["research"]["path"] = f"/tmp/{item['id']}-research.md"
        item["research"]["error"] = None

        overview = item["variants"]["overview"]
        overview["status"] = "failed"
        overview["script_path"] = script_path
        overview["audio_path"] = audio_path
        overview["published_title"] = "Episode 001 — Retry semantics — Overview"
        overview["script"].update({"status": "done", "path": script_path, "error": None})
        overview["audio"].update({"status": "done", "path": audio_path, "error": None})
        overview["publish"].update(
            {
                "status": "failed",
                "public_url": None,
                "completed_at": None,
                "error": "Azure deploy failed",
            }
        )

        deep_dive = item["variants"]["deep_dive"]
        deep_dive["status"] = "generated"
        deep_dive["script_path"] = f"/tmp/{item['id']}-deep-dive-script.md"
        deep_dive["audio_path"] = sibling_audio_path
        deep_dive["script"].update({"status": "done", "path": deep_dive["script_path"], "error": None})
        deep_dive["audio"].update({"status": "done", "path": sibling_audio_path, "error": None})
        deep_dive["publish"].update({"status": "queued", "public_url": None, "completed_at": None, "error": None})

    storage.update_topic(topic["id"], apply)
    updated = storage.retry_topic(topic["id"])

    overview = updated["variants"]["overview"]
    deep_dive = updated["variants"]["deep_dive"]

    assert updated["last_error"] is None
    assert updated["research"]["status"] == "done"
    assert overview["status"] == "generated"
    assert overview["script_path"] == script_path
    assert overview["audio_path"] == audio_path
    assert overview["script"]["status"] == "done"
    assert overview["audio"]["status"] == "done"
    assert overview["publish"]["status"] == "queued"
    assert overview["publish"]["error"] is None

    assert deep_dive["status"] == "generated"
    assert deep_dive["audio_path"] == sibling_audio_path


def test_retry_audio_failure_requeues_audio_and_publish_only(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
    storage = _reload_storage()

    topic = _seed_topic(storage, deep_dive=False)
    script_path = f"/tmp/{topic['id']}-overview-script.md"

    def apply(item: dict) -> None:
        item["status"] = "failed"
        item["last_error"] = "audio failed"
        item["research"]["status"] = "done"
        item["research"]["path"] = f"/tmp/{item['id']}-research.md"
        overview = item["variants"]["overview"]
        overview["status"] = "failed"
        overview["script_path"] = script_path
        overview["audio_path"] = f"/tmp/{item['id']}-overview-audio.mp3"
        overview["script"].update({"status": "done", "path": script_path, "error": None})
        overview["audio"].update({"status": "failed", "path": overview["audio_path"], "error": "tts timeout"})
        overview["publish"].update({"status": "queued", "public_url": None, "completed_at": None, "error": None})

    storage.update_topic(topic["id"], apply)
    updated = storage.retry_topic(topic["id"])

    overview = updated["variants"]["overview"]
    assert overview["status"] == "queued"
    assert overview["script_path"] == script_path
    assert overview["script"]["status"] == "done"
    assert overview["audio_path"] is None
    assert overview["audio"]["status"] == "queued"
    assert overview["audio"]["error"] is None
    assert overview["publish"]["status"] == "queued"
    assert overview["publish"]["error"] is None


def test_retry_research_failure_requeues_all_downstream_stages(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir)
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
    storage = _reload_storage()

    topic = _seed_topic(storage)

    def apply(item: dict) -> None:
        item["status"] = "failed"
        item["last_error"] = "research failed"
        item["research"].update({"status": "failed", "path": "/tmp/research.md", "error": "rate limit"})
        for variant in item["variants"].values():
            if not variant["enabled"]:
                continue
            variant["status"] = "failed"
            variant["script_path"] = "/tmp/script.md"
            variant["audio_path"] = "/tmp/audio.mp3"
            variant["script"].update({"status": "done", "path": "/tmp/script.md", "error": None})
            variant["audio"].update({"status": "done", "path": "/tmp/audio.mp3", "error": None})
            variant["publish"].update({"status": "queued", "public_url": None, "completed_at": None, "error": None})

    storage.update_topic(topic["id"], apply)
    updated = storage.retry_topic(topic["id"])

    assert updated["last_error"] is None
    assert updated["research"]["status"] == "queued"
    assert updated["research"]["path"] is None
    assert updated["research"]["error"] is None

    for variant in updated["variants"].values():
        if not variant["enabled"]:
            continue
        assert variant["status"] == "queued"
        assert variant["script_path"] is None
        assert variant["audio_path"] is None
        assert variant["script"]["status"] == "queued"
        assert variant["audio"]["status"] == "queued"
        assert variant["publish"]["status"] == "queued"
