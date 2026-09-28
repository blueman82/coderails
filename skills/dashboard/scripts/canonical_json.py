"""Preserve jq sorted compact JSON bytes used by durable queue hashes."""

import json
from decimal import Decimal
from typing import Union, cast

JsonValue = Union[None, bool, int, Decimal, str, list["JsonValue"], dict[str, "JsonValue"]]


def loads(text: str) -> JsonValue:
    """Preserve decimal scale and exponents instead of rounding through binary floats."""
    return cast(JsonValue, json.loads(text, parse_float=Decimal))


def dumps(value: JsonValue) -> str:
    """Sort nested keys and emit the same UTF-8 strings and decimal tokens as jq."""
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else "null"
    if isinstance(value, list):
        return "[" + ",".join(dumps(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False).replace(chr(127), "\\u007f") + ":" + dumps(value[key])
                for key in sorted(value)
            )
            + "}"
        )
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(chr(127), "\\u007f")
