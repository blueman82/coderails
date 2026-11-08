"""Native refusals for missing or changed required graph context in both providers."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/graph-semantics"))
from graph_contract import sections_sha256

from packages.tests.provider_fixture import Provider
from packages.tests.test_provider_add_unit_contract import assigned_checkout


class RequiredContextDispatchTests(unittest.TestCase):
    """Use provider hooks and state files, without changing a live graph."""

    def open(self, name: str) -> Provider:
        """Create one isolated active wave."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        provider = Provider(Path(temporary.name), name)
        self.addCleanup(lambda: self.assertFalse(provider.external_refusals.exists()))
        provider.success("begin-wave")
        return provider

    def refuse(self, provider: Provider, request: dict[str, Any], code: str) -> None:
        """Require a typed refusal and no state write."""
        before = provider.path.read_bytes()
        result = provider.hook("loop_dispatch_guard", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(provider.path.read_bytes(), before)
        trace = provider.path.with_name("recovery-trace.jsonl")
        self.assertEqual(json.loads(trace.read_text().splitlines()[-1])["reason_code"], code)

    def test_missing_or_changed_required_context_refuses(self) -> None:
        """A new hash cannot make a missing or false typed route valid."""
        for name in ("claude", "codex"):
            for change, code in (("missing", "dispatch_contract_altered"), ("changed", "dispatch_context_mismatch")):
                with self.subTest(provider=name, change=change):
                    provider = self.open(name)
                    request = provider.request()
                    state = provider.read()
                    record = next(iter(state["graph"]["dispatches"].values()))
                    if change == "missing":
                        del record["contract"]["required_context"]
                    else:
                        record["contract"]["required_context"]["skills"] = ["agentic-loop", "task-evals"]
                    record["prompt_sections_sha256"] = sections_sha256(record["contract"])
                    provider.write(state)
                    self.refuse(provider, request, code)

    def test_context_cutoff_must_be_bounded(self) -> None:
        """A missing or advanced cutoff cannot downgrade a new dispatch to old evidence."""
        for name in ("claude", "codex"):
            for stamp in (None, "2", 0, 10**9):
                with self.subTest(provider=name, stamp=stamp):
                    provider = self.open(name)
                    state = provider.read()
                    if stamp is None:
                        del state["graph"]["context_from_revision"]
                    else:
                        state["graph"]["context_from_revision"] = stamp
                    provider.write(state)
                    result = provider.call("inspect")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("dispatch_state_unconverted", result.stderr)

    def test_completed_freeze_keeps_context_after_supported_worktree_assignment(self) -> None:
        """A later source assignment cannot change the context of an already completed dispatch."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name), tempfile.TemporaryDirectory() as scratch:
                provider = Provider(Path(scratch), name)
                state = provider.state(("S2.7d[1]",))
                state["work_units"] = {"1": {"status": "pending"}}
                provider.write(state)
                provider.freeze()
                provider.finish_wave()
                issued = provider.read()["graph"]["dispatches"]
                checkout = assigned_checkout(provider.home)
                provider.success(
                    "assign-worktree",
                    "--session",
                    provider.session,
                    "--loop-id",
                    state["loop_id"],
                    "--unit",
                    "1",
                    "--worktree",
                    checkout,
                )
                self.assertEqual(provider.read()["graph"]["dispatches"], issued)
                check = (
                    "from hooks.scripts.lib.graph_evidence_revalidate import revalidate_all as check"
                    if name == "claude"
                    else "from graph_evidence import validate_worker_evidence as check"
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import json,sys; sys.path.insert(0,sys.argv[2]); "
                        + check
                        + "; check(json.load(open(sys.argv[1])))",
                        str(provider.path),
                        str(provider.plugin / "skills/agentic-loop/scripts"),
                    ],
                    cwd=Path(__file__).resolve().parents[2],
                    env=provider.environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                historical = provider.read()
                for change, code in (
                    ("changed", "dispatch_contract_altered"),
                    ("rehashed", "dispatch_sections_missing"),
                    ("missing", "dispatch_contract_altered"),
                ):
                    with self.subTest(provider=name, change=change):
                        altered = copy.deepcopy(historical)
                        record = next(iter(altered["graph"]["dispatches"].values()))
                        if change == "missing":
                            del record["contract"]["required_context"]
                        else:
                            record["contract"]["required_context"]["checks"].append("lessons")
                        if change == "rehashed":
                            record["prompt_sections_sha256"] = sections_sha256(record["contract"])
                        provider.write(altered)
                        denied = subprocess.run(
                            result.args,
                            cwd=Path(__file__).resolve().parents[2],
                            env=provider.environment,
                            text=True,
                            capture_output=True,
                            check=False,
                        )
                        self.assertNotEqual(denied.returncode, 0)
                        self.assertIn(code, denied.stderr)
                provider.write(historical)

    def test_unreadable_facts_keep_the_discovered_active_loop_route(self) -> None:
        """A facts read failure cannot remove the active-loop floor or claim valid requirements."""
        for name in ("claude", "codex"):
            provider = self.open(name)
            prefix = "coderails" if name == "claude" else "coderails-codex"
            for content in (b"{", b"\xff"):
                with self.subTest(provider=name, content=content):
                    provider.path.write_bytes(content)
                    result = provider.hook(
                        "inject_context",
                        {"session_id": provider.session, "cwd": str(provider.home), "prompt": "hello"},
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    text = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
                    self.assertIn(f"route: {prefix}:agentic-loop", text)
                    self.assertIn("facts=unavailable", text)
                    self.assertNotIn(f"{prefix}:task-evals", text)
                    self.assertEqual(provider.path.read_bytes(), content)

    def test_issued_worktree_still_binds_native_child_checkout(self) -> None:
        """Historical lookup cannot accept a child outside its issuance-time assigned checkout."""
        with tempfile.TemporaryDirectory() as scratch:
            provider = Provider(Path(scratch), "codex")
            state = provider.state(("S2.7d[1]",))
            state["work_units"] = {"1": {"status": "pending"}}
            provider.write(state)
            provider.freeze()
            checkout = assigned_checkout(provider.home)
            provider.success(
                "assign-worktree",
                "--session",
                provider.session,
                "--loop-id",
                state["loop_id"],
                "--unit",
                "1",
                "--worktree",
                checkout,
            )
            provider.success("begin-wave")
            report = provider.launch()
            child = next(provider.parent.parent.glob("fixture-child-*.jsonl"))
            rows = [json.loads(line) for line in child.read_text().splitlines()]
            rows[0]["payload"]["cwd"] = str(provider.home)
            child.write_text("".join(json.dumps(row) + "\n" for row in rows))
            before = provider.path.read_bytes()
            denied = provider.call("record-wave", json.dumps(report))
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("outside its assigned worktree", denied.stderr)
            self.assertEqual(provider.path.read_bytes(), before)
            rows[0]["payload"]["cwd"] = checkout
            child.write_text("".join(json.dumps(row) + "\n" for row in rows))
            provider.success("record-wave", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
