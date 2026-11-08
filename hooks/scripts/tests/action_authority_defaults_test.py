"""Exercise default receipt enforcement through both maintained hook entrypoints."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from hooks.scripts.tests.receipt_hook_case import MERGE, ReceiptHookCase  # noqa: E402
from hooks.scripts.tests.receipt_test_support import make_repo  # noqa: E402
from scripts.lib.receipt_counters import gate_summary, receipt_summary  # noqa: E402


class DefaultAuthorityTests(ReceiptHookCase):
    """Use inert command payloads and temporary keys; never execute a merge or owner approval."""

    def invoke_provider(self, provider: str, session: str, command: str = MERGE) -> bool:
        """Return the public hook decision and require a successful hook process."""
        plugin = ROOT if provider == "claude" else ROOT / "packages/codex"
        result = subprocess.run(
            [sys.executable, str(plugin / "hooks/scripts/action_authority_gate.py")],
            input=json.dumps(self.payload(command, session)), capture_output=True, text=True, check=False,
            env=self.environment | {"PLUGIN_ROOT": str(plugin), "PLUGIN_DATA": str(self.directory / "data")},
        )  # fmt: skip
        self.assertEqual(result.returncode, 0, result.stderr)
        output: dict[str, Any] = json.loads(result.stdout) if result.stdout.strip() else {}
        return bool(output.get("hookSpecificOutput", {}).get("permissionDecision") == "deny")

    def trace_counts(self, session: str) -> dict[str, int]:
        """Read actual reason/outcome rows for the maintained counter consumers."""
        counts: Counter[str] = Counter()
        for line in (self.loop / session / "trace.jsonl").read_text().splitlines():
            row = json.loads(line)
            counts[f"{row['command']}/{row['outcome']}/{row['reason_code']}"] += 1
        return dict(counts)

    def test_absent_config_and_omitted_key_deny_without_receipt(self) -> None:
        """Dropping the default to off must not permit a pinned merge without approval evidence."""
        for shape, text in (("absent", None), ("empty", ""), ("omitted", "sandbox_workers: true\n")):
            if text is not None:
                config = self.repo / ".coderails/workflow.config.yaml"
                config.parent.mkdir(exist_ok=True)
                config.write_text(text)
            for provider in ("claude", "codex"):
                with self.subTest(shape=shape, provider=provider):
                    session = f"{shape}-{provider}"
                    self.assertTrue(self.invoke_provider(provider, session))
                    self.assertEqual(self.reasons(session), ["denied_no_receipt"])
                    self.assertEqual(gate_summary(self.trace_counts(session))["no_receipt"], 1)

    def test_explicit_modes_keep_their_public_decisions(self) -> None:
        """Enforce denies; advisory warns and off skips only when selected explicitly."""
        for mode, denied, reasons in (
            ("enforce", True, ["denied_no_receipt"]),
            ("advisory", False, ["advisory_no_receipt"]),
            ("off", False, []),
        ):
            self.configure(mode)
            for provider in ("claude", "codex"):
                with self.subTest(mode=mode, provider=provider):
                    session = f"{mode}-{provider}"
                    self.assertEqual(self.invoke_provider(provider, session), denied)
                    self.assertEqual(self.reasons(session), reasons)

    def test_invalid_mode_refuses_even_with_a_signed_fixture(self) -> None:
        """Unknown values, bad types and duplicate modes cannot bypass strict configuration."""
        for index, text in enumerate(
            (
                "action_authority: enforse\n",
                "action_authority: false\n",
                "action_authority: off\naction_authority: enforce\n",
                "action_authority : off\n",
            )
        ):
            config = self.repo / ".coderails/workflow.config.yaml"
            config.parent.mkdir(exist_ok=True)
            config.write_text(text)
            for provider in ("claude", "codex"):
                with self.subTest(config=text, provider=provider):
                    session = f"invalid-{index}-{provider}"
                    self.mint(MERGE, "merge", session=session)
                    self.assertTrue(self.invoke_provider(provider, session))
                    self.assertIn("config_rejected", self.reasons(session))
                    self.assertFalse((self.loop / session / "receipts/r1.consumed").exists())

    def test_invalid_source_config_cannot_escape_by_changing_repository(self) -> None:
        """A command's invalid source config cannot disappear after cd into an off repository."""
        self.configure("enforse")
        target = make_repo(self.directory / "target")
        config = target / ".coderails/workflow.config.yaml"
        config.parent.mkdir()
        config.write_text("action_authority: off\n")
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider):
                session = f"source-{provider}"
                self.assertTrue(self.invoke_provider(provider, session, f"cd {target} && {MERGE}"))
                self.assertIn("config_rejected", self.reasons(session))

    def test_direct_merge_seam_defaults_to_enforce_and_rejects_bad_config(self) -> None:
        """The independently called merge receipt seam must not silently skip missing or invalid config."""
        code = (
            "from scripts.lib.receipt_gate import ReceiptRefusedError, require_merge_receipt\n"
            "try:\n require_merge_receipt('12')\n"
            "except ReceiptRefusedError as error:\n print(error); raise SystemExit(1)\n"
        )
        for index, text in enumerate((None, "", "action_authority: enforse\n", "action_authority: false\n")):
            if text is not None:
                config = self.repo / ".coderails/workflow.config.yaml"
                config.parent.mkdir(exist_ok=True)
                config.write_text(text)
            for provider in ("claude", "codex"):
                with self.subTest(config=text, provider=provider):
                    plugin = ROOT if provider == "claude" else ROOT / "packages/codex"
                    result = subprocess.run(
                        [sys.executable, "-c", code], cwd=self.repo, capture_output=True, text=True, check=False,
                        env=self.environment | {"PYTHONPATH": str(plugin), "CLAUDE_SESSION_ID": f"direct-{index}"},
                    )  # fmt: skip
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn("config_rejected" if index > 1 else "signed owner receipt", result.stdout)
                    self.assertNotIn("Traceback", result.stderr)

    def test_config_parse_error_denies_before_modes_are_resolved(self) -> None:
        """A config exception cannot select off before source and target modes are validated."""
        self.environment["PYTHONINTMAXSTRDIGITS"] = "4300"
        oversized = "wiki_stale_days: " + "9" * 5000 + "\n"
        target = make_repo(self.directory / "parse-target")
        target_config = target / ".coderails/workflow.config.yaml"
        target_config.parent.mkdir()
        config = self.repo / ".coderails/workflow.config.yaml"
        config.parent.mkdir()
        cases = (
            (oversized, "action_authority: off\n", MERGE),
            ("action_authority: off\n" + oversized, "action_authority: off\n", MERGE),
            ("action_authority: advisory\n" + oversized, "action_authority: off\n", MERGE),
            (oversized, "action_authority: off\n", f"cd {target} && {MERGE}"),
            ("action_authority: off\n", oversized, f"cd {target} && {MERGE}"),
            ("action_authority: advisory\n", oversized, f"cd {target} && {MERGE}"),
        )
        for index, (source_text, target_text, command) in enumerate(cases):
            config.write_text(source_text)
            target_config.write_text(target_text)
            for provider in ("claude", "codex"):
                with self.subTest(case=index, provider=provider):
                    session = f"parse-{index}-{provider}"
                    self.assertTrue(self.invoke_provider(provider, session, command))
                    self.assertEqual(self.reasons(session), ["denied_gate_error"])
                    self.assertEqual(receipt_summary(self.trace_counts(session))["by_outcome"], {"denied": 1})

    def test_unguarded_command_skips_broken_config(self) -> None:
        """A config error does not apply the receipt gate to an ordinary status command."""
        self.environment["PYTHONINTMAXSTRDIGITS"] = "4300"
        config = self.repo / ".coderails/workflow.config.yaml"
        config.parent.mkdir()
        config.write_text("wiki_stale_days: " + "9" * 5000 + "\n")
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider):
                session = f"unguarded-{provider}"
                self.assertFalse(self.invoke_provider(provider, session, "git status --short"))
                self.assertEqual(self.reasons(session), [])

    def test_default_consumes_signed_fixture_once_and_counts_replay(self) -> None:
        """A valid signature permits once; losing consumption or replay checks must fail this test."""
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider):
                session = f"signed-{provider}"
                self.mint(MERGE, "merge", session=session)
                self.assertFalse(self.invoke_provider(provider, session))
                self.assertTrue((self.loop / session / "receipts/r1.consumed").exists())
                self.assertTrue(self.invoke_provider(provider, session))
                self.assertEqual(
                    self.reasons(session),
                    [
                        "trust_root_user_tier",
                        "receipt_consumed",
                        "denied_consumed",
                    ],
                )
                self.assertEqual(receipt_summary(self.trace_counts(session))["by_outcome"], {"allowed": 1, "denied": 1})


if __name__ == "__main__":
    unittest.main()
