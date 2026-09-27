"""SearchMux: the search layer for AI agents over SerpApi."""

from searchmux.client import SearchMux
from searchmux.models import (
    BudgetExceeded,
    CassetteMiss,
    CatalogError,
    Money,
    Result,
    RoutingError,
    SearchMuxAPIError,
    SearchMuxError,
)

__all__ = [
    "BudgetExceeded",
    "CassetteMiss",
    "CatalogError",
    "Money",
    "SearchMuxAPIError",
    "SearchMux",
    "SearchMuxError",
    "Result",
    "RoutingError",
]
__version__ = "0.1.0"
