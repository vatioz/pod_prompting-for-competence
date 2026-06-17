# Future Pipeline Spec

## Purpose
Define the target future pipeline that replaces the current dummy artifact generation with a real content pipeline:
- research
- script writing
- ElevenLabs narration
- upload/publish

This spec is forward-looking and separate from the current-state spec.

---

## Goals
For each submitted topic, the system should be able to:
1. create a structured research artifact
2. create one or more episode scripts from that research
3. render those scripts to real MP3 audio with ElevenLabs
4. update the RSS feed to reference the new audio files
5. publish feed + audio together to the public hosting target

Primary hosting assumption for now:
- static hosting, such as Azure Static Website

---

## Non-goals
This phase does not require:
- multi-user auth
- a distributed job queue
- fully autonomous topic ingestion from external systems
- editing UI for full script authoring
- multi-voice conversation mode
- advanced analytics

---

## End-to-end pipeline
### Stage 0: Topic intake
Input:
- prompt text from UI
- enabled variants: overview and/or deep_dive

Output:
- queued topic in `runtime/data/topics.yaml`

Status transitions:
- `queued` -> `processing` -> `published` or `failed`

Variant transitions:
- `queued` -> `processing` -> `published` or `failed`

---

### Stage 1: Research
#### Purpose
Produce a topic-specific research artifact that can be reused by all enabled variants.

#### Inputs
- topic prompt
- optional future listener profile context from `runtime/config/listener-profile.md`
- optional future system prompt / content rules

#### Outputs
- `runtime/generated/research/<slug>-<topic_id>.md`

#### Minimum artifact structure
Recommended sections:
- topic statement
- key concepts
- why it matters
- practical examples
- tradeoffs / caveats
- glossary or jargon expansion
- source notes

#### Requirements
- deterministic artifact path
- safe retry behavior
- variant-independent artifact reusable across overview + deep_dive

#### Failure behavior
- if research fails, topic becomes `failed`
- `last_error` should record enough detail for retry/debugging

---

### Stage 2: Script writing
#### Purpose
Transform research into audio-first narration scripts.

#### Inputs
- research markdown
- variant type (`overview` or `deep_dive`)
- optional listener profile/context

#### Outputs
- `runtime/generated/scripts/<slug>-overview-<topic_id>.md`
- `runtime/generated/scripts/<slug>-deep_dive-<topic_id>.md`

#### Script requirements
Overview script should:
- optimize for fast orientation
- stay concise
- explain the core idea and why the user should care

Deep dive script should:
- go deeper into mechanisms, examples, tradeoffs, and context
- assume the listener wants more detail than the overview

For both variants:
- write for spoken delivery, not blog reading
- avoid excessive bullet formatting in final narration text
- include natural transitions
- avoid giant unbroken paragraphs
- optionally include a short intro and short outro

#### Future metadata to consider per script
- estimated duration
- target voice
- speaking rate
- pronunciation hints / glossary

---

### Stage 3: ElevenLabs TTS
#### Purpose
Convert approved/generated scripts into real MP3 narration.

#### Inputs
- script text
- ElevenLabs API credentials
- configured voice/model parameters

#### Outputs
- `runtime/generated/audio/<slug>-overview-<topic_id>.mp3`
- `runtime/generated/audio/<slug>-deep_dive-<topic_id>.mp3`

#### Configuration needed
Recommended additions to runtime config:
```yaml
tts:
  provider: elevenlabs
  voice_id: <voice-id>
  model_id: <model-id>
  stability: <optional>
  similarity_boost: <optional>
  style: <optional>
  speaker_boost: <optional>
```

Secrets should not live in repo files.
Credential should come from environment or secret storage, e.g.:
- `ELEVENLABS_API_KEY`

#### Requirements
- output must be MP3
- file path must be deterministic
- partial files should not be left behind as if successful
- failures should mark the variant `failed`
- retries should overwrite or replace stale outputs safely

#### Optional near-term enhancement
Store raw TTS request/response metadata separately for debugging, e.g.:
- voice id used
- model id used
- request timestamp
- duration/file size

---

### Stage 4: Feed update
#### Purpose
Regenerate RSS after successful audio generation.

#### Inputs
- topic/variant state
- generated MP3 files
- runtime config `podcast.base_url`

#### Outputs
- updated `runtime/generated/feed.xml`

