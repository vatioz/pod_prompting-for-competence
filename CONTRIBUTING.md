# Contributing

Thanks for taking a look. This is a personal side project, so keep expectations calibrated: it is maintained on a best-effort basis and design decisions lean toward "simple enough for one person to reason about."

## Getting set up

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
```

Run the test suite:

```bash
PYTHONPATH=. pytest                # Windows: $env:PYTHONPATH="."; pytest
```

The tests stub every external service. They make no network calls and need no API keys, so a clean checkout should go green immediately. If it does not, that is a bug worth reporting.

Run the app:

```bash
python scripts/run_app.py
```

Read [docs/architecture.md](docs/architecture.md) before making non-trivial changes — particularly the sections on stage state and the Azure deploy guardrails.

## Ground rules

- **Add a test.** Every stage, guardrail, and route in this repo has one. New behavior should too.
- **Never commit secrets.** No API keys, connection strings, or real endpoint hostnames — including in `config/podcast.yaml`, which is a committed seed file, and in test fixtures. Use `example.com`-style placeholders.
- **Keep seed config safe by default.** `config/podcast.yaml` must not point at real infrastructure or enable remote deploys out of the box.
- **Don't break resumability.** The worker skips stages already marked `done` with artifacts on disk. That is what makes retry cheap in tokens and API calls.
- **Match the surrounding style.** No formatter is enforced; just don't reformat unrelated code.

## Pull requests

CI runs the test suite and a Docker build on every PR. Both must pass.

Keep PRs focused on one thing, and describe what you changed and why. If you're planning something large, open an issue first so we can agree on the shape before you write it.

## Reporting bugs and requesting features

Use the issue templates. For bugs, the most useful thing you can include is your `podcast.yaml` with secrets removed, and the relevant stage error text — each stage stores its own `error` field in `runtime/data/topics.yaml`.

## Security

Do not open a public issue for security problems. See [SECURITY.md](SECURITY.md).
