# ElevenLabs Podcast Pipeline Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Replace the current dummy research/script/audio pipeline with a real MVP pipeline that produces publishable podcast episodes using ElevenLabs TTS and prepares feed + audio artifacts for upload.

**Architecture:** Keep the current file-backed app and runtime model, but split the worker into four explicit stages: research → script writing → TTS → publish/export. Persist artifacts on disk under `runtime/generated/`, store stage status in `runtime/data/topics.yaml`, and treat public hosting/upload as a separate final stage so feed publishing and audio publishing stay synchronized.

**Tech Stack:** Flask, file-backed YAML state, Python worker, Markdown artifacts, ElevenLabs HTTP API/SDK, MP3 output, Azure Static Website upload step.

---

## Current context / assumptions

- Live app config comes from `runtime/config/podcast.yaml`.
- Live state comes from `runtime/data/topics.yaml`.
- Generated artifacts live under `runtime/generated/`.
- Current worker is still a dummy pipeline in `app/worker.py`.
- The app already generates RSS from published items in `app/feedgen.py`.
- Public publish/upload is currently manual.
- User has created an ElevenLabs account and wants to try it for real audio generation.
- Existing public hosting target is Azure Static Website, so `feed.xml` and `/audio/*.mp3` must be uploaded together.

---

## Proposed approach

1. Add a real pipeline configuration section for LLM/script/TTS/upload settings.
2. Expand topic state so each variant tracks separate research, script, audio, and publish stages.
3. Replace the dummy worker with explicit stage functions.
4. Implement research as a deterministic artifact step first, even if the research source is still a stub or manual prompt-to-notes layer.
5. Implement script generation next, producing a narration-ready Markdown or plain-text script per variant.
6. Implement ElevenLabs TTS as a dedicated service module that turns scripts into MP3 files.
7. Add an export/publish stage that prepares a static bundle for Azure upload and updates the feed only when audio artifacts exist.
8. Keep actual Azure upload either manual-first or as an optional scripted step after the export bundle exists.

---

## Files likely to change

### Modify
- `app/config.py`
- `app/storage.py`
- `app/worker.py`
- `app/feedgen.py`
- `app/templates/index.html`
- `runtime/config/podcast.yaml` (example live config)
- `config/podcast.yaml` (seed default)
- `README.md`
- `runtime/README.md`
- `requirements.txt`

### Create
- `app/research.py`
- `app/script_writer.py`
- `app/tts_elevenlabs.py`
- `app/publisher.py`
- `scripts/export_static_bundle.py`
- `scripts/upload_to_azure.py` (optional, phase 2)
- `tests/test_storage.py`
- `tests/test_feedgen.py`
- `tests/test_tts_elevenlabs.py`
- `tests/test_publisher.py`

---

## Phase breakdown

### Phase 1: Data model and configuration cleanup

#### Task 1: Add TTS/publish config to the app config model

**Objective:** Introduce explicit config for ElevenLabs and publishing without implementing behavior yet.

**Files:**
- Modify: `app/config.py`
- Modify: `config/podcast.yaml`
- Modify: `runtime/config/podcast.yaml`

**Planned config shape:**

```yaml
tts:
  provider: elevenlabs
  voice_id: REPLACE_ME
  model_id: eleven_multilingual_v2
  output_format: mp3_44100_128
  stability: 0.45
  similarity_boost: 0.75
  style: 0.2
  use_speaker_boost: true
publishing:
  target: azure_static
  public_base_url: https://podappstorage.z6.web.core.windows.net
  export_dir: /data/publish
  auto_publish: false
research:
  mode: manual_or_stub
script:
  style: explanatory_podcast
```

**Validation:**
- `python -m py_compile app/config.py`
- start app and confirm existing routes still work

---

#### Task 2: Expand topic state schema for explicit pipeline stages

**Objective:** Make research/script/audio/publish first-class tracked stages instead of implicit side effects.

**Files:**
- Modify: `app/storage.py`
- Test: `tests/test_storage.py`

**Add fields per variant:**

```yaml
variants:
  overview:
    enabled: true
    status: queued
    script:
      status: queued
      path: null
      model: null
    audio:
      status: queued
      path: null
      provider: null
      voice_id: null
      duration_seconds: null
    publish:
      status: queued
      public_url: null
```

**Validation:**
- create a new topic and verify the saved YAML contains the expanded structure
- verify backward compatibility migration for existing topics in `runtime/data/topics.yaml`

---

### Phase 2: Research stage

