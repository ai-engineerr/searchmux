# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

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

[Unreleased]: https://github.com/ai-engineerr/searchmux/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ai-engineerr/searchmux/releases/tag/v0.1.0
