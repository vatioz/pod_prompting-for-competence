# Existing Functionality Spec

## Purpose
This document describes the **current implemented functionality** of the podcast-learning-agent PoC as it exists now. It is not a future roadmap. It captures the behavior of the current Dockerized Flask app, runtime files, and generated outputs.

## High-level summary
The project currently provides:
- a small Flask web UI for submitting podcast topics
- a YAML-backed topic queue and topic state store
- a dummy in-process worker that simulates a pipeline
- generation of research notes, script markdown, MP3 audio artifacts, and RSS feed entries
- a feed endpoint and audio endpoint suitable for local app hosting
- a runtime directory intended to be the live source of truth for config and generated artifacts

It does **not** currently provide:
- real research generation
- real script writing
- real TTS synthesis from generated text
- automated publication/export to Azure or another public host
- authentication, access control, or production hardening

---

## Repository shape
Relevant active areas:
- `app/` — Flask app, worker, storage, feed generation, templates, bundled sample audio
- `scripts/run_app.py` — starts the app under Waitress
- `compose.yaml` — Docker service definition
- `Dockerfile` — builds the app container image
- `config/` — seed config copied into runtime on first start only
- `data/` — seed topic state copied into runtime on first start only
- `runtime/` — live state: config, topic queue, generated feed/audio/scripts/research
- `archive/legacy-2026-06-12/` — archived legacy PoC/export assets

---

## Runtime and deployment model
### Docker service
There is currently one Docker Compose service:
- `app`

Current behavior:
- container binds to port `6001`
- `./runtime` is mounted into the container as `/data`
- runtime env used by the service:
  - `POD_RUNTIME_DIR=/data`
  - `POD_HOST=0.0.0.0`
  - `POD_PORT=6001`

### App startup
On startup the app:
1. ensures runtime directories exist
2. seeds runtime files from `config/` and `data/` if missing
3. loads runtime config from `runtime/config/podcast.yaml`
4. starts an in-process background worker thread
5. regenerates `runtime/generated/feed.xml`

### Source of truth for public URL
The live source of truth for the podcast base URL is:
- `runtime/config/podcast.yaml`

Current intended usage:
- if the user wants to change the public feed URL, they edit `runtime/config/podcast.yaml`
- `compose.yaml` no longer injects `POD_BASE_URL`

---

## Live runtime files
### Runtime config
- `runtime/config/podcast.yaml`
  - podcast title
  - description
  - author
  - `base_url`
  - language
  - worker poll interval
  - UI recent-topics limit

- `runtime/config/listener-profile.md`
  - static listener context shown in the UI

### Topic state
- `runtime/data/topics.yaml`
  - persistent YAML store for topics and per-variant status

### Generated outputs
- `runtime/generated/feed.xml`
- `runtime/generated/audio/*.mp3`
- `runtime/generated/scripts/*.md`
- `runtime/generated/research/*.md`

---

## Web UI
### Route: `GET /`
Renders the main UI.

Current UI sections:
- podcast title
- feed URL display: `<base_url>/feed.xml`
- topic submission form
- recent topics list
- topic/variant statuses
- retry button per topic
- remove-from-feed button per topic
- static listener context panel

### Route: `POST /submit`
Form fields:
- `prompt`
- `variant_overview`
- `variant_deep_dive`

Behavior:
- validates that prompt is non-empty
- validates that at least one variant is enabled
- creates a queued topic in YAML state
- wakes the worker
- redirects back to `/`

### Route: `POST /topics/<topic_id>/retry`
Behavior:
- resets failed topic and/or failed variants back to `queued`
- wakes the worker
- redirects back to `/`

### Route: `POST /topics/<topic_id>/unpublish`
Behavior:
- marks the topic as deleted/unpublished in YAML state
- regenerates the feed
- redirects back to `/`

---

## Feed and audio serving
### Route: `GET /feed.xml`
Behavior:
- serves the generated RSS feed from `runtime/generated/feed.xml`
- if the file does not exist, regenerates it first
- returns `application/rss+xml`

### Route: `GET /audio/<filename>`
Behavior:
- serves files from `runtime/generated/audio/`
- uses file extension to choose MIME type:
  - `.mp3` -> `audio/mpeg`
  - `.m4a` -> `audio/mp4`
  - `.wav` -> `audio/wav`

