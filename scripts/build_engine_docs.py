"""Regenerate docs/ENGINES.md from the committed engine catalog.

Run after changing searchmux/catalog.json:

    python scripts/build_engine_docs.py

The documentation is generated rather than hand-maintained so it cannot
drift away from the catalog the library actually loads.
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOG = ROOT / "searchmux" / "catalog.json"
OUTPUT = ROOT / "docs" / "ENGINES.md"

TTL_LABELS = {"volatile": "15 min", "news": "1 hour", "stable": "30 days"}

NOTES = """## Notes

**Parameter names are not uniform across engines.** They were verified \
against SerpApi's published documentation rather than assumed. Amazon \
takes `k`, eBay `_nkw`, Walmart `query`, Yelp requires `find_loc`, \
YouTube uses `search_query`, and Google Lens takes `url`. Guessing `q` \
everywhere produces a live 400.

**`google_play` is deliberately absent.** Its results nest as \
`organic_results[].items[]`, a list of lists that no flat or dotted \
path can express. Shipping an engine that silently returns nothing is \
worse than not listing it.

**`google_trends` returns timeline entries, not links.** It is a time \
series, so `Result.title` carries the date and the values live in \
`Result.raw`.
"""


def render(rows: list[dict]) -> str:
    """Return the full markdown page for a catalog.

    Args:
        rows: Catalog records, any order.

    Returns:
        The rendered page.
    """
    rows = sorted(rows, key=lambda r: r["engine_id"])
    out = [
        "# Engine catalog",
        "",
        f"The {len(rows)} engines SearchMux currently knows about. This "
        "file is generated from `searchmux/catalog.json` — edit the "
        "catalog, not this page.",
        "",
        "Adding an engine is one JSON record and zero lines of code. "
        "See [CONTRIBUTING.md](../CONTRIBUTING.md#adding-an-engine).",
        "",
        "## Summary",
        "",
        (
            "| Engine | Provider | Required parameters | Results key "
            "| Cache TTL |"
        ),
        "| --- | --- | --- | --- | --- |",
    ]
    for record in rows:
        required = ", ".join(
            f"`{name}`"
            for name, spec in record["params"].items()
            if spec.get("required")
        ) or "—"
        ttl = TTL_LABELS.get(record.get("ttl_class"), record.get("ttl_class"))
        out.append(
            f"| `{record['engine_id']}` | {record['provider']} | "
            f"{required} | `{record['results_key']}` | {ttl} |"
        )

    out += ["", "## Details", ""]
    for record in rows:
        out += [
            f"### `{record['engine_id']}`",
            "",
            f"Provider: `{record['provider']}`. {record['description']}",
            "",
        ]
        out += ["| Parameter | Type | Required |", "| --- | --- | --- |"]
        for name, spec in record["params"].items():
            out.append(
                f"| `{name}` | {spec.get('type', 'string')} | "
                f"{'yes' if spec.get('required') else 'no'} |"
            )
        mapped = ", ".join(
            f"`{key}` ← `{value}`"
            for key, value in record.get("result_map", {}).items()
        )
        out += [
            "",
            f"Results at `{record['results_key']}`. "
            f"Mapped: {mapped or '—'}.",
            "",
        ]

    out.append(NOTES)
    return "\n".join(out) + "\n"


def main() -> None:
    """Write docs/ENGINES.md from the catalog."""
    rows = json.loads(CATALOG.read_text(encoding="utf-8"))
    OUTPUT.write_text(render(rows), encoding="utf-8")
    print(f"wrote {OUTPUT} from {len(rows)} engines")


if __name__ == "__main__":
    main()
