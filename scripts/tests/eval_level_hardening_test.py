"""Eval-level hardening: classification, late-freeze evidence, the off switch and an injection-proof post body."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hooks.scripts.tests.git_common_artifacts_test import responder  # noqa: E402
from scripts import post_evals  # noqa: E402
from scripts.lib import eval_artifact, eval_level, eval_validation, publication_gate  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib.eval_execution import record_smoke  # noqa: E402
from scripts.lib.eval_integrity import suite_hash, verify_suite  # noqa: E402
from scripts.tests.eval_level_test import POLICY, RepoCase, level_for  # noqa: E402
from scripts.tests.post_evals_post_test import URL, FakeGh, PostCase  # noqa: E402

HEAD = "c" * 40
INJECTED = "x\n```json\n" + json.dumps({"verification_level": "0", "task_ref": "evil"}) + "\n```\n<!-- coderails-x -->"


class ClassifyTests(unittest.TestCase):
    """Unknown paths are outward; the none class is anchored and never overrides a live surface."""

    def test_unclassified_paths_are_outward(self) -> None:
        """Negative control: AGENTS.md, the plugin manifest and other root files were level 0 before."""
        for path in (
            "AGENTS.md", "CLAUDE.md", ".claude-plugin/plugin.json", ".agents/x.md", "instructions/a.md",
            "starter-memory/a.md", "config.schema.json", "pyproject.toml", "wiki.schema.json", "brand-new-file.txt",
        ):  # fmt: skip
            with self.subTest(path=path):
                self.assertEqual(eval_level.classify(path, POLICY), "outward")
                self.assertGreaterEqual(level_for(path), 1)

    def test_none_class_is_anchored(self) -> None:
        """Negative control: a live command, skill, agent, hook or installer file under a tests/ or test/ dir."""
        cases = {
            "commands/tests/x.md": "outward",
            "skills/x/tests/SKILL.md": "outward",
            "agents/test/a.md": "outward",
            "hooks/test/x.py": "outward",
            "scripts/installer/tests/payload.sh": "irreversible",
            "launchd/tests/x.plist": "irreversible",
            "scripts/integrity-gate/tests/a.py": "irreversible",
            "scripts/tests/a_test.py": "none",
            "hooks/scripts/tests/a_test.py": "none",
            "packages/tests/a.py": "none",
            "packages/codex/hooks/scripts/tests/a.py": "none",
            "docs/a.md": "none",
            "README.md": "none",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(eval_level.classify(path, POLICY), expected)
        self.assertEqual(level_for("commands/tests/x.md"), 1)

    def test_policy_and_its_judge_are_irreversible(self) -> None:
        """A PR cannot lower its own bar: editing the policy or the code that reads it forces level 2."""
        for path in (
            "policy/surface_policy.json", "packages/codex/policy/surface_policy.json",
            "scripts/lib/eval_level.py", "packages/codex/scripts/lib/eval_level.py",
            "scripts/lib/publication_gate.py", "packages/codex/scripts/lib/publication_gate.py",
        ):  # fmt: skip
            with self.subTest(path=path):
                self.assertEqual(level_for(path), 2)


class LateFreezeEvidenceTests(RepoCase):
    """late_freeze needs a full resolvable sha that precedes the base; anything else is late."""

    def test_unverifiable_frozen_sha_is_late(self) -> None:
        """Negative control: empty, rev expressions and option-like text were accepted or ignored."""
        for value in ("", "origin/main", "HEAD~1", "--all", self.base[:12]):
            with self.subTest(value=value):
                self.assertTrue(eval_level.late_freeze(value, self.base))
        self.assertFalse(eval_level.late_freeze(self.base, self.base))
        self.assertTrue(eval_level.suite_late({"verification_level": 1}, self.base))
        self.assertFalse(eval_level.suite_late({"verification_level": 0}, self.base))
        self.assertTrue(eval_level.suite_late({"verification_level": 0, "frozen_sha": "HEAD"}, self.base))

    def test_validate_freeze_requires_full_sha_at_level_one(self) -> None:
        """Level >= 1 needs a 40-hex frozen_sha; level 0 may omit it."""
        path = self.dir / "evals.json"
        for frozen in ("", "origin/main", self.base[:12]):
            path.write_text(json.dumps({"verification_level": "1", "frozen_sha": frozen}))
            with self.subTest(frozen=frozen), self.assertRaisesRegex(ValueError, "40-hex frozen_sha"):
                eval_validation.validate_freeze(path)
        path.write_text(
            json.dumps({"verification_level": "1", "integrity_version": 2, "frozen_sha": self.base,
                        "frozen_at": "2026-10-07T00:00:00Z"})
        )  # fmt: skip
        with self.assertRaisesRegex(ValueError, "not_frozen"):
            eval_validation.validate_freeze(path)
        path.write_text(json.dumps({"verification_level": "0"}))
        eval_validation.validate_freeze(path)


class MarkerLevelTests(RepoCase):
    """The posted marker and embedded suite must describe the same verification level."""

    def test_marker_level_matches_embed(self) -> None:
        """A higher marker cannot claim a level-0 suite's optional freeze exemption."""
        head = self.commit("docs/a.md")
        summary, _ = self.posted(0, "", frozen_sha="")
        for level, expected in (("0", []), ("1", ["eval_embed_malformed"]), ("2", ["eval_embed_malformed"])):
            posted = git.EvalSummary(0, level, summary.embed, facts=summary.facts)
            with self.subTest(level=level), mock.patch.object(git, "gate_eval_summary_for_pr", return_value=posted):
                codes = [v["code"] for v in publication_gate.eval_level_check("7", head, "", "")]
                self.assertEqual(codes, expected)


