"""Guard against committing anything that looks like an API key.

Exposing a key in public materials is grounds for disqualification
under the hackathon rules, so this runs in CI rather than relying on
anyone remembering to look.

It asks git which files are tracked rather than walking the filesystem:
only tracked files are ever published, and a local recording or cache
sitting in the working tree is not a leak.
"""

import pathlib
import re
import subprocess

import pytest

# SerpApi keys are 64 hex chars; Anthropic keys start sk-ant-.
KEY_PATTERN = re.compile(r"\b[0-9a-f]{40,}\b|sk-[A-Za-z0-9_-]{20,}")

SCANNED_SUFFIXES = {".py", ".json", ".jsonl", ".md", ".yml", ".yaml", ".txt"}

# This file necessarily contains the patterns it searches for.
SELF = pathlib.Path(__file__).name

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _tracked_files() -> list[pathlib.Path]:
    """Return every git-tracked file worth scanning.

    Returns:
        Paths relative to the repository root.

    Raises:
        pytest.skip.Exception: If git is unavailable.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git unavailable, cannot list tracked files: {exc}")

    files = []
    for name in out.split("\0"):
        if not name:
            continue
        path = ROOT / name
        if path.suffix not in SCANNED_SUFFIXES or path.name == SELF:
            continue
        if path.is_file():
            files.append(path)
    return files


def test_git_reports_some_tracked_files() -> None:
    """A silent empty listing would make the scan below vacuous."""
    assert _tracked_files(), "no tracked files found to scan"


def test_no_api_keys_in_tracked_files() -> None:
    offenders = []
    for path in _tracked_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if KEY_PATTERN.search(text):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"possible secrets in: {offenders}"


def test_env_example_holds_no_values() -> None:
    """The example file must name variables, never fill them in."""
    for line in (ROOT / ".env.example").read_text(
        encoding="utf-8"
    ).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert stripped.endswith("="), f"value committed: {stripped}"


def test_env_file_is_ignored_by_git() -> None:
    """A tracked .env is the exact failure this project must not have."""
    out = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip() == "", ".env is tracked by git"
