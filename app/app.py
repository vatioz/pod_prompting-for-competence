from __future__ import annotations

import mimetypes
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for

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

    def _render_index(*, validation_error: str | None = None, form_values: dict | None = None, status_code: int = 200):
        defaults = {
            "prompt": "",
            "script_steering": "",
            "variant_overview": True,
            "variant_deep_dive": False,
        }
        if form_values:
            defaults.update(form_values)
        return (
            render_template(
                "index.html",
                config=config,
                poll_interval_seconds=POLL_INTERVAL_SECONDS,
                topics=_recent_topics(),
                validation_error=validation_error,
                form_values=defaults,
            ),
            status_code,
        )

    @app.get("/")
    def index():
        return _render_index()

    @app.get("/ui/topics")
    def topics_fragment():
        return _topics_fragment_response()

    @app.post("/submit")
    def submit_topic():
        prompt = request.form.get("prompt", "")
        overview = request.form.get("variant_overview") == "on"
        deep_dive = request.form.get("variant_deep_dive") == "on"
        script_steering = request.form.get("script_steering", "")

        try:
            create_topic(prompt=prompt, overview=overview, deep_dive=deep_dive, script_steering=script_steering)
        except ValueError as exc:
            message = str(exc)
            if _wants_async_response():
                return jsonify({"error": message}), 422
            return _render_index(
                validation_error=message,
                form_values={
                    "prompt": prompt,
                    "script_steering": script_steering,
                    "variant_overview": overview,
                    "variant_deep_dive": deep_dive,
                },
                status_code=422,
            )

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
