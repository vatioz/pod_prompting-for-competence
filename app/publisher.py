from __future__ import annotations

import logging
from pathlib import Path
import shutil

from .azure_static_uploader import deploy_directory_to_azure_static
from .config import GENERATED_FEED_PATH, GENERATED_IMAGES_DIR, podcast_artwork_publish_name, resolve_podcast_artwork_source
from .feedgen import regenerate_feed
from .storage import load_state, recompute_topic_status, save_state, utc_now_iso


logger = logging.getLogger(__name__)

EXPORT_TARGETS = {"azure_static", "local_export", "export_bundle", "manual_export"}
APP_HOSTED_TARGETS = {"app_hosted", "local_app", "preview_app"}


def _publishing_target(config: dict) -> str:
    return str(config.get("publishing", {}).get("target") or "azure_static").strip().lower()


def _public_base_url(config: dict) -> str:
    publishing = config.get("publishing", {})
    configured = str(publishing.get("public_base_url") or "").strip()
    if configured:
        return configured.rstrip("/")
    return str(config["podcast"]["base_url"]).rstrip("/")


def _deploy_enabled(config: dict) -> bool:
    return bool(config.get("publishing", {}).get("deploy_enabled"))


def _should_remote_deploy(config: dict) -> bool:
    return _publishing_target(config) == "azure_static" and _deploy_enabled(config)


def _bundle_dir(config: dict) -> Path:
    export_root = Path(config.get("publishing", {}).get("export_dir") or GENERATED_FEED_PATH.parent.parent / "publish")
    return export_root.expanduser().resolve() / "current"


def _sync_show_artwork(config: dict, target_images_dir: Path) -> dict | None:
    artwork = config.get("podcast", {}).get("artwork", {})
    explicit_public_url = str(artwork.get("public_url") or "").strip()
    if explicit_public_url:
        return {"mode": "external", "public_url": explicit_public_url}
    source = resolve_podcast_artwork_source(config)
    if not source:
        return None
    if not source.exists():
        message = f"Configured podcast artwork file does not exist: {source}"
        logger.warning(message)
        return {"mode": "missing", "error": message}
    target_images_dir.mkdir(parents=True, exist_ok=True)
    target_name = podcast_artwork_publish_name(config)
    for existing in target_images_dir.glob('podcast-cover.*'):
        if existing.name != target_name:
            existing.unlink()
    destination = target_images_dir / target_name
    shutil.copyfile(source, destination)
    return {"mode": "local", "published_path": str(destination), "filename": target_name}


def _iter_publishable_audio(state: dict):
    for topic in state["topics"]:
        if topic.get("deleted"):
            continue
        for variant_name, variant in topic["variants"].items():
            if not variant.get("enabled"):
                continue
            publish = variant.get("publish") or {}
            if publish.get("status") != "done":
                continue
            audio_path = (variant.get("audio") or {}).get("path") or variant.get("audio_path")
            if not audio_path:
                continue
            audio_file = Path(audio_path)
            if not audio_file.exists():
                continue
            yield topic, variant_name, variant, audio_file


def rebuild_publish_outputs(config: dict, *, state: dict | None = None) -> dict:
    state = state or load_state()
    target = _publishing_target(config)
    item_rows = list(_iter_publishable_audio(state))
    if target in EXPORT_TARGETS:
        bundle_dir = _bundle_dir(config)
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        audio_dir = bundle_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        artwork_info = _sync_show_artwork(config, bundle_dir / "images")
        for _, _, _, audio_file in item_rows:
            shutil.copyfile(audio_file, audio_dir / audio_file.name)
        base_url = _public_base_url(config)
        feed_path = regenerate_feed(base_url, config["podcast"], state=state, output_path=bundle_dir / "feed.xml")
        regenerate_feed(base_url, config["podcast"], state=state, output_path=GENERATED_FEED_PATH)
        return {
            "target": target,
            "bundle_dir": str(bundle_dir),
            "feed_path": str(feed_path),
            "item_count": len(item_rows),
            "artwork": artwork_info,
        }
    if target in APP_HOSTED_TARGETS:
        base_url = str(config["podcast"]["base_url"]).rstrip("/")
        artwork_info = _sync_show_artwork(config, GENERATED_IMAGES_DIR)
        feed_path = regenerate_feed(base_url, config["podcast"], state=state, output_path=GENERATED_FEED_PATH)
        return {
            "target": target,
            "bundle_dir": None,
            "feed_path": str(feed_path),
            "item_count": len(item_rows),
            "artwork": artwork_info,
        }
    raise RuntimeError(f"Unsupported publishing target: {target}")


