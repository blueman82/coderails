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
    integrity_enabled,
    integrity_status_login,
    load_config,
    report_findings,
    require_signatures,
    resolve_config_json,
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
  enabled: false
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
        self.assertIs(values["integrity_review"]["enabled"], False)
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
        _, findings = load_config(self.write("integrity_review:\n  enabld: true\n"))
        self.assertEqual(findings[0]["key"], "integrity_review.enabld")
        self.assertEqual(findings[0]["hint"], "integrity_review.enabled")

    def test_legacy_integrity_login_stays_enforced_until_migration(self) -> None:
        """An installed machine-user setting cannot silently turn off the local gate."""
        path = self.write("integrity_review:\n  machine_user: attestor\n  enabled: false\n")
        _, findings = load_config(path)
        self.assertEqual(findings, [])
        self.assertTrue(integrity_enabled(path))

    def test_enum_violation_is_a_bad_value_with_closest_hint(self) -> None:
        """A string outside the property's enum is config_bad_value naming the closest allowed value."""
        values, findings = load_config(self.write("action_authority: enforse\n"))
        self.assertEqual(findings, [{"code": "config_bad_value", "key": "action_authority", "hint": "enforce"}])
        self.assertEqual(values["action_authority"], "enforse")

    def test_bad_type_keeps_raw_value(self) -> None:
        """A value of the wrong type is reported and left as written."""
        values, findings = load_config(self.write("sandbox_workers: maybe\nwiki_debt_epoch_pr: null\n"))
        self.assertEqual(self.codes(findings), ["config_bad_type", "config_bad_type"])
        self.assertEqual(values["sandbox_workers"], "maybe")
        self.assertEqual(values["wiki_debt_epoch_pr"], "null")

    def test_hash_is_comment_only_outside_quoted_or_attached_scalars(self) -> None:
        """A hash attached to a scalar remains data; whitespace-delimited hashes start comments."""
        text = 'sandbox_workers: false#suffix\naction_authority: off#suffix\nwiki_path: "vault#one" # comment\n'
        values, findings = load_config(self.write(text))
        self.assertEqual(values["sandbox_workers"], "false#suffix")
        self.assertEqual(values["action_authority"], "off#suffix")
        self.assertEqual(values["wiki_path"], "vault#one")
        self.assertEqual(
            [(item["code"], item["key"]) for item in findings],
            [("config_bad_type", "sandbox_workers"), ("config_bad_value", "action_authority")],
        )
        commented, clean = load_config(
            self.write("sandbox_workers: false # comment\naction_authority: off # comment\n")
        )
        self.assertEqual(clean, [])
        self.assertIs(commented["sandbox_workers"], False)
        self.assertEqual(commented["action_authority"], "off")
        self.assertEqual(
            config_value(self.write("action_authority: off#suffix # comment\n"), "action_authority"), "off#suffix"
        )

    def test_action_authority_enum(self) -> None:
        """The schema defaults to off; the runtime ignores unknown optional modes."""
        for value in ("enforce", "advisory", "off"):
            values, findings = load_config(self.write(f"action_authority: {value}\n"))
            self.assertEqual((values["action_authority"], findings), (value, []))
        values, findings = load_config(self.write("project: x\n"))
        self.assertEqual((values["action_authority"], findings), ("off", []))
        values, findings = load_config(self.write("action_authority: bogus\n"))
        self.assertEqual((values["action_authority"], self.codes(findings)), ("bogus", ["config_bad_value"]))
        schema = json.loads((ROOT / "config.schema.json").read_text())["properties"]["action_authority"]
        self.assertEqual((schema["status"], schema["default"]), ("enforced_by_code", "off"))

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

    def test_integrity_toggle_and_signatures(self) -> None:
        """Local status checks turn on for explicit true or invalid configured input."""
        with contextlib.redirect_stderr(io.StringIO()):
            self._readers()

    def _readers(self) -> None:
        """Body of the reader assertions, stderr muted."""
        self.assertTrue(integrity_enabled(self.write("integrity_review:\n  enabled: true # on\n")))
        self.assertEqual(integrity_status_login(self.write("integrity_review:\n  machine_user: machine\n")), "machine")
        self.assertEqual(
            integrity_status_login(self.write("integrity_review:\n  machine_user: machine\n  enabled: true\n")),
            "github-actions[bot]",
        )
        self.assertFalse(integrity_enabled(self.write("integrity_review:\n  enabled: null\n")))
        self.assertFalse(integrity_enabled(self.write("integrity_review:\n  machine_user: null\n")))
        self.assertTrue(integrity_enabled("/nonexistent"))  # a configured path that cannot be read fails closed
        self.assertFalse(integrity_enabled(""))  # no config keeps the gate inert
        self.assertTrue(require_signatures(self.write("evals:\n  require_signatures: true\n")))
        self.assertTrue(require_signatures(self.write("evals:\n  require_signatures: yes\n")))  # bad type: fail closed
        self.assertFalse(require_signatures(""))
        self.assertTrue(require_signatures(self.write("sandbox_workers: true\n")))  # default ON once a config exists
        self.assertFalse(require_signatures(self.write("evals:\n  require_signatures: false\n")))


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
        self.assertEqual(result.returncode, 1, result.stderr)  # findings: valid false and exit 1
        data = json.loads(result.stdout)
        self.assertIs(data["valid"], False)
        self.assertEqual(sorted(data), ["defaults_applied", "findings", "path", "unknown_keys", "valid", "values"])
        self.assertEqual(data["unknown_keys"], ["wiki_pth"])
        self.assertIn("wiki_path", data["defaults_applied"])
        self.assertNotIn("sandbox_workers", data["defaults_applied"])

    def test_json_clean_config_is_valid(self) -> None:
        """A clean file: valid true, exit 0, no findings."""
        result = self.run_cli("resolve-config", "--json", cwd=self.repo("sandbox_workers: false\n"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((json.loads(result.stdout)["valid"], json.loads(result.stdout)["findings"]), (True, []))

    def test_json_rejects_wrong_scalar_types_in_both_providers(self) -> None:
        """Quote marks keep strings typed as strings; bare bool and number cannot fill string keys."""
        cases = (
            ("wiki_path: true\n", "wiki_path"),
            ("diff_manifest_policy: 42\n", "diff_manifest_policy"),
            ("wiki_path: 3.14\n", "wiki_path"),
            ("wiki_path: +42\n", "wiki_path"),
            ("wiki_path: 0x2a\n", "wiki_path"),
            ("wiki_path: 1e2\n", "wiki_path"),
            ("sandbox_workers: 'false'\n", "sandbox_workers"),
            ("evals:\n  require_signatures: 'false'\n", "evals.require_signatures"),
            ("integrity_review:\n  machine_user: true\n", "integrity_review.machine_user"),
            ("wiki_path: [vault]\n", "wiki_path"),
        )
        for provider in (ROOT, CODEX):
            for source, key in cases:
                with self.subTest(provider=provider.name, source=source):
                    result = subprocess.run(
                        [sys.executable, str(provider / "scripts/lib/config.py"), "resolve-config", "--json"],
                        cwd=self.repo(source),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 1, result.stderr)
                    data = json.loads(result.stdout)
                    self.assertEqual((data["valid"], data["findings"][0]["key"]), (False, key))
                    self.assertEqual(data["findings"][0]["code"], "config_bad_type")
            for value in ("null", "true", "3.14"):
                with self.subTest(provider=provider.name, quoted=value):
                    quoted = subprocess.run(
                        [sys.executable, str(provider / "scripts/lib/config.py"), "resolve-config", "--json"],
                        cwd=self.repo(f'wiki_path: "{value}"\n'),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(quoted.returncode, 0, quoted.stderr)
                    self.assertEqual(json.loads(quoted.stdout)["values"]["wiki_path"], value)

    def test_json_rejects_mixed_scalar_list_and_mapping_shapes(self) -> None:
        """Malformed child shapes cannot turn off a Boolean control or eval signing."""
        cases = (
            "evals: false\n  require_signatures: false\n",
            "sandbox_workers: false\n  - junk\n",
            "evals:\n  require_signatures: false\n  - junk\n",
        )
        for provider in (ROOT, CODEX):
            for source in cases:
                with self.subTest(provider=provider.name, source=source):
                    result = subprocess.run(
                        [sys.executable, str(provider / "scripts/lib/config.py"), "resolve-config", "--json"],
                        cwd=self.repo(source),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 1, result.stderr)
                    data = json.loads(result.stdout)
                    self.assertFalse(data["valid"])
                    self.assertIn("config_unparseable_line", [finding["code"] for finding in data["findings"]])

    def test_json_unreadable_path_never_raises(self) -> None:
        """A discovered path that cannot be read yields JSON with a config_unreadable finding, not a traceback."""
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch("scripts.lib.config.config_path", return_value=temporary),
        ):
            data = resolve_config_json()
        self.assertEqual([f["code"] for f in data["findings"]], ["config_unreadable"])

    def test_hash_scalar_behavior_matches_both_provider_clis(self) -> None:
        """Both published config CLIs preserve attached and quoted hashes while accepting comments."""
        text = 'sandbox_workers: false#suffix\naction_authority: off#suffix\nwiki_path: "vault#one" # comment\n'
        for provider in (ROOT, CODEX):
            with self.subTest(provider=provider.name):
                root = self.repo(text)
                result = subprocess.run(
                    [sys.executable, str(provider / "scripts/lib/config.py"), "resolve-config", "--json"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(data["values"]["sandbox_workers"], "false#suffix")
                self.assertEqual(data["values"]["action_authority"], "off#suffix")
                self.assertEqual(data["values"]["wiki_path"], "vault#one")
                self.assertEqual(data["unknown_keys"], [])

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
        self.assertEqual(schema["properties"]["sandbox_workers"]["status"], "enforced_by_code")
        for key in ("action_authority", "diff_manifest", "diff_manifest_policy"):
            self.assertEqual(schema["properties"][key]["status"], "enforced_by_code", key)


if __name__ == "__main__":
    unittest.main()
