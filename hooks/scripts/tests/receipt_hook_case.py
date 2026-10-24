#!/usr/bin/env python3
"""Shared fixture for receipt hook tests: a repo on main, a fake gh, an owner key and a live authority."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.native_hook_test_support import HookCase
from hooks.scripts.tests.receipt_test_support import REPOSITORY, git, make_owner, make_repo, signed_receipt, store
from scripts.lib import action_binding as ab

MERGE_SHA = "f" * 40
PIN = f"--match-head-commit {MERGE_SHA}"
MERGE = f"gh pr merge 12 --squash {PIN}"
PUSH = "git push origin main"


class ReceiptHookCase(HookCase):
    """A real temp repo on main with a config file drives the hook as a subprocess."""

    def setUp(self) -> None:
        """Repo on main with an origin and a commit, a fake gh, and an owner key in the user-tier trust root."""
        super().setUp()
        self.repo = make_repo(self.directory / "repo")
        keys = self.directory / "home" / ".coderails" / "keys"
        self.key, signers = make_owner(keys)
        signers.rename(keys / "receipt_signers")
        self.agent_key, _ = make_owner(self.directory / "agent")
        gh = self.directory / "bin" / "gh"
        gh.parent.mkdir()
        gh.write_text(
            f'#!/bin/sh\ncase "$1 $2" in\n'
            f'"pr list") echo \'[{{"number":12}}]\';;\n'
            f'*) echo \'{{"baseRefName":"main","headRefOid":"{MERGE_SHA}"}}\';;\nesac\n'
        )
        gh.chmod(0o755)
        self.environment = self.environment | {"PATH": f"{gh.parent}:{self.environment['PATH']}"}

    def configure(self, value: str | None) -> None:
        """Write (or skip) the action_authority config line."""
        if value is not None:
            (self.repo / ".coderails").mkdir(exist_ok=True)
            (self.repo / ".coderails/workflow.config.yaml").write_text(f"action_authority: {value}\n")

    def payload(self, command: str, session: str = "s1") -> dict[str, Any]:
        """A Bash PreToolUse payload."""
        return {
            "hook_event_name": "PreToolUse",
            "session_id": session,
            "cwd": str(self.repo),
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }

    def mint(
        self, command: str, kind: str, session: str = "s1", cwd: Path | None = None, rid: str = "r1",
        key: Path | None = None, **over: object,
    ) -> str:  # fmt: skip
        """Store a signed receipt matching the hook's view of `command` run in `cwd` (default the repo) on main."""
        where = str(cwd or self.repo)
        bind = (
            {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": MERGE_SHA}
            if kind == "merge" else ab.binding(kind, command, where)
        )  # fmt: skip
        rec = signed_receipt(
            key or self.key, kind, command, where, git(Path(where), "branch", "--show-current"), bind, session,
            receipt_id=rid, **over,
        )  # fmt: skip
        store(self.loop, rec, session)
        return rid

    def reasons(self, session: str = "s1") -> list[str]:
        """Reason codes traced for a session."""
        path = self.loop / session / "trace.jsonl"
        return [json.loads(line)["reason_code"] for line in path.read_text().splitlines()] if path.exists() else []

    def grant(self, **over: object) -> None:
        """Write a live authority for session s1."""
        obj = {
            "authority_id": "auth-1", "loop_id": None, "session_id": "s1", "scope": ["code"], "denied": [],
            "max_prs": 3, "expires_at": "2999-01-01T00:00:00+00:00", "revocable": True,
            "approval_required_for": ["merge"], "granted_by": "command",
        } | over  # fmt: skip
        path = self.loop / "s1" / "authority.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj))
