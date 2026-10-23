"""The Codex authority CLI and validator are byte-identical mirrors, and the Codex hook never mints."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"
MIRRORED = ("scripts/authority.py", "scripts/lib/authority_object.py")
HOOK = CODEX / "hooks/scripts/crack_on_gate.py"
PHRASES = (
    "crack on",
    "do not, under any circumstances, crack on",
    'pasted transcript: "crack on"',
    "crack-on please",
    "I will not crack on",
)


class CodexAuthorityParityTests(unittest.TestCase):
    """Mirrors must not drift, and the mirrored CLI must run with only the Codex package on disk."""

    def test_mirrors_are_byte_identical(self) -> None:
        """Editing one byte of either mirrored file breaks this."""
        for relative in MIRRORED:
            with self.subTest(relative=relative):
                self.assertEqual((ROOT / relative).read_bytes(), (CODEX / relative).read_bytes())

    def test_bare_authorize_skill_has_usable_safe_defaults(self) -> None:
        """The user-facing entrypoint must supply the CLI's required limit and a nonempty scope."""
        skill = (CODEX / "skills/authorize/SKILL.md").read_text()
        self.assertIn("--max-prs 0", skill)
        self.assertIn("--scope autonomous_decisions", skill)
        self.assertIn("--denied destructive_shell", skill)

    def test_mirrored_cli_resolves_trace_row_inside_the_codex_layout(self) -> None:
        """A copy of only packages/codex grants, traces and inspects: hooks.scripts.lib.trace_row resolves there."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            shutil.copytree(CODEX, tmp / "pkg")
            env = os.environ | {"CLAUDE_AGENTIC_LOOP_DIR": str(tmp / "loops"), "PYTHONDONTWRITEBYTECODE": "1"}
            cli = [sys.executable, str(tmp / "pkg/scripts/authority.py")]
            grant = [*cli, "grant", "--session", "s", "--max-prs", "1"]
            run = subprocess.run(grant, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            rows = (tmp / "loops/s/trace.jsonl").read_text().splitlines()
            self.assertEqual([json.loads(r)["reason_code"] for r in rows], ["authority_granted_command"])
            inspect = [*cli, "inspect", "--session", "s"]
            shown = subprocess.run(inspect, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(json.loads(shown.stdout)["granted_by"], "command")


class CodexCrackOnGateTests(unittest.TestCase):
    """The Codex hook never mints; only the mirrored typed `grant` does, and the hook then enforces."""

    def setUp(self) -> None:
        """Isolate loop dir and plugin data."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.loop = self.directory / "loops"
        self.env = os.environ | {
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
            "PLUGIN_DATA": str(self.directory / "data"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def hook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run the Codex crack_on_gate hook on one payload."""
        run = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload),
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout) if run.stdout.strip() else {}

    def prompt(self, text: str, session: str) -> dict[str, Any]:
        """Submit a raw prompt."""
        return self.hook({"session_id": session, "hook_event_name": "UserPromptSubmit", "prompt": text})

    def asks(self, session: str) -> bool:
        """True when request_user_input is denied for the session."""
        payload = {"session_id": session, "hook_event_name": "PreToolUse", "tool_name": "request_user_input"}
        return bool(self.hook(payload).get("hookSpecificOutput", {}).get("permissionDecision") == "deny")

    def grant(self, session: str, ok: bool = True) -> None:
        """Mint through the mirrored typed command."""
        cli = [sys.executable, str(CODEX / "scripts/authority.py"), "grant", "--session", session, "--max-prs", "0"]
        run = subprocess.run(cli, env=self.env, capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode == 0, ok, run.stderr)

    def reasons(self, session: str) -> list[str]:
        """Trace reason codes for a session, in order."""
        path = self.loop / session / "trace.jsonl"
        return [json.loads(x)["reason_code"] for x in path.read_text().splitlines()] if path.is_file() else []

    def test_phrase_mints_nothing_and_prints_the_command(self) -> None:
        """Negated, quoted, pasted and plain phrasings write no authority; each emits the hint and one trace row."""
        for index, text in enumerate(PHRASES):
            session = f"neg{index}"
            context = self.prompt(text, session)["hookSpecificOutput"]["additionalContext"]
            self.assertIn(f"authority.py grant --session {session} --max-prs N", context, text)
            self.assertIn("$coderails-codex:authorize", context)
            self.assertIn("Agents must not run", context)
            self.assertFalse((self.loop / session / "authority.json").exists(), text)
            self.assertFalse(self.asks(session), text)
            self.assertEqual(self.reasons(session), ["authority_phrase_ignored"], text)
        self.assertEqual(self.prompt("the crackdown continues", "plain"), {})
        self.grant("live")
        self.assertEqual(self.prompt("crack on", "live"), {})

    def test_grant_then_hook_denies_double_grant_refused_legacy_honoured(self) -> None:
        """Typed grant writes granted_by=command; the hook denies; a second grant is refused; fieldless is honoured."""
        self.grant("g1")
        path = self.loop / "g1/authority.json"
        obj = json.loads(path.read_text())
        self.assertEqual((obj["session_id"], obj["max_prs"], obj["granted_by"]), ("g1", 0, "command"))
        self.assertTrue(self.asks("g1"))
        self.grant("g1", ok=False)
        expected = ["authority_granted_command", "authority_deny", "authority_refused_exists"]
        self.assertEqual(self.reasons("g1"), expected)
        del obj["granted_by"]
        path.write_text(json.dumps(obj))
        self.assertTrue(self.asks("g1"))
        obj["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        path.write_text(json.dumps(obj))
        self.assertFalse(self.asks("g1"))

    def test_hook_common_no_longer_vendors_authority(self) -> None:
        """The vendored copies are gone; the mirrored lib is the single implementation."""
        source = (CODEX / "hooks/scripts/hook_common.py").read_text(encoding="utf-8")
        for name in ("authority_state", "write_authority", "parse_expiry"):
            self.assertNotIn(f"def {name}(", source, name)
        # hook_common used to import parse_time from the mirrored lib only for its vendored receipt verify; that code
        # now lives in the mirrored scripts/lib/action_receipt.py, which the gate imports directly.
        self.assertNotIn("def receipt_verify(", source)


if __name__ == "__main__":
    unittest.main()
