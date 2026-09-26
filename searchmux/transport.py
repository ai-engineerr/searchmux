"""HTTP transport for SerpApi, with retry on server errors."""

import logging
import time

import httpx

from searchmux.constants import (
    HTTP_BACKOFF_BASE,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT,
    SERPAPI_BASE_URL,
)
from searchmux.models import SearchMuxAPIError

logger = logging.getLogger(__name__)


class Transport:
    """Performs SerpApi HTTP requests.

    Retries 5xx and timeouts with exponential backoff. Never retries
    4xx, because a bad request stays bad and each attempt is billable.
    """

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Store credentials and the HTTP client.

        Args:
            api_key: SerpApi key.
            client: Injected client, for tests. A default is built
                when omitted.
        """
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=HTTP_TIMEOUT)

    def fetch(self, engine_id: str, params: dict) -> dict:
        """Run one search and return the raw decoded body.

        Args:
            engine_id: SerpApi engine identifier.
            params: Engine parameters, without api_key or engine.

        Returns:
            The decoded JSON response body.

        Raises:
            SearchMuxAPIError: On a 4xx, or after retries are exhausted.
        """
        query = {**params, "engine": engine_id, "api_key": self._api_key}
        last_error: Exception | None = None

        for attempt in range(HTTP_MAX_RETRIES):
            try:
                response = self._client.get(SERPAPI_BASE_URL, params=query)
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
                    "server error on %s, attempt %d", engine_id, attempt + 1
                )

            if attempt < HTTP_MAX_RETRIES - 1:
                time.sleep(HTTP_BACKOFF_BASE * (2**attempt))

        raise SearchMuxAPIError(
            f"{engine_id} failed after {HTTP_MAX_RETRIES} attempts"
        ) from last_error

    @staticmethod
    def _error_text(response: httpx.Response) -> str:
        """Return SerpApi's error message, or the raw body."""
        try:
            return str(response.json().get("error", response.text))
        except ValueError:
            return response.text