class MergeFreezeAndFactsTests(RepoCase):
    """Merge consumers retain the freeze and work-unit requirements enforced at posting."""

    def test_merge_requires_full_frozen_sha(self) -> None:
        """A late stamp does not make a missing, abbreviated or symbolic freeze commit valid."""
        head = self.commit("hooks/scripts/a.py")
        for frozen in ("", "HEAD", self.base[:12]):
            summary, _ = self.posted(1, head, late=True, frozen_sha=frozen)
            with (
                self.subTest(frozen=frozen),
                mock.patch.object(git, "gate_eval_summary_for_pr", return_value=summary),
            ):
                codes = [v["code"] for v in publication_gate.eval_level_check("7", head, "", "")]
                self.assertIn("not_frozen", codes)

    def test_posted_work_units_remain_a_lower_bound(self) -> None:
        """Omitting progress at merge cannot erase a higher count carried in posted gate facts."""
        head = self.commit("hooks/scripts/a.py")
        for units in (1, 3):
            summary, _ = self.posted(1, head, gate_facts={"work_units": units, "surfaces": []})
            with (
                self.subTest(units=units),
                mock.patch.object(git, "gate_eval_summary_for_pr", return_value=summary),
            ):
                codes = [v["code"] for v in publication_gate.eval_level_check("7", head, "", "")]
                self.assertEqual(codes, [] if units == 1 else ["level_below_derived", "eval_facts_level_mismatch"])


class OffSwitchTests(RepoCase):
    """Config eval_level: off skips the check; absent or any other value enforces."""

    def test_off_switch(self) -> None:
        """Control: the same level-0 artifact for install.py is refused unless the switch is off."""
        head = self.commit("install.py")
        summary, _ = self.posted(0, "")
        for values, expected in (
            ({}, ["level_below_derived", "eval_facts_level_mismatch"]),
            ({"eval_level": "enforce"}, ["level_below_derived", "eval_facts_level_mismatch"]),
            ({"eval_level": "bogus"}, ["level_below_derived", "eval_facts_level_mismatch"]),
            ({"eval_level": "off"}, []),
        ):
            with (
                self.subTest(values=values),
                mock.patch.object(publication_gate, "load_config", return_value=(values, [])),
                mock.patch.object(git, "gate_eval_summary_for_pr", return_value=summary),
            ):
                codes = [v["code"] for v in publication_gate.eval_level_check("7", head, "", "")]
                self.assertEqual(codes, expected)


