import pytest

from app import config, storage, worker as worker_module


@pytest.fixture
def pipeline(monkeypatch):
    cfg = config.load_config()
    cfg["publishing"]["auto_publish"] = False
    calls = {"research": [], "script": [], "audio": []}

    def research(topic, output_dir, research_config):
        calls["research"].append(topic["id"])
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "research.md"
        path.write_text("# Research\nUnit research notes", encoding="utf-8")
        return path

    def script(topic, variant_name, research_markdown, output_dir, script_config):
        assert research_markdown == "# Research\nUnit research notes"
        calls["script"].append(variant_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{variant_name}.md"
        path.write_text("# Episode\nUnit narration", encoding="utf-8")
        return path

    def audio(script_path, output_path, tts_config):
        assert script_path.read_text(encoding="utf-8") == "# Episode\nUnit narration"
        calls["audio"].append(script_path.stem)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ID3unit-audio")
        return {"provider": "unit-provider", "voice_id": "unit-voice", "model": "unit-model", "segment_count": 1}

    monkeypatch.setattr(worker_module, "generate_research_markdown", research)
    monkeypatch.setattr(worker_module, "generate_script_markdown", script)
    monkeypatch.setattr(worker_module, "synthesize_script_to_mp3", audio)
    topic = storage.create_topic("Unit orchestration", True, True)
    return worker_module.DummyWorker(cfg), calls, topic


def test_worker_lifecycle_is_idempotent_and_stop_joins(monkeypatch):
    calls = []

    class Thread:
        def __init__(self, **kwargs):
            self.alive = False
            calls.append(kwargs)

        def start(self):
            calls.append("start")
            self.alive = True

        def is_alive(self):
            return self.alive

        def join(self, timeout):
            calls.append(("join", timeout))
            self.alive = False

    monkeypatch.setattr(worker_module.threading, "Thread", Thread)
    worker = worker_module.DummyWorker({})
    worker.start()
    worker.start()
    assert calls == [{"target": worker._run_loop, "name": "pod-worker", "daemon": True}, "start"]
    worker.wake()
    assert worker._wake_event.is_set()
    worker.stop()
    worker.stop()
    assert calls[-1] == ("join", 2)
    assert worker._stop_event.is_set()
    assert calls.count("start") == 1


def test_worker_loop_continues_work_waits_when_idle_and_recovers_from_errors(monkeypatch, capsys):
    worker = worker_module.DummyWorker({"worker": {"poll_seconds": 7}})
    results = [True, False, RuntimeError("loop failure")]
    waits, clears = [], []

    def process():
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def wait(timeout):
        waits.append(timeout)
        if len(waits) == 2:
            worker._stop_event.set()

    monkeypatch.setattr(worker, "process_once", process)
    monkeypatch.setattr(worker._wake_event, "wait", wait)
    monkeypatch.setattr(worker._wake_event, "clear", lambda: clears.append(True))
    worker._run_loop()
    assert results == []
    assert waits == [7, 7]
    assert len(clears) == 2
    assert "unexpected error: loop failure" in capsys.readouterr().out


def test_worker_skips_deleted_and_finished_topics_and_finds_pending_variant(monkeypatch):
    deleted = storage.create_topic("deleted", True, False)
    finished = storage.create_topic("finished", True, False)
    storage.update_topic(deleted["id"], lambda item: item.update(deleted=True))
    storage.update_topic(finished["id"], lambda item: (item.update(status="exported"), item["variants"]["overview"].update(status="exported")))
    worker = worker_module.DummyWorker({})
    calls = []
    monkeypatch.setattr(worker, "_process_topic", calls.append)
    assert worker.process_once() is False
    queued = storage.create_topic("pending variant", True, False)
    storage.update_topic(queued["id"], lambda item: item.update(status="failed"))
    assert worker.process_once() is True
    assert calls == [queued["id"]]


def test_worker_generates_each_variant_and_reuses_completed_artifacts(pipeline):
    worker, calls, topic = pipeline
    assert worker.process_once() is True
    generated = storage.get_topic(topic["id"])
    assert generated["status"] == "generated"
    for name in ["overview", "deep_dive"]:
        variant = generated["variants"][name]
        assert variant["script"]["status"] == variant["audio"]["status"] == "done"
        assert variant["status"] == "generated"
        assert variant["audio"]["voice"] == variant["audio"]["voice_id"] == "unit-voice"
        assert variant["audio"]["provider"] == "unit-provider"
        assert variant["publish"]["status"] == "queued"
    worker._process_topic(topic["id"])
    assert calls == {"research": [topic["id"]], "script": ["overview", "deep_dive"], "audio": ["overview", "deep_dive"]}


@pytest.mark.parametrize("stage", ["research", "script", "audio"])
def test_worker_stage_failures_preserve_successful_upstream_work(pipeline, monkeypatch, stage):
    worker, calls, topic = pipeline
    error = RuntimeError(f"{stage} unit failure")

    def fail(*args, **kwargs):
        raise error

    function = {"research": "generate_research_markdown", "script": "generate_script_markdown", "audio": "synthesize_script_to_mp3"}[stage]
    monkeypatch.setattr(worker_module, function, fail)
    with pytest.raises(RuntimeError, match=f"{stage} unit failure") as exc:
        worker._process_topic(topic["id"])
    assert exc.value is error
    failed = storage.get_topic(topic["id"])
    assert failed["status"] == "failed"
    assert failed["last_error"] == str(error)
    if stage == "research":
        assert failed["research"]["status"] == "failed"
        assert failed["research"]["error"] == str(error)
        assert calls["script"] == calls["audio"] == []
    else:
        variant = failed["variants"]["overview"]
        assert failed["research"]["status"] == "done"
        assert variant["status"] == variant[stage]["status"] == "failed"
        assert variant[stage]["error"] == str(error)
        if stage == "audio":
            assert variant["script"]["status"] == "done"


def test_worker_skips_published_variants(pipeline):
    worker, calls, topic = pipeline
    storage.update_topic(topic["id"], lambda item: item["variants"]["overview"].update(status="published"))
    worker._process_topic(topic["id"])
    assert calls["script"] == calls["audio"] == ["deep_dive"]
    assert storage.get_topic(topic["id"])["variants"]["overview"]["status"] == "published"


def test_worker_read_failure_marks_topic_without_losing_research(tmp_path, pipeline, monkeypatch):
    worker, _, topic = pipeline
    artifact = tmp_path / "unreadable.md"
    artifact.write_bytes(b"\xff")
    storage.update_topic(topic["id"], lambda item: item["research"].update(status="done", path=str(artifact)))
    with pytest.raises(UnicodeDecodeError):
        worker._process_topic(topic["id"])
    failed = storage.get_topic(topic["id"])
    assert failed["status"] == "failed"
    assert "decode" in failed["last_error"]
    assert failed["research"]["status"] == "done"
    assert failed["research"]["path"] == str(artifact)


@pytest.mark.parametrize("missing_paths", [False, True])
def test_worker_regenerates_done_stages_without_valid_artifacts(pipeline, missing_paths):
    worker, calls, topic = pipeline

    def invalidate(item):
        item["research"].update(status="done", path="absent-research.md" if missing_paths else None)
        for name in ["overview", "deep_dive"]:
            for stage in ["script", "audio"]:
                item["variants"][name][stage].update(status="done", path=f"absent-{name}-{stage}" if missing_paths else None)

    storage.update_topic(topic["id"], invalidate)
    worker._process_topic(topic["id"])
    assert calls["research"] == [topic["id"]]
    assert calls["script"] == calls["audio"] == ["overview", "deep_dive"]


def test_worker_marks_publish_stage_failure_with_upstream_errors_unchanged(pipeline):
    worker, _, topic = pipeline
    worker._mark_variant_stage_failed(topic["id"], "overview", stage_name="publish", error="upload failed")
    updated = storage.get_topic(topic["id"])
    variant = updated["variants"]["overview"]
    assert updated["status"] == variant["status"] == variant["publish"]["status"] == "failed"
    assert updated["last_error"] == variant["publish"]["error"] == "upload failed"
    assert variant["script"]["error"] is None
    assert variant["audio"]["error"] is None
