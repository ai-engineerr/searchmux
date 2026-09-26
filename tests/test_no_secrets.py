"""Guard against committing anything that looks like an API key.

Exposing a key in public materials is grounds for disqualification
under the hackathon rules, so this runs in CI rather than relying on
anyone remembering to look.
"""

import pathlib
import re

# SerpApi keys are 64 hex chars; Anthropic keys start sk-ant-.
KEY_PATTERN = re.compile(r"\b[0-9a-f]{40,}\b|sk-[A-Za-z0-9_-]{20,}")

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
}
SCANNED_SUFFIXES = {".py", ".json", ".jsonl", ".md", ".yml", ".yaml", ".txt"}

# This file necessarily contains the patterns it searches for.
SELF = pathlib.Path(__file__).name


def _tracked_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Return every scannable file under root."""
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if SKIP_DIRS & set(path.parts):
            continue
        if path.suffix not in SCANNED_SUFFIXES:
            continue
        if path.name == SELF:
            continue
        files.append(path)
    return files


def test_no_api_keys_in_tracked_files() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in _tracked_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if KEY_PATTERN.search(text):
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f"possible secrets in: {offenders}"


def test_env_example_holds_no_values() -> None:
    """The example file must name variables, never fill them in."""
    root = pathlib.Path(__file__).resolve().parent.parent
    for line in (root / ".env.example").read_text(
        encoding="utf-8"
    ).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert stripped.endswith("="), f"value committed: {stripped}"
