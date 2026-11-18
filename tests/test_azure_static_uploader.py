from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app import azure_static_uploader


class FakeBlob:
    def __init__(self, name: str):
        self.name = name


class FakeContainerClient:
    def __init__(self, existing=None):
        self.existing = set(existing or [])
        self.uploads = []
        self.deleted = []

    def upload_blob(self, name, data, overwrite, content_settings):
        self.uploads.append(
            {
                "name": name,
                "payload": data.read(),
                "overwrite": overwrite,
                "content_settings": content_settings,
            }
        )
        self.existing.add(name)

    def list_blobs(self, name_starts_with=None):
        for name in sorted(self.existing):
            if not name_starts_with or name.startswith(name_starts_with):
                yield FakeBlob(name)

    def delete_blob(self, name):
        self.deleted.append(name)
        self.existing.discard(name)


def _make_bundle(tmp_path: Path) -> Path:
    bundle_dir = tmp_path / "bundle"
    (bundle_dir / "audio").mkdir(parents=True, exist_ok=True)
    (bundle_dir / "feed.xml").write_text("<rss />\n", encoding="utf-8")
    (bundle_dir / "audio" / "001_test.mp3").write_bytes(b"ID3test")
    return bundle_dir


def test_missing_connection_string_env_fails_clearly(tmp_path, monkeypatch):
    bundle_dir = _make_bundle(tmp_path)
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)

    with pytest.raises(RuntimeError, match="AZURE_STORAGE_CONNECTION_STRING"):
        azure_static_uploader.deploy_directory_to_azure_static(
            bundle_dir,
            {
                "public_base_url": "https://public.example.com/podcast",
                "azure_path_prefix": "podcast",
                "azure_connection_string_env": "AZURE_STORAGE_CONNECTION_STRING",
            },
        )


def test_deploy_maps_files_under_prefix_and_sets_feed_url(tmp_path, monkeypatch):
    bundle_dir = _make_bundle(tmp_path)
    fake_client = FakeContainerClient()
    monkeypatch.setattr(azure_static_uploader, "_build_container_client", lambda config: fake_client)

    result = azure_static_uploader.deploy_directory_to_azure_static(
        bundle_dir,
        {
            "public_base_url": "https://public.example.com/podcast",
            "azure_path_prefix": "podcast",
            "azure_delete_stale": True,
        },
    )

    uploaded_names = [item["name"] for item in fake_client.uploads]
    assert uploaded_names == ["podcast/audio/001_test.mp3", "podcast/feed.xml"]
    assert result["remote_feed_url"] == "https://public.example.com/podcast/feed.xml"
    assert result["uploaded_count"] == 2
    assert fake_client.deleted == []

    feed_settings = fake_client.uploads[1]["content_settings"]
    audio_settings = fake_client.uploads[0]["content_settings"]
    assert feed_settings["content_type"] == "application/rss+xml"
    assert "no-cache" in feed_settings["cache_control"]
    assert audio_settings["content_type"] == "audio/mpeg"
    assert "immutable" in audio_settings["cache_control"]


def test_stale_delete_only_touches_managed_prefix(tmp_path, monkeypatch):
    bundle_dir = _make_bundle(tmp_path)
    fake_client = FakeContainerClient(existing={"podcast/audio/obsolete.mp3", "site/index.html"})
    monkeypatch.setattr(azure_static_uploader, "_build_container_client", lambda config: fake_client)

    result = azure_static_uploader.deploy_directory_to_azure_static(
        bundle_dir,
        {
            "public_base_url": "https://public.example.com/podcast",
            "azure_path_prefix": "podcast",
            "azure_delete_stale": True,
        },
    )

    assert result["deleted"] == ["podcast/audio/obsolete.mp3"]
    assert fake_client.deleted == ["podcast/audio/obsolete.mp3"]
    assert "site/index.html" in fake_client.existing


def test_refuses_root_scope_stale_delete_without_override(tmp_path, monkeypatch):
    bundle_dir = _make_bundle(tmp_path)
    fake_client = FakeContainerClient()
    monkeypatch.setattr(azure_static_uploader, "_build_container_client", lambda config: fake_client)

    with pytest.raises(RuntimeError, match="Refusing Azure stale-delete"):
        azure_static_uploader.deploy_directory_to_azure_static(
            bundle_dir,
            {
                "public_base_url": "https://public.example.com",
                "azure_path_prefix": "",
                "azure_delete_stale": True,
                "azure_allow_root_delete": False,
            },
        )


