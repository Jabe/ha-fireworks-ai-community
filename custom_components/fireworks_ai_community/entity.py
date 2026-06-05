"""Base entity for Fireworks AI."""

import base64
from collections.abc import AsyncGenerator, Callable
import json
from mimetypes import guess_file_type
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, Literal

import httpx
import openai
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionChunk,
    ChatCompletionContentPartImageParam,
    ChatCompletionFunctionToolParam,
    ChatCompletionMessageFunctionToolCallParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.chat.chat_completion_message_function_tool_call_param import Function
from openai.types.shared_params import FunctionDefinition, ResponseFormatJSONSchema
from openai.types.shared_params.response_format_json_schema import JSONSchema
import voluptuous as vol
from voluptuous_openapi import convert

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, llm
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.json import json_dumps

from . import FireworksConfigEntry
from .const import (
    CHAT_CONNECT_TIMEOUT,
    CHAT_REQUEST_TIMEOUT,
    CONF_REASONING_EFFORT,
    CONF_SHOW_REASONING,
    CONF_SLOW_STREAM,
    DOMAIN,
    LOGGER,
    REASONING_EFFORT_DEFAULT,
    REASONING_EFFORT_NONE,
    REASONING_MAX_TOKENS,
    SLOW_STREAM_FLUSH_INTERVAL,
)

MAX_TOOL_ITERATIONS = 10


def _adjust_schema(schema: dict[str, Any]) -> None:
    """Adjust the schema to be compatible with the Fireworks API.

    Fireworks' strict structured output (json_schema) requires every property to
    be listed in ``required``; optional properties are made nullable instead.
    """
    if schema["type"] == "object":
        if "properties" not in schema:
            return

        if "required" not in schema:
            schema["required"] = []

        for prop, prop_info in schema["properties"].items():
            _adjust_schema(prop_info)
            if prop not in schema["required"]:
                prop_info["type"] = [prop_info["type"], "null"]
                schema["required"].append(prop)

    elif schema["type"] == "array":
        if "items" not in schema:
            return

        _adjust_schema(schema["items"])


def _format_structured_output(
    name: str, schema: vol.Schema, llm_api: llm.APIInstance | None
) -> JSONSchema:
    """Format the schema to be compatible with the Fireworks API."""
    result: JSONSchema = {
        "name": name,
        "strict": True,
    }
    result_schema = convert(
        schema,
        custom_serializer=(
            llm_api.custom_serializer if llm_api else llm.selector_serializer
        ),
    )

    _adjust_schema(result_schema)

    result["schema"] = result_schema
    return result


def _format_tool(
    tool: llm.Tool,
    custom_serializer: Callable[[Any], Any] | None,
) -> ChatCompletionFunctionToolParam:
    """Format tool specification."""
    unsupported_keys = {"oneOf", "anyOf", "allOf"}
    schema = convert(tool.parameters, custom_serializer=custom_serializer)
    schema = {k: v for k, v in schema.items() if k not in unsupported_keys}

    tool_spec = FunctionDefinition(
        name=tool.name,
        parameters=schema,
    )
    if tool.description:
        tool_spec["description"] = tool.description
    return ChatCompletionFunctionToolParam(type="function", function=tool_spec)


def _convert_content_to_chat_message(
    content: conversation.Content,
) -> ChatCompletionMessageParam | None:
    """Convert any native chat message for this agent to the native format."""
    LOGGER.debug("_convert_content_to_chat_message=%s", content)
    if isinstance(content, conversation.ToolResultContent):
        return ChatCompletionToolMessageParam(
            role="tool",
            tool_call_id=content.tool_call_id,
            content=json_dumps(content.tool_result),
        )

    role: Literal["user", "assistant", "system"] = content.role
    if role == "system" and content.content:
        return ChatCompletionSystemMessageParam(role="system", content=content.content)

    if role == "user" and content.content:
        return ChatCompletionUserMessageParam(role="user", content=content.content)

    if role == "assistant":
        param = ChatCompletionAssistantMessageParam(
            role="assistant",
            content=content.content,
        )
        if isinstance(content, conversation.AssistantContent) and content.tool_calls:
            param["tool_calls"] = [
                ChatCompletionMessageFunctionToolCallParam(
                    type="function",
                    id=tool_call.id,
                    function=Function(
                        arguments=json_dumps(tool_call.tool_args),
                        name=tool_call.tool_name,
                    ),
                )
                for tool_call in content.tool_calls
            ]
        return param
    LOGGER.warning("Could not convert message to Completions API: %s", content)
    return None


def _decode_tool_arguments(arguments: str) -> Any:
    """Decode tool call arguments."""
    try:
        return json.loads(arguments)
    except json.JSONDecodeError as err:
        raise HomeAssistantError(f"Unexpected tool argument response: {err}") from err


