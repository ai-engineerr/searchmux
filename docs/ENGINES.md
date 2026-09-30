# Engine catalog

The 27 engines SearchMux currently knows about. This file is generated from `searchmux/catalog.json` — edit the catalog, not this page.

Adding an engine is one JSON record and zero lines of code. See [CONTRIBUTING.md](../CONTRIBUTING.md#adding-an-engine).

## Summary

| Engine | Provider | Required parameters | Results key | Cache TTL |
| --- | --- | --- | --- | --- |
| `amazon` | serpapi | `k` | `organic_results` | 15 min |
| `bing` | serpapi | `q` | `organic_results` | 1 hour |
| `brave_search` | brave | `q` | `web.results` | 1 hour |
| `duckduckgo` | serpapi | `q` | `organic_results` | 1 hour |
| `ebay` | serpapi | `_nkw` | `organic_results` | 15 min |
| `exa_search` | exa | `query` | `results` | 1 hour |
| `google` | serpapi | `q` | `organic_results` | 1 hour |
| `google_autocomplete` | serpapi | `q` | `suggestions` | 1 hour |
| `google_events` | serpapi | `q` | `events_results` | 1 hour |
| `google_finance` | serpapi | `q` | `summary` | 15 min |
| `google_flights` | serpapi | `departure_id`, `arrival_id`, `outbound_date` | `best_flights` | 15 min |
| `google_hotels` | serpapi | `q`, `check_in_date`, `check_out_date` | `properties` | 15 min |
| `google_images` | serpapi | `q` | `images_results` | 30 days |
| `google_jobs` | serpapi | `q` | `jobs_results` | 1 hour |
| `google_lens` | serpapi | `url` | `visual_matches` | 30 days |
| `google_local` | serpapi | `q` | `local_results` | 30 days |
| `google_maps` | serpapi | `q` | `local_results` | 30 days |
| `google_news` | serpapi | `q` | `news_results` | 1 hour |
| `google_patents` | serpapi | `q` | `organic_results` | 30 days |
| `google_scholar` | serpapi | `q` | `organic_results` | 30 days |
| `google_shopping` | serpapi | `q` | `shopping_results` | 15 min |
| `google_trends` | serpapi | `q` | `interest_over_time.timeline_data` | 1 hour |
| `google_videos` | serpapi | `q` | `video_results` | 1 hour |
| `tavily_search` | tavily | `query` | `results` | 1 hour |
| `walmart` | serpapi | `query` | `organic_results` | 15 min |
| `yelp` | serpapi | `find_loc` | `organic_results` | 30 days |
| `youtube` | serpapi | `search_query` | `video_results` | 1 hour |

## Details

### `amazon`

Provider: `serpapi`. Product listings from the Amazon marketplace

| Parameter | Type | Required |
| --- | --- | --- |
| `k` | string | yes |

Results at `organic_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `snippet`, `position` ← `position`, `price` ← `price`.

### `bing`

Provider: `serpapi`. Web search results from Bing

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |

Results at `organic_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `snippet`, `position` ← `position`.

### `brave_search`

Provider: `brave`. Web search via Brave Search's independent index

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |

Results at `web.results`. Mapped: `title` ← `title`, `url` ← `url`, `snippet` ← `description`.

### `duckduckgo`

Provider: `serpapi`. Privacy-preserving web search results

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |

Results at `organic_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `snippet`, `position` ← `position`.

### `ebay`

Provider: `serpapi`. Auctions and used goods listed on eBay

| Parameter | Type | Required |
| --- | --- | --- |
| `_nkw` | string | yes |

Results at `organic_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `snippet`, `position` ← `position`, `price` ← `price`.

### `exa_search`

Provider: `exa`. Neural/semantic web search via Exa, tuned for finding pages by meaning rather than keywords

| Parameter | Type | Required |
| --- | --- | --- |
| `query` | string | yes |

Results at `results`. Mapped: `title` ← `title`, `url` ← `url`, `snippet` ← `text`.

### `google`

Provider: `serpapi`. General web search across the whole internet

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `gl` | string | no |
| `hl` | string | no |
| `num` | integer | no |

Results at `organic_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `snippet`, `position` ← `position`.

### `google_autocomplete`

Provider: `serpapi`. Query suggestions as a search is being typed

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |

Results at `suggestions`. Mapped: `title` ← `value`, `url` ← `serpapi_link`, `snippet` ← `value`, `position` ← `position`.

### `google_events`

Provider: `serpapi`. Upcoming local events such as concerts and shows

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `location` | string | no |

Results at `events_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `description`, `position` ← `position`.

### `google_finance`

Provider: `serpapi`. Stock quotes and current market data for a ticker

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |

Results at `summary`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `stock`, `position` ← `position`, `price` ← `extracted_price`, `currency` ← `currency`, `price_text` ← `price`.

### `google_flights`

Provider: `serpapi`. Airline routes, fares, and flight schedules

| Parameter | Type | Required |
| --- | --- | --- |
| `departure_id` | string | yes |
| `arrival_id` | string | yes |
| `outbound_date` | string | yes |

Results at `best_flights`. Mapped: `title` ← `type`, `url` ← `booking_token`, `snippet` ← `airline`, `position` ← `position`, `price` ← `price`.

### `google_hotels`

Provider: `serpapi`. Hotel availability and nightly rates for a stay

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `check_in_date` | string | yes |
| `check_out_date` | string | yes |

Results at `properties`. Mapped: `title` ← `name`, `url` ← `serpapi_property_details_link`, `snippet` ← `type`, `position` ← `position`.

### `google_images`

Provider: `serpapi`. Pictures and visual references for a subject

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `gl` | string | no |
| `hl` | string | no |

Results at `images_results`. Mapped: `title` ← `title`, `url` ← `original`, `snippet` ← `source`, `position` ← `position`.

### `google_jobs`

Provider: `serpapi`. Job postings and openings matching a role or company

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `location` | string | no |

Results at `jobs_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `description`, `position` ← `position`.

### `google_lens`

Provider: `serpapi`. Look up an image to find what it is or where to buy it

| Parameter | Type | Required |
| --- | --- | --- |
| `url` | string | yes |

Results at `visual_matches`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `source`, `position` ← `position`.

### `google_local`

Provider: `serpapi`. Nearby businesses in a locality, such as restaurants or shops

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `ll` | string | no |

Results at `local_results`. Mapped: `title` ← `title`, `url` ← `place_id_search`, `snippet` ← `address`, `position` ← `position`.

### `google_maps`

Provider: `serpapi`. Places, businesses, and addresses with ratings and contact details

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `ll` | string | no |

Results at `local_results`. Mapped: `title` ← `title`, `url` ← `place_id_search`, `snippet` ← `address`, `position` ← `position`.

### `google_news`

Provider: `serpapi`. Recent news articles and coverage on a topic

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `gl` | string | no |
| `hl` | string | no |

Results at `news_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `snippet`, `position` ← `position`.

### `google_patents`

Provider: `serpapi`. Patents and inventions matching a topic or number

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |

Results at `organic_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `snippet`, `position` ← `position`.

### `google_scholar`

Provider: `serpapi`. Academic papers, citations, and scholarly literature

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `as_ylo` | integer | no |
| `as_yhi` | integer | no |
| `num` | integer | no |

Results at `organic_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `snippet`, `position` ← `position`.

### `google_shopping`

Provider: `serpapi`. Retail product listings with current prices, sellers, and ratings

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `gl` | string | no |
| `hl` | string | no |

Results at `shopping_results`. Mapped: `title` ← `title`, `url` ← `product_link`, `snippet` ← `snippet`, `position` ← `position`, `price` ← `extracted_price`, `currency` ← `currency`, `source` ← `source`, `price_text` ← `price`.

### `google_trends`

Provider: `serpapi`. Search interest over time for a topic

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `data_type` | string | no |

Results at `interest_over_time.timeline_data`. Mapped: `title` ← `date`, `snippet` ← `date`.

### `google_videos`

Provider: `serpapi`. Video clips across the web on a topic

| Parameter | Type | Required |
| --- | --- | --- |
| `q` | string | yes |
| `gl` | string | no |
| `hl` | string | no |

Results at `video_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `snippet`, `position` ← `position`.

### `tavily_search`

Provider: `tavily`. Web search via Tavily, an API built for LLM agents, returning clean flat results

| Parameter | Type | Required |
| --- | --- | --- |
| `query` | string | yes |

Results at `results`. Mapped: `title` ← `title`, `url` ← `url`, `snippet` ← `content`.

### `walmart`

Provider: `serpapi`. Product inventory and prices at Walmart

| Parameter | Type | Required |
| --- | --- | --- |
| `query` | string | yes |

Results at `organic_results`. Mapped: `title` ← `title`, `url` ← `product_page_url`, `snippet` ← `snippet`, `position` ← `position`, `price` ← `price`.

### `yelp`

Provider: `serpapi`. Restaurant and service reviews with ratings

| Parameter | Type | Required |
| --- | --- | --- |
| `find_desc` | string | no |
| `find_loc` | string | yes |

Results at `organic_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `snippet`, `position` ← `position`.

### `youtube`

Provider: `serpapi`. YouTube videos and reviews on a topic

| Parameter | Type | Required |
| --- | --- | --- |
| `search_query` | string | yes |

Results at `video_results`. Mapped: `title` ← `title`, `url` ← `link`, `snippet` ← `description`, `position` ← `position`.

## Notes

**Parameter names are not uniform across engines.** They were verified against SerpApi's published documentation rather than assumed. Amazon takes `k`, eBay `_nkw`, Walmart `query`, Yelp requires `find_loc`, YouTube uses `search_query`, and Google Lens takes `url`. Guessing `q` everywhere produces a live 400.

**`google_play` is deliberately absent.** Its results nest as `organic_results[].items[]`, a list of lists that no flat or dotted path can express. Shipping an engine that silently returns nothing is worse than not listing it.

**`google_trends` returns timeline entries, not links.** It is a time series, so `Result.title` carries the date and the values live in `Result.raw`.