def deploy_publish_bundle(config: dict, bundle_info: dict) -> dict:
    if not bundle_info.get("bundle_dir"):
        raise RuntimeError("Azure static deployment requires a local publish bundle directory")
    deployment = deploy_directory_to_azure_static(
        bundle_dir=Path(bundle_info["bundle_dir"]),
        publishing_config=config.get("publishing", {}),
    )
    return {"deployed": True, **deployment}


def rebuild_publish_outputs_and_maybe_deploy(config: dict, *, state: dict | None = None, deploy: bool = True) -> dict:
    outputs = rebuild_publish_outputs(config, state=state)
    if deploy and _should_remote_deploy(config):
        outputs["deploy"] = deploy_publish_bundle(config, outputs)
        outputs["remote_feed_url"] = outputs["deploy"]["remote_feed_url"]
    else:
        outputs["deploy"] = {"deployed": False}
    return outputs


def publish_topic_variant(topic_id: str, variant_name: str, config: dict) -> dict:
    state = load_state()
    try:
        return publish_topic_variant_in_state(state=state, topic_id=topic_id, variant_name=variant_name, config=config)
    finally:
        save_state(state)


def publish_topic_variant_in_state(*, state: dict, topic_id: str, variant_name: str, config: dict) -> dict:
    topic = next(item for item in state["topics"] if item["id"] == topic_id)
    variant = topic["variants"][variant_name]
    if not variant.get("enabled"):
        raise RuntimeError(f"Cannot publish disabled variant: {variant_name}")
    audio_path = (variant.get("audio") or {}).get("path") or variant.get("audio_path")
    if not audio_path:
        raise RuntimeError(f"Cannot publish {variant_name} before audio is generated")
    audio_file = Path(audio_path)
    if not audio_file.exists():
        raise RuntimeError(f"Cannot publish missing audio file: {audio_file}")

    target = _publishing_target(config)
    publish = variant.setdefault("publish", {})
    publish["status"] = "processing"
    publish["public_url"] = None
    publish["completed_at"] = None
    publish["error"] = None
    topic["updated_at"] = utc_now_iso()

    try:
        base_url = _public_base_url(config) if target in EXPORT_TARGETS else str(config["podcast"]["base_url"]).rstrip("/")
        publish["public_url"] = f"{base_url}/audio/{audio_file.name}"
        publish["completed_at"] = utc_now_iso()
        publish["status"] = "done"
        publish["error"] = None
        variant["status"] = "published" if target in APP_HOSTED_TARGETS else "exported"
        variant.setdefault("audio", {})["status"] = "done"
        topic["last_error"] = None
        topic["status"] = recompute_topic_status(topic)
        topic["updated_at"] = utc_now_iso()
        outputs = rebuild_publish_outputs_and_maybe_deploy(config, state=state, deploy=True)
        outputs["public_url"] = publish["public_url"]
        return outputs
    except Exception as exc:
        publish["status"] = "failed"
        publish["public_url"] = None
        publish["completed_at"] = None
        publish["error"] = str(exc)
        variant["status"] = "failed"
        topic["status"] = "failed"
        topic["last_error"] = str(exc)
        topic["updated_at"] = utc_now_iso()
        raise
