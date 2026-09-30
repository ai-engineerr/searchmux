# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.3.0] — 2026-09-30

### Added

- `recommended_providers(category)`, a data-backed provider fallback
  order derived directly from the provider eval's own per-category
  p95-latency findings (`evals/results/2026-09-30.json`) — the first
  place this project's own measurement changes a shipped default
  instead of staying a README number nobody acts on. Deliberately not
  automatic: SearchMux never classifies a query's category itself,
  this is an opinionated starting point a caller passes straight to
  `find(providers=recommended_providers("current_events"))`. Covers
  the six measured categories (factual, research, current_events,
  how_to, technical, health_science) plus a `DEFAULT_ORDER` fallback
  for anything else; excludes Brave, no live data for it yet.
- `Result.extra` now promotes any field a catalog entry maps under
  `result_map["extra"]`, not just `seller`. Tavily results carry a
  `score` (relevance) and Exa results carry `published_date`, verified
  against live responses from both. `google_shopping`'s existing
  `seller` promotion moved onto this same mechanism.
- Caching is now opt-out per engine. `Engine.cacheable` (default
  `True`) lets a catalog entry declare it must never be stored — for a
  provider whose terms restrict retaining results. `SearchMux(no_cache=
  {...})` adds the same exclusion at runtime, by provider name or
  engine id, without editing the catalog; it can only narrow, never
  re-enable an engine the catalog already marked non-cacheable.
- Optional dollar budget alongside the existing request-count one.
  `SearchMux(budget_usd=10.0, cost_per_request={"serpapi": 0.0075})`
  raises `BudgetExceeded` before a request would push real spend past
  the cap. No default prices are shipped — real per-request cost
  varies by the caller's own pricing plan, so a hardcoded number would
  misrepresent it for most users; a provider used under `budget_usd`
  with no rate given raises `ValueError` instead of silently not
  counting. `budget=` keeps meaning request-count exactly as before;
  `budget_usd` is off unless explicitly set.
- Provider-level fallback routing. `q.find(intent, providers=["exa",
  "serpapi"])` tries each provider in order, moving to the next on a
  backend failure, a missing key, or no matching engine, instead of
  the caller having to catch and retry manually. `Router.route()`
  gained a matching per-call `providers` filter that
  `SearchMux.find()` uses internally. `providers=None` (the default)
  is a single unrestricted attempt, identical to today's behavior,
  including for hand-written routers that don't accept a `providers`
  argument at all.

### Measured

- `python -m evals.provider_eval`, a head-to-head of SerpApi's
  `google`, Tavily's `tavily_search`, and Exa's `exa_search`, scaled
  from 15 to 60 queries across six categories — factual, research,
  current events, how-to, technical, health/science — with a
  per-category breakdown, not just one aggregate table. All three
  asked for the same 10 results per query. Reports median and p95
  latency plus first-attempt vs. after-retry success, not just a
  mean: this run caught a real SerpApi failure (1/60 after 3 retries)
  and a p95 tail (16.2s overall, 91.6s on `current_events`) that its
  1,068ms median alone would have hidden. Also reports a cost column
  from each provider's published list price (checked 2026-09-30,
  explicitly not account-specific) and an approximate-tokens-returned
  figure instead of a raw snippet length. Two free relevance signals:
  domain overlap between providers (Jaccard on result domains — all
  three stayed under 15% with each other, genuinely different
  sources) and answer-containment on the 10 factual-category queries
  (100% for all three). Brave is listed with its published price but
  has no live row — no key available — shown as a pending table row
  rather than silently omitted. Every run now saves a dated JSON
  snapshot to `evals/results/`, so this becomes a real history rather
  than a one-off number; nothing runs on a schedule or in CI, since
  that would mean committing to recurring paid spend without a
  standing decision to do so. See the README's Provider comparison
  section for the full numbers and caveats.

## [0.2.0] — 2026-09-30

### Added

- Multi-provider search: `tavily_search`, `brave_search`, and
  `exa_search` join the catalog alongside SerpApi's 24 engines, all
  through the same cache, budget guard, cassette replay, and
  `Result` normalization. `Engine.provider` marks which backend each
  entry uses.
- `SearchMux(tavily_api_key=, brave_api_key=, exa_api_key=)`, each
  falling back to its own environment variable, and a `backends=`
  constructor kwarg for injecting fakes in tests. `transport=` keeps
  working exactly as before for SerpApi.
- `transport.py`'s retry/backoff loop is now shared by every backend
  through a `Backend` base class; `Transport` is kept as an alias
  for the SerpApi backend, so no existing import breaks.

### Verified

- Tavily and Exa request shapes were checked against a live call
  using real keys. Brave was built and doc-verified to the same
  standard but has no live check yet — no key was available.
- Exa requests are capped to 500 characters of page text per result
  (`contents.text.maxCharacters`), not the full page — every other
  provider's snippet is a sentence or two, and Exa's default response
  is otherwise the entire page body.

## [0.1.5] — 2026-09-29

### Added

- `as_openai_tool()`, wrapping the existing schema in OpenAI's
  function-calling envelope. `as_tool()` was documented as
  OpenAI-compatible but returned Anthropic's flat shape, which OpenAI
  rejects.
