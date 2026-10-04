"""Re-execute remote eval embeds in real isolated trusted-commit worktrees."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import sys
import unittest
from collections.abc import Generator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.post_evals_fixture import ArtifactCase, command, entry
from scripts.lib.eval_validation import extract_json_block
from scripts.post_evals import smoke_verify


@contextlib.contextmanager
def in_directory(path: Path) -> Generator[None, None, None]:
    """Temporarily enter a private fixture repository for the native Git API."""
    before = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(before)


class TrustedHeadTests(ArtifactCase):
    """Only files at the trusted head can supply merge-time evidence."""

    def setUp(self) -> None:
        """Commit independent check/control fixtures in a repository with no remote."""
        super().setUp()
        self.repository()
        for name, source in (
            ("check.py", "print('real check')\n"),
            ("control.py", "print('real control'); raise SystemExit(1)\n"),
            ("vacuous.py", "print('vacuous control')\n"),
        ):
            (self.directory / name).write_text(source)
        self.git("add", "check.py", "control.py", "vacuous.py")
        self.git("commit", "-m", "checks at trusted head")
        self.head = self.git("rev-parse", "HEAD")
        interpreter = shlex.quote(sys.executable)
        self.honest = {**entry(), "cmd": f"{interpreter} check.py", "negative_control": f"{interpreter} control.py"}
        self.data["evals"] = [self.honest]
        self.save()

    def verify(self, expected: int, reason: str = "", head: str = "") -> None:
        """Assert result, exact refusal family and detached-worktree cleanup."""
        output = io.StringIO()
        with in_directory(self.directory), contextlib.redirect_stderr(output):
            result = smoke_verify(self.path, head or self.head)
        self.assertEqual(result, expected, output.getvalue())
        if reason:
            self.assertRegex(output.getvalue(), reason)
        self.assertEqual(self.git("worktree", "list", "--porcelain").count("worktree "), 1)

    def test_real_committed_commands_and_dirty_checkout_isolation(self) -> None:
        """Use the trusted committed control even when the caller checkout makes it pass."""
        (self.directory / "control.py").write_text("raise SystemExit(0)\n")
        self.verify(0)

    def test_fabricated_smoke_cannot_hide_absent_command(self) -> None:
        """Optimistic recorded outcomes do not establish actual executability."""
        self.data["evals"] = [{**self.honest, "cmd": "coderails_missing_trusted_command_3971"}]
        self.save()
        self.verify(1, "E1.*cmd did not execute at the gate")

    def test_committed_vacuous_control_is_rejected(self) -> None:
        """A real command returning zero is still an invalid negative control."""
        self.data["evals"] = [{**self.honest, "negative_control": f"{shlex.quote(sys.executable)} vacuous.py"}]
        self.save()
        self.verify(1, "E1.*negative_control exited 0")

    def test_all_priorities_empty_ids_and_duplicate_ids_execute(self) -> None:
        """Deployment labels or ambiguous IDs cannot suppress scripted entries."""
        for identity, priority, predecessors in (
            ("deployed", "P1", [self.honest]),
            ("deployed", "P0", []),
            ("", "P0", []),
            ("E1", "P0", [self.honest]),
        ):
            with self.subTest(identity=identity, priority=priority):
                self.data["evals"] = [
                    *predecessors,
                    {
                        **self.honest,
                        "id": identity,
                        "priority": priority,
                        "mode": "scripted",
                        "cmd": "coderails_missing_deployed_probe_3971",
                    },
                ]
                self.save()
                self.verify(1, "cmd did not execute at the gate")

    def test_stdin_consumption_does_not_hide_later_vacuous_control(self) -> None:
        """Observe the later control's actual exit rather than an unrelated failure."""
        self.data["evals"] = [
            {**self.honest, "cmd": command("import sys; sys.stdin.read()")},
            {**self.honest, "id": "vacuous", "negative_control": command("pass")},
        ]
        self.save()
        self.verify(1, "vacuous.*negative_control exited 0")

    def test_unresolvable_head_fails_without_leaking_worktree(self) -> None:
        """No configured remote can supply the nonexistent trusted commit."""
        self.verify(1, "fetch.*non-zero exit", "f" * 40)

    def test_malformed_remote_embeds_and_modes_refuse(self) -> None:
        """The literal remote embed must enumerate known-mode evals before execution."""
        malformed: tuple[object, ...] = (
            42,
            "bad",
            {},
            None,
            [{**entry(), "mode": "Scripted"}],
            [{"id": "missing-mode"}],
        )
        for evals in malformed:
            with self.subTest(evals=evals):
                body = f"```json\n{json.dumps({'verification_level': 1, 'evals': evals})}\n```"
                self.path.write_text(extract_json_block(body))
                self.verify(1, "array|mode")
        self.path.write_text("{bad")
        self.verify(1, "Expecting")
        self.data["evals"] = [{**entry(), "mode": "agent-run"}]
        self.save()
        self.verify(0)


if __name__ == "__main__":
    unittest.main()