#### Requirements
Feed items should include:
- title
- description
- RFC822 `pubDate`
- GUID
- enclosure URL
- enclosure byte length
- enclosure MIME type `audio/mpeg`

#### URL convention
For static hosting layout, enclosure URLs should be:
- `<base_url>/audio/<filename>.mp3`

This assumes published layout:
- `feed.xml` at root
- `audio/` as sibling folder

---

### Stage 5: Publish/export/upload
#### Purpose
Publish feed and audio artifacts to the final public hosting location.

#### Current gap
This is currently manual.

#### Target options
##### Option A: manual export only
User manually uploads:
- `runtime/generated/feed.xml`
- `runtime/generated/audio/*.mp3`

to the public static host.

##### Option B: local export bundle
System creates a publishable static bundle such as:
- `runtime/publish/feed.xml`
- `runtime/publish/audio/*.mp3`

User uploads that folder manually.

##### Option C: automated Azure upload
System uploads artifacts directly to Azure Storage Static Website.

#### Recommended near-term design
Implement **Option B first**, then Option C.

Why:
- keeps publish layout explicit
- reduces risk while integration is being proven
- gives a stable contract between generation and deployment

---

## Recommended publish layout
Target static publish directory:
- `publish/feed.xml`
- `publish/audio/*.mp3`
- optional future artwork files

Recommended future behavior:
1. generate into `runtime/generated/`
2. export/copy finalized publishable artifacts into `runtime/publish/`
3. upload `runtime/publish/` manually or automatically

This cleanly separates:
- working artifacts
- public publish artifacts

---

## Suggested future runtime schema additions
### Topic-level additions
Potential additions:
- `publish_status`
- `published_feed_version`
- `published_url`
- `source_notes`

### Variant-level additions
Potential additions:
- `script_status`
- `tts_status`
- `audio_duration_seconds`
- `audio_size_bytes`
- `voice_id`
- `model_id`
- `upload_status`
- `public_audio_url`

### Separate config sections
Recommended future config shape:
```yaml
podcast:
  title: ...
  description: ...
  author: ...
  base_url: https://...
  language: en-us

worker:
  poll_seconds: 3

ui:
  recent_topics_limit: 12

research:
  provider: <future>
  model: <future>

script:
  provider: <future>
  model: <future>

tts:
  provider: elevenlabs
  voice_id: ...
  model_id: ...

publish:
  target: azure_static_website
  container_or_endpoint: ...
  mode: manual|export|direct_upload
```

---

## Failure handling
### General rules
- failure in one stage must not masquerade as success in later stages
- each failed stage should record an actionable error
- retries should be stage-safe and overwrite stale outputs deterministically

### Failure examples
#### Research failure
- topic or relevant stage marked failed
- no script/TTS step should proceed

#### Script generation failure
- variant marked failed
- other enabled variant may still succeed if processed independently

#### ElevenLabs failure
- variant marked failed
- do not emit broken enclosure URL for missing file

#### Publish/upload failure
- generated artifacts remain available locally
- topic should not lose successful generation state
- publish status should be tracked separately from generation status

---

## Observability and operator visibility
The UI should eventually show, at minimum:
- topic status
- per-variant status
- last error
- whether feed/audio are generated
- whether publish/export has happened

Useful future additions:
- timestamps per stage
- artifact links
- public URL after upload
- retry stage controls

---

## Recommended implementation order
### Phase 1
Real research artifact generation

### Phase 2
Real script generation from research

### Phase 3
ElevenLabs MP3 generation from scripts

### Phase 4
Stable export bundle for static hosting

### Phase 5
Optional automated Azure upload

This order preserves fast validation and isolates failure domains.

---

## Acceptance criteria
### Milestone A: first real generated episode
Given one submitted topic with `overview` enabled,
when the pipeline runs,
then the system should produce:
- a non-placeholder research markdown file
- a non-placeholder script markdown file
- a real ElevenLabs MP3 file
- a feed item referencing that MP3

### Milestone B: publishable static bundle
Given at least one published episode,
when export runs,
then the system should produce a static publish directory containing:
- `feed.xml`
- matching `audio/*.mp3`

### Milestone C: automated upload
Given a configured Azure publish target,
when publish runs,
then the system should upload the feed and referenced audio files together and report success/failure clearly.

---

## Out of scope for this spec
- exact LLM prompts for research/script generation
- editorial quality heuristics
- chapter markers/transcripts
- artwork generation
- paid/private feed auth models
- analytics/dashboarding
