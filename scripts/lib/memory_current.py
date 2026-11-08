"""Read exact current Notes without assigning legacy privacy classification."""

from __future__ import annotations

import dataclasses
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, cast

from scripts.lib import memory_adapter as ma
from scripts.lib import memory_support as support

KNOWLEDGE_ID = re.compile(r"K_[0-9a-f]{32}")
MAX_CURRENT = 100


@dataclasses.dataclass(frozen=True)
class Note:
    """A current revision with all verified selected supports and conditional fields."""

    id: str
    revision: int
    body: dict[str, Any]
    expiry: dict[str, Any] | None
    supports: list[dict[str, Any]]
    request_id: str

    @property
    def claim(self) -> str:
        """Return the exact supported assertion."""
        return str(self.body["content"])

    @property
    def cite(self) -> str:
        """Display the first declared support only after the complete set passes."""
        return str(self.supports[0]["ref"])

    @property
    def quote(self) -> str:
        """Return its real selected excerpt, never a manufactured quote."""
        return str(self.supports[0]["quote"])

    def metadata(self) -> dict[str, Any]:
        """Preserve conditions; legacy dispatch and promotion cannot evaluate them."""
        conditional = (
            bool(self.body["conditions"]) or self.expiry is not None and self.expiry.get("condition") is not None
        )
        return {
            "revision": self.revision,
            "request_id": self.request_id,
            "body": self.body,
            "expiry": self.expiry,
            "supports": self.supports,
            "privacy_classification": "unknown",
            "privacy_checks": [
                "project_task",
                "live_primary_source",
                "physical_hash",
                "unredacted",
                "owner_prompt",
                "selected_quote",
            ],
            "use_allowed": not conditional,
            "use_reason": "learning_conditional_use_unsupported" if conditional else "ok",
        }


def project() -> str | ma.Degraded:
    """Resolve the caller's mapped repository identity, never the graph-state directory."""
    if shutil.which("muninn") is None:
        return ma.Degraded("muninn_absent")
    try:
        here = Path.cwd().resolve()
        run = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
            env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        )
        lines = run.stdout.splitlines()
        if run.returncode == 0 and len(lines) == 2:
            common = (here / lines[1]).resolve()
            return str(common.parent if common.name == ".git" else Path(lines[0]).resolve())
        return str(here)
    except (OSError, subprocess.SubprocessError):
        return ma.Degraded("learning_project_unavailable")


def current(task: str, kind: str, project_id: str) -> list[dict[str, Any]] | ma.Degraded:
    """Filter the public task list, which can also include repository-wide Notes."""
    listed = support.read(["know", "list", "--task", task])
    if isinstance(listed, ma.Degraded):
        return listed
    rows = support.objects(listed.get("knowledge"))
    if rows is None:
        return ma.Degraded("muninn_bad_output")
    if len(rows) > MAX_CURRENT:
        return ma.Degraded("learning_read_limit")
    result: list[dict[str, Any]] = []
    for row in rows:
        body = support.object_value(row.get("body"))
        if (
            body is not None
            and body.get("scope") == {"project_id": project_id, "task": task}
            and body.get("kind") == kind
        ):
            result.append(row)
    return result


def _expiry(value: object) -> dict[str, Any] | None | ma.Degraded:
    if value is None:
        return None
    expiry = support.object_value(value)
    if (
        expiry is None
        or not {"at", "condition", "evidence_refs"} <= expiry.keys()
        or support.evidence_ids(expiry.get("evidence_refs")) is None
    ):
        return ma.Degraded("muninn_bad_output")
    at, condition = expiry.get("at"), expiry.get("condition")
    if at is not None and (type(at) not in (int, float) or not math.isfinite(at) or at < 0):
        return ma.Degraded("muninn_bad_output")
    if condition is not None and (not isinstance(condition, str) or not condition.strip()):
        return ma.Degraded("muninn_bad_output")
    if at is None and condition is None:
        return ma.Degraded("muninn_bad_output")
    return ma.Degraded("learning_record_expired") if at is not None and at <= time.time() else expiry


def read(
    listed: dict[str, Any],
    detail: dict[str, Any],
    request_id: str,
    scope: dict[str, Any],
    window: dict[str, Any],
    *,
    deadline: float | None = None,
) -> Note | ma.Degraded:
    """Require exact current revision agreement and its complete relevant support set."""
    kid, revision = listed.get("id"), listed.get("revision")
    if not isinstance(kid, str) or KNOWLEDGE_ID.fullmatch(kid) is None or type(revision) is not int or revision < 1:
        return ma.Degraded("muninn_bad_output")
    shown = support.read(["know", "show", kid], deadline=deadline)
    if isinstance(shown, ma.Degraded):
        return shown
    required_fields = {
        "schema_version",
        "id",
        "revision",
        "state",
        "body",
        "origin",
        "expiry",
        "created_at",
        "retracted_at",
        "retracted_reason",
        "evidence_sources",
    }
    if (
        not required_fields <= shown.keys()
        or shown.get("origin") not in ("review", "proposal")
        or not support.seconds(shown.get("created_at"))
        or type(shown.get("schema_version")) is not int
    ):
        return ma.Degraded("muninn_bad_output")
    if any(shown.get(key) != listed.get(key) for key in ("id", "revision", "state", "body", "expiry")):
        return ma.Degraded("learning_record_changed")
    body = support.object_value(shown.get("body"))
    if shown.get("state") != "active" or shown.get("schema_version") != 1 or body is None or body.get("scope") != scope:
        return ma.Degraded("learning_no_matching_record")
    if body.get("form") != "note":
        return ma.Degraded("learning_form_unsupported")
    refs = support.evidence_ids(body.get("evidence_refs"))
    conditions = body.get("conditions")
    if (
        refs is None
        or not isinstance(conditions, list)
        or any(not isinstance(item, str) or not item.strip() for item in cast("list[object]", conditions))
        or any(not isinstance(body.get(key), str) or not body[key].strip() for key in ("content", "reason"))
    ):
        return ma.Degraded("muninn_bad_output")
    expiry = _expiry(shown.get("expiry"))
    if isinstance(expiry, ma.Degraded):
        return expiry
    required = list(dict.fromkeys(refs + (expiry["evidence_refs"] if expiry is not None else [])))
    checked = support.validate(
        required, shown.get("evidence_sources"), detail.get("evidence"), scope, window, deadline=deadline
    )
    return checked if isinstance(checked, ma.Degraded) else Note(kid, revision, body, expiry, checked, request_id)
