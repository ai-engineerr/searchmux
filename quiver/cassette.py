"""Record and replay SerpApi responses, so tests cost nothing."""

import json
import logging
from pathlib import Path

from quiver.cache import request_key
from quiver.constants import SECRET_PARAM_KEYS
from quiver.models import CassetteMiss

logger = logging.getLogger(__name__)

MODE_RECORD = "record"
MODE_REPLAY = "replay"


class Cassette:
    """A file of captured SerpApi responses.

    In replay mode a miss raises CassetteMiss and never falls through
    to the network. That is deliberate: a test must not silently start
    spending credits.
    """

    def __init__(self, path: str, mode: str) -> None:
        """Open a cassette.

        Args:
            path: Cassette file path.
            mode: Either "record" or "replay".

        Raises:
            ValueError: On an unknown mode.
        """
        if mode not in (MODE_RECORD, MODE_REPLAY):
            raise ValueError(f"mode must be record or replay, got {mode!r}")

        self._path = Path(path)
        self._mode = mode
        self._entries: dict[str, dict] = {}
        self._captured: dict[str, dict] = {}
        if mode == MODE_REPLAY:
            self._load()

    def _load(self) -> None:
        """Read entries from disk, tolerating an absent file."""
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.warning("cassette %s does not exist yet", self._path)
            return
        except json.JSONDecodeError:
            logger.error("cassette %s is not valid JSON", self._path)
            return

        for entry in payload.get("entries", []):
            key = request_key(entry["engine_id"], entry["params"])
            self._entries[key] = entry["body"]

    def play(self, engine_id: str, params: dict) -> dict:
        """Return a recorded body for this request.

        Args:
            engine_id: SerpApi engine identifier.
            params: Engine parameters. Secrets are ignored when
                matching, so any key replays any recording.

        Returns:
            The recorded response body.

        Raises:
            CassetteMiss: If nothing was recorded for this request.
        """
        key = request_key(engine_id, params)
        if key not in self._entries:
            raise CassetteMiss(
                f"no recording for {engine_id} with {self._safe(params)}; "
                f"re-record with Quiver.record()"
            )
        return self._entries[key]

    def capture(self, engine_id: str, params: dict, body: dict) -> None:
        """Store one response for later replay.

        Args:
            engine_id: SerpApi engine identifier.
            params: Engine parameters. Secrets are stripped.
            body: Raw response body.
        """
        key = request_key(engine_id, params)
        self._entries[key] = body
        self._captured[key] = {
            "engine_id": engine_id,
            "params": self._safe(params),
            "body": body,
        }

    def save(self) -> None:
        """Write captured entries to disk, secrets excluded."""
        entries = list(self._captured.values())
        payload = {"version": 1, "entries": entries}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("wrote %d entries to %s", len(entries), self._path)

    @property
    def entry_count(self) -> int:
        """Return how many responses this cassette holds."""
        return len(self._entries)

    @property
    def mode(self) -> str:
        """Return this cassette's mode."""
        return self._mode

    @staticmethod
    def _safe(params: dict) -> dict:
        """Return params with secret keys removed."""
        return {
            name: value
            for name, value in params.items()
            if name not in SECRET_PARAM_KEYS
        }