#### Task 3: Create a dedicated research module

**Objective:** Move research artifact generation out of `DummyWorker` into a standalone module.

**Files:**
- Create: `app/research.py`
- Modify: `app/worker.py`

**Behavior for MVP:**
- input: topic prompt
- output: Markdown notes file under `runtime/generated/research/`
- initial implementation can still be lightweight, but must produce a deterministic artifact with headings like:
  - topic
  - key concepts
  - likely episode angle
  - unresolved questions

**Validation:**
- submit one topic
- verify research file is written and state updates correctly

---

#### Task 4: Define research quality guardrails

**Objective:** Prevent garbage-in scripts by enforcing a minimum research artifact structure.

**Files:**
- Modify: `app/research.py`
- Test: `tests/test_storage.py` or `tests/test_research.py`

**Guardrails:**
- non-empty body
- required headings present
- minimum character count
- fail topic cleanly if research artifact is invalid

**Validation:**
- simulate invalid research output and verify topic moves to `failed` with useful `last_error`

---

### Phase 3: Script-writing stage

#### Task 5: Create a script writer module

**Objective:** Generate narration-ready script files per variant.

**Files:**
- Create: `app/script_writer.py`
- Modify: `app/worker.py`

**Output format:**
- plain text or Markdown optimized for speech
- separate files for overview and deep-dive
- include a short intro, body, and close
- avoid stage directions that should not be spoken aloud

**Per-variant intent:**
- overview: 2–4 minutes target
- deep_dive: 5–10 minutes target

**Validation:**
- verify `runtime/generated/scripts/*.md` exists for each enabled variant
- verify script file is non-empty and human-readable

---

#### Task 6: Add script constraints for TTS readiness

**Objective:** Make the scripts sound good when synthesized.

**Files:**
- Modify: `app/script_writer.py`

**Rules:**
- short-to-medium sentence lengths
- expand acronyms where useful
- no Markdown bullets in spoken body unless intentionally converted
- remove URLs/code blocks from spoken content
- add pronunciation hints or rewrite awkward phrases

**Validation:**
- inspect generated script manually for one technical topic
- confirm it reads like speech, not notes

---

### Phase 4: ElevenLabs TTS integration

#### Task 7: Add ElevenLabs dependency and config loading

**Objective:** Introduce a dedicated TTS integration point.

**Files:**
- Modify: `requirements.txt`
- Create: `app/tts_elevenlabs.py`
- Modify: `app/config.py`

**Implementation options:**
- preferred: official ElevenLabs SDK if it stays lightweight and stable
- fallback: direct HTTP requests with `requests`

**Required secret:**
- `ELEVENLABS_API_KEY`

**Validation:**
- app can start with TTS module imported
- clear error if API key is missing

---

#### Task 8: Implement script-to-MP3 generation

**Objective:** Turn a generated script file into a real MP3 artifact.

**Files:**
- Create: `app/tts_elevenlabs.py`
- Modify: `app/worker.py`
- Test: `tests/test_tts_elevenlabs.py`

**Behavior:**
- read script text
- call ElevenLabs TTS
- save MP3 under `runtime/generated/audio/`
- record provider, voice_id, and path in state

**Important constraint:**
- long scripts may need chunking before TTS request submission

**Validation:**
- run on one short script
- verify MP3 exists and size > 0
- verify state records `.mp3` path

---

#### Task 9: Add chunking/concatenation strategy for long episodes

**Objective:** Avoid failure on long deep-dive scripts.

**Files:**
- Modify: `app/tts_elevenlabs.py`
- Possibly create: `app/audio_utils.py`

**Strategy:**
- split script by paragraphs/sections
- synthesize chunk-by-chunk
- concatenate into final MP3
- keep chunk temp files in a temp working dir under runtime

**Validation:**
- synthesize a script that exceeds single-request comfort limits
- verify final MP3 is produced cleanly

---

### Phase 5: Publishing/export stage

#### Task 10: Separate “audio generated” from “publicly published”

**Objective:** Stop conflating local generation with public availability.

**Files:**
- Modify: `app/storage.py`
- Modify: `app/worker.py`
- Modify: `app/feedgen.py`

**Rule:**
- only include an episode in the public feed if its publish stage is complete or if the system is explicitly configured for app-hosted local serving

**Validation:**
- generate audio without publish step
- verify feed behavior matches chosen mode

---

#### Task 11: Create a static export bundle builder

