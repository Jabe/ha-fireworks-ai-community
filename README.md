# Fireworks AI for Home Assistant (community)

[![Marketplace][marketplace-badge]][marketplace] [![License: Apache 2.0][license-badge]][license]

A custom Home Assistant integration that adds [Fireworks AI][fireworks] as a
**conversation agent** and **AI Task** provider for Assist — using Fireworks'
fast, OpenAI-compatible chat completions API.

> **Community edition.** This is an unofficial custom integration, installed
> through the Home Assistant Marketplace (formerly HACS). Its domain is
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

- Home Assistant **2025.9** or newer.
- A [Fireworks AI API key][fireworks-keys].
- Models you select must support **tool/function calling** (for Assist device
  control) and **structured outputs** (for structured AI Tasks). Not every
  Fireworks model does — see the Fireworks model catalog.

## Installation

[![Open your Home Assistant instance and open this repository in the Marketplace.][my-badge]][my-repo]

This integration isn't in the Marketplace catalog, so add it by link.

**Home Assistant 2026.11 or newer (Marketplace):**

1. **Settings → Marketplace → Add from link**, enter
   `Jabe/ha-fireworks-ai-community` and select **Add**. If asked for a
   **Type**, pick **Integration**. Adding by link needs the Marketplace's
   GitHub connection.
2. Open the repository, select **Install**, and restart Home Assistant.

**Older Home Assistant (HACS):** In HACS → **Integrations** → ⋮ →
**Custom repositories**, add this repository with category **Integration**,
install **Fireworks AI** and restart Home Assistant.

Then, for both:

1. **Settings → Devices & Services → Add Integration → Fireworks AI**, then
   enter your API key.
2. Add a **conversation agent** and/or **AI Task** subentry and pick a model.

**Beta versions** are published as GitHub pre-releases. To get them in the
Marketplace, open **Settings → Devices & services → Marketplace**, open this
repository's device, enable its **Pre-release** entity (disabled by default)
and turn the switch on. In HACS, use **Show beta versions** on the repository.

## Configuration

- **API key** — your Fireworks AI key, validated on setup against Fireworks'
  serverless model catalog.
- **Model** (per subentry) — the dropdown comes from Fireworks' Gateway
  `List Models` API (`supports_serverless=true`). The catalog can lag the
  public [model library][fireworks-models], so you can also **type any model ID**
  directly — e.g. `accounts/fireworks/models/<name>`. Serverless models work
  immediately by ID whether or not they appear in the list; non-serverless
  catalog models must first have an [on-demand deployment][fireworks-ondemand]
  in your account.
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
[my-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[my-repo]: https://my.home-assistant.io/redirect/hacs_repository/?owner=Jabe&repository=ha-fireworks-ai-community&category=integration
[marketplace]: https://www.home-assistant.io/integrations/marketplace/
[marketplace-badge]: https://img.shields.io/badge/Marketplace-Custom-41BDF5.svg
[license]: ./LICENSE
[license-badge]: https://img.shields.io/badge/License-Apache_2.0-blue.svg
