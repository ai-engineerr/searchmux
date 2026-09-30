"""Load and query the generated engine catalog."""

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from searchmux.constants import DEFAULT_TTL_CLASS
from searchmux.models import CatalogError

logger = logging.getLogger(__name__)

_CATALOG_FILE = Path(__file__).with_name("catalog.json")


@dataclass(frozen=True, slots=True)
class Engine:
    """Metadata describing one search engine, from any provider.

    Attributes:
        engine_id: The value the provider expects for this engine.
        provider: Which backend serves this engine ("serpapi",
            "tavily", "brave", or "exa").
        description: Human-readable purpose, used for BM25 retrieval.
        keywords: Extra retrieval terms.
        params: Param name -> {"type", "required", ...}.
        results_key: Response key holding the result list.
        result_map: Result field -> source key in the raw item.
        ttl_class: Cache volatility class.
        cacheable: Whether responses may be stored at all. True unless
            a provider's terms forbid storing results.
    """

    engine_id: str
    provider: str
    description: str
    keywords: list[str]
    params: dict
    results_key: str
    result_map: dict
    ttl_class: str = DEFAULT_TTL_CLASS
    cacheable: bool = True


@lru_cache(maxsize=1)
def load_catalog(path: str | None = None) -> dict[str, Engine]:
    """Return every catalogued engine, keyed by engine_id.

    Args:
        path: Optional override for the catalog file location.

    Returns:
        Mapping of engine_id to Engine.

    Raises:
        CatalogError: If the catalog file is missing or malformed.
    """
    target = Path(path) if path else _CATALOG_FILE
    try:
        records = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"catalog not found at {target}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"catalog at {target} is not valid JSON") from exc

    catalog = {}
    for record in records:
        engine = Engine(
            engine_id=record["engine_id"],
            provider=record["provider"],
            description=record["description"],
            keywords=record.get("keywords", []),
            params=record["params"],
            results_key=record["results_key"],
            result_map=record.get("result_map", {}),
            ttl_class=record.get("ttl_class", DEFAULT_TTL_CLASS),
            cacheable=record.get("cacheable", True),
        )
        catalog[engine.engine_id] = engine

    logger.debug("loaded %d engines from %s", len(catalog), target)
    return catalog


def get_engine(engine_id: str) -> Engine:
    """Return one engine by id.

    Args:
        engine_id: The SerpApi engine identifier.

    Returns:
        The matching Engine.

    Raises:
        CatalogError: If no such engine is catalogued.
    """
    try:
        return load_catalog()[engine_id]
    except KeyError as exc:
        raise CatalogError(f"unknown engine: {engine_id}") from exc
