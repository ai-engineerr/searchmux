"""Regenerate searchmux/catalog.json param tables from SerpApi's docs.

Fetches each engine's documentation page and extracts its parameter
table, then merges the result onto the hand-written fields already in
catalog.json (description, keywords, result_map, ttl_class) by
engine_id. Those fields are never scraped; only params are extended.

Not on the critical path -- run manually when SerpApi changes a
param. The test suite never invokes this script.
"""

import json
import logging
import re
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "searchmux" / "catalog.json"
)
_DOC_URL_TEMPLATE = "https://serpapi.com/{engine_id}-api"
# ponytail: naive scrape, not a real HTML parser. Upgrade to
# BeautifulSoup if SerpApi's doc markup ever breaks this regex.
_PARAM_ROW = re.compile(
    r"<tr>\s*<td[^>]*><code>([\w.]+)</code></td>.*?</tr>",
    re.DOTALL,
)


def _load_existing(path: Path) -> dict[str, dict]:
    """Return existing catalog records keyed by engine_id.

    Args:
        path: Path to the committed catalog.json.

    Returns:
        Mapping of engine_id to its full existing record.
    """
    records = json.loads(path.read_text(encoding="utf-8"))
    return {record["engine_id"]: record for record in records}


def _fetch_params(engine_id: str, client: httpx.Client) -> dict:
    """Scrape the parameter table from an engine's SerpApi doc page.

    Args:
        engine_id: The SerpApi engine identifier.
        client: HTTP client to fetch the doc page with.

    Returns:
        Param name -> {"type": "string", "required": False}. Empty on
        any fetch or parse failure; the caller then keeps the params
        already on file for that engine.
    """
    slug = engine_id.replace("_", "-")
    url = _DOC_URL_TEMPLATE.format(engine_id=slug)
    try:
        response = client.get(url, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("could not fetch docs for %s: %s", engine_id, exc)
        return {}

    names = _PARAM_ROW.findall(response.text)
    return {name: {"type": "string", "required": False} for name in names}


def build_catalog(existing_path: Path = _CATALOG_PATH) -> list[dict]:
    """Regenerate params for every catalogued engine.

    Hand-written fields (description, keywords, result_map,
    ttl_class, and any required flags set by hand) are preserved by
    merging the scrape onto the existing record instead of replacing
    it outright.

    Args:
        existing_path: Path to the committed catalog.json.

    Returns:
        The merged list of engine records, in their original order.
    """
    existing = _load_existing(existing_path)
    merged = []
    with httpx.Client() as client:
        for engine_id, record in existing.items():
            scraped = _fetch_params(engine_id, client)
            params = dict(record["params"])
            for name, spec in scraped.items():
                if name not in params:
                    params[name] = spec
            merged.append({**record, "params": params})
    return merged


def main() -> None:
    """Regenerate catalog.json in place."""
    logging.basicConfig(level=logging.INFO)
    records = build_catalog()
    _CATALOG_PATH.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("wrote %d engines to %s", len(records), _CATALOG_PATH)


if __name__ == "__main__":
    main()