### Feed enclosure path convention
Current feed generation emits audio enclosure URLs as:
- `<base_url>/audio/<filename>`

This matches a static publish layout where `feed.xml` lives at the site root and audio files live under `/audio/`.

---

## Topic data model
Each topic in `runtime/data/topics.yaml` currently contains:
- `id`
- `slug`
- `prompt`
- `status`
- `deleted`
- `created_at`
- `updated_at`
- `last_error`
- `research`
  - `status`
  - `path`
- `variants`
  - `overview`
  - `deep_dive`

Each variant currently stores:
- `enabled`
- `status`
- `script_path`
- `audio_path`
- `published_title`
- `published_at`

Variant statuses currently used include:
- `queued`
- `processing`
- `published`
- `failed`
- `disabled`

Top-level topic statuses currently used include:
- `queued`
- `processing`
- `published`
- `failed`
- `unpublished`

---

## Worker behavior
The worker is currently a **dummy sequential in-process worker**.

### Worker loop
- runs in a daemon thread inside the Flask process
- polls every configured number of seconds
- also reacts to explicit wake-up events after submit/retry

### Processing order
For each queued topic, the worker:
1. marks topic `processing`
2. creates dummy research markdown
3. for each enabled variant (`overview`, `deep_dive`):
   - creates dummy script markdown
   - copies a bundled sample MP3 into generated audio output
   - records metadata as published
4. marks topic `published`
5. regenerates the RSS feed

### Important current limitation
The worker does **not** do real AI work.
Current outputs are placeholders:
- research file: static dummy notes
- script file: static dummy script text with topic/variant labels
- audio file: copied bundled sample MP3, not topic-specific synthesized narration

---

## Feed generation behavior
Feed generation loads topic state from YAML and includes all variants that are:
- enabled
- published
- not deleted via parent topic

For each feed item it emits:
- title
- description
- RFC822 `pubDate`
- non-permalink `guid`
- enclosure URL
- enclosure byte length
- enclosure MIME type

If an old or stale audio path is stored in state, feed generation tries to resolve by filename within `runtime/generated/audio/`.
This is a compatibility measure for previously stored paths.

---

## Seed and fallback behavior
On first startup, if runtime files do not exist, the app seeds them from:
- `config/podcast.yaml`
- `config/listener-profile.md`
- `data/topics.yaml`

Default config fallback in code includes:
- title: `Podcast Learning Agent`
- default base URL: `http://127.0.0.1:6001`
- language: `en-us`
- worker poll interval: `3`
- recent topics limit: `12`

---

## Archived functionality
The repository previously contained separate paths for:
- a static `feed-poc/`
- an `azure-static-test/` export bundle
- extra runtime/test directories

Those have been archived or removed from the active project layout.
They are not part of the current active functionality.

---

## Known current gaps and limitations
1. **No automated publishing pipeline**
   - Publishing `runtime/generated/feed.xml` and `runtime/generated/audio/*.mp3` to Azure static website or another public host is still manual.

2. **No real research generation**
   - research output is placeholder markdown only.

3. **No real script writing**
   - scripts are placeholders.

4. **No real TTS generation**
   - audio is copied from bundled sample MP3 files.

5. **No production deployment hardening**
   - no auth
   - no TLS handling in-app
   - no background job isolation beyond an in-process thread
   - no queue broker or separate worker service

6. **No export/deploy synchronization**
   - if using Azure Static Website, the user must manually keep `feed.xml` and `audio/` in sync when publishing.

---

## Current user-visible workflow
1. Start app via Docker Compose
2. Edit `runtime/config/podcast.yaml` if public feed URL changes
3. Open the web UI
4. Submit a topic with Overview and/or Deep Dive enabled
5. Worker creates placeholder research/script/audio outputs
6. Feed is regenerated
7. User can access:
   - app feed at `/feed.xml`
   - app-hosted audio at `/audio/<filename>`
8. If using static hosting (for example Azure Static Website), user manually publishes:
   - `runtime/generated/feed.xml`
   - `runtime/generated/audio/*.mp3`

---

## Non-goals of this spec
This document does not specify:
- the future ElevenLabs pipeline
- future research strategy
- future script-writing strategy
- future automatic upload/deploy design
- future multi-stage job orchestration

Those belong in a separate forward-looking design/spec document.
