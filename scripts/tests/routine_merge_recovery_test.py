"""A remote merge cannot be recorded as a local abort or cleaned up afterward."""

from __future__ import annotations

import json
import subprocess
import unittest

from scripts.tests.routine_run_test import LATER, STAGES, RoutineCase, last_marker_is_green


class MergeRecoveryTests(RoutineCase):
    """Exercise the remote-state boundary with a real local branch and fake gh."""

    def ready_to_merge(self) -> None:
        """Advance through every stage before the merge command."""
        self.write("docs/a.md", "x\n")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 0)
        for name in STAGES[4:] + LATER[:-1]:
            self.assertEqual(self.stage(name).returncode, 0, name)

    def merge_gate(self) -> subprocess.CompletedProcess[str]:
        """Invoke the shipped merge gate with the pinned PR number."""
        return self.run_tool("run-gate", "merge", "--", str(self.plugin / "scripts/merge.py"), "7")

    def test_remote_merge_then_cli_error_can_finish_without_cleanup(self) -> None:
        """A CLI error after the remote mutation does not abort the merged PR."""
        self.ready_to_merge()
        gate = self.plugin / "scripts/merge.py"
        gate.write_text(
            "#!/usr/bin/env python3\nfrom pathlib import Path\n"
            "(Path(__file__).parent / 'merged').write_text('yes')\nraise SystemExit(1)\n"
        )
        self.assertEqual(self.merge_gate().returncode, 0)
        self.assertEqual(self.run_tool("finish", "ok").returncode, 0)
        self.assertTrue(last_marker_is_green(self.log))
        self.assertNotIn("pr close", "\n".join(self.gh_calls()))

    def test_merged_before_stage_save_blocks_abort_and_new_begin(self) -> None:
        """Recovery leaves a merged but unfinished run red and keeps its local branch."""
        self.ready_to_merge()
        self.assertEqual(self.merge_gate().returncode, 0)
        state_path = self.log.with_suffix(".state.json")
        state = json.loads(state_path.read_text())
        state["next"] -= 1  # crash after remote success but before the final stage save
        state_path.write_text(json.dumps(state))
        self.assertEqual(self.run_tool("begin", "--new").returncode, 2)
        incomplete = [row for row in self.rows() if row["outcome"] == "run_incomplete"]
        self.assertEqual(incomplete[-1]["reason_code"], "merged_incomplete")
        self.assertEqual(self.run_tool("abort", "audit_failed").returncode, 2)
        self.assertNotIn("pr close", "\n".join(self.gh_calls()))
        self.assertFalse(last_marker_is_green(self.log))

    def unknown_state_blocks_cleanup(self, flag: str) -> None:
        """A failed fetch or changed head leaves a red unknown state, not a PR close."""
        self.ready_to_merge()
        gate = self.plugin / "scripts/merge.py"
        gate.write_text(
            "#!/usr/bin/env python3\nfrom pathlib import Path\n"
            f"(Path(__file__).parent / 'merged.{flag}').write_text('yes')\n"
            "raise SystemExit(1)\n"
        )
        self.assertEqual(self.merge_gate().returncode, 2)
        self.assertEqual(self.rows()[-1]["reason_code"], "merge_state_unknown")
        self.assertEqual(self.run_tool("abort", "audit_failed").returncode, 2)
        self.assertNotIn("pr close", "\n".join(self.gh_calls()))
        self.assertFalse(last_marker_is_green(self.log))

    def test_fetch_failure_blocks_cleanup(self) -> None:
        """An API error cannot authorize an abort or cleanup."""
        self.unknown_state_blocks_cleanup("fail")

    def test_head_mismatch_blocks_cleanup(self) -> None:
        """A changed PR head cannot authorize an abort or cleanup."""
        self.unknown_state_blocks_cleanup("mismatch")


if __name__ == "__main__":
    unittest.main()