@pytest.mark.parametrize("bundle_kind", ["missing", "file", "empty"])
def test_deployment_requires_nonempty_directory(tmp_path, monkeypatch, bundle_kind):
    bundle = tmp_path / "bundle"
    if bundle_kind == "file":
        bundle.write_text("not a directory", encoding="utf-8")
    elif bundle_kind == "empty":
        bundle.mkdir()
    monkeypatch.setattr(azure_static_uploader, "_build_container_client", lambda config: FakeContainerClient())
    with pytest.raises(RuntimeError, match="empty" if bundle_kind == "empty" else "does not exist"):
        azure_static_uploader.deploy_directory_to_azure_static(bundle, {
            "public_base_url": "https://example.com/pod", "azure_path_prefix": "pod",
        })


@pytest.mark.parametrize("public_url,message", [("", "public_base_url is required"), ("https://example.com/other", "same path suffix")])
def test_deployment_rejects_invalid_public_url_before_connecting(tmp_path, monkeypatch, public_url, message):
    monkeypatch.setattr(azure_static_uploader, "_build_container_client", lambda config: pytest.fail("invalid URL connected"))
    with pytest.raises(RuntimeError, match=message):
        azure_static_uploader.deploy_directory_to_azure_static(_make_bundle(tmp_path), {
            "public_base_url": public_url, "azure_path_prefix": "pod",
        })


def test_container_client_rejects_unsupported_credentials():
    with pytest.raises(RuntimeError, match="Unsupported Azure credential mode: managed_identity"):
        azure_static_uploader._build_container_client({"azure_credential_mode": "managed_identity"})


def test_container_client_missing_sdk_preserves_import_cause(monkeypatch):
    monkeypatch.setenv("UNIT_STORAGE_CONNECTION", "unit-connection")
    monkeypatch.setitem(sys.modules, "azure.storage.blob", None)
    with pytest.raises(RuntimeError, match="azure-storage-blob is required") as exc:
        azure_static_uploader._build_container_client({"azure_connection_string_env": "UNIT_STORAGE_CONNECTION"})
    assert isinstance(exc.value.__cause__, ImportError)


def test_container_client_uses_connection_string_and_sdk_content_settings(monkeypatch):
    monkeypatch.setenv("UNIT_STORAGE_CONNECTION", "unit-connection")
    calls = []
    client = FakeContainerClient()

    class Service:
        @staticmethod
        def from_connection_string(connection):
            calls.append(connection)
            return Service()

        def get_container_client(self, name):
            calls.append(name)
            return client

    monkeypatch.setitem(azure_static_uploader.__dict__, "ContentSettings", None)
    monkeypatch.setitem(sys.modules, "azure.storage.blob", SimpleNamespace(BlobServiceClient=Service, ContentSettings=SimpleNamespace))
    assert azure_static_uploader._build_container_client({
        "azure_connection_string_env": "UNIT_STORAGE_CONNECTION", "azure_container": "$web",
    }) is client
    settings = azure_static_uploader._content_settings_for_path("image.png")
    assert settings.content_type == "image/png"
    assert settings.cache_control == "public, max-age=300"
    assert calls == ["unit-connection", "$web"]


@pytest.mark.parametrize("allow_delete", [False, True])
def test_root_upload_and_explicit_root_deletion(tmp_path, monkeypatch, allow_delete):
    client = FakeContainerClient(existing={"old.mp3"})
    monkeypatch.setattr(azure_static_uploader, "_build_container_client", lambda config: client)
    result = azure_static_uploader.deploy_directory_to_azure_static(_make_bundle(tmp_path), {
        "public_base_url": "https://example.com/", "azure_delete_stale": allow_delete,
        "azure_allow_root_delete": allow_delete,
    })
    assert result["uploaded"] == ["audio/001_test.mp3", "feed.xml"]
    assert result["deleted"] == (["old.mp3"] if allow_delete else [])
    assert result["remote_feed_url"] == "https://example.com/feed.xml"


def test_blob_listing_supports_dictionary_entries_and_rejects_unknown_entries():
    assert azure_static_uploader._blob_name({"name": "pod/file.xml"}) == "pod/file.xml"
    with pytest.raises(RuntimeError, match="Unexpected blob listing entry"):
        azure_static_uploader._blob_name({"unexpected": "value"})


def test_unknown_file_upload_uses_safe_content_defaults(tmp_path, monkeypatch):
    bundle = _make_bundle(tmp_path)
    (bundle / "opaque.unknown-unit-extension").write_bytes(b"data")
    client = FakeContainerClient()
    monkeypatch.setattr(azure_static_uploader, "_build_container_client", lambda config: client)
    azure_static_uploader.deploy_directory_to_azure_static(bundle, {
        "public_base_url": "https://example.com/pod", "azure_path_prefix": "pod",
    })
    assert client.uploads[-1]["content_settings"] == {
        "content_type": "application/octet-stream", "cache_control": "public, max-age=300",
    }