async def _transform_stream(
    stream: openai.AsyncStream[ChatCompletionChunk],
    show_reasoning: bool,
    slow_stream: bool,
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    """Transform a Fireworks streaming response into ChatLog deltas.

    Emits the role once, then answer text (as content) fragments as they arrive —
    so the Assist pipeline can start speaking before generation finishes — and
    finally the fully-assembled tool calls. Tool-call arguments stream in
    fragments keyed by index and must be buffered until complete: ChatLog
    dispatches a tool the moment it sees a ToolInput, so a partial would fire a
    malformed call.

    When ``show_reasoning`` is set, a reasoning model's chain of thought (the
    non-standard ``reasoning_content`` field) is also surfaced as thinking_content.
    Off by default: the reasoning still runs server-side and improves the answer,
    but streaming it makes the Assist chat UI stall on tool-using turns (a message
    with thinking but no content yet), so it is opt-in.

    When ``slow_stream`` is set, answer text is coalesced into at most one content
    delta per ``SLOW_STREAM_FLUSH_INTERVAL`` instead of one per token. Fireworks
    streams tokens far faster than the Assist chat UI's async markdown renderer
    can keep up with, and a stale render can overwrite the final one and leave the
    chat stuck on "…"; pacing the deltas keeps the renderer from racing itself.
    The assembled content (and therefore the TTS stream) is unchanged.
    """
    yield {"role": "assistant"}

    tool_calls: dict[int, dict[str, str]] = {}

    # Diagnostics for slow turns: time-to-first-chunk and reasoning volume tell a
    # turn dominated by server-side thinking (high reasoning_chars) apart from an
    # infrastructure stall (high TTFC, little reasoning). Reasoning length is
    # tallied even when not surfaced, so `show_reasoning=False` turns stay
    # measurable. Pair this with the `create()` timing in _async_handle_chat_log:
    # a long create() means the SSE stream only opened after thinking finished.
    start = time.monotonic()
    first_chunk_at: float | None = None
    first_content_at: float | None = None
    reasoning_chars = 0
    content_chars = 0
    chunk_count = 0

    # Slow mode: coalesce the token firehose into at most one content delta per
    # SLOW_STREAM_FLUSH_INTERVAL. last_flush starts at 0.0 so the first token
    # paints immediately; whatever is left is flushed after the loop.
    content_buffer = ""
    last_flush = 0.0

    async for chunk in stream:
        if first_chunk_at is None:
            first_chunk_at = time.monotonic() - start
        chunk_count += 1

        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        extra = delta.model_extra or {}
        if reasoning := extra.get("reasoning_content") or extra.get("reasoning"):
            reasoning_chars += len(reasoning)
            if show_reasoning:
                yield {"thinking_content": reasoning}

        if delta.content:
            if first_content_at is None:
                first_content_at = time.monotonic() - start
            content_chars += len(delta.content)
            if slow_stream:
                content_buffer += delta.content
                now = time.monotonic()
                if now - last_flush >= SLOW_STREAM_FLUSH_INTERVAL:
                    yield {"content": content_buffer}
                    content_buffer = ""
                    last_flush = now
            else:
                yield {"content": delta.content}

        for tool_call in delta.tool_calls or []:
            buffer = tool_calls.setdefault(
                tool_call.index, {"id": "", "name": "", "arguments": ""}
            )
            if tool_call.id:
                buffer["id"] = tool_call.id
            if tool_call.function and tool_call.function.name:
                buffer["name"] = tool_call.function.name
            if tool_call.function and tool_call.function.arguments:
                buffer["arguments"] += tool_call.function.arguments

    # Flush any content held back by the slow-mode throttle (no-op otherwise).
    if content_buffer:
        yield {"content": content_buffer}

    LOGGER.debug(
        "Fireworks stream: ttfc=%.2fs ttf_content=%s total=%.2fs chunks=%d "
        "reasoning_chars=%d content_chars=%d tool_calls=%d",
        first_chunk_at if first_chunk_at is not None else -1.0,
        f"{first_content_at:.2f}s" if first_content_at is not None else "none",
        time.monotonic() - start,
        chunk_count,
        reasoning_chars,
        content_chars,
        len(tool_calls),
    )

    if tool_calls:
        yield {
            "tool_calls": [
                llm.ToolInput(
                    id=buffer["id"],
                    tool_name=buffer["name"],
                    tool_args=_decode_tool_arguments(buffer["arguments"] or "{}"),
                )
                for _, buffer in sorted(tool_calls.items())
            ]
        }


async def async_prepare_files_for_prompt(
    hass: HomeAssistant, files: list[tuple[Path, str | None]]
) -> list[ChatCompletionContentPartImageParam]:
    """Append files to a prompt.

    Caller needs to ensure that the files are allowed.
    """

    def append_files_to_content() -> list[ChatCompletionContentPartImageParam]:
        content: list[ChatCompletionContentPartImageParam] = []

        for file_path, mime_type in files:
            if not file_path.exists():
                raise HomeAssistantError(f"`{file_path}` does not exist")

            if mime_type is None:
                mime_type = guess_file_type(file_path)[0]

            if not mime_type or not mime_type.startswith(("image/", "application/pdf")):
                raise HomeAssistantError(
                    "Only images and PDF are supported by the Fireworks API, "
                    f"`{file_path}` is not an image file or PDF"
                )

            base64_file = base64.b64encode(file_path.read_bytes()).decode("utf-8")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{base64_file}"},
                }
            )

        return content

    return await hass.async_add_executor_job(append_files_to_content)


