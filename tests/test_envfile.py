"""Tests for optional .env loading."""

import os

from searchmux.envfile import load_env


def test_missing_file_is_not_an_error(tmp_path) -> None:
    assert load_env(str(tmp_path / "absent")) == []


def test_sets_variables_from_the_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SM_TEST_A", raising=False)
    path = tmp_path / ".env"
    path.write_text("SM_TEST_A=hello\n", encoding="utf-8")

    assert load_env(str(path)) == ["SM_TEST_A"]
    assert os.environ["SM_TEST_A"] == "hello"


def test_existing_environment_value_wins(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SM_TEST_B", "from-shell")
    path = tmp_path / ".env"
    path.write_text("SM_TEST_B=from-file\n", encoding="utf-8")

    assert load_env(str(path)) == []
    assert os.environ["SM_TEST_B"] == "from-shell"


def test_blank_values_are_skipped(tmp_path, monkeypatch) -> None:
    """An untouched .env.example must not set empty variables."""
    monkeypatch.delenv("SM_TEST_C", raising=False)
    path = tmp_path / ".env"
    path.write_text("SM_TEST_C=\n", encoding="utf-8")

    assert load_env(str(path)) == []
    assert "SM_TEST_C" not in os.environ


def test_comments_and_blank_lines_are_ignored(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SM_TEST_D", raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "# a comment\n\n   \nSM_TEST_D=value\n", encoding="utf-8"
    )

    assert load_env(str(path)) == ["SM_TEST_D"]


def test_export_prefix_is_stripped(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SM_TEST_E", raising=False)
    path = tmp_path / ".env"
    path.write_text("export SM_TEST_E=value\n", encoding="utf-8")

    assert load_env(str(path)) == ["SM_TEST_E"]
    assert os.environ["SM_TEST_E"] == "value"


def test_surrounding_quotes_are_stripped(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SM_TEST_F", raising=False)
    monkeypatch.delenv("SM_TEST_G", raising=False)
    path = tmp_path / ".env"
    path.write_text(
        'SM_TEST_F="double"\nSM_TEST_G=\'single\'\n', encoding="utf-8"
    )

    load_env(str(path))
    assert os.environ["SM_TEST_F"] == "double"
    assert os.environ["SM_TEST_G"] == "single"


def test_lines_without_an_equals_are_ignored(tmp_path) -> None:
    path = tmp_path / ".env"
    path.write_text("NOT_AN_ASSIGNMENT\n", encoding="utf-8")
    assert load_env(str(path)) == []


def test_value_containing_equals_is_preserved(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SM_TEST_H", raising=False)
    path = tmp_path / ".env"
    path.write_text("SM_TEST_H=a=b=c\n", encoding="utf-8")

    load_env(str(path))
    assert os.environ["SM_TEST_H"] == "a=b=c"
