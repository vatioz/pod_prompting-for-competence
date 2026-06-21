from __future__ import annotations

import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class _FakeElevenLabsHandler(BaseHTTPRequestHandler):
    requests = []
    response_body = b"ID3fake-mp3-data"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.__class__.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "json": json.loads(body.decode("utf-8")),
            }
        )
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(self.response_body)))
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, format, *args):
        return


class _FakeFoundryHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))
        self.__class__.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "json": payload,
            }
        )
        if payload.get("tools"):
            response_text = "\n".join(
                [
                    f"# Research Notes: {payload['input'].splitlines()[0].replace('Topic: ', '')}",
                    "",
                    "## Topic Statement",
                    "This topic explains how MCP can expose capabilities from tools to clients in a practical engineering workflow.",
                    "",
                    "## Key Concepts",
                    "- Hosts, clients, and servers each have separate responsibilities.",
                    "- The protocol standardizes tool and resource access.",
                    "",
                    "## Why It Matters",
                    "It helps engineering teams integrate models with tools in a more portable way.",
                    "",
                    "## Practical Examples",
                    "- Connecting an IDE assistant to repo tools.",
                    "- Standardizing access to internal APIs.",
                    "",
                    "## Tradeoffs / Caveats",
                    "- More moving parts than a one-off integration.",
                    "- Requires clear trust boundaries.",
                    "",
                    "## Glossary / Jargon Expansion",
                    "- MCP: Model Context Protocol.",
                    "",
                    "## Source Notes",
                    "- Will be replaced by the client with normalized sources.",
                    "",
                    "## Unresolved Questions",
                    "- Which patterns matter most for day-to-day engineering teams?",
                    "",
                ]
            )
        else:
            response_text = "\n".join(
                [
                    "# MCP for Engineering Teams — Overview",
                    "",
                    "Today we're getting a practical handle on Model Context Protocol, or MCP.",
                    "Instead of treating it like abstract protocol trivia, think of it as a standard way for an AI client to discover tools and resources from a server.",
                    "That matters because it gives teams a cleaner integration boundary between models, developer tools, and internal systems.",
                    "A useful example is connecting an IDE assistant to repository-aware tools without inventing a custom bridge for every product.",
                    "The tradeoff is that you gain portability and structure, but you also introduce another boundary that has to be understood, secured, and operated.",
                    "So the takeaway is simple: MCP is most helpful when it reduces repeated integration work and makes tool access more legible across a team.",
                ]
            )
        response = {
            "output_text": response_text,
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": response_text,
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://modelcontextprotocol.io/introduction",
                                    "title": "Model Context Protocol Introduction",
                                    "start_index": 0,
                                    "end_index": 20,
                                },
                                {
                                    "type": "url_citation",
                                    "url": "https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search",
                                    "title": "Web search with the Responses API",
                                    "start_index": 21,
                                    "end_index": 42,
                                },
                            ],
                        }
                    ],
                }
            ],
        }
        if payload.get("tools"):
            response["output"].insert(
                0,
                {
                    "type": "web_search_call",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "query": "MCP engineering teams",
                        "sources": [
                            {"type": "url", "url": "https://modelcontextprotocol.io/introduction"},
                            {"type": "url", "url": "https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search"},
                        ],
                    },
                },
            )
        response_bytes = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def log_message(self, format, *args):
        return


class _FakeAzureSpeechHandler(BaseHTTPRequestHandler):
    requests = []
    response_body = b"ID3fake-azure-speech-mp3"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.__class__.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": body.decode("utf-8"),
            }
        )
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(self.response_body)))
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, format, *args):
        return


