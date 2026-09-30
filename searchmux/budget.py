"""Credit and, optionally, dollar budget enforcement, checked before
any billable request.
"""

import logging
import threading
from collections import Counter

from searchmux.models import BudgetExceeded

logger = logging.getLogger(__name__)


class Budget:
    """Caps billable requests and, optionally, real spend in dollars.

    Check-and-increment happens under one lock, so a concurrent caller
    can never push usage past either limit.
    """

    def __init__(
        self,
        limit: int,
        budget_usd: float | None = None,
        cost_per_request: dict[str, float] | None = None,
    ) -> None:
        """Set the ceiling(s).

        Args:
            limit: Maximum billable requests allowed. Always active.
            budget_usd: Optional dollar cap, checked alongside limit.
                None, the default, means no dollar tracking at all.
            cost_per_request: Provider name -> real cost of one
                request on the caller's own pricing plan. Only
                consulted when budget_usd is set.
        """
        self._limit = limit
        self._budget_usd = budget_usd
        self._cost_per_request = cost_per_request or {}
        self._used = 0
        self._spent_usd = 0.0
        self._by_engine: Counter[str] = Counter()
        self._lock = threading.Lock()

    def spend(self, engine_id: str, provider: str | None = None) -> None:
        """Consume one credit, and its dollar cost if tracked, or refuse.

        Args:
            engine_id: The engine about to be called.
            provider: The engine's provider. Required only when
                budget_usd is set; ignored otherwise.

        Raises:
            BudgetExceeded: If the request-count cap is already
                exhausted, or this request would push dollar spend
                past budget_usd. Nothing is incremented when this
                raises.
            ValueError: If budget_usd is set and provider has no rate
                in cost_per_request. Raised before anything spends.
        """
        with self._lock:
            if self._used >= self._limit:
                raise BudgetExceeded(
                    f"budget of {self._limit} credits is exhausted; "
                    f"raise it or narrow the query"
                )

            cost = 0.0
            if self._budget_usd is not None:
                if provider not in self._cost_per_request:
                    raise ValueError(
                        f"budget_usd is set but cost_per_request has "
                        f"no rate for provider {provider!r}"
                    )
                cost = self._cost_per_request[provider]
                if self._spent_usd + cost > self._budget_usd:
                    raise BudgetExceeded(
                        f"budget of ${self._budget_usd:.2f} would be "
                        f"exceeded by a ${cost:.4f} request "
                        f"(${self._spent_usd:.2f} already spent)"
                    )

            self._used += 1
            self._by_engine[engine_id] += 1
            if self._budget_usd is not None:
                self._spent_usd += cost

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
            Keys credits_used, remaining, and by_engine. Also
            spent_usd and remaining_usd, but only when budget_usd
            was set at construction.
        """
        with self._lock:
            result = {
                "credits_used": self._used,
                "remaining": self._limit - self._used,
                "by_engine": dict(self._by_engine),
            }
            if self._budget_usd is not None:
                result["spent_usd"] = self._spent_usd
                result["remaining_usd"] = (
                    self._budget_usd - self._spent_usd
                )
            return result
