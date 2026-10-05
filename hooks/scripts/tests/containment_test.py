"""Worker containment resolve(): the sandbox_workers key is read by code, with exact modes and reason codes."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib.config import load_config
from scripts.lib.containment_counters import containment_summary
from scripts.sandbox import containment

ROOT = Path(__file__).resolve().parents[3]
TOOLS = {"sandbox-exec", "bwrap", "rg", "npx"}


def which(name: str) -> str | None:
    """Pretend every sandbox tool is installed."""
    return f"/fixture/{name}" if name in TOOLS else None


def nothing(name: str) -> None:
    """Pretend no tool is installed."""
    return None


class ResolveTableTests(unittest.TestCase):
    """sandbox_workers true/false/absent x runtime present/absent x credential present/absent."""

    def setUp(self) -> None:
        """A repo-less project directory and a private home."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.project = self.root / "project"
        for path in (self.home, self.project):
            path.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)  # config discovery stops at a repo root

    def provision(self, runtime: bool, credential: bool, mode: int = 0o600) -> None:
        """Create the pinned runtime cache and/or the owner credential file."""
        if runtime:
            manifest = self.home / ".npm/_npx/abc/node_modules/@anthropic-ai/sandbox-runtime/package.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"version": containment.SRT_VERSION}))
        if credential:
            path = self.home / ".coderails/worker_credential"
            path.parent.mkdir(parents=True)
            path.write_text("ANTHROPIC_API_KEY=sk-fixture\n")
            path.chmod(mode)

    def resolve(self, key: str | None, runtime: bool, credential: bool) -> tuple[str, str]:
        """Resolve for a project whose config has (or lacks) the key."""
        if key is not None:
            (self.project / ".coderails").mkdir()
            (self.project / ".coderails/workflow.config.yaml").write_text(f"sandbox_workers: {key}\n")
        self.provision(runtime, credential)
        result = containment.resolve(
            str(self.project), home=self.home, which=which if runtime else nothing, system="Darwin"
        )
        return result["mode"], result["reason_code"]

    def test_table(self) -> None:
        """Every row gives the exact mode and reason; the key defaults to true when absent."""
        cases = [
            (key, runtime, cred)
            for key in ("true", None, "false")
            for runtime in (True, False)
            for cred in (True, False)
        ]
        for key, runtime, cred in cases:
            if key == "false":
                expected = ("off", "sandbox_workers_off")
            elif not runtime:
                expected = ("fallback", "sandbox_unavailable")
            elif not cred:
                expected = ("fallback", "worker_credential_missing")
            else:
                expected = ("sandboxed", "sandboxed")
            with self.subTest(key=key, runtime=runtime, credential=cred):
                self.setUp()
                self.assertEqual(self.resolve(key, runtime, cred), expected)

    def test_default_is_true_and_enforced_by_code(self) -> None:
        """The loader default flips to true and the schema status names this reader."""
        values, findings = load_config("")
        self.assertIs(values["sandbox_workers"], True)
        self.assertEqual(findings, [])
        for relative in ("config.schema.json", "packages/codex/config.schema.json"):
            spec = json.loads((ROOT / relative).read_text())["properties"]["sandbox_workers"]
            self.assertEqual((spec["status"], spec["default"]), ("enforced_by_code", True))

    def test_loose_credential_or_missing_cache_is_not_ready(self) -> None:
        """A world-readable credential file and an uncached srt pin both keep the fallback."""
        self.provision(True, True, mode=0o644)
        result = containment.resolve(str(self.project), home=self.home, which=which, system="Darwin")
        self.assertEqual(result["reason_code"], "worker_credential_missing")
        self.setUp()
        self.provision(False, True)
        result = containment.resolve(str(self.project), home=self.home, which=which, system="Darwin")
        self.assertEqual(result["reason_code"], "sandbox_unavailable")

    def test_credential_names_are_allowlisted(self) -> None:
        """Only the two documented variables are accepted from the credential file."""
        path = self.home / ".coderails/worker_credential"
        path.parent.mkdir(parents=True)
        for text, expected in (
            ("CLAUDE_CODE_OAUTH_TOKEN=tok\n", ("CLAUDE_CODE_OAUTH_TOKEN", "tok")),
            ("GH_TOKEN=ghp_x\n", None),
            ("ANTHROPIC_API_KEY=\n", None),
        ):
            path.write_text(text)
            path.chmod(0o600)
            with self.subTest(text=text):
                self.assertEqual(containment.worker_credential(self.home), expected)

    def test_cli_prints_and_traces_the_decision(self) -> None:
        """The skill's decision point: JSON on stdout and one sandbox_launch/resolved trace row."""
        loop = self.root / "loops"
        env = {
            **os.environ,
            "HOME": str(self.home),
            "CLAUDE_AGENTIC_LOOP_DIR": str(loop),
            "CLAUDE_CODE_SESSION_ID": "s1",
        }
        done = subprocess.run(
            [sys.executable, str(ROOT / "scripts/sandbox/containment.py"), str(self.project)],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        decision = json.loads(done.stdout)
        self.assertEqual(decision["mode"], "fallback")  # a private HOME has no worker credential and no srt cache
        row = json.loads((loop / "s1/trace.jsonl").read_text().splitlines()[0])
        self.assertEqual(
            (row["command"], row["outcome"], row["reason_code"]),
            ("sandbox_launch", "resolved", decision["reason_code"]),
        )

    def test_high_risk_prefixes(self) -> None:
        """Manifest globs that can touch protected trees are high risk; an absent manifest cannot prove low risk."""
        for manifest, risky in (
            (["src/**", "docs/a.md"], False),
            (["hooks/scripts/x.py"], True),
            (["scripts/**"], True),
            (["packages/**"], True),
            (["config.schema.json"], True),
            (["*"], True),
            (["./agents/loop-worker.md"], True),
            ([], True),
        ):
            with self.subTest(manifest=manifest):
                self.assertIs(containment.is_high_risk(manifest), risky)


class CountersAndDocsTests(unittest.TestCase):
    """Counters read only trace counts; the docs name what is closed and what remains."""

    def test_summary(self) -> None:
        """Containment rows are counted by reason code; other commands are ignored."""
        rows = {
            "worker_containment/allowed/containment_fallback_low_risk": 2,
            "worker_containment/denied/containment_ack_required": 1,
            "sandbox_launch/refused/branch_import_refused": 3,
            "action_authority/allowed/receipt_consumed": 9,
        }
        counts = containment_summary(rows)
        self.assertEqual(counts["containment_fallback_low_risk"], 2)
        self.assertEqual(counts["containment_ack_required"], 1)
        self.assertEqual(counts["branch_import_refused"], 3)
        self.assertEqual(counts["worker_credential_missing"], 0)
        self.assertNotIn("receipt_consumed", counts)

    def test_sandboxed_workers_paragraph(self) -> None:
        """(f) The four closed residuals are no longer listed as open; the remaining ones are named."""
        text = (ROOT / "AGENTS.md").read_text()
        start = text.index("**Sandboxed workers")
        section = text[start : text.index("### Skills", start)]
        for closed in (
            "Primary `.git`-write residual",
            "Shared-`$TMPDIR` residual",
            "read_by_prose_only",
            "holds the operator's full",
        ):
            self.assertNotIn(closed, section)
        self.assertIsNone(re.search(r"Irreducible: `~/.claude.json`", section))
        for remaining in (
            "api.anthropic.com",
            "denyRead",
            "launcher is trusted",
            "never sandboxed",
            "sandbox_mode",
            "cooperating-agent safeguard",
        ):
            self.assertIn(remaining, section)


if __name__ == "__main__":
    unittest.main()