def _start_fake_server():
    _FakeElevenLabsHandler.requests = []
    server = HTTPServer(("127.0.0.1", 0), _FakeElevenLabsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _start_fake_foundry_server():
    _FakeFoundryHandler.requests = []
    server = HTTPServer(("127.0.0.1", 0), _FakeFoundryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _start_fake_azure_speech_server():
    _FakeAzureSpeechHandler.requests = []
    server = HTTPServer(("127.0.0.1", 0), _FakeAzureSpeechHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _write_runtime_fixture(
    runtime_dir: Path,
    base_url: str,
    tts_base_url: str,
    foundry_base_url: str = "http://127.0.0.1:9/openai/v1/",
) -> None:
    (runtime_dir / "config").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config" / "prompts").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "data").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "generated").mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config" / "podcast.yaml").write_text(
        "\n".join(
            [
                "podcast:",
                "  title: Prompting for Competence",
                "  description: Personal learning podcast feed generated from queued topics.",
                "  author: vatioz",
                f"  base_url: {base_url}",
                "  language: en-us",
                "worker:",
                "  poll_seconds: 1",
                "research:",
                "  provider: azure_foundry",
                f"  endpoint: {foundry_base_url}",
                "  model: gpt-4.1-mini",
                "  api_key_env: AZURE_OPENAI_API_KEY",
                "  timeout_seconds: 60",
                "  include_search_sources: true",
                "script:",
                "  provider: azure_foundry",
                f"  endpoint: {foundry_base_url}",
                "  model: gpt-4.1-mini",
                "  api_key_env: AZURE_OPENAI_API_KEY",
                "  timeout_seconds: 60",
                "  style: explanatory_podcast",
                "tts:",
                "  provider: elevenlabs",
                "  voice_id: test-voice",
                "  model_id: eleven_multilingual_v2",
                "  output_format: mp3_44100_128",
                f"  base_url: {tts_base_url}",
                "  timeout_seconds: 10",
                "publishing:",
                "  target: app_hosted",
                f"  public_base_url: {base_url}",
                f"  export_dir: {runtime_dir / 'publish'}",
                "  auto_publish: true",
                "ui:",
                "  recent_topics_limit: 12",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (runtime_dir / "config" / "prompts" / "research_prompt.txt").write_text(
        "\n".join(
            [
                "Research briefing for a software engineering podcast.",
                "Topic: {topic_prompt}",
                "Focus on practical engineering mechanisms, tradeoffs, and production realities.",
                "Return markdown with the required research headings.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (runtime_dir / "config" / "prompts" / "script_overview_prompt.txt").write_text(
        "\n".join(
            [
                "Write an overview podcast script.",
                "Topic: {topic_prompt}",
                "Variant: {variant_label}",
                "Target minutes: {target_minutes}",
                "Title: {script_title}",
                "{script_steering_block}",
                "Use a concise, audio-native voice and build a mental model.",
                "Research notes:",
                "{research_markdown}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (runtime_dir / "config" / "prompts" / "script_deep_dive_prompt.txt").write_text(
        "\n".join(
            [
                "Write a deep dive podcast script.",
                "Topic: {topic_prompt}",
                "Variant: {variant_label}",
                "Target minutes: {target_minutes}",
                "Title: {script_title}",
                "{script_steering_block}",
                "Use a concise, audio-native voice and build a mental model.",
                "Research notes:",
                "{research_markdown}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (runtime_dir / "data" / "topics.yaml").write_text("topics: []\n", encoding="utf-8")


def _reload_modules():
    import app.config as config
    import app.feedgen as feedgen
    import app.storage as storage
    import app.worker as worker
    import app.research as research
    import app.script_writer as script_writer
    import app.tts_elevenlabs as tts_elevenlabs
    import app.tts_dispatch as tts_dispatch
    import app.tts_azure_speech as tts_azure_speech
    import app.publisher as publisher

    modules = [config, storage, feedgen, research, script_writer, tts_elevenlabs, tts_dispatch, tts_azure_speech, publisher, worker]
    for module in modules:
        importlib.reload(module)
    return {
        "config": config,
        "storage": storage,
        "feedgen": feedgen,
        "research": research,
        "script_writer": script_writer,
        "tts_elevenlabs": tts_elevenlabs,
        "tts_dispatch": tts_dispatch,
        "tts_azure_speech": tts_azure_speech,
        "worker": worker,
    }


def test_generate_research_creates_structured_non_placeholder_markdown(tmp_path, monkeypatch):
    server = _start_fake_foundry_server()
    try:
        runtime_dir = tmp_path / "runtime"
        _write_runtime_fixture(
            runtime_dir,
            "https://example.com",
            "http://127.0.0.1:9",
            f"http://127.0.0.1:{server.server_port}/openai/v1/",
        )
        monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

        modules = _reload_modules()
        REQUIRED_HEADINGS = modules["research"].REQUIRED_HEADINGS
        generate_research_markdown = modules["research"].generate_research_markdown

        topic = {"id": "abc123", "slug": "mcp-ui", "prompt": "MCP UI"}
        research_config = {
            "provider": "azure_foundry",
            "endpoint": f"http://127.0.0.1:{server.server_port}/openai/v1/",
            "model": "gpt-4.1-mini",
            "api_key": "foundry-test-key",
            "timeout_seconds": 10,
            "include_search_sources": True,
        }

        output_path = generate_research_markdown(
            topic=topic,
            output_dir=tmp_path,
            research_config=research_config,
        )
        text = output_path.read_text(encoding="utf-8")

        assert output_path.exists()
        assert "dummy placeholder" not in text.lower()
        for heading in REQUIRED_HEADINGS:
            assert heading in text
        assert "practical" in text.lower()
        assert len(text) > 500
    finally:
        server.shutdown()
        server.server_close()


def test_storage_load_state_migrates_legacy_variant_schema(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, "https://example.com", "http://127.0.0.1:9")
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    legacy_state = {
        "topics": [
            {
                "id": "topic1",
                "slug": "mcp-ui",
                "prompt": "MCP UI",
                "status": "queued",
                "deleted": False,
                "created_at": "2026-06-13T00:00:00+00:00",
                "updated_at": "2026-06-13T00:00:00+00:00",
                "last_error": None,
                "research": {"status": "queued", "path": None},
                "variants": {
                    "overview": {
                        "enabled": True,
                        "status": "queued",
                        "script_path": None,
                        "audio_path": None,
                        "published_title": None,
                        "published_at": None,
                    }
                },
            }
        ]
    }
    modules["storage"].save_state(legacy_state)

    loaded = modules["storage"].load_state()
    overview = loaded["topics"][0]["variants"]["overview"]

    assert overview["script"]["status"] == "queued"
    assert overview["audio"]["status"] == "queued"
    assert overview["publish"]["status"] == "queued"
    assert overview["audio"]["voice"] is None
    assert overview["audio"]["model"] is None
    assert overview["audio"]["segment_count"] is None


def test_storage_normalizes_voice_and_voice_id_for_multi_provider_audio_metadata(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, "https://example.com", "http://127.0.0.1:9")
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    state = {
        "topics": [
            {
                "id": "topic1",
                "slug": "mcp-ui",
                "prompt": "MCP UI",
                "status": "generated",
                "deleted": False,
                "created_at": "2026-06-13T00:00:00+00:00",
                "updated_at": "2026-06-13T00:00:00+00:00",
                "last_error": None,
                "research": {"status": "done", "path": "/tmp/research.md", "error": None},
                "variants": {
                    "overview": {
                        "enabled": True,
                        "status": "generated",
                        "script": {"status": "done", "path": "/tmp/script.md", "model": "gpt-5.2", "error": None},
                        "audio": {
                            "status": "done",
                            "path": "/tmp/audio.mp3",
                            "provider": "azure_speech",
                            "voice": "en-US-Ava:DragonHDLatestNeural",
                            "model": "speech_sync",
                            "segment_count": 1,
                            "error": None,
                        },
                        "publish": {"status": "queued", "public_url": None, "completed_at": None, "error": None},
                    }
                },
            }
        ]
    }
    modules["storage"].save_state(state)

    loaded = modules["storage"].load_state()
    audio = loaded["topics"][0]["variants"]["overview"]["audio"]

    assert audio["provider"] == "azure_speech"
    assert audio["voice"] == "en-US-Ava:DragonHDLatestNeural"
    assert audio["voice_id"] == "en-US-Ava:DragonHDLatestNeural"
    assert audio["model"] == "speech_sync"
    assert audio["segment_count"] == 1


def test_create_topic_assigns_next_episode_number_from_existing_numbered_artifacts(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, "https://example.com", "http://127.0.0.1:9")
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    storage = modules["storage"]

    storage.save_state(
        {
            "topics": [
                {
                    "id": "old001",
                    "slug": "llm-caching",
                    "prompt": "LLM caching",
                    "status": "published",
                    "deleted": False,
                    "created_at": "2026-06-13T00:00:00+00:00",
                    "updated_at": "2026-06-13T00:00:00+00:00",
                    "last_error": None,
                    "research": {"status": "done", "path": "/data/generated/research/001_llm-caching-old001.md", "error": None},
                    "variants": {
                        "overview": {
                            "enabled": True,
                            "status": "published",
                            "script": {"status": "done", "path": "/data/generated/scripts/001_llm-caching-overview-old001.md", "model": "gpt", "error": None},
                            "audio": {"status": "done", "path": "/data/generated/audio/001_llm-caching-overview-old001.mp3", "provider": "elevenlabs", "voice": "v", "voice_id": "v", "model": None, "segment_count": 1, "duration_seconds": None, "error": None},
                            "publish": {"status": "done", "public_url": "https://example.com/audio/001_llm-caching-overview-old001.mp3", "completed_at": "2026-06-13T00:00:00+00:00", "error": None},
                        },
                        "deep_dive": {"enabled": False},
                    },
                },
                {
                    "id": "old003",
                    "slug": "opencode",
                    "prompt": "OpenCode",
                    "status": "queued",
                    "deleted": False,
                    "created_at": "2026-06-14T00:00:00+00:00",
                    "updated_at": "2026-06-14T00:00:00+00:00",
                    "last_error": None,
                    "research": {"status": "queued", "path": "/data/generated/research/003_opencode-old003.md", "error": None},
                    "variants": {
                        "overview": {"enabled": True},
                        "deep_dive": {"enabled": False},
                    },
                },
            ]
        }
    )

    topic = storage.create_topic(prompt="Episode numbering", overview=True, deep_dive=False)
    state = storage.load_state()

    assert state["topics"][0]["episode_number"] == 1
    assert state["topics"][1]["episode_number"] == 3
    assert topic["episode_number"] == 4
    assert state["topics"][-1]["episode_number"] == 4


def test_create_topic_persists_and_normalizes_optional_script_steering(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, "https://example.com", "http://127.0.0.1:9")
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    storage = modules["storage"]

    topic = storage.create_topic(
        prompt="MCP for agent tools",
        overview=True,
        deep_dive=False,
        script_steering="  Explain like I'm 5 first, then connect it back to real systems.  ",
    )
    storage.save_state(
        {
            "topics": [
                {
                    "id": "legacy-topic",
                    "episode_number": 9,
                    "slug": "legacy-topic",
                    "prompt": "Legacy topic",
                    "status": "queued",
                    "deleted": False,
                    "created_at": "2026-06-15T00:00:00+00:00",
                    "updated_at": "2026-06-15T00:00:00+00:00",
                    "last_error": None,
                    "research": {"status": "queued", "path": None, "error": None},
                    "variants": {"overview": {"enabled": True}, "deep_dive": {"enabled": False}},
                },
                topic,
            ]
        }
    )

    loaded = storage.load_state()

    assert loaded["topics"][0]["user_inputs"]["script_steering"] == ""
    assert loaded["topics"][1]["user_inputs"]["script_steering"] == "Explain like I'm 5 first, then connect it back to real systems."


def test_worker_generates_real_artifacts_and_calls_elevenlabs(tmp_path, monkeypatch):
    server = _start_fake_server()
    foundry_server = _start_fake_foundry_server()
    try:
        runtime_dir = tmp_path / "runtime"
        tts_base_url = f"http://127.0.0.1:{server.server_port}"
        foundry_base_url = f"http://127.0.0.1:{foundry_server.server_port}/openai/v1/"
        _write_runtime_fixture(runtime_dir, "https://pod.example.com", tts_base_url, foundry_base_url)

        monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "foundry-test-key")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

        modules = _reload_modules()
        storage = modules["storage"]
        config = modules["config"]
        worker_module = modules["worker"]

        storage.create_topic(prompt="Model Context Protocol for engineering teams", overview=True, deep_dive=False)
        worker = worker_module.DummyWorker(config.load_config())

        assert worker.process_once() is True

        state = storage.load_state()
        topic = state["topics"][0]
        variant = topic["variants"]["overview"]
        research_path = Path(topic["research"]["path"])
        script_path = Path(variant["script_path"])
        audio_path = Path(variant["audio_path"])
        feed_path = config.GENERATED_FEED_PATH

        assert topic["status"] == "published"
        assert research_path.exists()
        assert script_path.exists()
        assert audio_path.exists()
        assert audio_path.read_bytes() == b"ID3fake-mp3-data"
        assert variant["audio"]["provider"] == "elevenlabs"
        assert variant["audio"]["voice"] == "test-voice"
        assert variant["audio"]["voice_id"] == "test-voice"
        assert variant["audio"]["model"] == "eleven_multilingual_v2"
        assert variant["audio"]["segment_count"] == 1
        assert "dummy placeholder" not in research_path.read_text(encoding="utf-8").lower()
        assert "dummy script artifact" not in script_path.read_text(encoding="utf-8").lower()
        assert feed_path.exists()
        assert audio_path.name in feed_path.read_text(encoding="utf-8")
        assert _FakeElevenLabsHandler.requests
        request = _FakeElevenLabsHandler.requests[0]
        assert "/v1/text-to-speech/test-voice" in request["path"]
        assert "Model Context Protocol" in request["json"]["text"]
    finally:
        server.shutdown()
        server.server_close()
        foundry_server.shutdown()
        foundry_server.server_close()

def test_generate_research_uses_foundry_web_search_and_normalizes_sources(tmp_path, monkeypatch):
    server = _start_fake_foundry_server()
    try:
        runtime_dir = tmp_path / "runtime"
        _write_runtime_fixture(runtime_dir, "https://example.com", "http://127.0.0.1:9")
        (runtime_dir / "config" / "prompts" / "research_prompt.txt").write_text(
            "CUSTOM RESEARCH PROMPT\nTopic: {topic_prompt}\nFind practical engineering details, current docs, and implementation tradeoffs.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "foundry-test-key")
        modules = _reload_modules()
        generate_research_markdown = modules["research"].generate_research_markdown

        topic = {"id": "abc123", "slug": "mcp-ui", "prompt": "MCP UI"}
        research_config = {
            "provider": "azure_foundry",
            "endpoint": f"http://127.0.0.1:{server.server_port}/openai/v1/",
            "model": "gpt-4.1-mini",
            "api_key_env": "AZURE_OPENAI_API_KEY",
            "timeout_seconds": 10,
            "include_search_sources": True,
            "allowed_domains": ["modelcontextprotocol.io", "learn.microsoft.com"],
        }

        output_path = generate_research_markdown(
            topic=topic,
            output_dir=tmp_path,
            research_config=research_config,
        )
        text = output_path.read_text(encoding="utf-8")

        assert output_path.exists()
        assert _FakeFoundryHandler.requests
        request = _FakeFoundryHandler.requests[0]
        assert request["path"] == "/openai/v1/responses"
        headers = {key.lower(): value for key, value in request["headers"].items()}
        assert headers["api-key"] == "foundry-test-key"
        assert request["json"]["model"] == "gpt-4.1-mini"
        assert "CUSTOM RESEARCH PROMPT" in request["json"]["input"]
        assert request["json"]["tools"][0]["type"] == "web_search"
        assert request["json"]["tools"][0]["filters"]["allowed_domains"] == ["modelcontextprotocol.io", "learn.microsoft.com"]
        assert "web_search_call.action.sources" in request["json"]["include"]
        assert "## Source Notes" in text
        assert "modelcontextprotocol.io/introduction" in text
        assert "learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search" in text
    finally:
        server.shutdown()
        server.server_close()


def test_generate_script_markdown_uses_foundry_llm_without_web_search(tmp_path, monkeypatch):
    server = _start_fake_foundry_server()
    try:
        runtime_dir = tmp_path / "runtime"
        _write_runtime_fixture(runtime_dir, "https://example.com", "http://127.0.0.1:9")
        (runtime_dir / "config" / "prompts" / "script_overview_prompt.txt").write_text(
            "CUSTOM OVERVIEW PROMPT\nTopic: {topic_prompt}\nVariant: {variant_label}\nMinutes: {target_minutes}\nTitle: {script_title}\n{script_steering_block}\nUse a practical, audio-native voice for engineers.\nResearch:\n{research_markdown}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "foundry-test-key")
        modules = _reload_modules()
        generate_script_markdown = modules["script_writer"].generate_script_markdown
        spoken_text_from_markdown = modules["script_writer"].spoken_text_from_markdown

        topic = {
            "id": "abc123",
            "slug": "mcp-ui",
            "prompt": "MCP for engineering teams",
            "user_inputs": {"script_steering": "Explain like I'm 5 first, then map it back to real engineering tradeoffs."},
        }
        research_markdown = "\n".join(
            [
                "# Research Notes: MCP for engineering teams",
                "",
                "## Topic Statement",
                "MCP standardizes how clients discover tools and resources.",
                "",
                "## Key Concepts",
                "- Hosts, clients, and servers have different roles.",
                "- The protocol standardizes tool discovery.",
                "",
                "## Why It Matters",
                "It gives teams a more portable integration boundary.",
                "",
                "## Practical Examples",
                "- IDE assistant integration.",
                "",
                "## Tradeoffs / Caveats",
                "- Another system boundary to operate.",
                "",
                "## Glossary / Jargon Expansion",
                "- MCP: Model Context Protocol.",
                "",
                "## Source Notes",
                "- https://modelcontextprotocol.io/introduction",
                "",
                "## Unresolved Questions",
                "- Where does MCP add enough leverage to justify the complexity?",
                "",
            ]
        )
        script_config = {
            "provider": "azure_foundry",
            "endpoint": f"http://127.0.0.1:{server.server_port}/openai/v1/",
            "model": "gpt-4.1-mini",
            "api_key_env": "AZURE_OPENAI_API_KEY",
            "timeout_seconds": 10,
            "overview_target_minutes": 5,
            "deep_dive_target_minutes": 18,
        }

        output_path = generate_script_markdown(
            topic=topic,
            variant_name="overview",
            research_markdown=research_markdown,
            output_dir=tmp_path,
            script_config=script_config,
        )
        text = output_path.read_text(encoding="utf-8")

        assert output_path.exists()
        assert _FakeFoundryHandler.requests
        request = _FakeFoundryHandler.requests[0]
        assert request["path"] == "/openai/v1/responses"
        headers = {key.lower(): value for key, value in request["headers"].items()}
        assert headers["api-key"] == "foundry-test-key"
        assert request["json"]["model"] == "gpt-4.1-mini"
        assert "CUSTOM OVERVIEW PROMPT" in request["json"]["input"]
        assert "tools" not in request["json"]
        assert "MCP for engineering teams" in request["json"]["input"]
        assert "Explain like I'm 5 first, then map it back to real engineering tradeoffs." in request["json"]["input"]
        assert text.startswith("# MCP for Engineering Teams — Overview")
        assert "abstract protocol trivia" in text
        assert "MCP." in spoken_text_from_markdown(text)
    finally:
        server.shutdown()
        server.server_close()


def test_worker_can_use_foundry_for_research_and_elevenlabs_for_audio(tmp_path, monkeypatch):
    foundry_server = _start_fake_foundry_server()
    elevenlabs_server = _start_fake_server()
    try:
        runtime_dir = tmp_path / "runtime"
        tts_base_url = f"http://127.0.0.1:{elevenlabs_server.server_port}"
        _write_runtime_fixture(runtime_dir, "https://pod.example.com", tts_base_url)

        monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "foundry-test-key")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

        config_path = runtime_dir / "config" / "podcast.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "podcast:",
                    "  title: Prompting for Competence",
                    "  description: Personal learning podcast feed generated from queued topics.",
                    "  author: Vatioz",
                    "  base_url: https://pod.example.com",
                    "  language: en-us",
                    "worker:",
                    "  poll_seconds: 1",
                    "research:",
                    "  provider: azure_foundry",
                    f"  endpoint: http://127.0.0.1:{foundry_server.server_port}/openai/v1/",
                    "  model: gpt-4.1-mini",
                    "  api_key_env: AZURE_OPENAI_API_KEY",
                    "  timeout_seconds: 10",
                    "  include_search_sources: true",
                    "  allowed_domains:",
                    "    - modelcontextprotocol.io",
                    "    - learn.microsoft.com",
                    "script:",
                    "  provider: azure_foundry",
                    f"  endpoint: http://127.0.0.1:{foundry_server.server_port}/openai/v1/",
                    "  model: gpt-4.1-mini",
                    "  api_key_env: AZURE_OPENAI_API_KEY",
                    "  timeout_seconds: 10",
                    "  style: explanatory_podcast",
                    "tts:",
                    "  provider: elevenlabs",
                    "  voice_id: test-voice",
                    "  model_id: eleven_multilingual_v2",
                    "  output_format: mp3_44100_128",
                    f"  base_url: {tts_base_url}",
                    "  timeout_seconds: 10",
                    "publishing:",
                    "  target: app_hosted",
                    "  public_base_url: https://pod.example.com",
                    f"  export_dir: {runtime_dir / 'publish'}",
                    "  auto_publish: true",
                    "ui:",
                    "  recent_topics_limit: 12",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        modules = _reload_modules()
        storage = modules["storage"]
        config = modules["config"]
        worker_module = modules["worker"]

        storage.create_topic(prompt="Model Context Protocol for engineering teams", overview=True, deep_dive=False)
        worker = worker_module.DummyWorker(config.load_config())

        assert worker.process_once() is True

        state = storage.load_state()
        topic = state["topics"][0]
        research_path = Path(topic["research"]["path"])
        assert research_path.exists()
        research_text = research_path.read_text(encoding="utf-8")
        assert _FakeFoundryHandler.requests
        assert "modelcontextprotocol.io/introduction" in research_text
        assert topic["status"] == "published"
    finally:
        foundry_server.shutdown()
        foundry_server.server_close()
        elevenlabs_server.shutdown()
        elevenlabs_server.server_close()


def test_worker_can_use_foundry_for_script_and_elevenlabs_for_audio(tmp_path, monkeypatch):
    foundry_server = _start_fake_foundry_server()
    elevenlabs_server = _start_fake_server()
    try:
        runtime_dir = tmp_path / "runtime"
        tts_base_url = f"http://127.0.0.1:{elevenlabs_server.server_port}"
        _write_runtime_fixture(runtime_dir, "https://pod.example.com", tts_base_url)

        monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "foundry-test-key")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

        config_path = runtime_dir / "config" / "podcast.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "podcast:",
                    "  title: Prompting for Competence",
                    "  description: Personal learning podcast feed generated from queued topics.",
                    "  author: vatioz",
                    "  base_url: https://pod.example.com",
                    "  language: en-us",
                    "worker:",
                    "  poll_seconds: 1",
                    "research:",
                    "  provider: azure_foundry",
                    f"  endpoint: http://127.0.0.1:{foundry_server.server_port}/openai/v1/",
                    "  model: gpt-4.1-mini",
                    "  api_key_env: AZURE_OPENAI_API_KEY",
                    "  timeout_seconds: 10",
                    "script:",
                    "  provider: azure_foundry",
                    "  style: explanatory_podcast",
                    f"  endpoint: http://127.0.0.1:{foundry_server.server_port}/openai/v1/",
                    "  model: gpt-4.1-mini",
                    "  api_key_env: AZURE_OPENAI_API_KEY",
                    "  timeout_seconds: 10",
                    "  overview_target_minutes: 5",
                    "  deep_dive_target_minutes: 18",
                    "tts:",
                    "  provider: elevenlabs",
                    "  voice_id: test-voice",
                    "  model_id: eleven_multilingual_v2",
                    "  output_format: mp3_44100_128",
                    f"  base_url: {tts_base_url}",
                    "  timeout_seconds: 10",
                    "publishing:",
                    "  target: app_hosted",
                    "  public_base_url: https://pod.example.com",
                    f"  export_dir: {runtime_dir / 'publish'}",
                    "  auto_publish: true",
                    "ui:",
                    "  recent_topics_limit: 12",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        modules = _reload_modules()
        storage = modules["storage"]
        config = modules["config"]
        worker_module = modules["worker"]

        storage.create_topic(prompt="Model Context Protocol for engineering teams", overview=True, deep_dive=False)
        worker = worker_module.DummyWorker(config.load_config())

        assert worker.process_once() is True

        state = storage.load_state()
        topic = state["topics"][0]
        variant = topic["variants"]["overview"]
        script_path = Path(variant["script_path"])
        script_text = script_path.read_text(encoding="utf-8")

        assert script_path.exists()
        assert _FakeFoundryHandler.requests
        assert "abstract protocol trivia" in script_text
        assert _FakeElevenLabsHandler.requests
        assert "Model Context Protocol" in _FakeElevenLabsHandler.requests[0]["json"]["text"]
        assert variant["audio"]["provider"] == "elevenlabs"
        assert variant["audio"]["voice"] == "test-voice"
        assert variant["audio"]["model"] == "eleven_multilingual_v2"
        assert variant["audio"]["segment_count"] == 1
    finally:
        foundry_server.shutdown()
        foundry_server.server_close()
        elevenlabs_server.shutdown()
        elevenlabs_server.server_close()



def test_worker_can_use_azure_speech_for_audio(tmp_path, monkeypatch):
    class _FakeSpeechConfig:
        def __init__(self, subscription=None, endpoint=None, region=None):
            self.subscription = subscription
            self.endpoint = endpoint
            self.region = region
            self.speech_synthesis_voice_name = None
            self.output_format = None

        def set_speech_synthesis_output_format(self, value):
            self.output_format = value

    class _FakeAudioOutputConfig:
        def __init__(self, filename):
            self.filename = filename

    class _FakeSynthesisResult:
        def __init__(self, reason):
            self.reason = reason
            self.cancellation_details = None

    class _FakeSpeechSynthesizer:
        last_call = None

        def __init__(self, speech_config=None, audio_config=None):
            self.speech_config = speech_config
            self.audio_config = audio_config

        def speak_text_async(self, text):
            self.__class__.last_call = {
                "text": text,
                "speech_config": self.speech_config,
                "audio_config": self.audio_config,
            }
            Path(self.audio_config.filename).write_bytes(b"ID3fake-azure-speech-mp3")
            return type("R", (), {"get": lambda _self: _FakeSynthesisResult("SynthesizingAudioCompleted")})()

    class _FakeSpeechSdk:
        class ResultReason:
            SynthesizingAudioCompleted = "SynthesizingAudioCompleted"
            Canceled = "Canceled"

        class SpeechSynthesisOutputFormat:
            Audio24Khz96KBitRateMonoMp3 = "Audio24Khz96KBitRateMonoMp3"

        SpeechConfig = _FakeSpeechConfig
        SpeechSynthesizer = _FakeSpeechSynthesizer
        audio = type("A", (), {"AudioOutputConfig": _FakeAudioOutputConfig})

    foundry_server = _start_fake_foundry_server()
    try:
        runtime_dir = tmp_path / "runtime"
        _write_runtime_fixture(
            runtime_dir,
            "https://pod.example.com",
            "http://127.0.0.1:9",
            f"http://127.0.0.1:{foundry_server.server_port}/openai/v1/",
        )

        monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "foundry-test-key")
        monkeypatch.setenv("AZURE_SPEECH_KEY", "speech-test-key")

        modules = _reload_modules()
        modules["tts_azure_speech"]._load_speechsdk = lambda: _FakeSpeechSdk
        storage = modules["storage"]
        config = modules["config"]
        worker_module = modules["worker"]

        config_path = runtime_dir / "config" / "podcast.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "podcast:",
                    "  title: Prompting for Competence",
                    "  description: Personal learning podcast feed generated from queued topics.",
                    "  author: vatioz",
                    "  base_url: https://pod.example.com",
                    "  language: en-us",
                    "worker:",
                    "  poll_seconds: 1",
                    "research:",
                    "  provider: azure_foundry",
                    f"  endpoint: http://127.0.0.1:{foundry_server.server_port}/openai/v1/",
                    "  model: gpt-4.1-mini",
                    "  api_key_env: AZURE_OPENAI_API_KEY",
                    "  timeout_seconds: 10",
                    "script:",
                    "  provider: azure_foundry",
                    f"  endpoint: http://127.0.0.1:{foundry_server.server_port}/openai/v1/",
                    "  model: gpt-4.1-mini",
                    "  api_key_env: AZURE_OPENAI_API_KEY",
                    "  timeout_seconds: 10",
                    "  style: explanatory_podcast",
                    "tts:",
                    "  provider: azure_speech",
                    "  mode: sync",
                    "  speech_endpoint: https://example-speech-resource.cognitiveservices.azure.com",
                    "  speech_api_key_env: AZURE_SPEECH_KEY",
                    "  speech_voice: en-US-Ava:DragonHDLatestNeural",
                    "  speech_output_format: audio-24khz-96kbitrate-mono-mp3",
                    "  speech_sync_max_minutes: 9.5",
                    "  timeout_seconds: 10",
                    "publishing:",
                    "  target: app_hosted",
                    "  public_base_url: https://pod.example.com",
                    f"  export_dir: {runtime_dir / 'publish'}",
                    "  auto_publish: true",
                    "ui:",
                    "  recent_topics_limit: 12",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        storage.create_topic(prompt="Model Context Protocol for engineering teams", overview=True, deep_dive=False)
        worker = worker_module.DummyWorker(config.load_config())

        assert worker.process_once() is True

        state = storage.load_state()
        topic = state["topics"][0]
        variant = topic["variants"]["overview"]
        audio_path = Path(variant["audio_path"])

        assert audio_path.exists()
        assert audio_path.read_bytes() == b"ID3fake-azure-speech-mp3"
        assert variant["audio"]["provider"] == "azure_speech"
        assert variant["audio"]["voice"] == "en-US-Ava:DragonHDLatestNeural"
        assert variant["audio"]["voice_id"] == "en-US-Ava:DragonHDLatestNeural"
        assert variant["audio"]["model"] == "speech_sync"
        assert variant["audio"]["segment_count"] == 1
        assert _FakeSpeechSynthesizer.last_call is not None
    finally:
        foundry_server.shutdown()
        foundry_server.server_close()


def test_worker_marks_failed_stage_and_error_when_audio_generation_fails(tmp_path, monkeypatch):
    foundry_server = _start_fake_foundry_server()
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(
        runtime_dir,
        "https://pod.example.com",
        "http://127.0.0.1:9",
        f"http://127.0.0.1:{foundry_server.server_port}/openai/v1/",
    )

    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "foundry-test-key")

    modules = _reload_modules()
    storage = modules["storage"]
    config = modules["config"]
    worker_module = modules["worker"]

    storage.create_topic(prompt="Failure semantics for podcast pipeline", overview=True, deep_dive=False)
    worker = worker_module.DummyWorker(config.load_config())

    try:
        worker.process_once()
        assert False, "expected audio generation to fail"
    except RuntimeError as exc:
        assert "ElevenLabs API key" in str(exc)

    state = storage.load_state()
    topic = state["topics"][0]
    variant = topic["variants"]["overview"]

    assert topic["status"] == "failed"
    assert "ElevenLabs API key" in topic["last_error"]
    assert topic["research"]["status"] == "done"
    assert topic["research"]["error"] is None
    assert variant["status"] == "failed"
    assert variant["script"]["status"] == "done"
    assert variant["script"]["error"] is None
    assert variant["audio"]["status"] == "failed"
    assert "ElevenLabs API key" in variant["audio"]["error"]
    assert variant["publish"]["status"] == "queued"
    assert variant["publish"]["error"] is None
    foundry_server.shutdown()
    foundry_server.server_close()



def test_index_shows_stage_by_stage_status_and_stage_errors(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    _write_runtime_fixture(runtime_dir, "https://pod.example.com", "http://127.0.0.1:9")
    monkeypatch.setenv("POD_RUNTIME_DIR", str(runtime_dir))

    modules = _reload_modules()
    storage = modules["storage"]
    app_module = importlib.import_module("app.app")
    importlib.reload(app_module)

    topic = storage.create_topic(prompt="Pipeline visibility", overview=True, deep_dive=False)

    def apply(item: dict) -> None:
        item["status"] = "failed"
        item["last_error"] = "audio stage failed"
        item["research"]["status"] = "done"
        item["research"]["error"] = None
        overview = item["variants"]["overview"]
        overview["status"] = "failed"
        overview["script"]["status"] = "done"
        overview["script"]["error"] = None
        overview["audio"]["status"] = "failed"
        overview["audio"]["error"] = "ElevenLabs API key is not configured"
        overview["publish"]["status"] = "queued"
        overview["publish"]["error"] = None

    storage.update_topic(topic["id"], apply)

    app = app_module.create_app()
    app.config["TESTING"] = True
    try:
        response = app.test_client().get("/")
        body = response.get_data(as_text=True)
    finally:
        app.config["WORKER"].stop()

    assert response.status_code == 200
    assert "Pipeline visibility" in body
    assert "research" in body
    assert "script" in body
    assert "audio" in body
    assert "publish" in body
    assert "status-failed" in body
    assert "ElevenLabs API key is not configured" in body
