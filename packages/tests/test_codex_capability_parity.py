"""Pin the Codex copy of the capability tools: byte-identical, executable, and honestly instruction-only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"
MIRRORED = (
    "scripts/capability.py",
    "scripts/capability_mcp.py",
    "scripts/lib/capability_extra.py",
    "capabilities/profiles.json",
)


def mismatches(codex_root: Path) -> list[str]:
    """Mirrored files that are missing from, or differ in, codex_root compared with the Claude originals."""
    return [
        rel
        for rel in MIRRORED
        if not (codex_root / rel).is_file() or (codex_root / rel).read_bytes() != (ROOT / rel).read_bytes()
    ]


class CodexCapabilityTests(unittest.TestCase):
    """The Codex package ships the same script and profiles, with weaker (sandbox-only) enforcement."""

    def test_copies_are_byte_identical_and_executable(self) -> None:
        """scripts/capability.py and capabilities/profiles.json are mirrored into the package."""
        for relative in MIRRORED:
            with self.subTest(relative=relative):
                self.assertEqual((ROOT / relative).read_bytes(), (CODEX / relative).read_bytes())
        self.assertTrue(os.access(CODEX / "scripts/capability.py", os.X_OK))
        self.assertTrue(os.access(CODEX / "scripts/capability_mcp.py", os.X_OK))

    def test_mirror_check_catches_deletion_and_one_byte_edit(self) -> None:
        """Negative control: a missing or one-byte-different mirror is reported by the comparison."""
        with tempfile.TemporaryDirectory() as tmp:
            for relative in MIRRORED:
                target = Path(tmp) / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((CODEX / relative).read_bytes())
            self.assertEqual(mismatches(Path(tmp)), [])
            victim = Path(tmp) / "scripts/lib/capability_extra.py"
            victim.write_bytes(victim.read_bytes() + b" ")
            self.assertEqual(mismatches(Path(tmp)), ["scripts/lib/capability_extra.py"])
            victim.unlink()
            self.assertEqual(mismatches(Path(tmp)), ["scripts/lib/capability_extra.py"])

    def test_codex_mcp_server_lists_the_same_tools(self) -> None:
        """The Codex copy of capability_mcp.py serves the same per-role tool lists as the Claude copy."""
        for role in ("design-scout", "source-auditor"):
            lists: list[list[str]] = []
            for base in (ROOT, CODEX):
                lines = [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                ]
                done = subprocess.run(
                    [sys.executable, str(base / "scripts/capability_mcp.py"), "--role", role],
                    input="".join(json.dumps(m) + "\n" for m in lines),
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    env={"PATH": os.environ["PATH"], "CLAUDE_AGENTIC_LOOP_DIR": "/nonexistent-loop"},
                    check=False,
                )
                reply = json.loads(done.stdout.splitlines()[1])
                lists.append(sorted(t["name"] for t in reply["result"]["tools"]))
            self.assertEqual(lists[0], lists[1], role)
            self.assertIn("repo_inspect", lists[0])

    def test_codex_copy_runs_from_its_own_root(self) -> None:
        """From its own root the copy works, refuses undeclared tests, and traces only to the session's own file."""
        with tempfile.TemporaryDirectory() as loop:
            env = {"PATH": os.environ["PATH"], "CLAUDE_AGENTIC_LOOP_DIR": loop, "CLAUDE_SESSION_ID": "s_codex"}
            for tool, args, status in (
                ("repo.inspect", {"op": "list"}, 0),
                ("tests.run", {"name": "not-declared"}, 2),
            ):
                done = subprocess.run(
                    [sys.executable, str(CODEX / "scripts/capability.py"), tool, "--json-args", json.dumps(args)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )
                self.assertEqual(done.returncode, status, done.stdout)
            # the Codex package now ships its own trace_row, so rows land in <loop>/<session>/ and nowhere else
            self.assertEqual([p.name for p in Path(loop).iterdir()], ["s_codex"])

    def test_no_codex_hook_claims_per_agent_bash_gating(self) -> None:
        """Codex registers no allowlist hook: per-agent gating there is sandbox_mode plus instruction text only."""
        text = (CODEX / "hooks/hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("reviewer_bash_allowlist", text)
        self.assertNotIn("capability.py", text)


if __name__ == "__main__":
    unittest.main()
