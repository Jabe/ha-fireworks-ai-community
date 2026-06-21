"""Config flow for the Fireworks AI (community) integration."""

import logging
from typing import Any

from openai import AsyncOpenAI, APIStatusError, AuthenticationError, OpenAIError
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_MODEL
from homeassistant.core import callback
from homeassistant.helpers import llm
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
)

from .const import (
    CHAT_BASE_URL,
    CONF_PROMPT,
    CONF_REASONING_EFFORT,
    CONF_SHOW_REASONING,
    CONF_SLOW_STREAM,
    DOMAIN,
    REASONING_EFFORT_DEFAULT,
    REASONING_EFFORT_OPTIONS,
    RECOMMENDED_CONVERSATION_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)

_FIREWORKS_MODEL_PREFIX = "accounts/fireworks/models/"


def _model_label(model_id: str) -> str:
    """Return a friendlier label for a Fireworks model id.

    Fireworks model ids look like ``accounts/fireworks/models/llama-v3p1-8b``;
    the account prefix is trimmed for display only (the full id stays the value).
    """
    if model_id.startswith(_FIREWORKS_MODEL_PREFIX):
        return model_id[len(_FIREWORKS_MODEL_PREFIX) :]
    return model_id


def _reasoning_effort_selector() -> SelectSelector:
    """Build the (advanced) reasoning-effort dropdown.

    Reasoning models only. The leading "model default" option is a sentinel that
    leaves the param unset; the rest map straight to Fireworks' reasoning_effort.
    """
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=REASONING_EFFORT_DEFAULT, label="Model default"),
                *(
                    SelectOptionDict(value=value, label=value.capitalize())
                    for value in REASONING_EFFORT_OPTIONS
                ),
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


# Advanced-only fields and the default value that should never be persisted.
_ADVANCED_FIELD_DEFAULTS = {
    CONF_REASONING_EFFORT: REASONING_EFFORT_DEFAULT,
    CONF_SHOW_REASONING: False,
}


def _persist_advanced_fields(
    user_input: dict[str, Any], options: dict[str, Any]
) -> None:
    """Normalise the advanced-only fields before saving.

    Drops a field left at its default so it is never stored, and carries a
    previously-set value over when the field was hidden (advanced mode off), so
    reconfiguring without advanced mode does not wipe it.
    """
    for field, default in _ADVANCED_FIELD_DEFAULTS.items():
        if field in user_input:
            if user_input[field] == default:
                user_input.pop(field)
        elif field in options:
            user_input[field] = options[field]


class FireworksConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Fireworks AI."""

    VERSION = 1
    MINOR_VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this handler."""
        return {
            "conversation": ConversationFlowHandler,
            "ai_task_data": AITaskDataFlowHandler,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(user_input)
            client = AsyncOpenAI(
                base_url=CHAT_BASE_URL,
                api_key=user_input[CONF_API_KEY],
                http_client=get_async_client(self.hass),
            )
            try:
                async for _ in client.with_options(timeout=10.0).models.list():
                    break
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except APIStatusError as err:
                # A 5xx on the model-listing endpoint doesn't mean the key is
                # bad or the service is down: Fireworks' deployed-models endpoint
                # intermittently 500s for valid keys ("Error listing deployed
                # models"). The key already cleared auth (else AuthenticationError
                # above), so accept it — the entry's own setup tolerates the same
                # error. Non-5xx status errors keep failing as cannot_connect.
                if err.response.status_code < 500:
                    errors["base"] = "cannot_connect"
            except OpenAIError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            if not errors:
                # Fireworks has no key-label endpoint, so use a static title.
                return self.async_create_entry(
                    title="Fireworks AI",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )


class FireworksSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for Fireworks AI."""

    def __init__(self) -> None:
        """Initialize the subentry flow."""
        self.model_ids: list[str] = []

    async def _get_models(self) -> None:
        """Fetch the available model ids from Fireworks AI."""
        entry = self._get_entry()
        client = AsyncOpenAI(
            base_url=CHAT_BASE_URL,
            api_key=entry.data[CONF_API_KEY],
            http_client=get_async_client(self.hass),
        )
        # Same bound as the other validation calls; without it a hung API
        # stalls the form for the SDK's 600 s default.
        try:
            self.model_ids = [
                model.id
                async for model in client.with_options(timeout=10.0).models.list()
            ]
        except APIStatusError as err:
            # Fireworks' deployed-models endpoint intermittently 500s for valid
            # keys. The model field accepts any catalog id typed by hand
            # (custom_value=True), so degrade to an empty list and let the form
            # render instead of aborting the whole flow. Non-5xx errors still
            # propagate (the caller maps them to cannot_connect).
            if err.response.status_code < 500:
                raise
            _LOGGER.warning(
                "Fireworks model listing returned HTTP %s; showing the form "
                "without a prefilled model list (type the id manually): %s",
                err.response.status_code,
                err,
            )
            self.model_ids = []

    def _model_options(self) -> list[SelectOptionDict]:
        """Build the model dropdown options."""
        return [
            SelectOptionDict(value=model_id, label=_model_label(model_id))
            for model_id in self.model_ids
        ]


class ConversationFlowHandler(FireworksSubentryFlowHandler):
    """Handle conversation subentry flow."""

    def __init__(self) -> None:
        """Initialize the subentry flow."""
        super().__init__()
        self.options: dict[str, Any] = {}

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return self.source == SOURCE_USER

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """User flow to create a conversation agent."""
        self.options = RECOMMENDED_CONVERSATION_OPTIONS.copy()
        return await self.async_step_init(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of a conversation agent."""
        self.options = self._get_reconfigure_subentry().data.copy()
        return await self.async_step_init(user_input)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Manage conversation agent configuration."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        if user_input is not None:
            if not user_input.get(CONF_LLM_HASS_API):
                user_input.pop(CONF_LLM_HASS_API, None)
            _persist_advanced_fields(user_input, self.options)
            if self._is_new:
                return self.async_create_entry(
                    title=_model_label(user_input[CONF_MODEL]), data=user_input
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=user_input,
            )

        try:
            await self._get_models()
        except OpenAIError:
            return self.async_abort(reason="cannot_connect")
        except Exception:
            _LOGGER.exception("Unexpected exception")
            return self.async_abort(reason="unknown")

        hass_apis: list[SelectOptionDict] = [
            SelectOptionDict(
                label=api.name,
                value=api.id,
            )
            for api in llm.async_get_apis(self.hass)
        ]

        if suggested_llm_apis := self.options.get(CONF_LLM_HASS_API):
            valid_api_ids = {api["value"] for api in hass_apis}
            self.options[CONF_LLM_HASS_API] = [
                api for api in suggested_llm_apis if api in valid_api_ids
            ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODEL, default=self.options.get(CONF_MODEL)
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=self._model_options(),
                            mode=SelectSelectorMode.DROPDOWN,
                            sort=True,
                            # Fireworks' /v1/models is a curated subset — many
                            # serverless models are omitted even though they are
                            # callable — so allow typing any catalog model id
                            # (e.g. accounts/fireworks/models/<name>).
                            custom_value=True,
                        ),
                    ),
                    vol.Optional(
                        CONF_PROMPT,
                        description={
                            "suggested_value": self.options.get(
                                CONF_PROMPT,
                                RECOMMENDED_CONVERSATION_OPTIONS[CONF_PROMPT],
                            )
                        },
                    ): TemplateSelector(),
                    vol.Optional(
                        CONF_LLM_HASS_API,
                        default=self.options.get(
                            CONF_LLM_HASS_API,
                            RECOMMENDED_CONVERSATION_OPTIONS[CONF_LLM_HASS_API],
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(options=hass_apis, multiple=True)
                    ),
                    # Workaround for a chat-UI render race on very fast streams;
                    # kept visible (not advanced) so affected users can find it.
                    vol.Optional(
                        CONF_SLOW_STREAM,
                        default=self.options.get(CONF_SLOW_STREAM, False),
                    ): bool,
                    # Advanced-only: most users never touch these.
                    **(
                        {
                            vol.Optional(
                                CONF_REASONING_EFFORT,
                                default=self.options.get(
                                    CONF_REASONING_EFFORT, REASONING_EFFORT_DEFAULT
                                ),
                            ): _reasoning_effort_selector(),
                            vol.Optional(
                                CONF_SHOW_REASONING,
                                default=self.options.get(CONF_SHOW_REASONING, False),
                            ): bool,
                        }
                        if self.show_advanced_options
                        else {}
                    ),
                }
            ),
        )


class AITaskDataFlowHandler(FireworksSubentryFlowHandler):
    """Handle AI task subentry flow."""

    def __init__(self) -> None:
        """Initialize the subentry flow."""
        super().__init__()
        self.options: dict[str, Any] = {}

    @property
    def _is_new(self) -> bool:
        """Return if this is a new subentry."""
        return self.source == SOURCE_USER

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """User flow to create an AI task."""
        self.options = {}
        return await self.async_step_init(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of an AI task."""
        self.options = self._get_reconfigure_subentry().data.copy()
        return await self.async_step_init(user_input)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Manage AI task configuration."""
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")

        if user_input is not None:
            _persist_advanced_fields(user_input, self.options)
            if self._is_new:
                return self.async_create_entry(
                    title=_model_label(user_input[CONF_MODEL]), data=user_input
                )
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=user_input,
            )

        try:
            await self._get_models()
        except OpenAIError:
            return self.async_abort(reason="cannot_connect")
        except Exception:
            _LOGGER.exception("Unexpected exception")
            return self.async_abort(reason="unknown")

        # Fireworks' /models response does not expose structured-output support,
        # so list all models; structured-output support is model-dependent (see
        # the README).
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MODEL, default=self.options.get(CONF_MODEL)
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=self._model_options(),
                            mode=SelectSelectorMode.DROPDOWN,
                            sort=True,
                            # Fireworks' /v1/models is a curated subset — many
                            # serverless models are omitted even though they are
                            # callable — so allow typing any catalog model id
                            # (e.g. accounts/fireworks/models/<name>).
                            custom_value=True,
                        ),
                    ),
                    # Advanced-only: most users never touch these.
                    **(
                        {
                            vol.Optional(
                                CONF_REASONING_EFFORT,
                                default=self.options.get(
                                    CONF_REASONING_EFFORT, REASONING_EFFORT_DEFAULT
                                ),
                            ): _reasoning_effort_selector(),
                            vol.Optional(
                                CONF_SHOW_REASONING,
                                default=self.options.get(CONF_SHOW_REASONING, False),
                            ): bool,
                        }
                        if self.show_advanced_options
                        else {}
                    ),
                }
            ),
        )
