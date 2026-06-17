# Prompting for Competence

Prompting for Competence is a small Flask app for turning queued learning topics into podcast episodes.

It provides:
- a web UI for submitting topics
- overview and deep-dive episode variants
- a background worker that runs research, script generation, audio synthesis, and publishing
- podcast feed publishing either from the app itself or through an Azure Static Website export/deploy flow

## Current implementation status

Implemented:
- topic queue and recent-topic UI
- research generation with Azure OpenAI / Azure Foundry Responses API plus web search
- script generation from prompt templates
- MP3 synthesis with Azure Speech
- MP3 synthesis with ElevenLabs
- publish bundle rebuilds under the runtime directory
- optional Azure Static Website upload with stale-file cleanup scoped to a configured prefix

Not implemented yet:
- Azure OpenAI TTS (`tts.provider: azure_openai`)

## Repository layout

- `app/` - Flask app, worker, pipeline stages, templates, and static assets
- `config/` - seed configuration and prompt templates copied into the runtime directory on first startup
- `data/` - seed topic state copied into the runtime directory on first startup
- `scripts/run_app.py` - Waitress entrypoint
- `tests/` - automated tests for the pipeline, UI, feed generation, and Azure publishing logic
- `runtime/` - live mutable app state when running locally or in Docker; ignored by git

## Runtime model

The app keeps a clear split between committed seed files and live mutable runtime files.

Committed seed files:
- `config/podcast.yaml`
- `config/prompts/research_prompt.txt`
- `config/prompts/script_overview_prompt.txt`
- `config/prompts/script_deep_dive_prompt.txt`
- `data/topics.yaml`

Live runtime files after startup:
- `runtime/config/podcast.yaml`
- `runtime/config/prompts/*.txt`
- `runtime/data/topics.yaml`
- `runtime/generated/`
- `runtime/publish/`

On first startup, missing runtime files are seeded from `config/` and `data/`.
After that, change the files under `runtime/` for the active environment.

## Publishing modes

The publishing behavior is controlled in `runtime/config/podcast.yaml`.

### App-hosted preview

Use one of these targets:
- `app_hosted`
- `local_app`
- `preview_app`

In this mode the app serves:
- `/feed.xml`
- `/audio/<file>`
- `/images/<file>`

This is the simplest local-preview setup.

### Azure Static Website export and deploy

Use one of these targets:
- `azure_static`
- `local_export`
- `export_bundle`
- `manual_export`

In these modes the app rebuilds a publish bundle under `runtime/publish/current/`.
If `publishing.deploy_enabled: true`, it also uploads that bundle to Azure Blob Storage static website hosting.

Important:
- `publishing.auto_publish: true` means a generated episode will immediately enter the publishing step
- if `publishing.target` is `azure_static` and `publishing.deploy_enabled` is true, the app needs `AZURE_STORAGE_CONNECTION_STRING`
- for local-only work, the easiest path is to switch to an app-hosted target or set `publishing.deploy_enabled: false`

## Configuration

Main runtime config:
- `runtime/config/podcast.yaml`

Main sections in that file:
- `podcast` - title, base URL, artwork metadata
- `research` - endpoint, model, API key env var, search behavior
- `script` - endpoint, model, target lengths, prompt behavior
- `tts` - provider and provider-specific settings
- `publishing` - app-hosted vs Azure export/deploy behavior
- `ui` - recent topic list size

Prompt templates are loaded from the runtime prompt files:
- `runtime/config/prompts/research_prompt.txt`
- `runtime/config/prompts/script_overview_prompt.txt`
- `runtime/config/prompts/script_deep_dive_prompt.txt`

## Environment variables

The Docker setup expects these in `.env`:
- `AZURE_OPENAI_API_KEY`
- `AZURE_SPEECH_KEY`
- `ELEVENLABS_API_KEY`
- `AZURE_STORAGE_CONNECTION_STRING`

The research and script stages also support endpoint/model fallbacks from environment variables if they are not set in YAML:
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_MODEL`

## Running with Docker

1. Copy `.env.example` to `.env`
2. Fill in the environment variables you need
3. Review `config/podcast.yaml` before first start if you want different defaults
4. Start the app:

```bash
docker compose up --build app
```

The app listens on port `6001`.
With Docker, `./runtime` on the host is mounted as `/data` in the container.

Open:
- `http://127.0.0.1:6001`

## Running without Docker

### Linux or macOS

```bash
cd /workspace/pod
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/run_app.py
```

### Windows PowerShell

```powershell
cd C:\workspace\pod
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\run_app.py
```

## Development notes

- sample audio files under `app/assets/sample_audio/` are local assets and are ignored by git
- `runtime/`, generated outputs, and secrets in `.env` are intentionally not committed
- if you change seed defaults in `config/` or `data/`, existing runtime files are not overwritten automatically

## Tests

Run the test suite with:

```bash
PYTHONPATH=. pytest
```
