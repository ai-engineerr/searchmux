"""Map engine-specific response envelopes onto Result."""

import logging

from searchmux.catalog import Engine, get_engine
from searchmux.models import Money, Result

logger = logging.getLogger(__name__)


def normalize(engine_id: str, body: dict) -> list[Result]:
    """Convert a raw SerpApi body into common Result objects.

    A missing or empty results key yields an empty list: SerpApi omits
    the key entirely when a search returns nothing, and that is not an
    error.

    Args:
        engine_id: The engine that produced this body.
        body: Raw decoded SerpApi response.

    Returns:
        Normalized results, in the engine's own order.
    """
    engine = get_engine(engine_id)
    items = _dig(body, engine.results_key)

    if not items:
        logger.debug("no %s in %s response", engine.results_key, engine_id)
        return []
    if isinstance(items, dict):
        items = [items]

    results = []
    for item in items:
        result = _build_result(engine, item)
        if result is not None:
            results.append(result)
    return results


def _build_result(engine: Engine, item: dict) -> Result | None:
    """Return one Result, or None when the item has no title."""
    mapping = engine.result_map
    title = item.get(mapping.get("title", "title"))
    if not title:
        logger.debug("skipping %s item without a title", engine.engine_id)
        return None

    return Result(
        title=str(title),
        url=item.get(mapping.get("url", "link")),
        snippet=item.get(mapping.get("snippet", "snippet")),
        position=item.get(mapping.get("position", "position")),
        source=engine.engine_id,
        price=_build_money(mapping, item),
        extra=_build_extra(mapping, item),
        raw=item,
    )


def _build_money(mapping: dict, item: dict) -> Money | None:
    """Return a Money when the engine maps a price field."""
    amount = item.get(mapping.get("price", "__absent__"))
    if amount is None:
        return None
    try:
        return Money(
            amount=float(amount),
            currency=str(item.get(mapping.get("currency"), "") or "USD"),
        )
    except (TypeError, ValueError):
        logger.debug("unparseable price %r", amount)
        return None


def _build_extra(mapping: dict, item: dict) -> dict:
    """Promote engine-specific fields worth surfacing."""
    extra = {}
    seller = item.get(mapping.get("source", "__absent__"))
    if seller:
        extra["seller"] = seller
    return extra

def _dig(body: dict, path: str) -> object:
    """Return the value at a dotted path, or None if absent.

    Some engines nest their results one level down, e.g. Google Trends
    puts them at ``interest_over_time.timeline_data``. A path without
    dots behaves exactly like a plain lookup.

    Args:
        body: Raw decoded SerpApi response.
        path: Key, or dot-separated path of keys.

    Returns:
        The value found, or None if any segment is missing.
    """
    node: object = body
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node
