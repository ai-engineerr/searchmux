"""SearchMux: cost control and offline testing for agent search."""

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
from searchmux.recommendations import recommended_providers

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
    "recommended_providers",
]
__version__ = "0.2.0"
