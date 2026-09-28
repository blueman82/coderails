"""Share CLI argument handling and privacy-safe JSON object access."""

from __future__ import annotations

import argparse
import json
from typing import Any, NoReturn, cast


class AuditParser(argparse.ArgumentParser):
    """Retain status one for invalid audit CLI arguments."""

    def error(self, message: str) -> NoReturn:
        """Report invalid input distinctly without an argparse traceback."""
        self.exit(1, f"unknown_arg:{message}\n")


def number(value: str, default: int) -> int:
    """Preserve nonnegative ASCII numeric values and historical fallback defaults."""
    return int(value) if value and value.isascii() and value.isdigit() else default


def object_value(value: object) -> dict[str, Any]:
    """Read object fields without coercing malformed values into output text."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def array_value(value: object) -> list[Any]:
    """Read JSON array items while refusing arbitrary iterable coercion."""
    return cast(list[Any], cast(object, value)) if isinstance(value, list) else []


def text_value(value: object) -> str:
    """Return string fields only, never stringify private structured content."""
    return value if isinstance(value, str) else ""


def emit(value: object) -> None:
    """Print compact Unicode JSON without debug or private input contents."""
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
