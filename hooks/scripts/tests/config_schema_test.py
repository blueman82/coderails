"""Typed workflow-config layer: schema, load_config findings, resolve-config --json, provider mirror."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib.config import (
    config_value,
    integrity_machine_user,
    load_config,
    report_findings,
    require_signatures,
)

ROOT = Path(__file__).resolve().parents[3]
CODEX = ROOT / "packages/codex"
REAL_SHAPE = """project: coderails
wiki_path: /tmp/vault
wiki_supervision: discuss
wiki_git_worktree: true
wiki_git_bypass_flag: null
wiki_git_pull_path: null
worktree_base: /tmp
worktree_script: null
jira: null
engineering_principles_paths:
  - "**/*.sh"
engineering_principles_skill: coderails-codex:engineering-principles-bash
sandbox_workers: false
wiki_debt_epoch_pr: 80
integrity_review:
  machine_user: null
evals:
  require_signatures: true
"""


class ConfigCase(unittest.TestCase):
    """Write a throwaway config file per test, with trace output sandboxed."""

    def setUp(self) -> None:
        """Keep trace rows out of the real loop dir."""
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.loop = Path(scratch.name)
        patcher = patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": scratch.name, "CLAUDE_CODE_SESSION_ID": "S1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, text: str) -> Path:
        """Return a path holding text, cleaned up with the test."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "workflow.config.yaml"
        path.write_text(text)
        return path

    def codes(self, findings: list[dict[str, str]]) -> list[str]:
        """Reason codes only."""
        return [finding["code"] for finding in findings]


