"""Tests for cache keying and the SQLite cache."""

from quiver.cache import Cache, request_key


def test_key_ignores_param_order() -> None:
    a = request_key("google", {"q": "x", "gl": "in"})
    b = request_key("google", {"gl": "in", "q": "x"})
    assert a == b


def test_key_excludes_the_api_key() -> None:
    with_key = request_key("google", {"q": "x", "api_key": "secret-1"})
    other_key = request_key("google", {"q": "x", "api_key": "secret-2"})
    bare = request_key("google", {"q": "x"})
    assert with_key == other_key == bare


def test_key_never_contains_the_secret() -> None:
    key = request_key("google", {"q": "x", "api_key": "secret-1"})
    assert "secret-1" not in key


def test_key_handles_non_ascii_queries() -> None:
    a = request_key("google", {"q": "café"})
    b = request_key("google", {"q": "café"})
    assert a == b
    assert a != request_key("google", {"q": "cafe"})


def test_key_separates_engines() -> None:
    assert request_key("google", {"q": "x"}) != request_key(
        "bing", {"q": "x"}
    )


def test_set_then_get_round_trips(tmp_path) -> None:
    cache = Cache(str(tmp_path / "c.db"))
    cache.set("k", {"organic_results": [{"a": 1}]})
    assert cache.get("k", ttl=60) == {"organic_results": [{"a": 1}]}
    cache.close()


def test_get_returns_none_on_miss(tmp_path) -> None:
    cache = Cache(str(tmp_path / "c.db"))
    assert cache.get("absent", ttl=60) is None
    cache.close()


def test_ttl_boundary_is_inclusive(tmp_path) -> None:
    clock = {"t": 1000.0}
    cache = Cache(str(tmp_path / "c.db"), now=lambda: clock["t"])
    cache.set("k", {"v": 1})

    clock["t"] = 1059.0
    assert cache.get("k", ttl=60) is not None
    clock["t"] = 1060.0
    assert cache.get("k", ttl=60) is not None
    clock["t"] = 1061.0
    assert cache.get("k", ttl=60) is None
    cache.close()


def test_set_overwrites_and_refreshes_timestamp(tmp_path) -> None:
    clock = {"t": 0.0}
    cache = Cache(str(tmp_path / "c.db"), now=lambda: clock["t"])
    cache.set("k", {"v": 1})
    clock["t"] = 100.0
    cache.set("k", {"v": 2})
    assert cache.get("k", ttl=60) == {"v": 2}
    cache.close()


def test_cache_persists_across_instances(tmp_path) -> None:
    path = str(tmp_path / "c.db")
    first = Cache(path)
    first.set("k", {"v": 1})
    first.close()

    second = Cache(path)
    assert second.get("k", ttl=3600) == {"v": 1}
    second.close()
