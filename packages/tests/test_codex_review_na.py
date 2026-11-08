"""Both real writers and the direct Codex hook enforce bounded security N/A scope."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests import test_codex_review_passes as fixture  # noqa: E402
from packages.tests.eval_artifact_fixture import write_comment  # noqa: E402
from packages.tests.test_codex_review_passes import (  # noqa: E402
    CLEAN,
    CODEX,
    POST_SHIM,
    ROOT,
    artifact,
    entry,
    git_cmd,
    review_valid,
    shim,
)


def add_context(repo: fixture.Repo, text: str = "INERT_INPUT = 'page names control access'\n") -> None:
    """Build an independent unchanged access-input canary below the authored page addition."""
    git_cmd(repo.dir, "checkout", "-q", "main")
    (repo.dir / "access-input.py").write_text(text)
    git_cmd(repo.dir, "add", ".")
    git_cmd(repo.dir, "commit", "-qm", "context baseline")
    repo.base = git_cmd(repo.dir, "rev-parse", "HEAD").strip()
    git_cmd(repo.dir, "update-ref", "refs/remotes/origin/main", repo.base)
    git_cmd(repo.dir, "checkout", "-qb", "context-pages")
    target = repo.dir / repo.touched
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("Only explanatory prose changes.\n")
    git_cmd(repo.dir, "add", ".")
    git_cmd(repo.dir, "commit", "-qm", "page addition")
    repo.sha = git_cmd(repo.dir, "rev-parse", "HEAD").strip()
    repo.eval_file = write_comment(repo.tmp, repo.sha, repo.eval_level, signing_keys=repo.keys, frozen_sha=repo.base)


class WikiPostTests(fixture.Repo):
    """Both real posting CLIs bind N/A to live immutable facts and preserve the companion."""

    touched = "hooks/page.md"
    post = fixture.PostTests.post

    def scope_file(self: fixture.Repo, provider: str) -> Path:
        """Run the real prep CLI and add the reviewer's complete no-consumer assessment."""
        log = self.tmp / "gh.log"
        log.write_text("")
        env = {
            **os.environ,
            "PATH": f"{shim(self.tmp, POST_SHIM)}{os.pathsep}{os.environ['PATH']}",
            "FAKE_LOG": str(log),
            "FAKE_SHA": self.sha,
            "FAKE_BASES": json.dumps([self.base]),
        }
        script = (CODEX if provider == "codex" else ROOT) / "scripts/post_review.py"
        result = subprocess.run(
            [sys.executable, str(script), "na-scope", "12"], cwd=self.dir, env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        prepared = json.loads(result.stdout)
        self.assertEqual(prepared["binding"]["base_sha"], self.base)
        self.assertEqual(prepared["inventory"][0]["status"], "A")
        scope: dict[str, Any] = {
            "boundary": "standalone_wiki_prose_v3",
            "binding": prepared["binding"],
            "repository_purpose": "Standalone prose wiki.",
            "consumer_scope": {
                "complete": True,
                "effect_state": "effect_free",
                "references": [
                    {
                        "paths": ["README.md"],
                        "base_change_assessment": None,
                        "effect_state": "effect_free",
                        "assessment": "The unchanged README only displays explanatory prose.",
                    }
                ],
                "unresolved": [],
                "assessment": "No code, config or instruction consumer exists here; all page operations are inert.",
            },
        }
        path = self.tmp / "na.md"
        path.write_text("## Not applicable\n\n```json\n" + json.dumps(scope) + "\n```\n")
        return path

    def test_both_writers_post_and_reuse_the_same_valid_scope_pair(self) -> None:
        """The new enum is derived from text; only the unmodified ordinary companion reaches the server."""
        clean = self.tmp / "clean.md"
        clean.write_text(CLEAN)
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider):
                na = self.scope_file(provider)
                # The shim models a new API destination for each provider run.
                for old in (self.tmp / "posted.md", self.tmp / "posted.md.companion"):
                    old.unlink(missing_ok=True)
                result, _, posted = self.post(
                    "12", "--summary", str(clean), "--pass", f"security-review={na}", provider=provider
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                passes = json.loads(
                    posted.read_text()
                    .splitlines()[1]
                    .removeprefix("<!-- coderails-review-passes v1 ")
                    .removesuffix(" -->")
                )["passes"]
                self.assertEqual(passes[1]["verdict"], "not_applicable")
                self.assertEqual(set(passes[1]), {"name", "verdict", "blocking", "summary_sha256"})
                companion = posted.with_name(posted.name + ".companion").read_text()
                self.assertTrue(review_valid(companion, 12, self.sha))
                comments = [
                    {"body": value, "author": "me", "url": str(index), "created": "t"}
                    for index, value in enumerate((posted.read_text(), companion))
                ]
                reused, log, _ = self.post(
                    "12",
                    "--summary",
                    str(clean),
                    "--pass",
                    f"security-review={na}",
                    provider=provider,
                    comments=comments,
                )
                self.assertEqual(reused.returncode, 0, reused.stderr)
                self.assertIn("Existing:", reused.stdout)
                self.assertFalse(any("-F" in json.loads(line) for line in log.read_text().splitlines()))

    def test_both_writers_refuse_base_movement_before_each_write_and_reuse(self) -> None:
        """A base-only unrelated change invalidates the old binding, without writing a comment first."""
        clean = self.tmp / "clean.md"
        clean.write_text(CLEAN)
        for provider in ("claude", "codex"):
            na = self.scope_file(provider)
            git_cmd(self.dir, "checkout", "-q", "main")
            (self.dir / "README.md").write_text(provider)
            git_cmd(self.dir, "commit", "-qam", "unrelated base")
            moved = git_cmd(self.dir, "rev-parse", "HEAD").strip()
            git_cmd(self.dir, "checkout", "-q", "feature/x")
            for tips, posted_count in (([moved], 0), ([self.base, moved], 0), ([self.base, self.base, moved], 1)):
                with self.subTest(provider=provider, tips=tips):
                    result, log, _ = self.post(
                        "12", "--summary", str(clean), "--pass", f"security-review={na}", provider=provider, bases=tips
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("stale", result.stderr)
                    self.assertEqual(
                        sum("-F" in json.loads(line) for line in log.read_text().splitlines()), posted_count
                    )

    def test_both_writers_refuse_partial_context_omission(self) -> None:
        """The API is never written when one context path is removed from an otherwise complete claim."""
        add_context(self)
        clean = self.tmp / "clean.md"
        clean.write_text(CLEAN)
        for provider in ("claude", "codex"):
            na = self.scope_file(provider)
            claim = json.loads(na.read_text().split("```json\n")[1].split("\n```")[0])
            claim["consumer_scope"]["references"][0]["paths"].append("access-input.py")
            na.write_text("## Not applicable\n```json\n" + json.dumps(claim) + "\n```\n")
            positive, _, _ = self.post(
                "12", "--summary", str(clean), "--pass", f"security-review={na}", provider=provider
            )
            self.assertEqual(positive.returncode, 0, positive.stderr)
            claim["consumer_scope"]["references"][0]["paths"].remove("access-input.py")
            na.write_text("## Not applicable\n```json\n" + json.dumps(claim) + "\n```\n")
            denied, log, _ = self.post(
                "12", "--summary", str(clean), "--pass", f"security-review={na}", provider=provider
            )
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("context coverage", denied.stderr)
            self.assertFalse(any("-F" in json.loads(line) for line in log.read_text().splitlines()))

    def test_both_writers_refuse_the_complete_oversized_body_before_posting(self) -> None:
        """A valid large general summary cannot exceed the API body limit when paired with N/A."""
        general = self.tmp / "large.md"
        general.write_text("## Critical\nNone\n## Important\n- " + "x" * 65536 + "\n## Suggestions\nNone\n")
        for provider in ("claude", "codex"):
            na = self.scope_file(provider)
            denied, log, _ = self.post(
                "12", "--summary", str(general), "--pass", f"security-review={na}", provider=provider
            )
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("65536", denied.stderr)
            self.assertFalse(any("-F" in json.loads(line) for line in log.read_text().splitlines()))

    def test_preparation_limit_includes_the_actual_cli_line_ending(self) -> None:
        """Both actual entrypoints bound emitted UTF-8 bytes, not just their upstream JSON string."""
        driver = """import json,runpy,sys
from pathlib import Path
from unittest.mock import patch
script, payload = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(script.parent.parent))
from scripts.lib import review_na
with patch.object(review_na, 'prepare', return_value=json.loads(payload.read_text())):
    sys.argv = [str(script), 'na-scope', '12']
    runpy.run_path(str(script), run_name='__main__')
"""
        # Only the upstream metadata producer is controlled; serialization and CLI output remain real.
        row: dict[str, Any] = {
            "path": "ctx/0000.md",
            "mode": "100644",
            "type": "blob",
            "blob": "a" * 40,
            "at": ["merge_base", "base", "head"],
        }

        def encode(value: object) -> bytes:
            """Encode controlled metadata independently of the production helper."""
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

        for target in (131071, 131072, 131073):
            count = (target - len(encode({"context_inventory": []})) + 1) // (len(encode(row)) + 1)
            rows = [{**row, "path": f"ctx/{index:04d}.md"} for index in range(count)]
            payload = {"context_inventory": rows}
            padding = target - len(encode(payload))
            rows[-1]["path"] += "é" * (padding // 2) + "x" * (padding % 2)
            raw = encode(payload)
            self.assertEqual(len(raw), target)
            path = self.tmp / "bounded-metadata.json"
            path.write_bytes(raw)
            for provider in (ROOT, CODEX):
                with self.subTest(provider=provider, target=target):
                    result = subprocess.run(
                        [sys.executable, "-c", driver, str(provider / "scripts/post_review.py"), str(path)],
                        capture_output=True,
                    )
                    if target == 131071:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(len(result.stdout), 131072)
                        self.assertEqual(json.loads(result.stdout), payload)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(result.stdout, b"")
                        self.assertIn(b"input byte limit", result.stderr)


class WikiHookTests(fixture.Repo):
    """The actual Codex direct publication hook independently reads a posted N/A pair."""

    touched = "hooks/page.md"
    reason = fixture.HookTests.reason
    scope_file = WikiPostTests.scope_file

    def test_direct_hook_refuses_partial_context_omission(self) -> None:
        """The real full gate recomputes coverage after a correctly hashed claim omits one consumer."""
        add_context(self)
        path = self.scope_file("codex")
        claim = json.loads(path.read_text().split("```json\n")[1].split("\n```")[0])
        claim["binding"]["pr"] = 7
        group = claim["consumer_scope"]["references"][0]
        group["paths"].append("access-input.py")
        for omit in (False, True):
            if omit:
                group["paths"].remove("access-input.py")
            text = "## Not applicable\n```json\n" + json.dumps(claim) + "\n```\n"
            digest = hashlib.sha256(text.strip().encode()).hexdigest()
            na = {"name": "security-review", "verdict": "not_applicable", "blocking": False, "summary_sha256": digest}
            given = {
                **artifact(entry("review-pr")),
                "FAKE_PASSES": json.dumps([entry("review-pr"), na]),
                "FAKE_TAIL": CLEAN + "\n<!-- coderails-review-pass security-review -->\n" + text,
            }
            reason = self.reason(**given)
            self.assertTrue(
                reason.startswith("required_review_not_applicable_invalid:security-review") if omit else not reason,
                reason,
            )

    def test_direct_hook_accepts_bound_na_and_refuses_stale_or_nonsecurity_na(self) -> None:
        """Extending the enum alone must not turn unknown dispositions into publication permission."""
        text = self.scope_file("codex").read_text().replace('"pr": 12', '"pr": 7')
        digest = hashlib.sha256(text.strip().encode()).hexdigest()
        na = {"name": "security-review", "verdict": "not_applicable", "blocking": False, "summary_sha256": digest}
        given = {
            **artifact(entry("review-pr")),
            "FAKE_PASSES": json.dumps([entry("review-pr"), na]),
            "FAKE_TAIL": CLEAN + "\n<!-- coderails-review-pass security-review -->\n" + text,
        }
        self.assertEqual(self.reason(**given), "")
        for variant in (
            {**given, "FAKE_PASSES": given["FAKE_PASSES"].replace('"not_applicable"', '"unknown"')},
            {**given, "FAKE_PASSES": given["FAKE_PASSES"].replace('"blocking": false', '"blocking": true')},
            {**given, "FAKE_TAIL": given["FAKE_TAIL"].replace('"complete": true', '"complete": false')},
            {**given, "FAKE_TAIL": given["FAKE_TAIL"].replace("pass security-review", "pass deploy-safety")},
        ):
            with self.subTest(variant=variant):
                self.assertTrue(self.reason(**variant).startswith("review_passes_malformed"))
        git_cmd(self.dir, "checkout", "-q", "main")
        (self.dir / "README.md").write_text("base moved\n")
        git_cmd(self.dir, "commit", "-qam", "base moved")
        moved = git_cmd(self.dir, "rev-parse", "HEAD").strip()
        reason = self.reason(**given, FAKE_BASE_SHA=moved)
        self.assertTrue(reason.startswith("required_review_not_applicable_invalid:security-review"), reason)


class MirrorTests(unittest.TestCase):
    """Policy and library copies are byte-identical; the security reviewer exists on both providers."""

    def test_copies_are_byte_identical(self) -> None:
        """Mirrored files must not drift between the Claude root and the Codex package."""
        for name in (
            "policy/review_policy.json",
            "scripts/lib/review_passes.py",
            "scripts/lib/review_na.py",
            "scripts/lib/review_artifact.py",
            "scripts/lib/git_common.py",
            "scripts/lib/publication_gate.py",
            "capabilities/profiles.json",
        ):
            with self.subTest(name=name):
                self.assertEqual((ROOT / name).read_bytes(), (CODEX / name).read_bytes())

    def test_security_reviewer_on_both_providers(self) -> None:
        """Agent files exist, are read-only, are profiled and are in the Codex installer's name list."""
        claude = (ROOT / "agents/security-reviewer.md").read_text()
        self.assertRegex(claude, r"(?m)^name: security-reviewer$")
        self.assertRegex(claude, r"(?m)^disallowedTools: Write, Edit, NotebookEdit$")
        header = (CODEX / "agents/security-reviewer.toml").read_text().partition('developer_instructions = """')[0]
        self.assertRegex(header, r'(?m)^name = "security-reviewer"$')
        self.assertRegex(header, r'(?m)^sandbox_mode = "read-only"$')
        for root in (ROOT, CODEX):
            profiles = json.loads((root / "capabilities/profiles.json").read_text())
            self.assertEqual(profiles["agents"]["security-reviewer"], ["repo.inspect", "diff.read"])
        self.assertIn('"security-reviewer"', (ROOT / "scripts/installer/codex.py").read_text())


if __name__ == "__main__":
    unittest.main()