class LoadConfigTests(ConfigCase):
    """load_config applies defaults, coerces types and reason-codes problems without raising."""

    def test_every_documented_shape_is_clean(self) -> None:
        """Back-compat: the example file, init.md's example block and a real-shaped file raise no finding."""
        init = (ROOT / "commands/init.md").read_text()
        block = re.search(r"Example output:\n```yaml\n(.*?)```", init, re.S)
        assert block is not None
        for name, text in (
            ("example", (ROOT / "examples/workflow.config.yaml").read_text()),
            ("init", block[1]),
            ("real", REAL_SHAPE),
        ):
            with self.subTest(name):
                _, findings = load_config(self.write(text))
                self.assertEqual(findings, [])

    def test_values_are_typed(self) -> None:
        """Booleans, integers, nulls, lists and nested sections are coerced."""
        values, _ = load_config(self.write(REAL_SHAPE))
        self.assertIs(values["wiki_git_worktree"], True)
        self.assertIs(values["sandbox_workers"], False)
        self.assertEqual(values["wiki_debt_epoch_pr"], 80)
        self.assertIsNone(values["worktree_script"])
        self.assertEqual(values["engineering_principles_paths"], ["**/*.sh"])
        self.assertIsNone(values["integrity_review"]["machine_user"])
        self.assertIs(values["evals"]["require_signatures"], True)

    def test_defaults_applied_for_absent_keys(self) -> None:
        """An absent key takes its schema default."""
        values, _ = load_config(self.write("wiki_path: ../w\n"))
        self.assertEqual(values["wiki_supervision"], "discuss")
        self.assertIs(values["wiki_git_worktree"], True)

    def test_typo_key_is_reason_coded_with_hint(self) -> None:
        """Negative control: config_value silently returns nothing for the typo; load_config names it."""
        path = self.write("wiki_pth: ../w\n")
        self.assertEqual(config_value(path, "wiki_path"), "")
        values, findings = load_config(path)
        self.assertEqual(findings, [{"code": "config_unknown_key", "key": "wiki_pth", "hint": "wiki_path"}])
        self.assertEqual(values["wiki_pth"], "../w")

    def test_nested_typo(self) -> None:
        """A typo inside a typed section is flagged with its dotted key."""
        _, findings = load_config(self.write("integrity_review:\n  machin_user: x\n"))
        self.assertEqual(findings[0]["key"], "integrity_review.machin_user")
        self.assertEqual(findings[0]["hint"], "integrity_review.machine_user")

    def test_bad_type_keeps_raw_value(self) -> None:
        """A value of the wrong type is reported and left as written."""
        values, findings = load_config(self.write("sandbox_workers: maybe\nwiki_debt_epoch_pr: null\n"))
        self.assertEqual(self.codes(findings), ["config_bad_type", "config_bad_type"])
        self.assertEqual(values["sandbox_workers"], "maybe")
        self.assertEqual(values["wiki_debt_epoch_pr"], "null")

    def test_unreadable_never_raises(self) -> None:
        """Missing, torn (non-UTF-8) and directory paths fall back to defaults with one finding."""
        torn = self.write("")
        torn.write_bytes(b"wiki_path: \xff\xfe\n")
        for path in (Path("/nonexistent/workflow.config.yaml"), torn, torn.parent):
            with self.subTest(path=str(path)):
                values, findings = load_config(path)
                self.assertEqual(self.codes(findings), ["config_unreadable"])
                self.assertEqual(values["wiki_supervision"], "discuss")

    def test_findings_reach_stderr_and_trace(self) -> None:
        """Typo is visible: one stderr line plus a non-authoritative trace row with a stable reason code."""
        _, findings = load_config(self.write("wiki_pth: x\n"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            report_findings(findings)
        self.assertIn("config_unknown_key:wiki_pth", err.getvalue())
        rows = [json.loads(line) for line in (self.loop / "S1/trace.jsonl").read_text().splitlines()]
        self.assertEqual([(r["command"], r["reason_code"]) for r in rows], [("config", "config_unknown_key")])

    def test_no_config_is_quiet(self) -> None:
        """An empty path means NO_CONFIG: defaults, no finding."""
        values, findings = load_config("")
        self.assertEqual(findings, [])
        self.assertIsNone(values["wiki_path"])


class ReaderTests(ConfigCase):
    """Re-pointed readers keep their old answers."""

    def test_machine_user_and_signatures(self) -> None:
        """A named attestor is returned; a literal null is inactive instead of the login 'null'."""
        with contextlib.redirect_stderr(io.StringIO()):
            self._machine()

    def _machine(self) -> None:
        """Body of the reader assertions, stderr muted."""
        self.assertEqual(integrity_machine_user(self.write("integrity_review:\n  machine_user: bot # x\n")), "bot")
        self.assertEqual(integrity_machine_user(self.write("integrity_review:\n  machine_user: null\n")), "")
        self.assertEqual(integrity_machine_user("/nonexistent"), "")
        self.assertTrue(require_signatures(self.write("evals:\n  require_signatures: true\n")))
        self.assertFalse(require_signatures(self.write("evals:\n  require_signatures: yes\n")))
        self.assertFalse(require_signatures(""))


class CliTests(ConfigCase):
    """resolve-config stays byte-identical; --json adds the typed view."""

    def run_cli(self, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        """Run the module entrypoint."""
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/lib/config.py"), *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )

    def repo(self, text: str) -> Path:
        """Git repo containing a config."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".coderails").mkdir()
        (root / ".coderails/workflow.config.yaml").write_text(text)
        return root

    def test_plain_unchanged_and_json(self) -> None:
        """Plain output is the raw file; --json reports path, values, defaults, unknown keys, findings."""
        text = "wiki_pth: x\nsandbox_workers: false\n"
        root = self.repo(text)
        self.assertEqual(self.run_cli("resolve-config", cwd=root).stdout, text)
        result = self.run_cli("resolve-config", "--json", cwd=root)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(sorted(data), ["defaults_applied", "findings", "path", "unknown_keys", "values"])
        self.assertEqual(data["unknown_keys"], ["wiki_pth"])
        self.assertIn("wiki_path", data["defaults_applied"])
        self.assertNotIn("sandbox_workers", data["defaults_applied"])

    def test_json_without_config(self) -> None:
        """NO_CONFIG still yields valid JSON and exit 0."""
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_cli("resolve-config", "--json", cwd=Path(temporary))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["path"], "")


class MirrorTests(unittest.TestCase):
    """The Codex package ships the same parser and schema."""

    def test_byte_identical(self) -> None:
        """Parser and schema copies must not drift."""
        for relative in ("scripts/lib/config.py", "config.schema.json"):
            with self.subTest(relative):
                self.assertEqual((ROOT / relative).read_bytes(), (CODEX / relative).read_bytes())

    def test_schema_shape(self) -> None:
        """Every key has type, default, description and a valid status; sandbox_workers is not called dead."""
        schema = json.loads((ROOT / "config.schema.json").read_text())
        self.assertIs(schema["additionalProperties"], False)

        def walk(properties: dict[str, dict[str, object]]) -> None:
            for key, spec in properties.items():
                self.assertTrue({"type", "default", "description", "status"} <= set(spec), key)
                self.assertIn(spec["status"], {"enforced_by_code", "read_by_prose_only", "unused"}, key)
                walk(spec.get("properties", {}))  # type: ignore[arg-type]

        walk(schema["properties"])
        self.assertEqual(schema["properties"]["sandbox_workers"]["status"], "read_by_prose_only")


if __name__ == "__main__":
    unittest.main()
