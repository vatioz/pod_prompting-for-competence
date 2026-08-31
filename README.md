# Prompting for Competence

Turn a one-line learning topic into a private podcast episode you can listen to on your commute.

Submit a topic in a small web UI; a background worker researches it with web search, writes a narration script, synthesizes audio, and publishes it to an RSS feed your podcast app can subscribe to. Each topic can produce a short **Overview** and a longer **Deep Dive**.

Built on Flask with file-backed state — no database, no queue broker. Bring your own Azure OpenAI / Azure Speech or ElevenLabs keys.

> **Not hardened for the public internet.** There is no authentication on any route. Run it locally or behind something that authenticates. See [SECURITY.md](SECURITY.md).

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
- `docs/architecture.md` - how the pipeline, state model, and publishing actually work
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

This is the simplest local-preview setup, and it is the default in the seed config.

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
- deploying **deletes** remote files under `publishing.azure_path_prefix` that are not part of the current bundle, so the published site matches local state — always set a prefix, and never point it at a container holding unrelated content
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

Copy `.env.example` to `.env` and fill in only what you actually use:

| Variable | Needed when |
|---|---|
| `AZURE_OPENAI_API_KEY` | always — research and script generation |
| `AZURE_SPEECH_KEY` | `tts.provider: azure_speech` |
| `ELEVENLABS_API_KEY` | `tts.provider: elevenlabs` |
| `AZURE_STORAGE_CONNECTION_STRING` | `publishing.target: azure_static` with `deploy_enabled: true` |

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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/run_app.py
```

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\run_app.py
```

## Development notes

- `runtime/`, generated outputs, and secrets in `.env` are intentionally not committed
- if you change seed defaults in `config/` or `data/`, existing runtime files are not overwritten automatically
- `config/research-profile.md` and `config/script-guidance.md` are reference notes, not read by the app; the live prompts are under `config/prompts/`
- see [docs/architecture.md](docs/architecture.md) for the pipeline, state model, and deploy guardrails
- see [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request

## Tests

Install the dev dependencies, then run the suite:

```bash
pip install -r requirements-dev.txt
PYTHONPATH=. pytest
```

On Windows PowerShell:

```powershell
pip install -r requirements-dev.txt
$env:PYTHONPATH="."; pytest
```

The tests stub every external service, so they need no API keys and make no network calls.

## License

[MIT](LICENSE)
