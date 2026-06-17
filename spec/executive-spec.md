# Executive Spec

## Product
Podcast Learning Agent PoC

## Purpose
Turn short user-submitted learning topics into private podcast-style episodes that can be consumed from a podcast app.

## Current state
The PoC already supports:
- a phone-friendly web UI for submitting topics
- two episode variants per topic: Overview and Deep Dive
- persistent runtime config and YAML-backed topic state
- generated RSS feed output
- generated MP3 placeholder audio files
- manual publishing of generated feed/audio to a public host such as Azure Static Website

The PoC does **not** yet support:
- real research generation
- real script generation
- real narration synthesis
- automated upload/publish pipeline

## Source of truth
The live public feed URL is controlled by:
- `runtime/config/podcast.yaml`

Key field:
```yaml
podcast:
  base_url: https://your-public-url.example.com
```

## User workflow
1. Start the app
2. Open the web UI
3. Submit a topic
4. Worker produces placeholder research, script, audio, and feed entries
5. Feed and audio files appear under `runtime/generated/`
6. User manually publishes generated artifacts to the public host
7. Podcast app reads the published feed

## Current generated outputs
Under `runtime/generated/`:
- `feed.xml`
- `audio/*.mp3`
- `scripts/*.md`
- `research/*.md`

## Current architecture
- Flask app + in-process background worker
- Dockerized single service
- mounted runtime directory at `/data`
- file-based state and artifacts
- app-hosted feed endpoint: `/feed.xml`
- app-hosted audio endpoint: `/audio/<filename>`

## Current limitations
1. Research is placeholder-only
2. Script writing is placeholder-only
3. Audio is copied sample MP3, not real TTS
4. Publishing to Azure/public host is manual
5. Feed publishing and audio publishing are not synchronized by automation
6. No auth, scheduling, queue broker, or production deployment hardening

## Next target capability
Replace the dummy pipeline with a real pipeline:
- research
- script writing
- ElevenLabs TTS
- publish/export/upload

## Acceptance target for next phase
For one submitted topic, the system should be able to:
1. generate a real research artifact
2. generate a real narration script
3. generate a real ElevenLabs MP3
4. place feed + audio into a publishable static layout
5. allow the user to manually or automatically publish that output

## Non-goals for this PoC phase
- multi-user auth
- advanced editorial tooling
- multi-speaker dramatization
- large-scale queueing/distributed workers
- analytics or listener telemetry
