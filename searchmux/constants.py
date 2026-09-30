"""Project-wide constants. No hardcoded values elsewhere."""

SERPAPI_BASE_URL = "https://serpapi.com/search"
ENV_API_KEY = "SERPAPI_API_KEY"

TAVILY_BASE_URL = "https://api.tavily.com/search"
ENV_TAVILY_KEY = "TAVILY_API_KEY"

BRAVE_BASE_URL = "https://api.search.brave.com/res/v1/web/search"
ENV_BRAVE_KEY = "BRAVE_API_KEY"

EXA_BASE_URL = "https://api.exa.ai/search"
ENV_EXA_KEY = "EXA_API_KEY"

ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"

DEFAULT_CACHE_PATH = ".searchmux.db"
DEFAULT_BUDGET = 50
# None means no narrowing: send every engine to the model. Measured
# on evals/routing.jsonl, BM25 narrowing to 5 caps accuracy at its
# own recall (82%) while sending all engines scores 98%. Narrowing is
# kept for catalogs large enough that prompt size matters.
DEFAULT_ROUTER_TOP_K = None

HTTP_TIMEOUT = 30.0
HTTP_MAX_RETRIES = 3
HTTP_BACKOFF_BASE = 0.5

# Cache lifetime in seconds, by volatility class.
TTL_VOLATILE = 15 * 60
TTL_NEWS = 60 * 60
TTL_STABLE = 30 * 24 * 60 * 60

TTL_BY_CLASS = {
    "volatile": TTL_VOLATILE,
    "news": TTL_NEWS,
    "stable": TTL_STABLE,
}
DEFAULT_TTL_CLASS = "news"

# Request keys that must never reach a cache key or a cassette file.
SECRET_PARAM_KEYS = frozenset({"api_key", "serp_api_key"})

# Router LLM. Opus is the default; set ROUTER_MODEL to a cheaper model
# if routing volume makes that worthwhile. Effort is low because engine
# selection is a classification, not a reasoning problem.
ROUTER_MODEL = "claude-opus-5"
ROUTER_MAX_TOKENS = 1024
ROUTER_EFFORT = "low"
