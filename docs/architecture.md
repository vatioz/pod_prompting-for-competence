# Architecture

This document describes how the app is actually built today. For setup and usage, see the [README](../README.md).

## Overview

A single Flask process serves the web UI and podcast feed, and runs an in-process background worker thread that turns queued topics into published episodes. All state lives on disk as YAML and Markdown files under a runtime directory — there is no database, queue broker, or separate worker service.

```
submit topic  ->  research  ->  script  ->  TTS  ->  publish
   (web UI)      (Azure       (Azure     (Azure    (feed +
                  Foundry      Foundry    Speech    audio
                  + web        Responses  or        bundle)
                  search)      API)       ElevenLabs)
```

## Process model

`create_app()` in `app/app.py` does the following on startup:

1. `ensure_runtime_dirs()` creates the runtime tree and seeds missing files from `config/` and `data/`
2. loads `runtime/config/podcast.yaml` merged over `DEFAULT_CONFIG` in `app/config.py`
3. constructs and starts the worker thread
4. rebuilds publish outputs so a feed exists immediately

The worker (`app/worker.py`) runs as a daemon thread. It polls every `worker.poll_seconds` and is woken immediately by an event after submit or retry. It processes one topic per iteration and loops without sleeping while work remains.

Because the worker shares the Flask process, running multiple app replicas against the same runtime directory is not supported.

## Pipeline stages

Each topic has one research artifact and up to two variants (`overview`, `deep_dive`). Each variant runs through script, audio, and publish stages independently.

| Stage | Module | Output | Notes |
|---|---|---|---|
| Research | `app/research.py` | `runtime/generated/research/<stem>.md` | Once per topic, shared by both variants |
| Script | `app/script_writer.py` | `runtime/generated/scripts/<stem>.md` | Per variant |
| Audio | `app/tts_dispatch.py` | `runtime/generated/audio/<stem>.mp3` | Per variant |
| Publish | `app/publisher.py` | feed + bundle | Per variant, then feed rebuild |

### Research

Calls the Azure OpenAI / Azure Foundry **Responses API** (`POST <endpoint>/responses`) with a `web_search` tool. The prompt comes from `runtime/config/prompts/research_prompt.txt`.

The result is validated before being accepted — it must exceed `research.minimum_characters` and contain all of these headings:

`## Topic Statement`, `## Key Concepts`, `## Why It Matters`, `## Practical Examples`, `## Tradeoffs / Caveats`, `## Glossary / Jargon Expansion`, `## Source Notes`, `## Unresolved Questions`

URLs from web search calls and `url_citation` annotations are collected and rewritten into the `## Source Notes` section, so citations reflect what the model actually retrieved rather than what it claimed.

`research.allowed_domains` and `research.blocked_domains` are passed through as search tool filters.

### Script

Also uses the Responses API, with the research Markdown as input and a variant-specific prompt (`script_overview_prompt.txt` or `script_deep_dive_prompt.txt`). Output is validated to start with a Markdown title, exceed a minimum length, and contain multiple paragraphs.

Optional per-topic steering text entered in the UI is stored on the topic as `user_inputs.script_steering` and rendered into the script prompt.

### Audio

`app/tts_dispatch.py` selects a provider from `tts.provider`:

- `azure_speech` — `app/tts_azure_speech.py`, uses the Azure Speech SDK
- `elevenlabs` — `app/tts_elevenlabs.py`, uses the ElevenLabs HTTP API
- `azure_openai` — **not implemented**, raises at dispatch time

Any other value raises `Unsupported tts.provider`.

### Publish

`app/publisher.py` supports two families of targets:

**App-hosted** (`app_hosted`, `local_app`, `preview_app`) — the Flask app serves `/feed.xml`, `/audio/<file>`, and `/images/<file>` directly. Variants reach status `published`.

**Export** (`azure_static`, `local_export`, `export_bundle`, `manual_export`) — a self-contained bundle is rebuilt from scratch at `runtime/publish/current/` containing `feed.xml`, `audio/`, and `images/`. Variants reach status `exported`.

