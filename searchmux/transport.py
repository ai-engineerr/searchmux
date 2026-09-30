"""HTTP backends per search provider, with retry on server errors."""

import logging
import time

import httpx

from searchmux.constants import (
    BRAVE_BASE_URL,
    EXA_BASE_URL,
    HTTP_BACKOFF_BASE,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT,
    SERPAPI_BASE_URL,
    TAVILY_BASE_URL,
)
from searchmux.models import SearchMuxAPIError

logger = logging.getLogger(__name__)


class Backend:
    """Shared retry/backoff HTTP loop for every search provider.

    Retries 5xx and timeouts with exponential backoff. Never retries
    4xx, because a bad request stays bad and each attempt is
    billable. Subclasses supply only _build_request.
    """

    def __init__(self, client: httpx.Client | None = None) -> None:
        """Store the HTTP client.

        Args:
            client: Injected client, for tests. A default is built
                when omitted.
        """
        self._client = client or httpx.Client(timeout=HTTP_TIMEOUT)

    def _build_request(self, engine_id: str, params: dict) -> dict:
        """Return kwargs for httpx.Client.request().

        Must include "method" and "url", plus "params" or "json" for
        the request body, and "headers" when auth needs one.
        """
        raise NotImplementedError

    def fetch(self, engine_id: str, params: dict) -> dict:
        """Run one search and return the raw decoded body.

        Args:
            engine_id: The provider's identifier for this engine.
            params: Engine parameters, without any secret.

        Returns:
            The decoded JSON response body.

        Raises:
            SearchMuxAPIError: On a 4xx, or after retries are
                exhausted.
        """
        request = self._build_request(engine_id, params)
        last_error: Exception | None = None

        for attempt in range(HTTP_MAX_RETRIES):
            try:
                response = self._client.request(**request)
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "timeout on %s, attempt %d", engine_id, attempt + 1
                )
            else:
                if response.status_code < 400:
                    return response.json()
                if response.status_code < 500:
                    raise SearchMuxAPIError(
                        f"{engine_id} returned {response.status_code}: "
                        f"{self._error_text(response)}"
                    )
                last_error = SearchMuxAPIError(
                    f"{engine_id} returned {response.status_code}"
                )
                logger.warning(
                    "server error on %s, attempt %d",
                    engine_id,
                    attempt + 1,
                )

            if attempt < HTTP_MAX_RETRIES - 1:
                time.sleep(HTTP_BACKOFF_BASE * (2**attempt))

        raise SearchMuxAPIError(
            f"{engine_id} failed after {HTTP_MAX_RETRIES} attempts"
        ) from last_error

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        """Return the provider's error message, or the raw body."""
        try:
            return str(response.json().get("error", response.text))
        except ValueError:
            return response.text


class SerpApiBackend(Backend):
    """Performs SerpApi HTTP requests."""

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Store credentials and the HTTP client.

        Args:
            api_key: SerpApi key.
            client: Injected client, for tests.
        """
        super().__init__(client)
        self._api_key = api_key

    def _build_request(self, engine_id: str, params: dict) -> dict:
        query = {**params, "engine": engine_id, "api_key": self._api_key}
        return {"method": "GET", "url": SERPAPI_BASE_URL, "params": query}


class TavilyBackend(Backend):
    """Performs Tavily HTTP requests.

    POST with a JSON body; auth is a bearer token, not a body field.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(client)
        self._api_key = api_key

    def _build_request(self, engine_id: str, params: dict) -> dict:
        return {
            "method": "POST",
            "url": TAVILY_BASE_URL,
            "json": params,
            "headers": {"Authorization": f"Bearer {self._api_key}"},
        }


class BraveBackend(Backend):
    """Performs Brave Search HTTP requests.

    GET with query params, closest to SerpApi's own shape; auth is a
    header, not a query param.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(client)
        self._api_key = api_key

    def _build_request(self, engine_id: str, params: dict) -> dict:
        return {
            "method": "GET",
            "url": BRAVE_BASE_URL,
            "params": params,
            "headers": {"X-Subscription-Token": self._api_key},
        }


class ExaBackend(Backend):
    """Performs Exa HTTP requests.

    POST with a JSON body; x-api-key is used over the equally valid
    Authorization: Bearer form, for the simpler single-purpose header.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(client)
        self._api_key = api_key

    def _build_request(self, engine_id: str, params: dict) -> dict:
        return {
            "method": "POST",
            "url": EXA_BASE_URL,
            "json": {"contents": {"text": {"maxCharacters": 500}}, **params},
            "headers": {"x-api-key": self._api_key},
        }


# Backward-compat: existing code and tests import Transport directly.
Transport = SerpApiBackend
