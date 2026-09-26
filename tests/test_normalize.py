"""Tests for envelope normalization across engines."""

from quiver.normalize import normalize


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
