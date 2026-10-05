#!/usr/bin/env python3
"""Pin the read-only Bash allowlist for reviewer and scout subagents."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.native_hook_test_support import HookCase

ROOT = Path(__file__).resolve().parents[3]
HOOK = "reviewer_bash_allowlist"
GUARDED = ("deploy-safety-reviewer", "design-scout", "disposition-scout", "preflight-scout", "source-auditor")
ALLOWED = (
    "ls -la hooks",
    "cat README.md",
    "head -n 5 AGENTS.md",
    "tail -n 5 AGENTS.md",
    "wc -l AGENTS.md",
    "grep -rn 'foo$' hooks",
    "rg -n foo hooks",
    "git status",
    "git log --oneline -5",
    "git diff origin/main --name-only",
    "git show HEAD:README.md",
    "gh pr view 12 --json state",
    "gh pr list --json number",
    "sha256sum README.md",
)
DENIED = (
    "ls; echo hi",
    "ls | cat",
    "ls && echo hi",
    "echo $(whoami)",
    "cat `whoami`",
    "cat README.md > out.txt",
    "cat < README.md",
    "ls\necho hi",
    "git -c core.pager=x log",
    "git commit -m x",
    "git diff --output=out.patch",
    "git diff --ext-diff",
    "rg --pre sh foo",
    "find . -exec rm {} +",
    "find . -delete",
    "sed -i s/a/b/ f",
    "python3 -c 'print(1)'",
    "python -c 'print(1)'",
    "node -e 1",
    "bash -c 'ls'",
    "gh pr view 12",
    "gh pr merge 12 --json x",
    "rm -rf x",
    "echo 'unterminated",
)


def request(command: str, agent_type: object = "design-scout", **fields: object) -> dict[str, Any]:
    """Build a subagent-shaped native Bash PreToolUse request."""
    body: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "session_id": "s_al",
        "cwd": "/x",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        **fields,
    }
    if agent_type is not None:
        body.update(agent_id="a1", agent_type=agent_type)
    return body


class ReviewerAllowlistTests(HookCase):
    """Only guarded agent types are restricted; everyone else is a no-op."""

    def test_allowed_reads_pass_for_every_guarded_type(self) -> None:
        """Exact read-only argv prefixes are silent."""
        for agent in GUARDED:
            for command in ALLOWED:
                with self.subTest(agent=agent, command=command):
                    self.assertEqual(self.output(HOOK, request(command, agent)), {})

    def test_chaining_writes_and_interpreters_denied(self) -> None:
        """Chaining, substitution, redirection, writers and interpreters are denied and traced."""
        for command in DENIED:
            with self.subTest(command=command):
                self.assertTrue(self.denied(HOOK, request(command)))
        rows = [json.loads(x) for x in (self.loop / "s_al" / "trace.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), len(DENIED))
        self.assertEqual({(r["command"], r["outcome"]) for r in rows}, {(HOOK, "denied")})
        self.assertTrue(all(r["reason_code"].startswith("bash_allowlist_deny_") for r in rows))
        self.assertIn("bash_allowlist_deny_", self.log.read_text())

    def test_each_cause_has_its_own_code_in_trace_log_and_message(self) -> None:
        """Meta-chaining, dangerous flag, unparsable quoting and off-list argv are told apart everywhere."""
        causes = {
            "ls; rm x": "bash_allowlist_deny_meta",
            "cat f > g": "bash_allowlist_deny_meta",
            "git diff --output=x": "bash_allowlist_deny_flag",
            "rg --hostname-bin=./sh.sh a f": "bash_allowlist_deny_flag",
            "echo 'unterminated": "bash_allowlist_deny_parse",
            "python3 -m pytest": "bash_allowlist_deny_argv",
        }
        for command, code in causes.items():
            with self.subTest(command=command):
                result = self.invoke(HOOK, request(command))
                self.assertIn(code, result.stdout)
        rows = [json.loads(x) for x in (self.loop / "s_al" / "trace.jsonl").read_text().splitlines()]
        self.assertEqual([r["reason_code"] for r in rows], list(causes.values()))
        log = self.log.read_text()
        for code in set(causes.values()):
            self.assertIn(f"reason_code={code}", log)
        self.assertIn("argv0=python3", log)

    def test_rg_unknown_long_flags_denied(self) -> None:
        """Rg is on a per-flag allowlist: executing or writing flags, known or not yet invented, are denied."""
        for flag in ("--hostname-bin=./sh.sh", "--pre=./x", "--some-future-exec=./x", "-z"):
            with self.subTest(flag=flag):
                self.assertTrue(self.denied(HOOK, request(f"rg {flag} a f")))
        for ok in ("rg -n -i foo hooks", "rg --line-number --glob '*.py' foo", "rg -- -x f"):
            with self.subTest(ok=ok):
                self.assertEqual(self.output(HOOK, request(ok)), {})

    def test_namespaced_agent_type_is_guarded(self) -> None:
        """A plugin-namespaced agent_type (coderails:design-scout) gets the same restriction."""
        for agent in ("coderails:design-scout", "coderails:source-auditor"):
            with self.subTest(agent=agent):
                self.assertTrue(self.denied(HOOK, request("python3 -c 1", agent)))
                self.assertEqual(self.output(HOOK, request("ls", agent)), {})
        self.assertEqual(self.output(HOOK, request("python3 -c 1", "coderails:loop-worker")), {})

    def test_other_identities_are_a_noop(self) -> None:
        """A coder agent, a foreign type, a top-level call and a non-Bash tool are never restricted."""
        for command in DENIED:
            for agent in ("loop-worker", "general-purpose", "Design-Scout", "", None):
                with self.subTest(command=command, agent=agent):
                    self.assertEqual(self.output(HOOK, request(command, agent)), {})
        other_tool = request("rm x") | {"tool_name": "Read"}
        self.assertEqual(self.output(HOOK, other_tool), {})

    def test_malformed_payload_fails_open(self) -> None:
        """Unparseable or command-less input stands aside."""
        values: list[object] = [
            "",
            "broken{",
            {},
            request("ls") | {"tool_input": "x"},
            request("ls") | {"tool_input": {}},
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(self.output(HOOK, value), {})

    def test_negative_control_nothing_else_blocks(self) -> None:
        """Red without the hook: the existing destructive gate does not deny these chained or interpreter calls."""
        for command in ("ls; echo hi", "python3 -c 'print(1)'", "git -c core.pager=x log", "cat README.md > out.txt"):
            with self.subTest(command=command):
                self.assertFalse(self.denied("destructive_bash_gate", request(command)))
                self.assertTrue(self.denied(HOOK, request(command)))

    def test_registered_after_existing_bash_hooks_without_reordering(self) -> None:
        """The new hook is appended last in the Bash group; the four prior entries keep their order."""
        groups = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]["PreToolUse"]
        bash = [g for g in groups if g.get("matcher") == "Bash"][0]["hooks"]
        names = [Path(h["command"].strip('"')).name for h in bash]
        self.assertEqual(
            names,
            [
                "destructive_bash_gate.py",
                "enforce_pr_workflow.py",
                "test_gate.py",
                "verification_volume_ceiling.py",
                f"{HOOK}.py",
                "action_authority_gate.py",  # later pure append; must not precede or reorder the entries above
            ],
        )


if __name__ == "__main__":
    unittest.main()
