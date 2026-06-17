from __future__ import annotations

from pathlib import Path

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
