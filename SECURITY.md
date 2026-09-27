# Security

SearchMux handles API keys and writes files that people commit to public repositories, so most of its security surface is about keeping credentials out of places they should not be.

## Reporting a vulnerability

Open a [GitHub security advisory](https://github.com/ai-engineerr/searchmux/security/advisories/new) rather than a public issue. That applies especially to anything involving a credential that may have leaked through the cache, a cassette, or a log line.

If you believe a key has already been exposed, rotate it first at [serpapi.com](https://serpapi.com/manage-api-key) or [console.anthropic.com](https://console.anthropic.com/settings/keys), then report.

## How credentials are handled

**Keys are read from the environment only.** `SERPAPI_API_KEY` and `ANTHROPIC_API_KEY` are read through `os.getenv()`. Nothing is hardcoded and nothing is written to disk by the library.

**`.env` is gitignored; `.env.example` holds names only.** A test asserts that `.env` is untracked and that every line in `.env.example` ends in `=` with no value after it.

**Cache keys cannot contain a key.** `request_key()` removes every name in `SECRET_PARAM_KEYS` before hashing, so key text never reaches the digest input. Two users with different keys produce identical cache keys, which is also why a shared cache is safe.

**Cassettes are stripped on write.** `api_key` is removed before a cassette is saved, which is what makes committing them safe. A cassette recorded with one key replays with any key, or with none.

**Nothing is logged at a level that would print a key.** Request parameters are not logged; only engine identifiers and truncated cache-key prefixes are.

## Automated checks

`tests/test_no_secrets.py` runs on every CI build and:

- asks **git** which files are tracked, rather than walking the filesystem, since only tracked files are ever published
- scans each one for 40+ character hex strings and `sk-` prefixed tokens
- asserts `.env` is not tracked
- asserts `.env.example` contains no values

A local recording or cache file sitting in your working tree is not a leak and is correctly ignored.

## What to check before publishing

If you fork this or record your own cassettes:

```bash
python -m pytest tests/test_no_secrets.py -q
git ls-files | xargs grep -lE 'sk-[A-Za-z0-9_-]{20,}|\b[0-9a-f]{64}\b'
```

The second command should print nothing.

Be aware that **force-pushing does not immediately remove blobs from GitHub.** A commit remains reachable by its full SHA until GitHub's garbage collection runs. If a credential ever reaches a public commit, rotate the credential — rewriting history is not sufficient on its own.

## Scope and limits

SearchMux is a client library. It does not run a server, open a port, accept untrusted input from a network, or execute anything it receives.

Two things worth knowing:

- **Cached and recorded responses are third-party content.** They are stored and replayed verbatim, never executed or interpreted. If you commit a cassette, you are publishing whatever that search returned, so read it first.
- **Caching reduces duplicate billable requests.** That is a supported usage pattern, not a way around rate limits or terms of service. SearchMux does not proxy, rotate keys, or evade limits, and pull requests adding such behaviour will not be accepted.

## Supported versions

The project is pre-1.0. Fixes land on `main` and are released from there.

`anthropic>=1.8` is a hard requirement for the router. Earlier versions accept the call and reject it at runtime, which `tests/test_sdk_compat.py` catches at install time.
