from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

from .config import normalize_publish_path_prefix


def deploy_directory_to_azure_static(bundle_dir: Path, publishing_config: dict) -> dict:
    bundle_path = Path(bundle_dir).expanduser().resolve()
    if not bundle_path.exists() or not bundle_path.is_dir():
        raise RuntimeError(f"Azure deploy bundle directory does not exist: {bundle_path}")

    normalized = _normalize_publishing_config(publishing_config)
    prefix = normalized["azure_path_prefix"]
    if normalized["azure_delete_stale"] and not prefix and not normalized["azure_allow_root_delete"]:
        raise RuntimeError(
            "Refusing Azure stale-delete at the root of $web. Set publishing.azure_path_prefix or enable azure_allow_root_delete."
        )
    _validate_public_base_url(normalized["public_base_url"], prefix)

    container_client = _build_container_client(normalized)
    local_files = _collect_local_files(bundle_path)

    uploaded: list[str] = []
    for relative_path, local_path in local_files.items():
        blob_name = _blob_name_for_relative_path(relative_path, prefix)
        with local_path.open("rb") as handle:
            container_client.upload_blob(
                name=blob_name,
                data=handle,
                overwrite=True,
                content_settings=_content_settings_for_path(relative_path),
            )
        uploaded.append(blob_name)

    deleted: list[str] = []
    if normalized["azure_delete_stale"]:
        managed_prefix = f"{prefix}/" if prefix else None
        existing = {_blob_name(blob) for blob in container_client.list_blobs(name_starts_with=managed_prefix)}
        desired = set(uploaded)
        for blob_name in sorted(existing - desired):
            container_client.delete_blob(blob_name)
            deleted.append(blob_name)

    remote_feed_url = _public_url(normalized["public_base_url"], "feed.xml")
    return {
        "uploaded": uploaded,
        "deleted": deleted,
        "uploaded_count": len(uploaded),
        "deleted_count": len(deleted),
        "remote_feed_url": remote_feed_url,
        "container": normalized["azure_container"],
        "prefix": prefix,
    }


def _normalize_publishing_config(publishing_config: dict) -> dict:
    normalized = dict(publishing_config or {})
    normalized["public_base_url"] = str(normalized.get("public_base_url") or "").strip().rstrip("/")
    normalized["azure_container"] = str(normalized.get("azure_container") or "$web").strip() or "$web"
    normalized["azure_path_prefix"] = normalize_publish_path_prefix(normalized.get("azure_path_prefix"))
    normalized["azure_delete_stale"] = bool(normalized.get("azure_delete_stale", True))
    normalized["azure_allow_root_delete"] = bool(normalized.get("azure_allow_root_delete"))
    normalized["azure_credential_mode"] = str(normalized.get("azure_credential_mode") or "connection_string").strip().lower()
    normalized["azure_connection_string_env"] = str(
        normalized.get("azure_connection_string_env") or "AZURE_STORAGE_CONNECTION_STRING"
    ).strip() or "AZURE_STORAGE_CONNECTION_STRING"
    normalized["azure_account_url"] = str(normalized.get("azure_account_url") or "").strip().rstrip("/")
    return normalized


def _build_container_client(publishing_config: dict):
    credential_mode = publishing_config.get("azure_credential_mode") or "connection_string"
    if credential_mode != "connection_string":
        raise RuntimeError(f"Unsupported Azure credential mode: {credential_mode}")

    env_name = publishing_config["azure_connection_string_env"]
    connection_string = os.environ.get(env_name)
    if not connection_string:
        raise RuntimeError(
            f"Azure static publishing requires environment variable {env_name} to be set with a storage connection string."
        )

    try:
        from azure.storage.blob import BlobServiceClient, ContentSettings
    except ImportError as exc:  # pragma: no cover - import failure depends on environment
        raise RuntimeError(
            "azure-storage-blob is required for Azure static publishing. Install dependencies from requirements.txt."
        ) from exc

    globals()["ContentSettings"] = ContentSettings
    service_client = BlobServiceClient.from_connection_string(connection_string)
    return service_client.get_container_client(publishing_config["azure_container"])


def _collect_local_files(bundle_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(bundle_dir.rglob("*")):
        if path.is_file():
            files[path.relative_to(bundle_dir).as_posix()] = path
    if not files:
        raise RuntimeError(f"Azure deploy bundle directory is empty: {bundle_dir}")
    return files


def _blob_name_for_relative_path(relative_path: str, prefix: str) -> str:
    relative = relative_path.strip("/")
    return f"{prefix}/{relative}" if prefix else relative


def _content_settings_for_path(relative_path: str):
    cache_control = _cache_control_for_path(relative_path)
    content_type = _content_type_for_path(relative_path)
    content_settings_cls = globals().get("ContentSettings")
    if content_settings_cls is None:
        return {"content_type": content_type, "cache_control": cache_control}
    return content_settings_cls(content_type=content_type, cache_control=cache_control)


def _content_type_for_path(relative_path: str) -> str:
    normalized = relative_path.lower()
    if normalized == "feed.xml":
        return "application/rss+xml"
    if normalized.endswith(".mp3"):
        return "audio/mpeg"
    guessed, _ = mimetypes.guess_type(relative_path)
    return guessed or "application/octet-stream"


def _cache_control_for_path(relative_path: str) -> str:
    normalized = relative_path.lower()
    if normalized == "feed.xml":
        return "no-cache, no-store, must-revalidate"
    if normalized.endswith(".mp3"):
        return "public, max-age=31536000, immutable"
    return "public, max-age=300"


def _blob_name(blob) -> str:
    if hasattr(blob, "name"):
        return blob.name
    if isinstance(blob, dict) and "name" in blob:
        return str(blob["name"])
    raise RuntimeError(f"Unexpected blob listing entry: {blob!r}")


def _validate_public_base_url(public_base_url: str, prefix: str) -> None:
    if not public_base_url:
        raise RuntimeError("publishing.public_base_url is required for Azure static publishing")
    if not prefix:
        return
    parsed = urlparse(public_base_url)
    path = parsed.path.strip("/")
    if path != prefix:
        raise RuntimeError(
            "publishing.public_base_url must include the same path suffix as publishing.azure_path_prefix "
            f"(expected '/{prefix}', got '{parsed.path or '/'}')."
        )


def _public_url(base_url: str, relative_path: str) -> str:
    return f"{base_url.rstrip('/')}/{relative_path.lstrip('/')}"
