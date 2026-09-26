"""Credit budget enforcement, checked before any billable request."""

import logging
import threading
from collections import Counter

from searchmux.models import BudgetExceeded

logger = logging.getLogger(__name__)


class Budget:
    """Caps billable requests and records where credits went.

    Check-and-increment happens under one lock, so a concurrent caller
    can never push usage past the limit.
    """

    def __init__(self, limit: int) -> None:
        """Set the ceiling.

        Args:
            limit: Maximum billable requests allowed.
        """
        self._limit = limit
        self._used = 0
        self._by_engine: Counter[str] = Counter()
        self._lock = threading.Lock()

    def spend(self, engine_id: str) -> None:
        """Consume one credit, or refuse.

        Args:
            engine_id: The engine about to be called.

        Raises:
            BudgetExceeded: If the budget is already exhausted. Nothing
                is incremented when this raises.
        """
        with self._lock:
            if self._used >= self._limit:
                raise BudgetExceeded(
                    f"budget of {self._limit} credits is exhausted; "
                    f"raise it or narrow the query"
                )
            self._used += 1
            self._by_engine[engine_id] += 1

    @property
    def used(self) -> int:
        """Return credits consumed so far."""
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        """Return credits still available."""
        with self._lock:
            return self._limit - self._used

    def report(self) -> dict:
        """Return a spend breakdown.

        Returns:
            Keys credits_used, remaining, and by_engine.
        """
        with self._lock:
            return {
                "credits_used": self._used,
                "remaining": self._limit - self._used,
                "by_engine": dict(self._by_engine),
            }
