#!/usr/bin/env python3
"""Pin the capability branch of the reviewer Bash allowlist hook: profile-gated, exact path, no interpreters."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.capability_profiles import guarded_agents, load_profiles  # noqa: E402
from hooks.scripts.reviewer_bash_allowlist import GUARDED  # noqa: E402
from hooks.scripts.tests.native_hook_test_support import HookCase  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
HOOK = "reviewer_bash_allowlist"
CAP = str(ROOT / "scripts" / "capability.py")
TESTS_RUN = f'{CAP} tests.run --json-args \'{{"name":"scripts"}}\''
INSPECT = f'{CAP} repo.inspect --json-args \'{{"op":"list"}}\''
COMMENT = f'{CAP} pr.comment --json-args \'{{"pr":1,"body":"x"}}\''


def request(command: str, agent_type: object = "source-auditor") -> dict[str, Any]:
    """Build a subagent-shaped native Bash PreToolUse request."""
    body: dict[str, Any] = {
        "hook_event_name": "PreToolUse",
        "session_id": "s_cap",
        "cwd": "/x",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    if agent_type is not None:
        body.update(agent_id="a1", agent_type=agent_type)
    return body


class CapabilityHookTests(HookCase):
    """The hook is the only gate, so each path and identity form is pinned."""

    def rows(self) -> list[dict[str, Any]]:
        """Trace rows written for the session."""
        path = self.loop / "s_cap" / "trace.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def test_guarded_set_derives_from_profiles(self) -> None:
        """Single source: the hook's GUARDED is computed from capabilities/profiles.json."""
        self.assertEqual(GUARDED, guarded_agents(load_profiles(ROOT)))

    def test_e2_known_cost_closed_without_widening_bash(self) -> None:
        """Interpreters stay denied; the declared test run is allowed for source-auditor and denied for design-scout."""
        for denied in ("python3 -c 'print(1)'", f"python3 {CAP} tests.run --json-args '{{}}'", "bash -c ls"):
            with self.subTest(denied=denied):
                self.assertTrue(self.denied(HOOK, request(denied)))
        self.assertEqual(self.output(HOOK, request(TESTS_RUN, "source-auditor")), {})
        self.assertEqual(self.output(HOOK, request(TESTS_RUN, "coderails:source-auditor")), {})
        self.assertTrue(self.denied(HOOK, request(TESTS_RUN, "design-scout")))
        self.assertIn("capability_denied_tests.run", self.invoke(HOOK, request(TESTS_RUN, "design-scout")).stdout)

    def test_each_guarded_agent_gets_exactly_its_profile(self) -> None:
        """repo.inspect passes for all five; pr.comment and (except source-auditor) tests.run are denied."""
        profiles = load_profiles(ROOT)["agents"]
        for agent in sorted(GUARDED):
            for tool, command in (("repo.inspect", INSPECT), ("tests.run", TESTS_RUN), ("pr.comment", COMMENT)):
                with self.subTest(agent=agent, tool=tool):
                    self.assertEqual(self.denied(HOOK, request(command, agent)), tool not in profiles[agent])

    def test_unknown_agent_refused_raw_agent_and_top_level_untouched(self) -> None:
        """A foreign agent_type is refused; shell.raw agents and top-level calls are not restricted."""
        result = self.invoke(HOOK, request(INSPECT, "general-purpose"))
        self.assertIn("capability_unknown_agent", result.stdout)
        self.assertEqual(self.output(HOOK, request(COMMENT, "loop-worker")), {})
        self.assertEqual(self.output(HOOK, request(COMMENT, None)), {})

    def test_only_exact_absolute_path_counts(self) -> None:
        """Relative, lookalike, copied and chained forms of the script fall to the plain allowlist and are denied."""
        args = 'repo.inspect --json-args \'{"op":"list"}\''
        for command in (
            f"scripts/capability.py {args}",
            f"./scripts/capability.py {args}",
            f"/tmp/evil/scripts/capability.py {args}",
            f"{CAP}x {args}",
            f"{CAP} {args}; ls",
            f"{CAP} {args} > out",
            f"ls && {CAP} {args}",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied(HOOK, request(command, "source-auditor")))

    def test_argv_shape_is_strict(self) -> None:
        """Unknown tool and extra or missing flags are refused with their own codes, not passed to the script."""
        cases = {
            f"{CAP} repo.nuke --json-args '{{}}'": "capability_unknown_tool",
            f"{CAP} repo.inspect": "capability_bad_argv",
            f"{CAP} repo.inspect --json-args '{{}}' --extra": "capability_bad_argv",
            f"{CAP} repo.inspect --help": "capability_bad_argv",
        }
        for command, code in cases.items():
            with self.subTest(command=command):
                self.assertIn(code, self.invoke(HOOK, request(command)).stdout)

    def test_allow_and_deny_are_traced_with_low_cardinality_codes(self) -> None:
        """One row per decision: allowed rows name the tool, denials carry the stable reason."""
        self.output(HOOK, request(TESTS_RUN, "source-auditor"))
        self.output(HOOK, request(TESTS_RUN, "design-scout"))
        self.output(HOOK, request(INSPECT, "general-purpose"))
        self.assertEqual(
            [(r["command"], r["outcome"], r["reason_code"]) for r in self.rows()],
            [
                (HOOK, "allowed", "capability_allowed_tests.run"),
                (HOOK, "denied", "capability_denied_tests.run"),
                (HOOK, "denied", "capability_unknown_agent"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
