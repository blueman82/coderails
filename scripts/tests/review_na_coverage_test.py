"""Independent E3 canaries for complete context and bounded inspection records."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests import test_codex_review_na as wire  # noqa: E402
from packages.tests import test_codex_review_passes as transport  # noqa: E402
from scripts.lib import review_na, review_passes  # noqa: E402
from scripts.tests import review_na_test as fixture  # noqa: E402


class ContextCoverageTests(fixture.WikiNaTests):
    """Use real inert Git objects; never load fixture programs as Python."""

    def add_context(self) -> None:
        """Add two known unchanged inputs below the authored page change."""
        old_head = self.head
        self.git("checkout", "-q", "main")
        for path, text in {
            "notes/index.md": "A plain index.\n",
            "tools/access.py": "INERT_ACCESS_INPUT = 'page'\n",
        }.items():
            target = self.directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git("add", ".")
        self.git("commit", "-qm", "context baseline")
        self.base = self.live_base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-qb", "context-pages")
        self.git("cherry-pick", old_head)
        self.head = self.git("rev-parse", "HEAD").strip()

    def test_partial_omission_fails_while_the_complete_mixed_context_passes(self) -> None:
        """Two correct retained paths cannot conceal an omitted third consumer."""
        self.add_context()
        claim = self.scope()
        group = claim["consumer_scope"]["references"][0]
        group["paths"] += ["notes/index.md", "tools/access.py"]
        try:
            review_na.validate(claim, "7", self.head)
        except ValueError as error:
            self.fail(f"complete v3 sibling refused: {error}")
        facts = review_na.prepare("7", self.head)
        self.assertEqual(
            {row["path"] for row in facts["context_inventory"]},
            {".obsidian/plugins/view/main.js", "notes/index.md", "tools/access.py"},
        )
        group["paths"].remove("tools/access.py")
        with self.assertRaisesRegex(ValueError, "context.*coverage"):
            review_na.validate(claim, "7", self.head)

    def test_duplicate_foreign_pattern_and_empty_groups_refuse(self) -> None:
        """Coverage is an exact set, rather than a count or a nonempty-array check."""
        claim = self.scope()
        review_na.validate(claim, "7", self.head)
        for paths in ([], ["*"], ["elsewhere.md"], [".obsidian/plugins/view/main.js"] * 2):
            bad = copy.deepcopy(claim)
            bad["consumer_scope"]["references"][0]["paths"] = paths
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                review_na.validate(bad, "7", self.head)

    def test_context_digest_and_base_change_groups_bind_actual_entries(self) -> None:
        """A group cannot mix an unchanged entry with a base-only changed entry."""
        self.add_context()
        original = self.scope()
        original["consumer_scope"]["references"][0]["paths"] += ["notes/index.md", "tools/access.py"]
        review_na.validate(original, "7", self.head)
        bad = copy.deepcopy(original)
        bad["binding"]["context_inventory_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "stale"):
            review_na.validate(bad, "7", self.head)
        self.git("checkout", "-q", "main")
        (self.directory / "notes/index.md").write_text("New plain index.\n")
        self.git("commit", "-qam", "new base index")
        self.live_base = self.git("rev-parse", "HEAD").strip()
        fresh = self.scope()
        group = fresh["consumer_scope"]["references"][0]
        group["paths"] += ["notes/index.md", "tools/access.py"]
        for reasoning in (None, "Inspected base change; only display wording changed."):
            group["base_change_assessment"] = reasoning
            with self.assertRaisesRegex(ValueError, "base change"):
                review_na.validate(fresh, "7", self.head)
        group["paths"].remove("notes/index.md")
        group["base_change_assessment"] = None
        fresh["consumer_scope"]["references"].append(
            {
                "paths": ["notes/index.md"],
                "effect_state": "effect_free",
                "base_change_assessment": "Inspected base change; only display wording changed.",
                "assessment": "Actual base/head entries display prose only.",
            }
        )
        review_na.validate(fresh, "7", self.head)

    def test_403_path_context_fits_comment_and_uses_bounded_git_processes(self) -> None:
        """The real 426-entry shape needs a fixed number of object processes, not one for each path."""
        old_head = self.head
        self.git("checkout", "-q", "main")
        paths = [".obsidian/plugins/view/main.js"]
        lengths = [42] * 402
        lengths[0] = 84
        for index in range(1, 143):
            lengths[index] += 1
        for index, length in enumerate(lengths):
            prefix, suffix = f"notes/item-{index:03d}/", "/page.md"
            path = prefix + "x" * (length - len(prefix) - len(suffix)) + suffix
            paths.append(path)
            target = self.directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"Unique inert context {index}.\n")
        for index in range(20):
            (self.directory / f"hooks/extra-{index:02d}.md").write_text(f"Before {index}.\n")
        self.git("add", ".")
        self.git("commit", "-qm", "large context baseline")
        self.base = self.live_base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-qb", "large-pages")
        self.git("cherry-pick", old_head)
        for index in range(18):
            (self.directory / f"hooks/extra-{index:02d}.md").write_text(f"After {index}.\n")
        for index in (18, 19):
            (self.directory / f"hooks/extra-{index:02d}.md").unlink()
            (self.directory / f"commands/added-{index}.md").write_text("New prose.\n")
        self.git("add", ".")
        self.git("commit", "-qm", "large authored prose change")
        self.head = self.git("rev-parse", "HEAD").strip()
        claim = self.scope()
        claim["consumer_scope"]["references"][0]["paths"] = paths
        self.assertEqual(len(json.dumps(paths, separators=(",", ":"))), 18308)
        self.assertEqual(max(map(len, paths)), 84)
        real_run = subprocess.run
        with mock.patch.object(subprocess, "run", wraps=real_run) as observed:
            review_na.validate(claim, "7", self.head)
        commands = [list(call.args[0]) for call in observed.call_args_list]
        self.assertLessEqual(sum("ls-tree" in argv for argv in commands), 3)
        self.assertEqual(sum("--batch-check" in argv for argv in commands), 1)
        prepared = review_na.prepare("7", self.head)
        self.assertEqual(len(prepared["inventory"]), 26)
        self.assertEqual(len(prepared["context_inventory"]), 403)
        self.assertEqual(len(self.git("ls-tree", "-r", self.head).splitlines()), 426)
        text = fixture.na_summary(claim)
        body = review_passes.tail([("review-pr", "## No findings\n"), ("security-review", text)])
        self.assertLess(len(body) + 1024, 65536)
        review_na.check_comment_bodies(body)
        with self.assertRaises(ValueError):
            review_na.check_comment_bodies(body + "x" * 65536)
        self.assertLess(len(review_na.preparation_json("7").encode()), 131072)

    def test_malformed_effect_states_and_old_boundaries_do_not_gain_permission(self) -> None:
        """Only explicit affirmative declarations work; no legacy form receives inferred fields."""
        original = self.scope()
        states: list[object] = [True, 1, "", "inert", [], {"effect_free": True}]
        for location in ("scope", "group"):
            for state in states:
                claim = copy.deepcopy(original)
                consumers = claim["consumer_scope"]
                target = consumers if location == "scope" else consumers["references"][0]
                target["effect_state"] = state
                with self.subTest(location=location, state=state), self.assertRaises(ValueError):
                    review_passes.validate_summary_text(fixture.na_summary(claim), name="security-review")
        for boundary in ("standalone_wiki_prose_v1", "standalone_wiki_prose_v2"):
            claim = copy.deepcopy(original)
            claim["boundary"] = boundary
            with self.subTest(boundary=boundary), self.assertRaises(ValueError):
                review_passes.validate_summary_text(fixture.na_summary(claim), name="security-review")

    def test_input_limits_refuse_instead_of_truncating(self) -> None:
        """Oversized structured input and complete metadata cannot silently lose coverage."""
        claim = self.scope()
        claim["repository_purpose"] = "x" * 131072
        with self.assertRaisesRegex(ValueError, "input byte limit"):
            review_passes.validate_summary_text(fixture.na_summary(claim), name="security-review")
        with (
            mock.patch.object(review_na, "prepare", return_value={"context_inventory": ["x" * 131072]}),
            self.assertRaisesRegex(ValueError, "input byte limit"),
        ):
            review_na.preparation_json("7")


class EffectDeclarationTests(transport.Repo):
    """A complete context list cannot waive an applicable known effect or an unknown decision."""

    touched = "hooks/page.md"
    post = transport.PostTests.post
    reason = transport.HookTests.reason
    scope_file = wire.WikiPostTests.scope_file

    def check_declared_scope(self, claim: dict[str, Any], *, allowed: bool) -> None:
        """Use both real writers, both complete publication libraries and the direct Codex hook."""
        clean, path = self.tmp / "clean.md", self.tmp / "effect.md"
        clean.write_text(transport.CLEAN)
        text = "## Not applicable\n```json\n" + json.dumps(claim) + "\n```\n"
        path.write_text(text)
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider, allowed=allowed):
                result, log, _ = self.post(
                    "12", "--summary", str(clean), "--pass", f"security-review={path}", provider=provider
                )
                self.assertEqual(result.returncode == 0, allowed, result.stderr)
                if not allowed:
                    self.assertFalse(any("-F" in json.loads(line) for line in log.read_text().splitlines()))
        claim = copy.deepcopy(claim)
        claim["binding"]["pr"] = 7
        text = "## Not applicable\n```json\n" + json.dumps(claim) + "\n```\n"
        na = {
            "name": "security-review",
            "verdict": "not_applicable",
            "blocking": False,
            "summary_sha256": hashlib.sha256(text.strip().encode()).hexdigest(),
        }
        given = {
            **transport.artifact(transport.entry("review-pr")),
            "FAKE_PASSES": json.dumps([transport.entry("review-pr"), na]),
            "FAKE_TAIL": transport.CLEAN + "\n<!-- coderails-review-pass security-review -->\n" + text,
        }
        self.assertEqual(not self.reason(**given), allowed)
        env = {
            **os.environ,
            **given,
            "PATH": f"{transport.shim(self.tmp, transport.HOOK_SHIM)}{os.pathsep}{os.environ['PATH']}",
            "FAKE_SHA": self.sha,
            "FAKE_BASE_SHA": self.base,
            "FAKE_EVAL_FILE": str(self.eval_file),
            "CODERAILS_KEYS_DIR": str(self.keys),
            "CODERAILS_PUBLICATION_SESSION_ID": "s",
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.tmp / "loops"),
        }
        driver = """import json,sys
