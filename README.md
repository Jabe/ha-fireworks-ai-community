# Fireworks AI for Home Assistant (community)

[![hacs][hacs-badge]][hacs] [![License: Apache 2.0][license-badge]][license]

A custom Home Assistant integration that adds [Fireworks AI][fireworks] as a
**conversation agent** and **AI Task** provider for Assist — using Fireworks'
fast, OpenAI-compatible chat completions API.

> **Community edition.** This is an unofficial HACS integration. Its domain is
> `fireworks_ai_community` so it never collides with a possible future official
> `fireworks_ai` integration in Home Assistant core.

## Features

- **Conversation agent** — talk to a Fireworks-hosted LLM in Assist, with
  optional access to Home Assistant's LLM tools (device/entity control).
- **AI Task** — generate text or structured data from automations and scripts.
- Per-agent **model selection** from your Fireworks account.
- Image/PDF attachments are forwarded to vision-capable models.

## Not included (and why)

| Capability | Status |
| --- | --- |
| Text-to-speech (TTS) | ❌ Fireworks has no TTS API. Pair Assist with a separate TTS (e.g. Piper). |
| Speech-to-text (STT) | ⏳ Fireworks has Whisper, but on a separate audio host/protocol. Planned as a follow-up. |
| Image generation | ⏳ Fireworks has FLUX, but via a non-OpenAI endpoint. Planned as a follow-up. |

The architecture reserves clean extension points for STT and image generation.

## Requirements

- Home Assistant **2025.7** or newer.
- A [Fireworks AI API key][fireworks-keys].
- Models you select must support **tool/function calling** (for Assist device
  control) and **structured outputs** (for structured AI Tasks). Not every
  Fireworks model does — see the Fireworks model catalog.

## Installation (HACS)

1. In HACS → **Integrations** → ⋮ → **Custom repositories**, add this
   repository with category **Integration**.
2. Install **Fireworks AI** and restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Fireworks AI**, then
   enter your API key.
4. Add a **conversation agent** and/or **AI Task** subentry and pick a model.

## Configuration

- **API key** — your Fireworks AI key, validated on setup against the Fireworks
  models endpoint.
- **Model** (per subentry) — the dropdown lists the models Fireworks reports as
  available to your account (its `/v1/models` response), which is only a subset
  of the full catalog. You can also **type any model ID** directly — e.g.
  `accounts/fireworks/models/<name>` from the [model catalog][fireworks-models].
  Serverless models work immediately; other models must first have an
  [on-demand deployment][fireworks-ondemand] in your Fireworks account.
- **Prompt** / **LLM tools** (conversation) — standard Assist options.

## Development

Local tooling is managed with [mise][mise]:

```sh
mise install      # Python 3.13 + ruff per mise.toml
mise run setup    # create .venv and install dev deps (Home Assistant + openai)
mise run check    # ruff lint + format-check + byte-compile
```

The authoritative checks (**hassfest** + **HACS validation**) run in CI on every
push and pull request. Runtime behaviour must be verified in a real Home
Assistant instance with a Fireworks API key.

## Credits & license

This integration is derived from the Home Assistant core
[`open_router`][open-router] integration and is distributed under the same
[Apache-2.0][license] license. Home Assistant is a trademark of the Open Home
Foundation; this project is not affiliated with or endorsed by Fireworks AI or
the Open Home Foundation.

[mise]: https://mise.jdx.dev/
[fireworks]: https://fireworks.ai/
[fireworks-keys]: https://fireworks.ai/account/api-keys
[fireworks-models]: https://fireworks.ai/models
[fireworks-ondemand]: https://docs.fireworks.ai/guides/ondemand-deployments
[open-router]: https://www.home-assistant.io/integrations/open_router/
[hacs]: https://hacs.xyz/
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[license]: ./LICENSE
[license-badge]: https://img.shields.io/badge/License-Apache_2.0-blue.svg
