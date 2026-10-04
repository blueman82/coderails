"""Exercise native hook contracts using Python-owned fixtures and subprocesses."""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "packages/codex"
HOOKS = PACKAGE / "hooks/scripts"


class HookTests(unittest.TestCase):
    """Preserve native event, security, input, and Stop-hook behavior."""

    def setUp(self) -> None:
        """Create isolated Git and plugin data roots."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repo = self.directory / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/feature/test"], check=True)
        self.environment = os.environ | {
            "HOME": str(self.directory / "home"),
            "PLUGIN_ROOT": str(PACKAGE),
            "PLUGIN_DATA": str(self.directory / "data"),
            "CODERAILS_TEST_OUTPUT_DIR": str(self.directory / "logs"),
        }

    def hook(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute the native hook and require a successful hook process."""
        result = subprocess.run(
            [sys.executable, str(HOOKS / f"{name}.py")],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=self.environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def command(self, name: str, command: str) -> dict[str, Any]:
        """Send a Bash event with native command input."""
        return self.hook(
            name,
            {
                "session_id": "s1",
                "cwd": str(self.repo),
                "tool_name": "Bash",
                "hook_event_name": "PreToolUse",
                "tool_input": {"command": command},
            },
        )

    def test_native_registration(self) -> None:
        """Registered hook paths remain native, executable Python entry points."""
        data = json.loads((PACKAGE / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(
            [group["matcher"] for group in data["PreToolUse"]],
            ["^Bash$", "^request_user_input$", "^spawn_agent$", "^apply_patch$"],
        )
        for groups in data.values():
            for group in groups:
                for hook in group["hooks"]:
                    relative = hook["command"].removeprefix('"${PLUGIN_ROOT}/').removesuffix('"')
                    self.assertTrue(relative.endswith(".py"))
                    self.assertTrue(os.access(PACKAGE / relative, os.X_OK))
                    self.assertGreaterEqual(hook["timeout"], 5)

    def test_bootstrap_sources_and_configuration(self) -> None:
        """Only startup nudges missing canonical config, never mutating existing config."""
        legacy = self.repo / ".codex/workflow.config.yaml"
        legacy.parent.mkdir()
        legacy.write_text("sandbox_workers: true\n", encoding="utf-8")
        for source in ("startup", "resume", "clear", "compact"):
            output = self.hook("inject_bootstrap", {"session_id": "s1", "cwd": str(self.repo), "source": source})
            context = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("using-coderails", context)
            self.assertEqual("$coderails-codex:init" in context, source == "startup")
        self.assertEqual(legacy.read_text(encoding="utf-8"), "sandbox_workers: true\n")
        config = self.repo / ".coderails/workflow.config.yaml"
        config.parent.mkdir()
        config.write_text("sandbox_workers: true\n", encoding="utf-8")
        output = self.hook("inject_bootstrap", {"cwd": str(self.repo), "source": "startup"})
        self.assertNotIn("$coderails-codex:init", output["hookSpecificOutput"]["additionalContext"])

    def test_destructive_and_protected_paths(self) -> None:
        """Block destructive families and normalized literal owner config paths."""
        commands = [
            "rm -rf /tmp/example",
            "rm${IFS}-rf /tmp/example",
            "git reset --hard",
            "git clean -fd",
            "find . -delete",
            "truncate -s 0 sample",
            "shred sample",
            "git push --force",
            "git commit --no-verify",
            "cat .env",
            "DROP TABLE sample",
            "dd if=/dev/zero",
            "mkfs.ext4 device",
            "chmod -R 777 directory",
        ]
        targets = [".codex/config.toml", "./.codex/../.codex/requirements.toml", str(self.repo / ".codex/config.toml")]
        commands.extend(
            f"{verb} {target}" for target in targets for verb in ("cat", "pip install -r", "tee", "cp source")
        )
        commands.append("python3 -c 'open(\".codex/config.toml\").read()'")
        for command in commands:
            with self.subTest(command=command):
                result = self.command("destructive_bash_gate", command)
                self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        for command in (
            "git status",
            "cat .env.example",
            "cat .codex/config.toml.bak",
            "cat .codexish/config.toml",
            "git clean --dry-run -f",
        ):
            self.assertEqual(self.command("destructive_bash_gate", command), {})

    def test_trusted_test_command(self) -> None:
        """Use Git-internal Bash commands, deny failures, and retain captured output."""
        malicious = self.repo / ".codex/test_command"
        malicious.parent.mkdir()
        malicious.write_text("exit 99", encoding="utf-8")
        self.assertEqual(self.command("test_gate", "git commit -m test"), {})
        trusted = self.repo / ".git/coderails/test_command"
        trusted.parent.mkdir()
        trusted.write_text("[[ 1 == 1 ]] && true\n", encoding="utf-8")
        self.assertEqual(self.command("test_gate", "git commit -m test"), {})
        trusted.write_text("python3 -c 'print(\"x\" * 2000)'; false\n", encoding="utf-8")
        output = self.command("test_gate", "git commit -m test")["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("Full log:", output["permissionDecisionReason"])
        self.assertTrue(
            any(
                gzip.decompress(p.read_bytes()).decode() == "x" * 2000 + "\n"
                for p in (self.directory / "logs").rglob("output.log.gz")
            )
        )
        self.assertEqual(self.command("test_gate", "git status"), {})

    def test_complete_unicode_log_survives_failed_hook(self) -> None:
        """Preserve Unicode and all lines after the hook returns instead of deleting its log."""
        trusted = self.repo / ".git/coderails/test_command"
        trusted.parent.mkdir()
        writer = self.repo / "unicode_test.py"
        text = "FIRST ERROR\n" + "x" * 1499 + "€\n" + "last\n" * 50
        writer.write_text(f"import sys\nsys.stdout.write({text!r})\nraise SystemExit(1)\n")
        trusted.write_text(f'"{sys.executable}" "{writer}"\n')
        output = self.command("test_gate", "git commit -m test")["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("Full log:", output["permissionDecisionReason"])
        logs = list((self.directory / "logs").rglob("output.log.gz"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(gzip.decompress(logs[0].read_bytes()).decode(), text)
        self.assertNotIn("FIRST ERROR", output["permissionDecisionReason"])
        record = json.loads(logs[0].with_name("run.json").read_text())
        self.assertEqual(record["total_bytes"], len(text.encode()))
        self.assertEqual(record["total_lines"], 52)

    def test_confidence_labels_is_advisory_with_trace_row(self) -> None:
        """An unlabeled long message warns via additionalContext, never blocks, and writes one demoted trace row."""
        loops = self.directory / "loops"
        self.environment["CODERAILS_AGENTIC_LOOP_DIR"] = str(loops)
        log = self.directory / "d.log"
        self.environment["CODERAILS_DISCIPLINE_LOG"] = str(log)
        for event in ("Stop", "SubagentStop"):
            payload = {"session_id": f"s-{event}", "hook_event_name": event, "last_assistant_message": "x " * 150}
            out = self.hook("check_confidence_labels", payload)
            self.assertNotIn("decision", out)
            special = out["hookSpecificOutput"]
            self.assertEqual(special["hookEventName"], event)
            self.assertIn("[discipline-advisory]", special["additionalContext"])
            rows = [json.loads(x) for x in (loops / f"s-{event}/trace.jsonl").read_text().splitlines()]
            self.assertEqual(
                [(r["command"], r["outcome"], r["reason_code"]) for r in rows],
                [("check_confidence_labels", "demoted", "confidence_label_missing")],
            )
            self.assertTrue(rows[0]["event_id"] and rows[0]["ts"])
        lines = log.read_text().splitlines()
        self.assertEqual(sum("would_block=1" in x for x in lines), 2)
        self.assertEqual(sum("demoted=1" in x for x in lines), 2)
        self.assertNotIn("blocked=1", log.read_text())

    def test_confidence_labels_trace_failures_and_clean_pass(self) -> None:
        """Crash control: unwritable trace store or unsafe session still exits 0 advisory; labeled text is silent."""
        blocker = self.directory / "file"
        blocker.write_text("x")
        self.environment["CODERAILS_AGENTIC_LOOP_DIR"] = str(blocker)
        for session in ("s1", "../x", "."):
            payload = {"session_id": session, "hook_event_name": "Stop", "last_assistant_message": "x " * 150}
            self.assertIn("additionalContext", self.hook("check_confidence_labels", payload)["hookSpecificOutput"])
        labeled = {
            "session_id": "s1",
            "hook_event_name": "Stop",
            "last_assistant_message": "ok (verified) " + "x" * 300,
        }
        self.assertEqual(self.hook("check_confidence_labels", labeled), {})

    def test_crack_on_negation_never_stamps(self) -> None:
        """Negated requests leave no flag; clause-separated and plain requests stamp."""
        cases = {"don't crack on yet": False, "never crack on": False, "no problem, crack on": True, "crack on": True}
        for index, (text, stamped) in enumerate(cases.items()):
            session = f"neg{index}"
            self.hook("crack_on_gate", {"session_id": session, "hook_event_name": "UserPromptSubmit", "prompt": text})
            flags = list((self.directory / "data").rglob(f"{session}/crack_on_active"))
            self.assertEqual(bool(flags), stamped, text)

    def test_crack_on_prose_and_cap(self) -> None:
        """Strip quoted/code text and keep the three-block recursion cap."""
        directory = self.directory / "data/sessions/s1"
        directory.mkdir(parents=True)
        (directory / "crack_on_active").touch()
        payload: dict[str, Any] = {"session_id": "s1", "last_assistant_message": "Should I proceed?"}
        self.assertEqual(self.hook("crack_on_prose_gate", payload)["decision"], "block")
        payload["stop_hook_active"] = True
        for _ in range(2):
            self.assertEqual(self.hook("crack_on_prose_gate", payload)["decision"], "block")
        self.assertEqual(self.hook("crack_on_prose_gate", payload), {})
        for text in (
            "Done.",
            "> Should I proceed?",
            "```\nShould I proceed?\n```",
            "Done.\n## Did Not Verify\nCould you check?",
        ):
            self.assertEqual(self.hook("crack_on_prose_gate", {"session_id": "s1", "last_assistant_message": text}), {})

    def test_wiki_taxonomy(self) -> None:
        """Only an identified wiki Git root receives taxonomy restrictions."""
        config = self.repo / ".coderails/workflow.config.yaml"
        config.parent.mkdir()
        config.write_text('wiki_path: "."\n', encoding="utf-8")
        (self.repo / "AGENTS-wiki-schema.md").write_text(
            "## Page types\n`concepts/`\n`projects/`\n## Other\n", encoding="utf-8"
        )
        for directory in ("concepts", "projects"):
            (self.repo / directory).mkdir()
        for path in ("wrong/new.md", "concepts/new.md", "raw/source.md", "index.md", ".codex/test.md"):
            result = self.hook(
                "wiki_taxonomy_gate", {"cwd": str(self.repo), "tool_input": {"command": f"*** Add File: {path}"}}
            )
            self.assertEqual(bool(result), path.startswith("wrong"))


if __name__ == "__main__":
    unittest.main()
