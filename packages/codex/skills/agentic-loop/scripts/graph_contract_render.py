"""Stable field order, prompt sections, and digest for graph dispatch contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

CONTRACT_FIELDS = tuple(
    (  # noqa: SIM905 - keep the closed ordered field list compact
        "role model_role base_ref worktree manifest source_manifest_sha256 source_head_sha "
        "publication_command disposition lessons lessons_sha256 write_scope skip_phases scope required_context"
    ).split()
)
BEGIN, END = "CODERAILS_GRAPH_CONTRACT v2", "END CODERAILS_GRAPH_CONTRACT"
CODES = (  # noqa: SIM905 - keep the shared counter vocabulary compact
    "dispatch_missing_envelope dispatch_unknown_id dispatch_foreign dispatch_stale_revision dispatch_replayed "
    "dispatch_contract_altered dispatch_sections_missing dispatch_state_unconverted role_mismatch "
    "dispatch_unauthorized dispatch_publication_mismatch dispatch_source_mismatch "
    "dispatch_lessons_unavailable dispatch_lessons_stale dispatch_context_mismatch"
).split()


def render_sections(contract: dict[str, Any]) -> str:
    """Render the deterministic prompt block, one JSON value per line."""
    lines = [f"{key}: {json.dumps(contract[key], sort_keys=True)}" for key in CONTRACT_FIELDS if key in contract]
    return "\n".join([BEGIN, *lines, END])


def sections_sha256(contract: dict[str, Any]) -> str:
    """Return the digest stored at begin-wave and checked before dispatch."""
    return hashlib.sha256(render_sections(contract).encode("utf-8")).hexdigest()
