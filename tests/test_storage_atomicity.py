from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _reload_storage():
    import app.config as config
    import app.storage as storage

    importlib.reload(config)
    importlib.reload(storage)
    return storage


def test_save_state_preserves_existing_file_when_dump_fails(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    topics_path = runtime_dir / "data" / "topics.yaml"
    topics_path.parent.mkdir(parents=True, exist_ok=True)

    original_text = "topics:\n  - id: existing\n    prompt: Keep this intact\n"
    topics_path.write_text(original_text, encoding="utf-8")
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    storage = _reload_storage()
    def flaky_dump(data, handle, *args, **kwargs):
        handle.write("topics:\n  - broken: [\n")
        raise RuntimeError("simulated yaml write failure")

    monkeypatch.setattr(storage.yaml, "safe_dump", flaky_dump)

    with pytest.raises(RuntimeError, match="simulated yaml write failure"):
        storage.save_state({"topics": [{"id": "new-topic", "prompt": "new"}]})

    assert topics_path.read_text(encoding="utf-8") == original_text
    assert not list(topics_path.parent.glob("*.tmp"))


def test_save_state_writes_valid_yaml_without_leaving_temp_files(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
    storage = _reload_storage()

    storage.save_state({"topics": [{"id": "topic-1", "prompt": "Atomic writes"}]})

    topics_path = runtime_dir / "data" / "topics.yaml"
    saved = yaml.safe_load(topics_path.read_text(encoding="utf-8"))

    assert saved["topics"][0]["id"] == "topic-1"
    assert not list(topics_path.parent.glob("*.tmp"))