- `examples/openai_agent.py`, a real tool-calling loop verified
  against a mocked OpenAI client.
- PyPI, CI, and license badges in the README.

## [0.1.4] — 2026-09-29

### Changed

- The "In plain terms" label removal did not make it into 0.1.3 (an
  earlier, unseen upload attempt of that version must have succeeded
  before the label was removed locally). Carried here.

## [0.1.3] — 2026-09-29

### Changed

- The plain-English opening line did not make it into 0.1.2 (a PyPI
  upload reported a client-side error but had already succeeded
  server-side, the same way 0.1.1's first upload did). Carried here.

## [0.1.2] — 2026-09-29

### Changed

- Team names in the README now link to LinkedIn profiles.

## [0.1.1] — 2026-09-29

### Fixed

- README links to `docs/*.md` and other repo files were relative
  paths, which resolve on GitHub but 404 on PyPI, where the README is
  served from the project page rather than the repo root. All doc
  links are now absolute GitHub URLs; the interactive architecture
  diagram links through htmlpreview.github.io since GitHub's own
  `blob` view shows HTML as source rather than rendering it.
- Removed the hackathon/track line from the PyPI-facing description.

## [0.1.0] — 2026-09-27

First release. Built for the SerpApi India Hackathon 2026.

### Added

- **`SearchMux` facade** with a single request pipeline: route → cache → budget → transport → normalize → cache write.
- **Engine catalog** covering 24 SerpApi engines, generated at build time and committed so the library resolves no schemas over the network and works fully offline.
- **SQLite response cache** keyed by a canonical hash of the request with secrets excluded, so entries are portable across API keys and machines. TTL is set per engine class: 15 minutes for prices and fares, 1 hour for news, 30 days for patents and papers.
- **Thread-safe budget guard** that raises `BudgetExceeded` *before* a request rather than after, with per-engine spend reporting through `report()`.
- **Record and replay cassettes**, so a test suite can exercise search paths at zero cost. A replay miss raises rather than falling through to the network, and `api_key` is stripped on write so cassettes are safe to commit.
- **Normalized results.** One `Result` dataclass across every engine, with the untouched original always available on `raw`. `results_key` supports dotted paths for engines whose results nest.
- **Intent router** using BM25 retrieval plus schema-constrained synthesis, with a deterministic bypass (`engine=`) that needs no LLM at all.
- **Adapters**: `as_tool()` emits a JSON-schema tool definition for Anthropic, OpenAI function-calling and LangChain; `searchmux-mcp` runs an MCP stdio server exposing a single `find` tool.
- **Evaluation harness** (`python -m evals.run_eval`) scoring three routing strategies against 50 hand-labelled intents. The retrieval-only arm runs free and offline.
- **Opt-in `.env` loading** via `load_env()`, never called on import.
- 115 tests, all passing with no API key set, enforced in CI on Python 3.11, 3.12 and 3.13.

### Measured

Routing accuracy on `evals/routing.jsonl`, all figures from real runs against the live API:

| arm | accuracy |
| --- | --- |
| Random choice over 24 engines | ~4% |
| BM25 top-1, no LLM | 52% |
| BM25 top-5 + closed schemas | 82% |
| BM25 top-12 + closed schemas | 88% |
| All engine names, no schemas | 98% |
| **All engines + closed schema** | **98%** |

### Changed during development

Recorded because the reasoning matters more than the result.

- **Narrowing is off by default.** The project's starting thesis was that BM25 narrowing would beat handing the model every engine. It measured worse: the top-5 arm scored exactly its own retrieval recall@5 of 82%, meaning the shortlist was discarding the right answer 18% of the time. `DEFAULT_ROUTER_TOP_K` is now `None`.
- **Parameters travel as name/value pairs.** A schema built from every engine's parameters is rejected by the API as *"Schema is too complex"*, so the schema is now a fixed size regardless of catalog growth, with names validated against the chosen engine afterwards.
- **Currency is never invented.** An earlier version defaulted to `"USD"` when SerpApi reported `currency: null`, which misreported ₹ prices as dollars. `Money.currency` is now optional and the symbol is recovered from the price text where possible.
- **`google_play` was removed from the catalog.** Its results nest as `organic_results[].items[]`, which no flat or dotted path can reach, so it would have silently returned nothing.
- **`anthropic>=1.8` is now required.** Version 0.40 accepts `output_config` and rejects it at call time; `tests/test_sdk_compat.py` now catches that at install time instead.

### Fixed

- Nested object schemas need `additionalProperties: false` too, not only the root. Missing it produced a 400 on every routing call.
- The demo crashed on Windows consoles when a result title contained a typographic space.
- The secret scanner walked the filesystem instead of asking git which files are tracked, flagging local recordings that were never going to be published.

[Unreleased]: https://github.com/ai-engineerr/searchmux/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/ai-engineerr/searchmux/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/ai-engineerr/searchmux/compare/v0.1.5...v0.2.0
[0.1.5]: https://github.com/ai-engineerr/searchmux/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/ai-engineerr/searchmux/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/ai-engineerr/searchmux/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/ai-engineerr/searchmux/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/ai-engineerr/searchmux/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ai-engineerr/searchmux/releases/tag/v0.1.0
