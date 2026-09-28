"""Identify maintained Python sources independently of filename extensions."""

from __future__ import annotations

import re
from pathlib import Path

PYTHON_SHEBANG = re.compile(
    r"^#!\s*(?:/[^\s]*/)?(?:python(?:\d+(?:\.\d+)*)?|env(?:\s+-S)?\s+python(?:\d+(?:\.\d+)*)?)(?:\s|$)"
)


def is_python_source(path: Path, text: str | None = None) -> bool:
    """Recognize Python suffixes and extensionless Python interpreter shebangs."""
    if path.suffix == ".py":
        return True
    if path.suffix:
        return False
    if text is None:
        try:
            with path.open(encoding="utf-8") as stream:
                text = stream.readline()
        except (OSError, UnicodeError):
            return False
    return bool(PYTHON_SHEBANG.match(text.splitlines()[0] if text else ""))
