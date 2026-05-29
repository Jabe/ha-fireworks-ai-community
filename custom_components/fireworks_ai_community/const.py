"""Constants for the Fireworks AI (community) integration."""

import logging

from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT
from homeassistant.helpers import llm

DOMAIN = "fireworks_ai_community"
LOGGER = logging.getLogger(__package__)

CONF_RECOMMENDED = "recommended"

# Fireworks AI's OpenAI-compatible chat completions endpoint. This is the only
# base URL used in v1 (conversation + AI Task).
CHAT_BASE_URL = "https://api.fireworks.ai/inference/v1"

# Reserved expansion points for future platforms (STT / image generation).
# Fireworks serves audio on separate hosts from chat, so these are kept out of
# CHAT_BASE_URL. Documented here only so the next platform is isolated; they are
# UNUSED in v1 and MUST be re-verified against the Fireworks docs before STT work
# begins (a faster `audio-turbo.api.fireworks.ai` host and an `-v2` streaming
# host also exist). See https://docs.fireworks.ai/api-reference/.
AUDIO_BASE_URL = "https://audio-prod.api.fireworks.ai/v1"
AUDIO_STREAM_URL = (
    "wss://audio-streaming.api.fireworks.ai/v1/audio/transcriptions/streaming"
)

RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_RECOMMENDED: True,
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
}
