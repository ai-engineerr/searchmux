"""Tests for envelope normalization across engines."""

from searchmux.normalize import normalize


def test_organic_results_map_to_common_shape() -> None:
    body = {
        "organic_results": [
            {
                "title": "A paper",
                "link": "https://x.test/a",
                "snippet": "about things",
                "position": 1,
            }
        ]
    }
    results = normalize("google_scholar", body)
    assert len(results) == 1
    assert results[0].title == "A paper"
    assert results[0].url == "https://x.test/a"
    assert results[0].position == 1
    assert results[0].source == "google_scholar"
    assert results[0].price is None


def test_shopping_results_populate_price() -> None:
    body = {
        "shopping_results": [
            {
                "title": "Pixel 10",
                "product_link": "https://x.test/p",
                "extracted_price": 79999.0,
                "currency": "INR",
                "source": "Flipkart",
            }
        ]
    }
    result = normalize("google_shopping", body)[0]
    assert result.price is not None
    assert result.price.amount == 79999.0
    assert result.price.currency == "INR"
    assert result.extra["seller"] == "Flipkart"


def test_missing_results_key_returns_empty_list() -> None:
    body = {"search_metadata": {"status": "Success"}}
    assert normalize("google", body) == []


def test_empty_results_key_returns_empty_list() -> None:
    assert normalize("google", {"organic_results": []}) == []


def test_raw_item_is_always_preserved() -> None:
    body = {"organic_results": [{"title": "t", "link": "u", "odd": 9}]}
    assert normalize("google", body)[0].raw["odd"] == 9


def test_item_without_title_is_skipped_not_fatal() -> None:
    body = {"organic_results": [{"link": "u"}, {"title": "ok", "link": "v"}]}
    results = normalize("google", body)
    assert [r.title for r in results] == ["ok"]


def test_nested_results_key_is_reached_by_dotted_path() -> None:
    """Google Trends nests its results one level down."""
    body = {
        "interest_over_time": {
            "timeline_data": [{"date": "Jan 2026", "values": [{"value": 7}]}]
        }
    }
    results = normalize("google_trends", body)
    assert len(results) == 1
    assert results[0].title == "Jan 2026"
    assert results[0].raw["values"] == [{"value": 7}]


def test_missing_intermediate_key_returns_empty_list() -> None:
    assert normalize("google_trends", {"search_metadata": {}}) == []


def test_partially_present_nested_path_returns_empty_list() -> None:
    assert normalize("google_trends", {"interest_over_time": {}}) == []


def test_non_dict_along_the_path_returns_empty_list() -> None:
    body = {"interest_over_time": "unexpected string"}
    assert normalize("google_trends", body) == []


def test_currency_symbol_is_recovered_from_price_text() -> None:
    """SerpApi reports currency as null and puts the symbol in price."""
    body = {
        "shopping_results": [
            {
                "title": "Pixel 10",
                "product_link": "https://x.test/p",
                "price": "₹67,400",
                "extracted_price": 67400,
                "currency": None,
                "source": "Amazon.in",
            }
        ]
    }
    result = normalize("google_shopping", body)[0]
    assert result.price is not None
    assert result.price.amount == 67400.0
    assert result.price.currency == "₹"
    assert str(result.price) == "₹ 67400.00"


def test_explicit_currency_code_wins_over_the_symbol() -> None:
    body = {
        "shopping_results": [
            {
                "title": "Pixel 10",
                "price": "₹67,400",
                "extracted_price": 67400,
                "currency": "INR",
            }
        ]
    }
    assert normalize("google_shopping", body)[0].price.currency == "INR"


def test_unknown_currency_is_never_invented() -> None:
    """Defaulting to USD would misreport money. It must stay None."""
    body = {
        "shopping_results": [
            {"title": "Thing", "extracted_price": 1200}
        ]
    }
    price = normalize("google_shopping", body)[0].price
    assert price is not None
    assert price.currency is None
    assert str(price) == "1200.00"


def test_trailing_currency_code_is_recovered() -> None:
    body = {
        "shopping_results": [
            {"title": "T", "price": "1 299 kr", "extracted_price": 1299}
        ]
    }
    assert normalize("google_shopping", body)[0].price.currency == "kr"


def test_tavily_results_map_to_common_shape() -> None:
    body = {
        "results": [
            {
                "title": "Pixel 10 review",
                "url": "https://x.test/a",
                "content": "A thorough review of the Pixel 10.",
            }
        ]
    }
    result = normalize("tavily_search", body)[0]
    assert result.title == "Pixel 10 review"
    assert result.url == "https://x.test/a"
    assert result.snippet == "A thorough review of the Pixel 10."
    assert result.source == "tavily_search"


def test_brave_results_map_to_common_shape() -> None:
    body = {
        "web": {
            "results": [
                {
                    "title": "Pixel 10 review",
                    "url": "https://x.test/b",
                    "description": "Hands-on with the Pixel 10.",
                }
            ]
        }
    }
    result = normalize("brave_search", body)[0]
    assert result.title == "Pixel 10 review"
    assert result.url == "https://x.test/b"
    assert result.snippet == "Hands-on with the Pixel 10."
    assert result.source == "brave_search"


def test_exa_results_map_to_common_shape() -> None:
    body = {
        "results": [
            {
                "title": "Pixel 10 review",
                "url": "https://x.test/c",
                "text": "Exa's neural search summary of the Pixel 10.",
            }
        ]
    }
    result = normalize("exa_search", body)[0]
    assert result.title == "Pixel 10 review"
    assert result.url == "https://x.test/c"
    assert result.snippet == "Exa's neural search summary of the Pixel 10."
    assert result.source == "exa_search"


def test_tavily_extra_promotes_relevance_score() -> None:
    body = {
        "results": [
            {
                "title": "Pixel 10 review",
                "url": "https://x.test/a",
                "content": "A review.",
                "score": 0.87,
            }
        ]
    }
    result = normalize("tavily_search", body)[0]
    assert result.extra["score"] == 0.87


def test_exa_extra_promotes_published_date() -> None:
    body = {
        "results": [
            {
                "title": "Pixel 10 review",
                "url": "https://x.test/c",
                "text": "Exa's neural search summary of the Pixel 10.",
                "publishedDate": "2025-09-04T00:00:00.000Z",
            }
        ]
    }
    result = normalize("exa_search", body)[0]
    assert result.extra["published_date"] == "2025-09-04T00:00:00.000Z"


def test_extra_omits_a_mapped_field_when_the_item_lacks_it() -> None:
    body = {
        "results": [
            {
                "title": "No score here",
                "url": "https://x.test/d",
                "content": "x",
            }
        ]
    }
    result = normalize("tavily_search", body)[0]
    assert "score" not in result.extra
