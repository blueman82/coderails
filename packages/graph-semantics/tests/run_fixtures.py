#!/usr/bin/env python3
"""Run the frozen schema-v3 graph-semantics fixture corpus."""

from __future__ import annotations

import copy
import importlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
sys.path.insert(0, str(ROOT))


def call(core: ModuleType, operation: str, state: dict[str, Any], request: dict[str, Any]) -> object:
    """Dispatch one frozen operation request to the maintained core."""
    function = cast(Callable[..., object], getattr(core, operation))
    return function(state, **request)


def main() -> int:
    """Compare every fixture's exact semantic result or error."""
    core = importlib.import_module("graph_semantics")
    failures: list[str] = []
    for path in sorted(FIXTURES.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        state = fixture["state"]
        before = copy.deepcopy(state)
        try:
            actual = call(core, fixture["operation"], state, fixture.get("request", {}))
        except core.GraphSemanticError as error:
            actual = {"error": {"code": error.code, "message": error.message}}
        expected = fixture["expected"]
        if actual != expected:
            failures.append(f"{path.name}: expected {expected!r}, got {actual!r}")
        if fixture.get("unchanged") and state != before:
            failures.append(f"{path.name}: rejected request mutated its input state")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"graph semantics fixtures: {len(list(FIXTURES.glob('*.json')))} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
