#!/usr/bin/env python3
"""Resolve active Codex implementations from skills/index.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class CatalogError(ValueError):
    """Raised when a route is unknown, inactive, malformed, or unavailable."""


@dataclass(frozen=True)
class Route:
    kind: str
    route_id: str
    path: Path
    status: str


_SECTION = re.compile(r"^([a-z][a-z-]*):$")
_ENTRY = re.compile(r"^  ([a-z0-9][a-z0-9-]*):$")
_FIELD = re.compile(r"^    ([a-z_]+):(?: (.*))?$")
_PROVIDER_FIELD = re.compile(r"^      (path|status):(?: (.*))?$")


def _routes(index: Path) -> dict[tuple[str, str], Route]:
    routes: dict[tuple[str, str], Route] = {}
    section = entry = provider = status = path = kind = None
    for line in index.read_text(encoding="utf-8").splitlines():
        if match := _SECTION.match(line):
            section = match.group(1) if match.group(1) in {"skills", "agents", "commands"} else None
            entry = provider = status = path = None
            continue
        if not section:
            continue
        if match := _ENTRY.match(line):
            if entry is not None and provider == "codex" and status and path:
                routes[(kind, entry)] = Route(kind, entry, Path(path), status)
            entry, provider, status, path, kind = match.group(1), None, None, None, None
            continue
        if entry is None:
            continue
        if match := _FIELD.match(line):
            field, value = match.groups()
            if field == "source_kind":
                kind = f"{value}s"
            if field in {"claude", "codex"}:
                provider = field
            continue
        if match := _PROVIDER_FIELD.match(line):
            if provider == "codex":
                field, value = match.groups()
                if field == "path":
                    path = value
                else:
                    status = value
    if entry is not None and provider == "codex" and status and path:
        routes[(kind, entry)] = Route(kind, entry, Path(path), status)
    return routes


def resolve(route_id: str, *, kind: str | None = None, root: Path | None = None) -> Path:
    """Return an active, existing native implementation or fail closed."""
    root = root or Path(__file__).parents[1]
    routes = _routes(root / "skills/index.yaml")
    matches = [(key, route) for key, route in routes.items() if key[1] == route_id]
    if kind:
        matches = [(key, route) for key, route in matches if key[0] == kind]
    if len(matches) != 1:
        raise CatalogError(f"unknown or ambiguous Codex route: {route_id}")
    key, route = matches[0]
    native = root / route.path
    if route.status != "active":
        raise CatalogError(f"inactive Codex route: {key[0]}/{key[1]}")
    native_path = route.path.as_posix()
    valid_path = native_path == f"codex/{route.kind}/{route.route_id}.md"
    valid_path |= route.kind == "agents" and native_path == f".codex/skills/{route.route_id}/SKILL.md"
    if not valid_path or not native.is_file():
        raise CatalogError(f"missing Codex implementation: {key[0]}/{key[1]}")
    return native


def all_routes(*, root: Path | None = None) -> tuple[Route, ...]:
    """Return all active routes after validating their native files."""
    root = root or Path(__file__).parents[1]
    routes = _routes(root / "skills/index.yaml")
    if not routes:
        raise CatalogError("index contains no active Codex routes")
    result = []
    for route in routes.values():
        resolve(route.route_id, kind=route.kind, root=root)
        result.append(route)
    return tuple(sorted(result, key=lambda route: (route.kind, route.route_id)))
