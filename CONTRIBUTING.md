# Contributing

Thanks for looking. This is a small, focused library and the bar for changes is mostly about not breaking two promises: **nothing silently spends credits**, and **the test suite runs without an API key**.

## Setup

```bash
git clone https://github.com/ai-engineerr/searchmux.git
cd searchmux
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Python 3.11 or newer.

## Run the tests

```bash
python -m pytest -q
```

**The whole suite must pass with no API key set.** CI enforces this by clearing `SERPAPI_API_KEY` and `ANTHROPIC_API_KEY` on Python 3.11, 3.12 and 3.13. If a test needs the network, it is a mis-written test — record a cassette instead.

To prove it locally:

```bash
env -u SERPAPI_API_KEY -u ANTHROPIC_API_KEY python -m pytest -q
```

## Code style

Matching the existing code matters more than personal preference.

- PEP 8, 4-space indent, **maximum line length 79**
- `snake_case` for functions and variables, `CamelCase` for classes
- Imports grouped standard library → third-party → local, never wildcard
- Type hints on every function, method and public API
- Google-style docstrings, concise and accurate
- `logging`, never `print`; catch specific exceptions, never a bare `except:`
- No hardcoded values — strings, URLs and settings live in `searchmux/constants.py`
- Secrets come from `os.getenv()` and nowhere else

Check line length before opening a pull request:

```bash
awk 'length>79 {print FILENAME":"FNR": "length}' searchmux/*.py tests/*.py
```

## Tests come first

Write the failing test, watch it fail, then write the smallest code that passes it. Every behaviour worth keeping is worth a test that fails when it breaks.

Two areas deserve extra care because their failure modes are silent:

- **Anything touching money or credits.** A wrong currency or a budget that increments on a rejected spend will not raise; it will just be wrong. Test the boundary.
- **Anything touching keys.** `tests/test_no_secrets.py` scans every git-tracked file. Do not weaken it.

## Adding an engine

Most additions are one JSON record and no code.

1. Read the engine's page on serpapi.com. **Verify the parameter names against the documentation — do not guess.** Several engines are counter-intuitive: Amazon takes `k`, eBay takes `_nkw`, Walmart takes `query`, Yelp requires `find_loc`, YouTube takes `search_query`.
2. Add a record to `searchmux/catalog.json`:

```json
{
  "engine_id": "google_scholar",
  "description": "Academic papers, citations, and scholarly literature",
  "keywords": ["paper", "research", "citation", "academic", "journal"],
  "params": {
    "q": {"type": "string", "required": true},
    "as_ylo": {"type": "integer", "required": false}
  },
  "results_key": "organic_results",
  "result_map": {"title": "title", "url": "link", "snippet": "snippet"},
  "ttl_class": "stable"
}
```

3. Every engine needs at least one `"required": true` parameter — a test asserts it.
4. `results_key` may be a dotted path when results nest, for example `interest_over_time.timeline_data`.
5. `ttl_class` is `volatile` (prices, fares), `news` (news, jobs, videos) or `stable` (patents, papers, places).
6. `description` and `keywords` are the BM25 retrieval corpus. Write them as the words a user would actually type. **Never put the engine's own name in its keywords** — the evaluation would then measure the label rather than the router.
7. Add at least one case to `evals/routing.jsonl` and re-run the evaluation.

If an engine's results cannot be reached by a flat or dotted path, **do not add it**. `google_play` nests as `organic_results[].items[]` and is deliberately absent. An engine that silently returns nothing is worse than an engine that is missing.

## Running the evaluation

```bash
python -m evals.run_eval
```

The BM25 arm runs free and offline. The two LLM arms need `ANTHROPIC_API_KEY` and cost real money, roughly a dollar for all 50 cases.

If a change moves routing accuracy, say so in the pull request with the numbers. A measured regression is useful information; an unmeasured claim is not.

## Pull requests

- One concern per pull request
- Keep the diff small; delete more than you add where you can
- Say what you measured, not what you expect
- If you found something we got wrong, the README documents where our own thesis was disproved — corrections in that spirit are welcome

## Reporting a security issue

See [SECURITY.md](SECURITY.md). Please do not open a public issue for anything involving a leaked credential.
