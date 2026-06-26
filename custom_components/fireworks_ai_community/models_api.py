"""Fireworks Gateway API helpers for listing serverless models."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from .const import MODELS_BASE_URL, MODELS_LIST_TIMEOUT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class FireworksAuthError(Exception):
    """Raised when the Fireworks API rejects the API key."""


class FireworksApiError(Exception):
    """Raised when the Fireworks API returns a non-auth error."""

    def __init__(self, status_code: int, message: str) -> None:
        """Initialize."""
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def async_fetch_serverless_model_ids(
    hass: HomeAssistant,
    api_key: str,
    *,
    limit: int | None = None,
) -> list[str]:
    """Return serverless model ids from Fireworks' Gateway List Models API.

    Fireworks' OpenAI-compatible ``/inference/v1/models`` endpoint lists the
    caller's *deployed* models and 500s for serverless-only accounts. The
    control-plane catalog at ``/v1/accounts/fireworks/models`` is the supported
    way to discover callable serverless models.
    """
    from homeassistant.helpers.httpx_client import get_async_client

    client = get_async_client(hass)
    model_ids: list[str] = []
    page_token: str | None = None

    while True:
        page_size = 200
        if limit is not None:
            remaining = limit - len(model_ids)
            if remaining <= 0:
                break
            page_size = min(page_size, remaining)

        params: dict[str, str | int] = {
            "filter": "supports_serverless=true",
            "pageSize": page_size,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            response = await client.get(
                f"{MODELS_BASE_URL}/v1/accounts/fireworks/models",
                headers={"Authorization": f"Bearer {api_key}"},
                params=params,
                timeout=MODELS_LIST_TIMEOUT,
            )
        except httpx.RequestError as err:
            raise FireworksApiError(0, str(err)) from err

        if response.status_code == 401:
            raise FireworksAuthError(response.text)
        if response.status_code >= 400:
            raise FireworksApiError(response.status_code, response.text)

        data = response.json()
        model_ids.extend(model["name"] for model in data.get("models", []))

        page_token = data.get("nextPageToken")
        if not page_token or (limit is not None and len(model_ids) >= limit):
            break

    if limit is not None:
        return model_ids[:limit]
    return model_ids
