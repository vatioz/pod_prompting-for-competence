# Podcast Learning Agent PoC Scaffold

This repository is now intentionally pared down to the smallest app-backed PoC shape:

- one Dockerized app service
- one mounted runtime directory
- one live source of truth for the podcast URL: `runtime/config/podcast.yaml`

## Source of truth

If you want to change the public feed URL, edit:

- `runtime/config/podcast.yaml`

Specifically:

```yaml
podcast:
  base_url: https://your-public-url.example.com
```

The app reads that file at runtime. `compose.yaml` no longer overrides `base_url`.

## What matters

### App/source
- `app/` — Flask app, worker, storage, templates, bundled sample audio
- `scripts/run_app.py` — starts the app with Waitress
- `compose.yaml` — Docker service definition
- `Dockerfile` — container image
- `config/` — seed defaults copied into runtime only on first start
- `data/` — seed topic state copied into runtime only on first start

### Live runtime state
- `runtime/config/podcast.yaml` — live app config
- `runtime/config/listener-profile.md` — live listener profile
- `runtime/data/topics.yaml` — live topic queue/state
- `runtime/generated/` — generated feed, scripts, research, audio

## Known current gap

The publishing pipeline is **not automated yet**.

Current manual flow:
- generate/update content under `runtime/generated/`
- publish `runtime/generated/feed.xml`
- publish `runtime/generated/audio/*.mp3`

This still needs a proper automated pipeline so feed updates and audio file publishing happen together and consistently.

## What was archived/deleted

Archived under `archive/legacy-2026-06-12/`:
- former `feed-poc/` static proof-of-concept
- former `azure-static-test/` export bundle

Deleted as disposable clutter:
- top-level `generated/`
- `runtime-check/`
- `runtime-test/`
- in-repo virtualenvs like `.venv/` and `.venv_win/`

## Running with Docker

```bash
docker compose up --build app
```

This publishes port `6001` and mounts `./runtime` as `/data` inside the container.

## Runtime behavior

On first startup, the app seeds `/data` with:
- `config/podcast.yaml`
- `config/listener-profile.md`
- `data/topics.yaml`
- generated output directories

After that, edit files in `runtime/`, not the seed files in `config/` or `data/`.

## Known gap

Publishing `runtime/generated/feed.xml` together with `runtime/generated/audio/*` to the final public host is still a **manual** step. There is currently no automated export/deploy pipeline for feed + audio publishing.

## Running without Docker

### Linux/macOS

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


# Resources

## Research LLM
- RG: ai_vsb_robotics
- Foundry Project: ai-robo-sweden
- agent pod-research with Web search tool
- model: gpt-5.2
- prompt: runtime/config/prompts/research_prompt.txt

## Scripting LLM
- RG: ai_vsb_robotics
- Foundry Project: ai-robo-sweden
- model: gpt-5.2
- prompt: runtime/config/prompts/script_overiview_prompt.txt
- prompt: runtime/config/prompts/script_deep_dive_prompt.txt

## TTS

Tried multiple options

### ElevenLabs
My personal account, crazy expensive, ~ 2USD per 10min
Provider exists, but not being used

### Azure Speech
- doesn't require model to be deployed like LLMs do
- RG: ai_vsb_robotics
- Foundry Project: ai-robo-sweden

Batch variant for episodes over 10min not yet implemented.

### Azure OpenAI TTS
not implemented yet


## Publishing
- RG: rg-ai
- storage account: podappstorage
- container: $web
- static web site enabled for whole storage account
- website URL: https://podappstorage.z6.web.core.windows.net/
- feed location: https://podappstorage.z6.web.core.windows.net/podcast/feed.xml
- audio location: https://podappstorage.z6.web.core.windows.net/podcast/audio/
