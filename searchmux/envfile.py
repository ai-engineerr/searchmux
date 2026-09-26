"""Optional .env loading for scripts.

Deliberately *not* called on import. A library that silently reads a
file from the working directory surprises its callers, so this is
explicit: scripts and examples call ``load_env()``, the library itself
only ever reads ``os.environ``.

Values already present in the environment win, so an exported variable
is never overwritten by a stale file.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_ENV_FILE = ".env"


def load_env(path: str = DEFAULT_ENV_FILE) -> list[str]:
    """Load KEY=value pairs from a .env file into os.environ.

    Missing files are not an error: running without a .env is the
    normal case for the test suite and for CI.

    Args:
        path: Path to the env file.

    Returns:
        The names of variables this call actually set, in file order.
    """
    target = Path(path)
    if not target.is_file():
        logger.debug("no env file at %s", target)
        return []

    loaded = []
    for raw in target.read_text(encoding="utf-8").splitlines():
        name, value = _parse_line(raw)
        if name is None or not value:
            continue
        if os.environ.get(name):
            logger.debug("%s already set, leaving it alone", name)
            continue
        os.environ[name] = value
        loaded.append(name)

    if loaded:
        logger.debug("loaded %d variables from %s", len(loaded), target)
    return loaded


def _parse_line(raw: str) -> tuple[str | None, str]:
    """Split one env-file line into a name and value.

    Handles ``export`` prefixes, surrounding quotes, and comments.

    Args:
        raw: A single line from the file.

    Returns:
        The variable name and its value, or (None, "") for blank lines,
        comments, and anything without an ``=``.
    """
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None, ""

    if line.startswith("export "):
        line = line[len("export "):].lstrip()

    name, _, value = line.partition("=")
    name = name.strip()
    value = value.strip()

    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]

    return (name, value) if name else (None, "")
