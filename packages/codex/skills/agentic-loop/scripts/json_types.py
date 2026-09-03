"""JSON values exchanged by the native graph command interfaces."""

from __future__ import annotations

from typing import Union

JsonScalar = Union[None, bool, int, float, str]
JsonValue = Union[JsonScalar, list["JsonValue"], dict[str, "JsonValue"]]
JsonObject = dict[str, JsonValue]