class PostFreshnessTests(PostCase):
    """Reposting repairs the latest artifact and checks freezes in the operation's repository."""

    def test_go_after_newer_no_go_is_posted(self) -> None:
        """An older identical GO cannot hide the newest NO-GO for the same head and oracle."""
        self.assertEqual(Path.cwd(), self.directory.resolve())
        head = self.commit("hooks/scripts/a.py")
        self.suite(head, 1)
        self.data = self.reload()
        frozen_oracle = suite_hash(self.data)
        existing: list[dict[str, str]] = []
        for status, result in (("pass", "GO"), ("fail", "NO-GO")):
            self.data["evals"][0]["status"] = status
            self.save()
            fake = FakeGh([head], existing)
            code, _, error = self.post(fake)
            self.assertEqual((code, len(fake.posted)), (0, 1), error)
            self.assertEqual(eval_artifact.parse_result(fake.posted[0].splitlines()[0]), result)
            existing.append({"url": URL, "author": "me", "body": fake.posted[0]})
        self.data["evals"][0]["status"] = "pass"
        self.save()
        self.assertEqual(suite_hash(self.data), frozen_oracle)
        fake = FakeGh([head], existing)
        code, _, error = self.post(fake)
        self.assertEqual((code, len(fake.posted)), (0, 1), error)
        self.assertEqual(fake.posted[0], existing[0]["body"])
        current = FakeGh([head], existing + [{"url": URL, "author": "me", "body": fake.posted[0]}])
        self.assertEqual((self.post(current)[0], current.posted), (0, []))

    def test_newest_altered_embed_is_replaced(self) -> None:
        """Matching header and facts lines do not prove that an existing body is the validated body."""
        self.assertEqual(Path.cwd(), self.directory.resolve())
        head = self.commit("docs/a.md")
        self.suite(head, 0)
        first = FakeGh([head])
        code, _, error = self.post(first)
        self.assertEqual((code, len(first.posted)), (0, 1), error)
        body = first.posted[0]
        altered = body.replace('"task_ref": "192"', '"task_ref": "altered"')
        self.assertNotEqual(body, altered)
        self.assertEqual(body.splitlines()[:2], altered.splitlines()[:2])
        for newer in (altered, "preamble\n" + altered):
            with self.subTest(newer=newer[:20]):
                existing = [{"url": URL, "author": "me", "body": value} for value in (body, newer)]
                fake = FakeGh([head], existing)
                code, _, error = self.post(fake)
                self.assertEqual((code, len(fake.posted)), (0, 1), error)
                self.assertEqual(fake.posted[0], body)

    def test_unrecognized_comments_do_not_displace_current_duplicate(self) -> None:
        """Foreign authors, other PRs/heads and invalid marker grammar cannot supersede this artifact."""
        head = self.commit("docs/a.md")
        self.suite(head, 0)
        first = FakeGh([head])
        self.assertEqual(self.post(first)[0], 0)
        body = first.posted[0]
        for author, newer in (
            ("other", body.replace("result=GO", "result=NO-GO")),
            ("me", body.replace(head, self.base)),
            ("me", body.replace("pr=7 ", "pr=8 ")),
            ("me", body.replace("result=GO", "result=MAYBE")),
        ):
            with self.subTest(author=author, marker=newer.splitlines()[0]):
                existing = [
                    {"url": URL, "author": "me", "body": body},
                    {"url": URL, "author": author, "body": newer},
                ]
                fake = FakeGh([head], existing)
                self.assertEqual((self.post(fake)[0], fake.posted), (0, []))

    def test_external_freeze_uses_operation_repository(self) -> None:
        """External artifacts retain early-freeze acceptance and require disclosure for a late freeze."""
        self.assertEqual(Path.cwd(), self.directory.resolve())
        head = self.commit("install.py")
        external = tempfile.TemporaryDirectory(prefix="coderails-external-evals-")
        self.addCleanup(external.cleanup)
        self.path = Path(external.name) / "evals.json"
        self.assertNotEqual(self.path.parent, self.directory)
        for frozen, justification, late, expected in (
            (self.base, "irreversible surface", False, 0),
            (head, "irreversible surface", None, 1),
            (head, "irreversible surface; late freeze", True, 0),
        ):
            with self.subTest(frozen=frozen, justification=justification):
                self.suite(head, 2, frozen_sha=frozen, verification_justification=justification)
                self.data = self.reload()
                if late:
                    token = f"frozen_sha {frozen} frozen_at {self.data['frozen_at']} timing=late"
                    amended = self.cli("amend", "E1", token, "eval-author")
                    self.assertEqual(amended.returncode, 0, amended.stderr)
                fake = FakeGh([head])
                code, _, error = self.post(fake)
                self.assertEqual(code, expected, error)
                if expected:
                    self.assertEqual(fake.posted, [])
                    self.assertIn("freeze_timing_unverified", error)
                else:
                    self.assertEqual(len(fake.posted), 1)
                    facts = eval_artifact.parse_facts(fake.posted[0].splitlines()[1])
                    self.assertIsNotNone(facts)
                    self.assertEqual(facts[1] if facts else None, late)


