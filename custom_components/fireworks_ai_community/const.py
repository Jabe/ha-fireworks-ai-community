"""Constants for the Fireworks AI (community) integration."""

import logging

from homeassistant.const import CONF_LLM_HASS_API, CONF_PROMPT
from homeassistant.helpers import llm

DOMAIN = "fireworks_ai_community"
LOGGER = logging.getLogger(__package__)

CONF_RECOMMENDED = "recommended"

# Reasoning-effort control (Fireworks' `reasoning_effort` param, reasoning models
# only). REASONING_EFFORT_DEFAULT is a UI-only sentinel meaning "don't send the
# param" so the model keeps its own default.
CONF_REASONING_EFFORT = "reasoning_effort"
REASONING_EFFORT_DEFAULT = "default"
REASONING_EFFORT_NONE = "none"
REASONING_EFFORT_OPTIONS = ("none", "low", "medium", "high", "max")

# When reasoning is on, its tokens share the max_tokens budget with the answer,
# so a long chain can truncate the reply before any `content` is emitted. Give it
# generous headroom (Fireworks recommends >=16000 for the Kimi K2 family). Only
# applied when reasoning is explicitly enabled, so it never caps other models.
REASONING_MAX_TOKENS = 16000

# Whether to surface the reasoning chain as thinking_content in the UI. Off by
# default: streaming it stalls the Assist chat UI on tool-using turns, and the
# reasoning improves the answer whether or not it is shown.
CONF_SHOW_REASONING = "show_reasoning"

# "Slow mode" for the chat stream. Fireworks emits tokens in sub-millisecond
# bursts, and the Assist chat UI re-renders every content delta through an async
# markdown web worker that has no last-write-wins guard (frontend
# ha-markdown-element._render): at full token speed a stale render can land after
# the final one and leave the chat stuck on "…", even though the turn already
# finished server-side. The slower the provider, the smaller the race window —
# which is why this bites fast Fireworks streaming (and bites *more* on
# non-reasoning turns, where there is no server-side think pause to space the
# tokens out). When enabled, content deltas are coalesced into at most one flush
# per SLOW_STREAM_FLUSH_INTERVAL seconds, so the worker stops racing itself.
# 0.1 s proved too tight in the field: fast non-reasoning turns still collided
# (and the end-of-stream tail flush could land ~50 ms behind the previous one,
# re-creating exactly the back-to-back render the throttle exists to prevent).
# 0.3 s spaces renders enough that a typical short answer paints in one or two
# well-separated deltas; the tail flush is held to the same minimum gap.
# Opt-in and conversation-only; the assembled answer and the TTS stream are
# byte-for-byte identical, only the streamed delta granularity changes.
CONF_SLOW_STREAM = "slow_stream"
SLOW_STREAM_FLUSH_INTERVAL = 0.3

# Per-request bound for an interactive chat stream. The client already sets a
# 30 s read timeout, but its default retries turn a stalled request into a
# silent ~2x wait: a 30 s timeout plus one retry lands at ~33 s, which is the
# "hang" seen in the field (and it surfaces as a slow success, not an error,
# because the retry goes through). On the conversation / AI-task path we restate
# the timeout and disable retries so a dead stream fails promptly instead of
# stacking into a multi-second freeze.
CHAT_REQUEST_TIMEOUT = 30.0
CHAT_CONNECT_TIMEOUT = 5.0

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
