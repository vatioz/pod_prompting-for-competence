from pathlib import Path


def test_ensure_runtime_dirs_seeds_prompt_files(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    import importlib
    import app.config as config

    importlib.reload(config)
    config.ensure_runtime_dirs()

    assert (config.PROMPTS_DIR / "research_prompt.txt").exists()
    assert (config.PROMPTS_DIR / "script_overview_prompt.txt").exists()
    assert (config.PROMPTS_DIR / "script_deep_dive_prompt.txt").exists()


def test_prompt_loader_reads_and_renders_templates(tmp_path):
    from app.prompt_loader import load_prompt_template, render_prompt_template

    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("Hello {name} from {place}", encoding="utf-8")

    template = load_prompt_template(prompt_path)
    rendered = render_prompt_template(template, {"name": "Petr", "place": "Azure"})

    assert rendered == "Hello Petr from Azure"


def test_prompt_loader_rejects_missing_and_empty_templates(tmp_path):
    from app.prompt_loader import load_prompt_template

    missing_path = tmp_path / "missing.txt"
    try:
        load_prompt_template(missing_path)
        assert False, "expected missing prompt file to raise"
    except RuntimeError as exc:
        assert str(missing_path) in str(exc)

    empty_path = tmp_path / "empty.txt"
    empty_path.write_text("\n", encoding="utf-8")
    try:
        load_prompt_template(empty_path)
        assert False, "expected empty prompt file to raise"
    except RuntimeError as exc:
        assert str(empty_path) in str(exc)


def test_prompt_loader_rejects_missing_placeholders():
    from app.prompt_loader import render_prompt_template

    try:
        render_prompt_template("Hello {name}", {"place": "Azure"})
        assert False, "expected missing placeholder to raise"
    except RuntimeError as exc:
        assert "name" in str(exc)



def test_prompt_loader_supports_script_steering_block_placeholder():
    from app.prompt_loader import render_prompt_template

    rendered = render_prompt_template(
        "Topic: {topic_prompt}\n{script_steering_block}\n",
        {
            "topic_prompt": "MCP",
            "script_steering_block": "Additional script steering: none",
        },
    )

    assert "Additional script steering: none" in rendered