class FireworksEntity(Entity):
    """Base entity for Fireworks AI."""

    _attr_has_entity_name = True

    def __init__(self, entry: FireworksConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.subentry = subentry
        self.model = subentry.data[CONF_MODEL]
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
        structure_name: str | None = None,
        structure: vol.Schema | None = None,
    ) -> None:
        """Generate an answer for the chat log."""

        model_args = {
            "model": self.model,
            "user": chat_log.conversation_id,
        }

        # Reasoning models accept `reasoning_effort` (none/low/medium/high/max);
        # the sentinel default means "leave it unset" so the model keeps its own.
        effort = self.subentry.data.get(CONF_REASONING_EFFORT, REASONING_EFFORT_DEFAULT)
        if effort != REASONING_EFFORT_DEFAULT:
            model_args["reasoning_effort"] = effort
            if effort != REASONING_EFFORT_NONE:
                # Reasoning on: keep its tokens from starving the answer.
                model_args["max_tokens"] = REASONING_MAX_TOKENS

        tools: list[ChatCompletionFunctionToolParam] | None = None
        if chat_log.llm_api:
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]

        if tools:
            model_args["tools"] = tools

        model_args["messages"] = [
            m
            for content in chat_log.content
            if (m := _convert_content_to_chat_message(content))
        ]

        last_content = chat_log.content[-1]

        # Handle attachments by adding them to the last user message
        if last_content.role == "user" and last_content.attachments:
            last_message: ChatCompletionMessageParam = model_args["messages"][-1]
            assert last_message["role"] == "user" and isinstance(
                last_message["content"], str
            )
            # Encode files with base64 and append them to the text prompt
            files = await async_prepare_files_for_prompt(
                self.hass,
                [(a.path, a.mime_type) for a in last_content.attachments],
            )
            last_message["content"] = [
                {"type": "text", "text": last_message["content"]},
                *files,
            ]

        if structure:
            if TYPE_CHECKING:
                assert structure_name is not None
            model_args["response_format"] = ResponseFormatJSONSchema(
                type="json_schema",
                json_schema=_format_structured_output(
                    structure_name, structure, chat_log.llm_api
                ),
            )

        client = self.entry.runtime_data.chat
        show_reasoning = self.subentry.data.get(CONF_SHOW_REASONING, False)
        slow_stream = self.subentry.data.get(CONF_SLOW_STREAM, False)

        for _iteration in range(MAX_TOOL_ITERATIONS):
            try:
                create_start = time.monotonic()
                # Disable retries here: a stalled stream that hits the read
                # timeout must fail fast, not silently retry and stack into a
                # multi-second freeze for the (often voice) caller.
                result = await client.with_options(
                    timeout=httpx.Timeout(
                        CHAT_REQUEST_TIMEOUT, connect=CHAT_CONNECT_TIMEOUT
                    ),
                    max_retries=0,
                ).chat.completions.create(**model_args, stream=True)
                LOGGER.debug(
                    "Fireworks create() returned in %.2fs "
                    "(model=%s, reasoning_effort=%s, max_tokens=%s, tools=%d)",
                    time.monotonic() - create_start,
                    self.model,
                    model_args.get("reasoning_effort", "<unset>"),
                    model_args.get("max_tokens", "<unset>"),
                    len(model_args.get("tools", [])),
                )

                model_args["messages"].extend(
                    [
                        msg
                        async for content in chat_log.async_add_delta_content_stream(
                            self.entity_id,
                            _transform_stream(result, show_reasoning, slow_stream),
                        )
                        if (msg := _convert_content_to_chat_message(content))
                    ]
                )
            except openai.OpenAIError as err:
                LOGGER.error("Error talking to API: %s", err)
                raise HomeAssistantError("Error talking to API") from err

            if not chat_log.unresponded_tool_results:
                break