When the target is `azure_static` **and** `publishing.deploy_enabled` is true, the bundle is uploaded by `app/azure_static_uploader.py` to Blob Storage static website hosting.

The publish bundle is deleted and rebuilt on every publish. It is derived state — the source of truth is `runtime/data/topics.yaml` plus the generated artifacts.

## Azure static deploy safety

`app/azure_static_uploader.py` has guardrails worth knowing about, because it deletes remote blobs:

- **Root delete guard** — stale-file cleanup at the root of `$web` is refused unless `publishing.azure_allow_root_delete` is explicitly set. Normally you set `publishing.azure_path_prefix` so deletion is scoped to that prefix.
- **Prefix/URL consistency** — `publishing.public_base_url` must end with the same path as `azure_path_prefix`, so generated feed URLs cannot silently point somewhere other than where files were uploaded.
- **Cache headers** — `feed.xml` is uploaded `no-cache, no-store, must-revalidate`; MP3s get `max-age=31536000, immutable`. Audio filenames are content-stable, the feed is not.

Credentials come only from a connection string in the env var named by `publishing.azure_connection_string_env`. Any `azure_credential_mode` other than `connection_string` is rejected.

## State and storage

`runtime/data/topics.yaml` is the single source of truth for topic state. `app/storage.py` writes it atomically (write to a temp file in the same directory, then `os.replace`) so a crash mid-write cannot truncate it.

Each topic holds `id`, `slug`, `prompt`, `status`, `deleted`, timestamps, `last_error`, `user_inputs`, a `research` stage dict, and a `variants` dict. Each variant holds `enabled`, `status`, and separate `script`, `audio`, and `publish` stage dicts, each with its own `status` and `error`.

Stage statuses: `queued`, `processing`, `done`, `failed`.
Variant statuses: `queued`, `processing`, `generated`, `exported`, `published`, `failed`, `disabled`.

Topic status is derived from its variants via `recompute_topic_status()` rather than being set independently.

### Resumability

Stage state is what makes retry cheap. On retry, the worker checks whether each stage is already `done` **and** its artifact still exists on disk; if so, that stage is skipped. A failed TTS call therefore does not re-run research or script generation, and does not re-spend tokens.

## Configuration

`DEFAULT_CONFIG` in `app/config.py` is the base. `runtime/config/podcast.yaml` is deep-merged over it, then normalized (URLs stripped of trailing slashes, booleans coerced, path prefixes cleaned).

Seed files in `config/` and `data/` are copied into `runtime/` **only when the destination does not exist**. Editing a seed file never overwrites live runtime state.

Endpoint and model settings fall back to `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, and `AZURE_OPENAI_MODEL` when absent from YAML. API keys are read only from environment variables — the env var *names* are configured in YAML, never the values.

`config/research-profile.md` and `config/script-guidance.md` are human-authored reference notes describing editorial intent. They are not read by application code; the live prompts are the files under `config/prompts/`.

## Web UI

Server-rendered Jinja templates with a small amount of vanilla JS. `app/static/app.js` polls `GET /ui/topics` on an interval and swaps in a re-rendered `_topics_list.html` fragment, so the topic list updates without a full page reload.

Requests carrying `X-Requested-With: XMLHttpRequest` get `204`/`422` responses instead of redirects, which lets submit and retry work without navigation.

| Route | Purpose |
|---|---|
| `GET /` | Main UI |
| `GET /ui/topics` | Topic list fragment for polling |
| `POST /submit` | Queue a topic |
| `POST /topics/<id>/retry` | Reset failed stages and re-run |
| `POST /topics/<id>/unpublish` | Mark deleted and rebuild the feed |
| `GET /feed.xml` | RSS feed |
| `GET /audio/<file>` | Generated MP3 |
| `GET /images/<file>` | Show artwork |

There is **no authentication on any route.** See [SECURITY.md](../SECURITY.md).

## Testing

`tests/` covers the pipeline stages, storage atomicity, feed generation, retry semantics, publishing targets, the Azure uploader guardrails, and the web UI. External services are stubbed — the suite makes no network calls and needs no API keys.
