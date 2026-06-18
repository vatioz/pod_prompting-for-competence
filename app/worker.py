from __future__ import annotations

from datetime import timezone, datetime
from pathlib import Path
import threading

from .config import (
    GENERATED_AUDIO_DIR,
    GENERATED_RESEARCH_DIR,
    GENERATED_SCRIPTS_DIR,
)
from .publisher import publish_topic_variant, rebuild_publish_outputs
from .research import generate_research_markdown
from .script_writer import generate_script_markdown
from .storage import load_state, recompute_topic_status, save_state, topic_artifact_stem, topic_variant_title
from .tts_dispatch import synthesize_script_to_mp3


class DummyWorker:
    def __init__(self, config: dict):
        self.config = config
        self._wake_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="pod-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def wake(self) -> None:
        self._wake_event.set()

    def _run_loop(self) -> None:
        poll_seconds = self.config["worker"]["poll_seconds"]
        while not self._stop_event.is_set():
            try:
                worked = self.process_once()
            except Exception as exc:  # pragma: no cover - defensive logging path
                print(f"[worker] unexpected error: {exc}")
                worked = False
            if worked:
                continue
            self._wake_event.wait(timeout=poll_seconds)
            self._wake_event.clear()

    def process_once(self) -> bool:
        state = load_state()
        for topic in state["topics"]:
            if topic.get("deleted"):
                continue
            if topic["status"] in {"queued", "processing", "generated"} or any(
                variant["enabled"] and variant["status"] in {"queued", "processing", "generated"}
                for variant in topic["variants"].values()
            ):
                self._process_topic(topic["id"])
                return True
        return False

    def _process_topic(self, topic_id: str) -> None:
        state = load_state()
        topic = next(item for item in state["topics"] if item["id"] == topic_id)
        topic["status"] = "processing"
        topic["last_error"] = None
        self._save(state)
        try:
            research_path = self._run_research_stage(topic_id)
            research_text = research_path.read_text(encoding="utf-8")
            for variant_name in ["overview", "deep_dive"]:
                state = load_state()
                topic = next(item for item in state["topics"] if item["id"] == topic_id)
                variant = topic["variants"][variant_name]
                if not variant["enabled"] or variant["status"] in {"exported", "published"}:
                    continue
                self._run_variant_generation(topic_id, variant_name, research_text)
                if self._auto_publish_enabled():
                    publish_topic_variant(topic_id=topic_id, variant_name=variant_name, config=self.config)
                state = load_state()
                topic = next(item for item in state["topics"] if item["id"] == topic_id)
                topic["status"] = recompute_topic_status(topic)
                self._save(state)
            state = load_state()
            topic = next(item for item in state["topics"] if item["id"] == topic_id)
            topic["status"] = recompute_topic_status(topic)
            self._save(state)
            rebuild_publish_outputs(self.config, state=state)
        except Exception as exc:
            state = load_state()
            topic = next(item for item in state["topics"] if item["id"] == topic_id)
            topic["status"] = "failed"
            topic["last_error"] = topic.get("last_error") or str(exc)
            self._save(state)
            raise

    def _run_research_stage(self, topic_id: str) -> Path:
        state = load_state()
        topic = next(item for item in state["topics"] if item["id"] == topic_id)
        research = topic["research"]
        existing_path = Path(research["path"]) if research.get("path") else None
        if research["status"] == "done" and existing_path and existing_path.exists():
            return existing_path

        research["status"] = "processing"
        research["error"] = None
        topic["updated_at"] = _utc_now_iso()
        self._save(state)
        try:
            research_path = generate_research_markdown(
                topic=topic,
                output_dir=GENERATED_RESEARCH_DIR,
                research_config=self.config.get("research", {}),
            )
        except Exception as exc:
            state = load_state()
            topic = next(item for item in state["topics"] if item["id"] == topic_id)
            topic["research"]["status"] = "failed"
            topic["research"]["error"] = str(exc)
            topic["status"] = "failed"
            topic["last_error"] = str(exc)
            self._save(state)
            raise

        state = load_state()
        topic = next(item for item in state["topics"] if item["id"] == topic_id)
        topic["research"]["path"] = str(research_path)
        topic["research"]["status"] = "done"
        topic["research"]["error"] = None
        topic["updated_at"] = _utc_now_iso()
        self._save(state)
        return research_path

    def _run_variant_generation(self, topic_id: str, variant_name: str, research_text: str) -> None:
        state = load_state()
        topic = next(item for item in state["topics"] if item["id"] == topic_id)
        variant = topic["variants"][variant_name]

        def _existing_done_path(stage: dict, fallback_path: str | None) -> Path | None:
            if stage.get("status") != "done":
                return None
            raw_path = stage.get("path") or fallback_path
            if not raw_path:
                return None
            candidate = Path(raw_path)
            return candidate if candidate.exists() else None

        script_stage = variant.setdefault("script", {})
        audio_stage = variant.setdefault("audio", {})
        publish_stage = variant.setdefault("publish", {})

        script_path = _existing_done_path(script_stage, variant.get("script_path"))
        audio_path = _existing_done_path(audio_stage, variant.get("audio_path"))

        variant["status"] = "processing"
        publish_stage["status"] = publish_stage.get("status") or "queued"
        publish_stage["error"] = None
        publish_stage["public_url"] = None
        publish_stage["completed_at"] = None
        topic["updated_at"] = _utc_now_iso()
        self._save(state)

        if script_path is None:
            script_stage["status"] = "processing"
            script_stage["error"] = None
            topic["updated_at"] = _utc_now_iso()
            self._save(state)
            try:
                script_path = generate_script_markdown(
                    topic=topic,
                    variant_name=variant_name,
                    research_markdown=research_text,
                    output_dir=GENERATED_SCRIPTS_DIR,
                    script_config=self.config.get("script", {}),
                )
            except Exception as exc:
                self._mark_variant_stage_failed(topic_id, variant_name, stage_name="script", error=str(exc))
                raise

            state = load_state()
            topic = next(item for item in state["topics"] if item["id"] == topic_id)
            variant = topic["variants"][variant_name]
            script_stage = variant.setdefault("script", {})
            audio_stage = variant.setdefault("audio", {})
            script_stage["status"] = "done"
            script_stage["path"] = str(script_path)
            script_stage["model"] = self.config.get("script", {}).get("model") or self.config.get("script", {}).get("style")
            script_stage["error"] = None
            variant["script_path"] = str(script_path)
            audio_stage["status"] = "queued"
            audio_stage["error"] = None
            topic["updated_at"] = _utc_now_iso()
            self._save(state)
        else:
            state = load_state()
            topic = next(item for item in state["topics"] if item["id"] == topic_id)
            variant = topic["variants"][variant_name]
            script_stage = variant.setdefault("script", {})
            script_stage["status"] = "done"
            script_stage["path"] = str(script_path)
            script_stage["error"] = None
            variant["script_path"] = str(script_path)
            topic["updated_at"] = _utc_now_iso()
            self._save(state)

        if audio_path is None:
            state = load_state()
            topic = next(item for item in state["topics"] if item["id"] == topic_id)
            variant = topic["variants"][variant_name]
            audio_stage = variant.setdefault("audio", {})
            audio_stage["status"] = "processing"
            audio_stage["error"] = None
            topic["updated_at"] = _utc_now_iso()
            self._save(state)

            audio_path = GENERATED_AUDIO_DIR / f"{topic_artifact_stem(topic, variant_name)}.mp3"
            try:
                audio_meta = self._materialize_audio(script_path=script_path, variant_name=variant_name, target_mp3=audio_path)
            except Exception as exc:
                self._mark_variant_stage_failed(topic_id, variant_name, stage_name="audio", error=str(exc))
                raise

            state = load_state()
            topic = next(item for item in state["topics"] if item["id"] == topic_id)
            variant = topic["variants"][variant_name]
            audio_stage = variant.setdefault("audio", {})
            audio_stage["status"] = "done"
            audio_stage["path"] = str(audio_path)
            audio_stage["provider"] = audio_meta["provider"]
            audio_stage["voice"] = audio_meta.get("voice") or audio_meta.get("voice_id")
            audio_stage["voice_id"] = audio_meta.get("voice_id") or audio_meta.get("voice")
            audio_stage["model"] = audio_meta.get("model")
            audio_stage["segment_count"] = audio_meta.get("segment_count")
            audio_stage["duration_seconds"] = audio_meta.get("duration_seconds")
            audio_stage["error"] = None
            variant["audio_path"] = str(audio_path)
            variant["published_title"] = topic_variant_title(topic, variant_name)
            variant["status"] = "generated"
            topic["updated_at"] = _utc_now_iso()
            self._save(state)
            return

        state = load_state()
        topic = next(item for item in state["topics"] if item["id"] == topic_id)
        variant = topic["variants"][variant_name]
        audio_stage = variant.setdefault("audio", {})
        audio_stage["status"] = "done"
        audio_stage["path"] = str(audio_path)
        audio_stage["error"] = None
        variant["audio_path"] = str(audio_path)
        variant["published_title"] = variant.get("published_title") or topic_variant_title(topic, variant_name)
        variant["status"] = "generated"
        topic["updated_at"] = _utc_now_iso()
        self._save(state)

    def _mark_variant_stage_failed(self, topic_id: str, variant_name: str, *, stage_name: str, error: str) -> None:
        state = load_state()
        topic = next(item for item in state["topics"] if item["id"] == topic_id)
        variant = topic["variants"][variant_name]
        variant.setdefault(stage_name, {})["status"] = "failed"
        variant[stage_name]["error"] = error
        if stage_name != "script":
            variant.setdefault("script", {}).setdefault("error", None)
        if stage_name != "audio":
            variant.setdefault("audio", {}).setdefault("error", None)
        if stage_name != "publish":
            variant.setdefault("publish", {}).setdefault("error", None)
        variant["status"] = "failed"
        topic["status"] = "failed"
        topic["last_error"] = error
        topic["updated_at"] = _utc_now_iso()
        self._save(state)

    def _materialize_audio(self, script_path: Path, variant_name: str, target_mp3: Path) -> dict:
        return synthesize_script_to_mp3(script_path=script_path, output_path=target_mp3, tts_config=self.config.get("tts", {}))

    def _auto_publish_enabled(self) -> bool:
        return bool(self.config.get("publishing", {}).get("auto_publish"))

    @staticmethod
    def _save(state: dict) -> None:
        for topic in state["topics"]:
            topic["updated_at"] = _utc_now_iso()
        save_state(state)
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
