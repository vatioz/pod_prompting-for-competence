from pathlib import Path
import runpy
import sys

import pytest


@pytest.mark.parametrize("run_name,root_in_path", [("unit_entrypoint", True), ("__main__", False)])
def test_entrypoint_creates_app_and_only_serves_when_run_as_main(monkeypatch, capsys, run_name, root_in_path):
    import app
    from app import config
    import waitress

    root = Path(__file__).resolve().parent.parent
    fake_app = object()
    creates, serves = [], []

    def create():
        creates.append(True)
        return fake_app

    monkeypatch.setattr(app, "create_app", create)
    monkeypatch.setattr(config, "get_bind_host", lambda: "127.0.0.1")
    monkeypatch.setattr(config, "get_bind_port", lambda: 4321)
    monkeypatch.setattr(waitress, "serve", lambda application, **kwargs: serves.append((application, kwargs)))
    paths = [path for path in sys.path if path != str(root)]
    monkeypatch.setattr(sys, "path", [str(root), *paths] if root_in_path else paths)
    result = runpy.run_path(str(root / "scripts" / "run_app.py"), run_name=run_name)
    assert result["app"] is fake_app
    assert creates == [True]
    assert str(root) in sys.path
    if run_name == "__main__":
        assert serves == [(fake_app, {"host": "127.0.0.1", "port": 4321})]
        assert "Serving app on http://127.0.0.1:4321" in capsys.readouterr().out
    else:
        assert serves == []
        assert capsys.readouterr().out == ""
