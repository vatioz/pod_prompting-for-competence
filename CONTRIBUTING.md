# Contributing

Thanks for taking a look. This is a personal side project, so keep expectations calibrated: it is maintained on a best-effort basis and design decisions lean toward "simple enough for one person to reason about."

## Getting set up

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
npm ci                            # Node.js 26
```

Run the unit coverage gates (both must reach **100% line coverage**):

```bash
python -m coverage run -m pytest -m "not integration" -q
python -m coverage report
python -m coverage json
python -m coverage xml
python -m coverage html
npm run test:coverage
```

Python coverage includes every source under `app/` and `scripts/`, including the startup script and defensive error paths. Browser coverage includes every JavaScript source under `app/static/` and enforces the line threshold per file. Reports are written to the ignored `coverage/` directory: Python JSON/XML/HTML and browser JSON/LCOV/HTML. CI uploads these reports as the `unit-coverage` artifact. The target is line coverage, not a claim of exhaustive branch or production-service testing; do not add coverage exclusions to make the gates pass.

Unit tests isolate runtime files in temporary directories, stub service boundaries, and reject socket connections and binds. They need no API keys. DOM-based browser tests execute the real browser script with fake HTTP responses and timers. The `test-exclude` dependency overrides in `package.json` keep coverage tooling on patched glob/minimatch releases.

Run the loopback HTTP integration tests separately; they do **not** contribute to the unit coverage result:

```bash
python -m pytest -m integration -q
```

These integration tests also stub external providers; only local loopback connections are permitted. `python -m pytest -q` runs both Python groups without measuring coverage.

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

CI enforces both unit coverage gates, runs the loopback integration tests separately, and builds Docker on every PR. All checks must pass.

Keep PRs focused on one thing, and describe what you changed and why. If you're planning something large, open an issue first so we can agree on the shape before you write it.

## Reporting bugs and requesting features

Use the issue templates. For bugs, the most useful thing you can include is your `podcast.yaml` with secrets removed, and the relevant stage error text — each stage stores its own `error` field in `runtime/data/topics.yaml`.

## Security

Do not open a public issue for security problems. See [SECURITY.md](SECURITY.md).
