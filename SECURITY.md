# Security Policy

## Reporting a vulnerability

Please report security issues privately via [GitHub Security Advisories](https://github.com/vatioz/pod_prompting-for-competence/security/advisories/new) rather than opening a public issue.

This is a personal side project maintained on a best-effort basis. There is no SLA, but reports will be read.

## Intended deployment model

**This app has no authentication, authorization, or rate limiting.** Every route — including topic submission, retry, and unpublish — is open to anyone who can reach the port.

It is designed to run on `127.0.0.1` or inside a trusted private network. Do not expose it directly to the internet. Anyone who reaches it can spend your Azure OpenAI, Azure Speech, and ElevenLabs credits, and can trigger writes to your configured storage account.

If you need remote access, put it behind an authenticating reverse proxy, a VPN, or a tunnel with access control.

## Secrets

All credentials are read from environment variables. Their *names* are configured in `podcast.yaml`; their *values* must never be:

- `AZURE_OPENAI_API_KEY`
- `AZURE_SPEECH_KEY`
- `ELEVENLABS_API_KEY`
- `AZURE_STORAGE_CONNECTION_STRING`

`.env` is gitignored. Do not commit it, and do not paste real endpoints or keys into `config/podcast.yaml`, which is a committed seed file.

## Destructive publishing behavior

With `publishing.target: azure_static` and `deploy_enabled: true`, the app **deletes remote blobs** that are not part of the current bundle, so the published site matches local state.

Two guardrails exist:

- deletion at the root of `$web` is refused unless `azure_allow_root_delete` is explicitly enabled
- `public_base_url` must agree with `azure_path_prefix`

Set `publishing.azure_path_prefix` to scope the app to a subdirectory of your storage account. Do not point it at a container holding unrelated content.