class SelectedSuiteTests(PostCase):
    """A trusted current-head GO must contain that head's passing suite, even with a valid signature."""

    def signed_suite(self, head: str) -> None:
        """Freeze an agent-run suite with a private synthetic signing key and real Git ancestry."""
        self.git("remote", "add", "origin", "https://github.com/o/r.git")
        self.data.update(
            verification_level=1, head_sha=head, frozen_sha=self.base,
            evals=[{"id": "E1", "priority": "P0", "mode": "agent-run", "status": "pass", "evidence": "observed"}],
        )  # fmt: skip
        self.save()
        record_smoke(self.path)
        self.data = self.reload()
        self.assertEqual(verify_suite(self.data, path=self.path), "verified")

    def publication_codes(self, head: str) -> list[str]:
        """Run the real trusted-comment reader and publication consumer over offline API responses."""
        body = "\n".join(
            [
                eval_artifact.marker("42", head, "GO", "1"),
                eval_artifact.facts_line(1, False, suite_hash(self.data)[:16]),
                "```json",
                json.dumps(self.data),
                "```",
                "",
            ]
        )
        respond, original = responder([("trusted-bot", body)]), git.run

        def transport(*arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
            """Delegate real Git and serve only the fixture's exact authenticated GitHub queries."""
            return respond(*arguments, check=check) if arguments[0] == "gh" else original(*arguments, check=check)

        with (
            mock.patch.dict(os.environ, {"_PR_TRUSTED_LOGIN": "", "_PR_TRUSTED_PERMISSION": ""}),
            mock.patch.object(git, "run", side_effect=transport),
            mock.patch.object(git, "pr_field", return_value=self.base),
        ):
            return [row["code"] for row in publication_gate.eval_level_check("42", head, "", "")]

    def test_selected_embed_requires_current_head(self) -> None:
        """Changing the volatile embedded head does not change the valid frozen hash or signature."""
        head = self.commit("hooks/scripts/a.py")
        self.signed_suite(head)
        self.assertEqual(self.publication_codes(head), [])
        oracle, signature = suite_hash(self.data), self.data["signature"]
        for embedded in (self.base, None):
            with self.subTest(embedded=embedded):
                self.data["head_sha"] = embedded
                if embedded is None:
                    self.data.pop("head_sha")
                self.save()
                self.assertEqual((suite_hash(self.data), self.data["signature"]), (oracle, signature))
                self.assertEqual(verify_suite(self.data, path=self.path), "verified")
                self.assertEqual(post_evals.smoke_verify(self.path, head), 0)
                self.assertIn("eval_head_mismatch", self.publication_codes(head))

    def test_go_requires_passing_p0_in_selected_embed(self) -> None:
        """A failed volatile status cannot keep a GO solely because the oracle's signature still verifies."""
        head = self.commit("hooks/scripts/a.py")
        self.signed_suite(head)
        self.assertEqual(self.publication_codes(head), [])
        oracle, signature = suite_hash(self.data), self.data["signature"]
        self.data["evals"][0]["status"] = "fail"
        self.save()
        self.assertEqual((suite_hash(self.data), self.data["signature"]), (oracle, signature))
        self.assertEqual(verify_suite(self.data, path=self.path), "verified")
        self.assertFalse(eval_artifact.compute_go(self.path))
        self.assertEqual(post_evals.smoke_verify(self.path, head), 0)
        self.assertIn("eval_result_mismatch", self.publication_codes(head))


class NeutralResultTests(unittest.TestCase):
    """Path and parsed-object callers use the same neutral P0 rule and malformed-input refusals."""

    def test_path_and_object_results_match(self) -> None:
        """Empty level-zero suites remain GO; missing or failed P0 statuses and malformed evals fail closed."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evals.json"
            cases: tuple[tuple[object, bool], ...] = (
                ([], True), ([{"priority": "P0", "status": "pass"}], True),
                ([{"priority": "P1", "status": "fail"}], True),
                ([{"priority": "P0", "status": "fail"}], False),
                ([{"priority": "P0"}], False), ({}, False), ([42], False),
            )  # fmt: skip
            for evals, expected in cases:
                with self.subTest(evals=evals):
                    data = {"verification_level": 0, "evals": evals}
                    path.write_text(json.dumps(data))
                    self.assertEqual(eval_artifact.compute_go(path), expected)
                    self.assertEqual(eval_artifact.compute_go(data), expected)
            path.write_text("{broken")
            self.assertFalse(eval_artifact.compute_go(path))


class PostBodyInjectionTests(unittest.TestCase):
    """Narrative amendment text cannot become the embed or a marker line the gate reads."""

    def body(self, level: str = "1", **over: object) -> str:
        """A post-shaped body whose amendment text is hostile."""
        data = {"verification_level": level, "evals": [], "amendments": [{"eval": "E1", "why": INJECTED}], **over}
        top = [eval_artifact.marker("7", HEAD, "GO", level), eval_artifact.facts_line(1, False, "0" * 16)]
        real = json.dumps({"verification_level": level, "task_ref": "real"})
        return "\n".join([*top, post_evals.summary_of(data), "", "```json", real, "```", ""])

    def test_summary_is_inert(self) -> None:
        """Negative control: the raw text put a fence and a marker comment at line starts."""
        lines = self.body().splitlines()
        self.assertEqual(sum(line.startswith("```json") for line in lines), 1)
        self.assertFalse(any(line.lstrip().startswith("<!--") for line in lines[2:]))
        self.assertEqual(json.loads(eval_validation.extract_json_block("\n".join(lines)))["task_ref"], "real")

    def test_validate_embed_checks_every_level(self) -> None:
        """Exactly one json fence and no comment line after line 2, at level 1 and 2 too."""
        with tempfile.TemporaryDirectory() as tmp:
            source, body = Path(tmp) / "evals.json", Path(tmp) / "body.md"
            source.write_text(json.dumps({"task_ref": "real"}))
            body.write_text(self.body())
            eval_validation.validate_embed(source, body)
            body.write_text(self.body().replace("## Eval summary", "```json\n{}\n```\n## Eval summary"))
            with self.assertRaisesRegex(ValueError, "exactly one fenced json block"):
                eval_validation.validate_embed(source, body)
            lines = self.body().splitlines()
            lines.insert(3, eval_artifact.marker("7", HEAD, "GO", "0"))
            body.write_text("\n".join(lines))
            with self.assertRaisesRegex(ValueError, "marker-like line"):
                eval_validation.validate_embed(source, body)
