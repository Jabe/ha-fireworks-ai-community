"""The Fireworks AI (community) integration."""

from dataclasses import dataclass

import httpx
from openai import AsyncOpenAI, APIStatusError, AuthenticationError, OpenAIError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers.httpx_client import get_async_client

from .const import CHAT_BASE_URL, LOGGER

PLATFORMS = [Platform.AI_TASK, Platform.CONVERSATION]


@dataclass
class FireworksData:
    """Runtime data stored on the config entry.

    A dataclass (rather than a bare client) so future platforms can attach more
    clients (e.g. an audio client for STT) without churning existing entities.
    """

    chat: AsyncOpenAI


type FireworksConfigEntry = ConfigEntry[FireworksData]


async def async_setup_entry(hass: HomeAssistant, entry: FireworksConfigEntry) -> bool:
    """Set up Fireworks AI from a config entry."""
    client = AsyncOpenAI(
        base_url=CHAT_BASE_URL,
        api_key=entry.data[CONF_API_KEY],
        http_client=get_async_client(hass),
        # Bound a stalled stream instead of inheriting the SDK's 600 s default.
        # Responses are streamed, so this read timeout applies *between* chunks
        # (per token), not to the whole generation — 30 s catches a dead stream
        # fast while easily covering time-to-first-token even on a cold or queued
        # reasoning model. The Assist pipeline puts no timeout around the
        # conversation stage (it just awaits conversation.async_converse), so on a
        # Wyoming satellite this is the only backstop against a multi-minute
        # freeze. max_retries=1 keeps a stall from stacking that wait ~3x.
        timeout=httpx.Timeout(30.0, connect=5.0),
        max_retries=1,
    )

    # Cache current platform data which gets added to each request
    # (caching done by library)
    _ = await hass.async_add_executor_job(client.platform_headers)

    # Validate the key and reachability before setting up platforms.
    try:
        async for _ in client.with_options(timeout=10.0).models.list():
            break
    except AuthenticationError as err:
        LOGGER.error("Invalid API key: %s", err)
        raise ConfigEntryError("Invalid API key") from err
    except APIStatusError as err:
        # A server-side (5xx) failure on the model-listing endpoint must not
        # block setup. This probe only confirms the key + reachability; the
        # integration never lists models at runtime (the model is chosen in
        # options and chat goes to /chat/completions). Fireworks' deployed-
        # models listing is known to intermittently 500 ("Error listing
        # deployed models") even for valid keys, so a 5xx here already proves we
        # reached Fireworks and the key was accepted — proceed and let any real
        # outage surface on the first chat request. Non-5xx status errors keep
        # the retry behaviour.
        if err.response.status_code >= 500:
            LOGGER.warning(
                "Fireworks model listing returned HTTP %s during setup; "
                "continuing anyway (endpoint unused at runtime): %s",
                err.response.status_code,
                err,
            )
        else:
            raise ConfigEntryNotReady(err) from err
    except OpenAIError as err:
        raise ConfigEntryNotReady(err) from err

    entry.runtime_data = FireworksData(chat=client)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: FireworksConfigEntry
) -> None:
    """Handle update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FireworksConfigEntry) -> bool:
    """Unload Fireworks AI."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
