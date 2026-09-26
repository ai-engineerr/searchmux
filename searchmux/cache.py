"""SQLite-backed response cache, keyed by canonical request hash."""

import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Callable

from searchmux.constants import SECRET_PARAM_KEYS

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key        TEXT PRIMARY KEY,
    body       TEXT NOT NULL,
    stored_at  REAL NOT NULL
)
"""


def request_key(engine_id: str, params: dict) -> str:
    """Return a stable hash identifying one logical request.

    Secret parameters are excluded, so the key is portable across API
    keys and safe to write into a committed file. Params are sorted and
    JSON-encoded with ensure_ascii off, so key order and non-ASCII text
    both hash deterministically.

    Args:
        engine_id: SerpApi engine identifier.
        params: Engine parameters, secrets included or not.

    Returns:
        A hex SHA-256 digest.
    """
    safe = {
        name: value
        for name, value in params.items()
        if name not in SECRET_PARAM_KEYS
    }
    canonical = json.dumps(
        [engine_id, sorted(safe.items())],
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Cache:
    """Stores raw SerpApi bodies so repeat requests cost no credits.

    Raw bodies are stored rather than normalized results, so changing
    the normalizer does not invalidate a warm cache.
    """

    def __init__(
        self,
        path: str,
        now: Callable[[], float] = time.time,
    ) -> None:
        """Open the cache database.

        Args:
            path: SQLite file path.
            now: Clock function, injected for tests.
        """
        self._now = now
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def get(self, key: str, ttl: int) -> dict | None:
        """Return a cached body if present and within its TTL.

        Args:
            key: Request key from request_key.
            ttl: Maximum age in seconds, inclusive.

        Returns:
            The cached body, or None on a miss or expiry.
        """
        row = self._conn.execute(
            "SELECT body, stored_at FROM responses WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None

        body, stored_at = row
        if self._now() - stored_at > ttl:
            logger.debug("cache entry %s expired", key[:8])
            return None
        return json.loads(body)

    def set(self, key: str, body: dict) -> None:
        """Store a body, replacing any existing entry.

        Args:
            key: Request key from request_key.
            body: Raw SerpApi response.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (key, body, stored_at) "
            "VALUES (?, ?, ?)",
            (key, json.dumps(body, ensure_ascii=False), self._now()),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()