**Objective:** Produce an Azure-ready bundle with synchronized `feed.xml` and `/audio/*.mp3`.

**Files:**
- Create: `app/publisher.py`
- Create: `scripts/export_static_bundle.py`
- Test: `tests/test_publisher.py`

**Output target:**
- e.g. `runtime/publish/current/`
  - `feed.xml`
  - `audio/*.mp3`
  - optional `cover.png`

**Validation:**
- run export script
- verify bundle contains matching feed + audio paths

---

#### Task 12: Optional Azure upload script

**Objective:** Add a repeatable publish command, while keeping it optional.

**Files:**
- Create: `scripts/upload_to_azure.py`
- Modify: `README.md`

**Behavior:**
- upload static bundle to Azure Static Website container
- set correct content types:
  - `feed.xml` → `application/rss+xml` or `application/xml`
  - `*.mp3` → `audio/mpeg`
- upload feed and audio as one deployment unit

**Validation:**
- dry-run mode first
- then real upload to test account/container

---

### Phase 6: UI and operator ergonomics

#### Task 13: Expose pipeline stage visibility in the UI

**Objective:** Make it obvious where a topic is stuck: research, script, TTS, or publish.

**Files:**
- Modify: `app/templates/index.html`
- Modify: `app/app.py`

**Display:**
- research status
- script status
- audio status
- publish status
- last error

**Validation:**
- submit topic and observe stage progression in browser

---

#### Task 14: Add retry semantics by stage

**Objective:** Let retries target the failed stage, not blindly rerun everything.

**Files:**
- Modify: `app/storage.py`
- Modify: `app/app.py`
- Modify: `app/templates/index.html`

**Validation:**
- force a TTS failure
- retry and verify research/script artifacts are reused instead of regenerated unnecessarily

---

## Validation plan

### Functional checks
- submit a topic from the UI
- research file appears
- script file appears
- ElevenLabs MP3 appears
- export bundle contains synchronized `feed.xml` + `/audio/*.mp3`
- public URL serves playable audio in browser/podcast app

### State checks
- `runtime/data/topics.yaml` reflects stage-by-stage progress
- failures are visible in `last_error`
- reruns do not duplicate already-good artifacts unless explicitly requested

### Feed checks
- feed only references real public URLs
- enclosure MIME is `audio/mpeg`
- no stale local `/media` or host-only paths appear

---

## Risks / tradeoffs

### 1. Script quality may matter more than TTS quality
Even very good voices sound bad with note-like scripts.

### 2. Long-form TTS chunking can create audible joins
Need paragraph-aware chunking and maybe silence normalization later.

### 3. Publishing must stay atomic
Uploading feed before audio is available will create broken episodes.

### 4. Cost and latency
ElevenLabs may be great for quality, but cost/turnaround should be measured before scaling.

### 5. Research provenance
If research is weak, the whole episode quality drops. This stage deserves real attention, not just “some notes on disk.”

---

## Open questions to settle before implementation

1. What is the desired default ElevenLabs voice?
2. Do you want one voice for all episodes or different voices per variant?
3. Should the script stage use an external LLM immediately, or do you want a structured/manual intermediate step first?
4. Should Azure upload remain manual for the first real TTS milestone, or should we automate export + upload right away?
5. Do you want episodes to appear in the public feed only after upload succeeds, or is local app-hosted preview still important?

---

## Recommended implementation order

1. Phase 1: config + state schema
2. Phase 2: research module
3. Phase 3: script writer
4. Phase 4: ElevenLabs TTS
5. Phase 5 Task 11: static export bundle
6. Phase 6: UI visibility and retry ergonomics
7. Phase 5 Task 12: automated Azure upload

That sequencing keeps the work incremental and debuggable.

---

## Suggested first milestone

**Milestone A: “One real topic to one real MP3 on disk.”**

Success criteria:
- submit topic
- research artifact generated
- script artifact generated
- ElevenLabs produces MP3
- topic state reflects real pipeline steps
- feed/export work can remain manual for this milestone

That is the best first proof that the core content loop works.

---

## Suggested second milestone

**Milestone B: “One-click static export bundle for Azure.”**

Success criteria:
- build `feed.xml` + `/audio/*.mp3` bundle together
- upload manually or via script
- Pocket Casts can fetch and play the resulting episode

---

## Suggested third milestone

**Milestone C: “Automated publish pipeline.”**

Success criteria:
- generation and upload happen in one coordinated flow
- feed only updates when audio is publicly available
- retries are safe and stage-aware
