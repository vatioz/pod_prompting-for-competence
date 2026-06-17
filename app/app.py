from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

from .config import GENERATED_AUDIO_DIR, GENERATED_FEED_PATH, GENERATED_IMAGES_DIR, ensure_runtime_dirs, load_config
from .publisher import rebuild_publish_outputs, rebuild_publish_outputs_and_maybe_deploy
from .storage import create_topic, list_topics, retry_topic, unpublish_topic
from .worker import DummyWorker


POLL_INTERVAL_SECONDS = 5


def _audio_mimetype(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix == ".wav":
        return "audio/wav"
    return "application/octet-stream"


def _image_mimetype(file_path: Path) -> str:
    guessed, _ = mimetypes.guess_type(file_path.name)
    return guessed or "application/octet-stream"


def _publishing_status(config: dict, topics: list[dict]) -> dict:
    publishing = config.get("publishing", {})
    target = str(publishing.get("target") or "azure_static").strip().lower()
    auto_publish = bool(publishing.get("auto_publish"))
    deploy_enabled = bool(publishing.get("deploy_enabled"))
    public_base_url = str(publishing.get("public_base_url") or config["podcast"]["base_url"]).rstrip("/")
    effective_feed_url = f"{public_base_url}/feed.xml"
    connection_env = str(publishing.get("azure_connection_string_env") or "AZURE_STORAGE_CONNECTION_STRING").strip()
    connection_present = bool(os.environ.get(connection_env))
    azure_prefix = str(publishing.get("azure_path_prefix") or "").strip("/")
    azure_container = str(publishing.get("azure_container") or "$web").strip() or "$web"

    latest_publish_error = None
    for topic in reversed(topics):
        if topic.get("last_error"):
            latest_publish_error = topic["last_error"]
            break
        for variant in topic.get("variants", {}).values():
            publish = variant.get("publish") or {}
            if publish.get("error"):
                latest_publish_error = publish["error"]
                break
        if latest_publish_error:
            break

    if target == "azure_static":
        if not deploy_enabled:
            readiness = "Bundle only"
            readiness_tone = "warn"
            readiness_detail = "Azure upload is disabled, so publishing only rebuilds the local export bundle."
        elif not connection_present:
            readiness = "Blocked"
            readiness_tone = "danger"
            readiness_detail = f"Azure upload is enabled, but {connection_env} is missing in the app environment."
        else:
            readiness = "Ready"
            readiness_tone = "ok"
            readiness_detail = "Azure upload is enabled and the storage connection string is present."
    else:
        readiness = "App hosted"
        readiness_tone = "ok"
        readiness_detail = "Publishing updates the feed served directly by this app; no Azure upload is attempted."

    return {
        "target": target,
        "auto_publish": auto_publish,
        "deploy_enabled": deploy_enabled,
        "public_base_url": public_base_url,
        "effective_feed_url": effective_feed_url,
        "azure_container": azure_container,
        "azure_path_prefix": azure_prefix,
        "azure_connection_string_env": connection_env,
        "azure_connection_string_present": connection_present,
        "latest_publish_error": latest_publish_error,
        "readiness": readiness,
        "readiness_tone": readiness_tone,
        "readiness_detail": readiness_detail,
    }


def create_app() -> Flask:
    ensure_runtime_dirs()
    config = load_config()
    app = Flask(__name__)
    app.config["APP_CONFIG"] = config
    app.config["WORKER"] = DummyWorker(config)

    def _recent_topics() -> list[dict]:
        recent_limit = config["ui"]["recent_topics_limit"]
        return list_topics(limit=recent_limit)

    def _wants_async_response() -> bool:
        return request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _topics_fragment_response():
        return render_template("_topics_list.html", topics=_recent_topics())

    @app.get("/")
    def index():
        listener_profile = ""
        topics = _recent_topics()
        return render_template(
            "index.html",
            config=config,
            topics=topics,
            listener_profile=listener_profile,
            poll_interval_seconds=POLL_INTERVAL_SECONDS,
            publishing_status=_publishing_status(config, topics),
        )

    @app.get("/ui/topics")
    def topics_fragment():
        return _topics_fragment_response()

    @app.post("/submit")
    def submit_topic():
        prompt = request.form.get("prompt", "")
        overview = request.form.get("variant_overview") == "on"
        deep_dive = request.form.get("variant_deep_dive") == "on"
        script_steering = request.form.get("script_steering", "")
        create_topic(prompt=prompt, overview=overview, deep_dive=deep_dive, script_steering=script_steering)
        app.config["WORKER"].wake()
        if _wants_async_response():
            return ("", 204)
        return redirect(url_for("index"))

    @app.post("/topics/<topic_id>/retry")
    def retry_topic_route(topic_id: str):
        updated = retry_topic(topic_id)
        if not updated:
            abort(404)
        app.config["WORKER"].wake()
        if _wants_async_response():
            return ("", 204)
        return redirect(url_for("index"))

    @app.post("/topics/<topic_id>/unpublish")
    def unpublish_topic_route(topic_id: str):
        updated = unpublish_topic(topic_id)
        if not updated:
            abort(404)
        rebuild_publish_outputs_and_maybe_deploy(config, deploy=True)
        if _wants_async_response():
            return ("", 204)
        return redirect(url_for("index"))

    @app.get("/feed.xml")
    def generated_feed():
        if not GENERATED_FEED_PATH.exists():
            rebuild_publish_outputs(config)
        return send_file(GENERATED_FEED_PATH, mimetype="application/rss+xml")

    def _send_audio(filename: str):
        file_path = GENERATED_AUDIO_DIR / Path(filename).name
        if not file_path.exists():
            abort(404)
        return send_file(file_path, mimetype=_audio_mimetype(file_path))

    @app.get("/audio/<path:filename>")
    def audio(filename: str):
        return _send_audio(filename)

    @app.get("/images/<path:filename>")
    def image(filename: str):
        file_path = GENERATED_IMAGES_DIR / Path(filename).name
        if not file_path.exists():
            abort(404)
        return send_file(file_path, mimetype=_image_mimetype(file_path))

    worker = app.config["WORKER"]
    worker.start()
    rebuild_publish_outputs(config)
    return app
