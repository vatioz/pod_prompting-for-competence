from __future__ import annotations

import importlib
from pathlib import Path


def _write_runtime_fixture(runtime_dir: Path, *, target: str = "azure_static", public_url: str = "") -> None:
    (runtime_dir / "config" / "assets").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "data").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "generated" / "audio").mkdir(parents=True, exist_ok=True)
    export_dir = runtime_dir / "publish"
    lines = [
        "podcast:",
        "  title: Prompting for Competence",
        "  description: Personal learning podcast feed generated from queued topics.",
        "  author: vatioz",
        "  base_url: https://pod.example.com",
        "  language: en-us",
        "  artwork:",
        "    source_path: config/assets/show-cover.png",
        f"    public_url: {public_url}",
        '    alt_text: "Podcast cover"',
        "worker:",
        "  poll_seconds: 1",
        "research:",
        "  provider: azure_foundry",
        "script:",
        "  provider: azure_foundry",
        "tts:",
        "  provider: elevenlabs",
        "publishing:",
        f"  target: {target}",
        "  public_base_url: https://public.example.com/podcast",
        f"  export_dir: {export_dir}",
        "  auto_publish: false",
        "ui:",
        "  recent_topics_limit: 12",
        "",
    ]
    (runtime_dir / "config" / "podcast.yaml").write_text("\n".join(lines), encoding="utf-8")
    (runtime_dir / "config" / "assets" / "show-cover.png").write_bytes(b"\x89PNGtest-image")
    (runtime_dir / "data" / "topics.yaml").write_text("topics: []\n", encoding="utf-8")


def _reload_modules():
    import app.app as app_module
    import app.config as config
    import app.feedgen as feedgen
    import app.publisher as publisher

    modules = [config, feedgen, publisher, app_module]
    for module in modules:
        importlib.reload(module)
    return {
        "app": app_module,
        "config": config,
        "feedgen": feedgen,
        "publisher": publisher,
    }


def test_export_bundle_includes_show_art_and_feed_tags(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, target="azure_static")
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    config = modules["config"]
    publisher = modules["publisher"]

    result = publisher.rebuild_publish_outputs(config.load_config())
    bundle_dir = Path(result["bundle_dir"])
    image_path = bundle_dir / "images" / "podcast-cover.png"
    feed_text = (bundle_dir / "feed.xml").read_text(encoding="utf-8")

    assert image_path.exists()
    assert image_path.read_bytes() == b"\x89PNGtest-image"
    assert 'itunes:image href="https://public.example.com/podcast/images/podcast-cover.png"' in feed_text
    assert '<image>' in feed_text
    assert '<url>https://public.example.com/podcast/images/podcast-cover.png</url>' in feed_text


def test_app_hosted_serves_local_show_art(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, target="app_hosted")
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    modules["app"].DummyWorker.start = lambda self: None
    app = modules["app"].create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    try:
        response = client.get("/images/podcast-cover.png")
        feed_text = client.get("/feed.xml").get_data(as_text=True)
    finally:
        app.config["WORKER"].stop()

    assert response.status_code == 200
    assert response.data == b"\x89PNGtest-image"
    assert response.mimetype == "image/png"
    assert 'itunes:image href="https://pod.example.com/images/podcast-cover.png"' in feed_text


def test_external_show_art_url_does_not_require_local_copy(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, target="azure_static", public_url="https://cdn.example.com/podcast-cover.png")
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    config = modules["config"]
    publisher = modules["publisher"]

    result = publisher.rebuild_publish_outputs(config.load_config())
    bundle_dir = Path(result["bundle_dir"])
    feed_text = (bundle_dir / "feed.xml").read_text(encoding="utf-8")

    assert not (bundle_dir / "images" / "podcast-cover.png").exists()
    assert 'itunes:image href="https://cdn.example.com/podcast-cover.png"' in feed_text


def test_missing_local_show_art_does_not_crash_or_emit_broken_feed_image(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, target="app_hosted")
    (runtime_dir / "config" / "assets" / "show-cover.png").unlink()
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    modules["app"].DummyWorker.start = lambda self: None
    app = modules["app"].create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    try:
        feed_text = client.get("/feed.xml").get_data(as_text=True)
        image_response = client.get("/images/podcast-cover.png")
    finally:
        app.config["WORKER"].stop()

    assert 'itunes:image href=' not in feed_text
    assert image_response.status_code == 404