from scripts.lib import publication_gate
print(json.dumps(publication_gate.evaluate('7',sys.argv[1])))
"""
        for root in (transport.ROOT, transport.CODEX):
            result = subprocess.run(
                [sys.executable, "-c", driver, self.sha],
                cwd=self.dir,
                env={**env, "PYTHONPATH": str(root)},
                text=True,
                capture_output=True,
                check=True,
            )
            violations = json.loads(result.stdout)
            self.assertEqual(not violations, allowed, (root, violations))
            if not allowed:
                self.assertTrue(
                    any(item["code"].startswith("review_passes_malformed") for item in violations), violations
                )

    def test_missing_or_unknown_scope_and_group_decisions_refuse(self) -> None:
        """Neither a legacy form nor a complete list with no affirmative decision can waive inspection."""
        path = self.scope_file("claude")
        original = json.loads(path.read_text().split("```json\n")[1].split("\n```")[0])
        self.check_declared_scope(original, allowed=True)
        for location in ("scope", "group"):
            for state in (None, "unknown"):
                claim = copy.deepcopy(original)
                consumers = claim["consumer_scope"]
                target = consumers if location == "scope" else consumers["references"][0]
                if state is None:
                    target.pop("effect_state", None)
                else:
                    target["effect_state"] = state
                with self.subTest(location=location, state=state):
                    self.check_declared_scope(claim, allowed=False)

    def test_known_execution_access_and_instruction_effects_refuse(self) -> None:
        """Known effects remain applicable even with complete coverage and no unresolved reads."""
        programs = {
            "execution": "def consume(page):\n    exec(page.read_text())\n",
            "access": "def allowed(account, page):\n    return account in page.read_text().splitlines()\n",
            "instruction": "def instructions(page):\n    return {'role': 'system', 'content': page.read_text()}\n",
        }
        for kind, program in programs.items():
            with self.subTest(kind=kind):
                if kind != "execution":
                    git = transport.git_cmd
                    git(self.dir, "checkout", "-q", "main")
                    git(self.dir, "branch", "-D", "context-pages")
                wire.add_context(self, program)
                path = self.scope_file("claude")
                original = json.loads(path.read_text().split("```json\n")[1].split("\n```")[0])
                consumers = original["consumer_scope"]
                consumers["references"][0]["paths"].append("access-input.py")
                consumers["assessment"] = f"The unchanged program has a known {kind} effect through this page."
                consumers["references"][0]["assessment"] = consumers["assessment"]
                for location in ("scope", "group"):
                    claim = copy.deepcopy(original)
                    target = claim["consumer_scope"]
                    if location == "group":
                        target = target["references"][0]
                    target["effect_state"] = "active"
                    with self.subTest(location=location):
                        self.check_declared_scope(claim, allowed=False)


if __name__ == "__main__":
    import unittest

    unittest.main()
