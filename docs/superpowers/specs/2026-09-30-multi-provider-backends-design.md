# Multi-provider search backends — Design Spec

**Date:** 2026-09-30
**Status:** Approved, ready for implementation planning
**Constraint:** Local work only. No `git push`, no PyPI publish, until explicitly authorized.

---

## 1. Problem

SearchMux currently supports exactly one search provider: SerpApi. That is a real, deliberate limitation raised in external review: agent builders increasingly use search APIs designed specifically for LLM consumption — Tavily, Brave Search, Exa — which already return clean, flat result shapes. SerpApi could add caching or smarter routing to its own tools at any time, which makes a SerpApi-only cost/testing layer a comparatively narrow bet.

The counter-argument, and the one this spec acts on: SearchMux's cache, budget guard, cassette replay, and normalized `Result` shape were never actually SerpApi-specific in design — only the transport layer (`Transport`, hardcoded to SerpApi's URL and query convention) and the catalog (SerpApi's 24 engines) are. Generalizing those two pieces turns a SerpApi add-on into a provider-agnostic search layer without touching what already works.

## 2. Scope

Add three new providers as first-class catalog entries, sharing every existing pipeline stage unchanged: cache, budget, cassette, and normalizer.

- **Tavily** — 1 engine (`tavily_search`)
- **Brave Search** — 1 engine (`brave_search`)
- **Exa** — 1 engine (`exa_search`)

Each is a single search endpoint (unlike SerpApi's 24), so this is three new catalog records, not an attempt to replicate SerpApi's breadth per provider.

**Verified access for this work:** Tavily and Exa keys are available and will be live-tested. Brave has no key available — it is built and doc-verified to the same standard as the other two, but not live-tested. This asymmetry is disclosed in the catalog and docs, not hidden.

**Explicitly out of scope:** reframing the project's public identity. The README continues to lead with SerpApi as the primary, most deeply integrated backend; the other three are documented as additional supported backends underneath. This is a decision, not an oversight — revisiting it is a separate, later choice.

## 3. Verified provider contracts

Checked against each provider's current published documentation, not assumed:

| Provider | Method | URL | Auth | Required param | Results path |
|---|---|---|---|---|---|
| SerpApi (existing) | GET | `serpapi.com/search` | `api_key` query param | `q` (varies) | flat, per-engine |
| Tavily | POST | `api.tavily.com/search` | `Authorization: Bearer <key>` header | `query` | `results[]` |
| Brave | GET | `api.search.brave.com/res/v1/web/search` | `X-Subscription-Token: <key>` header | `q` | `web.results[]` |
| Exa | POST | `api.exa.ai/search` | `x-api-key: <key>` header | `query` | `results[]` |

All three new providers use header-based auth — none need the key in the query string or the JSON body, which is simpler than initially assumed for Tavily. Two are POST-with-JSON-body (Tavily, Exa); one is GET-with-query-params (Brave), matching SerpApi's own shape most closely.

Exa's docs accept either `x-api-key` or `Authorization: Bearer` for the same purpose. `x-api-key` is used here — a deliberate pick for the simpler, single-purpose header, not an oversight of the alternative.

**Result-field mapping**, verified against each provider's documented response shape:

| Provider | title | url | snippet |
|---|---|---|---|
| Tavily | `title` | `url` | `content` |
| Brave | `title` | `url` | `description` |
| Exa | `title` | `url` | `text` |

All three fit the *existing* `results_key` (with dotted-path support, already built for `google_trends`) and `result_map` convention. **No changes to `normalize.py` are needed** — this is a smaller change than it first appeared, since the generic envelope-mapping logic already handles arbitrary result shapes; only new catalog data is needed, not new normalization code.

## 4. Architecture

### 4.1 `Engine` gains a `provider` field

```python
@dataclass(frozen=True, slots=True)
class Engine:
    engine_id: str
    provider: str          # NEW: "serpapi" | "tavily" | "brave" | "exa"
    description: str
    keywords: list[str]
    params: dict
    results_key: str
    result_map: dict
    ttl_class: str = DEFAULT_TTL_CLASS
```

All 24 existing SerpApi catalog records get `"provider": "serpapi"` added explicitly. Not defaulted — the same discipline the catalog already holds itself to.

### 4.2 `Backend` replaces the single concrete `Transport`

Today, `Transport` is one class hardcoded to SerpApi's convention: GET, `api_key` and `engine` as query params, retry 5xx up to 3 times, never retry 4xx.

That retry/backoff logic is shared and correct; only *how one request is built* varies by provider. The design splits this:

- A shared `fetch()` implementation (the existing retry loop, moved to one place) calls an abstract `_build_request(engine_id, params) -> Request` on whichever backend is in use.
- `SerpApiBackend` is the current `Transport`, renamed and refactored to supply only its own `_build_request`.
- `TavilyBackend`, `BraveBackend`, `ExaBackend` are new, each roughly 20-30 lines: base URL, auth placement, and whether params go in the query string or the JSON body.

This is a refactor of `transport.py`, not a rewrite — the retry/backoff behavior every existing test already exercises stays identical, just relocated to the shared base.

### 4.3 Multi-key configuration, lazy per-provider

```python
SearchMux(
    api_key=None,           # SerpApi, existing
    tavily_api_key=None,    # NEW, falls back to TAVILY_API_KEY
    brave_api_key=None,     # NEW, falls back to BRAVE_API_KEY
    exa_api_key=None,       # NEW, falls back to EXA_API_KEY
)
```

Backends are constructed lazily, one per provider, only when an engine from that provider is actually requested — exactly today's behavior for SerpApi (`_require_transport()`), generalized to `_require_backend(provider)`. Requesting a SerpApi engine still never touches the other three keys. A missing key for a requested provider raises `ValueError` naming the specific environment variable, matching the existing message shape.

### 4.4 Backward compatibility (126 existing tests)

The `transport=` constructor kwarg keeps working exactly as-is for SerpApi injection — every existing SerpApi-focused test is untouched. A new `backends={"tavily": fake, "exa": fake, ...}` kwarg is added alongside it for the three new providers' tests. Internally, `_require_backend("serpapi")` checks the legacy `transport=` injection first for backward compatibility, then falls through to the new `backends` map, then to lazy real construction.

## 5. Testing, without live keys for Brave

Same pattern already proven for SerpApi's `Transport`:

- **Request-shape tests** (`httpx.MockTransport`): for each new backend, assert the exact method, URL, and auth placement — mirrors `tests/test_transport.py` exactly.
- **Normalization tests**: for each new catalog entry, assert a doc-derived sample response body maps to `Result` correctly — mirrors `tests/test_normalize.py` exactly.
- **The whole-suite-offline invariant extends.** No new test requires `TAVILY_API_KEY`, `BRAVE_API_KEY`, or `EXA_API_KEY` to run. `tests/test_no_secrets.py` and the "runs with no key" CI step cover the new provider keys the same way they already cover the first two.
- **Tavily and Exa get one additional pass Brave doesn't**: a manual live smoke check against the real API, using the now-available keys, confirming the doc-verified shape matches an actual response — the same live-correction step that caught real errors in the original SerpApi catalog (Amazon's `k` vs `q`).

## 6. Rollout

- **Version**: this is `0.2.0` — new public surface (`tavily_api_key`, `brave_api_key`, `exa_api_key` constructor args; `backends=` kwarg), backward compatible, nothing breaking.
- **Local only.** Every commit stays local. No `git push`, no PyPI build/upload, until explicitly authorized — this spec does not change that instruction.
- **Docs to update once implemented**: `docs/API.md` (new constructor args), `docs/ARCHITECTURE.md` (the Backend abstraction and why), `docs/ENGINES.md` (regenerated via the existing `scripts/build_engine_docs.py`, extended to show a provider column), `CHANGELOG.md`. README's opening framing is unchanged per §3.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Brave shape is wrong without a live check | Doc-verified to the same standard as the other two; disclosed as unverified live, not silently treated as equal confidence |
| Refactoring `Transport` regresses the 126 existing SerpApi tests | Retry/backoff logic is relocated, not rewritten; `transport=` injection kwarg is preserved byte-for-byte for existing tests |
| Scope creep into full backend-agnostic reframing | Explicitly out of scope (§2); README framing decision already made and recorded |
| Accidentally pushing or publishing mid-work | Rollout section states the constraint explicitly; no push/publish step appears anywhere in the implementation plan that follows this spec |
