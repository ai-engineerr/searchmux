"""Value objects and the exception hierarchy for SearchMux."""

from dataclasses import dataclass, field


class SearchMuxError(Exception):
    """Base class for every error SearchMux raises."""


class BudgetExceeded(SearchMuxError):
    """Raised before a request that would exceed the credit budget."""


class RoutingError(SearchMuxError):
    """Raised when intent cannot be resolved to an engine."""


class CassetteMiss(SearchMuxError):
    """Raised on a replay miss. Never falls through to network."""


class SearchMuxAPIError(SearchMuxError):
    """Raised on a non-retryable SerpApi response."""


class CatalogError(SearchMuxError):
    """Raised when an engine is absent from the catalog."""


@dataclass(frozen=True, slots=True)
class Money:
    """A price, with its currency when the engine reports one.

    currency is None when the engine did not say. SerpApi frequently
    leaves the field null and puts a symbol in the price text instead,
    and guessing a code there would misreport money.
    """

    amount: float
    currency: str | None = None

    def __str__(self) -> str:
        """Return the amount, prefixed by its currency when known."""
        if not self.currency:
            return f"{self.amount:.2f}"
        return f"{self.currency} {self.amount:.2f}"


@dataclass(frozen=True, slots=True)
class Result:
    """One normalized search result from any engine.

    Attributes:
        title: Display title.
        url: Destination link, when the engine supplies one.
        snippet: Short description or excerpt.
        position: Rank within the engine's own result list.
        source: The engine_id that produced this result.
        price: Populated for commerce engines only.
        extra: Engine-specific fields worth promoting.
        raw: The untouched original item. Nothing is ever lost.
    """

    title: str
    url: str | None = None
    snippet: str | None = None
    position: int | None = None
    source: str | None = None
    price: Money | None = None
    extra: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
