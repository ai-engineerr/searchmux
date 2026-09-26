"""Tests for record and replay cassettes."""

import json

import pytest

from quiver.cassette import Cassette
from quiver.models import CassetteMiss


def test_capture_then_replay_returns_the_body(tmp_path) -> None:
    path = str(tmp_path / "c.json")
    recorder = Cassette(path, mode="record")
    recorder.capture("google", {"q": "x"}, {"organic_results": [{"a": 1}]})
    recorder.save()

    player = Cassette(path, mode="replay")
    assert player.play("google", {"q": "x"}) == {
        "organic_results": [{"a": 1}]
    }


def test_replay_miss_raises_and_never_returns_none(tmp_path) -> None:
    path = str(tmp_path / "c.json")
    Cassette(path, mode="record").save()

    player = Cassette(path, mode="replay")
    with pytest.raises(CassetteMiss, match="google"):
        player.play("google", {"q": "unrecorded"})


def test_api_key_is_stripped_from_the_saved_file(tmp_path) -> None:
    path = str(tmp_path / "c.json")
    recorder = Cassette(path, mode="record")
    recorder.capture(
        "google",
        {"q": "x", "api_key": "super-secret"},
        {"organic_results": []},
    )
    recorder.save()

    contents = (tmp_path / "c.json").read_text(encoding="utf-8")
    assert "super-secret" not in contents


def test_replay_matches_regardless_of_api_key(tmp_path) -> None:
    path = str(tmp_path / "c.json")
    recorder = Cassette(path, mode="record")
    recorder.capture("google", {"q": "x", "api_key": "k1"}, {"ok": True})
    recorder.save()

    player = Cassette(path, mode="replay")
    assert player.play("google", {"q": "x", "api_key": "k2"}) == {"ok": True}


def test_replay_on_a_missing_file_raises_on_first_play(tmp_path) -> None:
    player = Cassette(str(tmp_path / "absent.json"), mode="replay")
    with pytest.raises(CassetteMiss):
        player.play("google", {"q": "x"})


def test_saved_file_is_human_readable_json(tmp_path) -> None:
    path = str(tmp_path / "c.json")
    recorder = Cassette(path, mode="record")
    recorder.capture("google", {"q": "x"}, {"ok": True})
    recorder.save()

    payload = json.loads((tmp_path / "c.json").read_text(encoding="utf-8"))
    assert payload["entries"][0]["engine_id"] == "google"
    assert payload["entries"][0]["params"] == {"q": "x"}


def test_entry_count_reflects_captures(tmp_path) -> None:
    recorder = Cassette(str(tmp_path / "c.json"), mode="record")
    recorder.capture("google", {"q": "a"}, {})
    recorder.capture("google", {"q": "b"}, {})
    assert recorder.entry_count == 2
