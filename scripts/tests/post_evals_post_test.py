"""post_evals.py post: argument gate, derived level, oracle integrity, stamped late freeze, body shape, dedupe."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hooks.scripts.tests.lib.post_evals_fixture import ArtifactCase, entry  # noqa: E402
from scripts import post_evals  # noqa: E402
from scripts.lib import eval_artifact  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib.eval_execution import record_smoke  # noqa: E402
from scripts.lib.eval_integrity import suite_hash  # noqa: E402

URL = "https://github.com/o/r/pull/7#issuecomment-1"


class FakeGh:
    """Stand-in for git.run: gh calls are scripted, git calls run for real in the temp repository."""

    def __init__(self, heads: list[str], existing: list[dict[str, str]] | None = None) -> None:
        """Script the PR head replies and the comments already on the PR."""
        self.heads, self.existing = list(heads), existing or []
        self.calls: list[tuple[str, ...]] = []
        self.posted: list[str] = []

    def __call__(self, *argv: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        """Answer one argv list."""
        self.calls.append(argv)
        out = ""
        if argv[0] == "git":
            return subprocess.run(argv, capture_output=True, text=True, check=False)
        if argv[:3] == ("gh", "pr", "view"):
            out = self.heads.pop(0) if len(self.heads) > 1 else self.heads[0]
        elif argv[:3] == ("gh", "repo", "view"):
            out = "o/r"
        elif argv[:3] == ("gh", "api", "user"):
            out = "me"
        elif argv[0] == "gh" and argv[1] == "api" and "-F" in argv:
            self.posted.append(Path(argv[argv.index("-F") + 1].removeprefix("body=@")).read_text())
            out = json.dumps({"url": URL, "author": "me", "created": "2026-10-05T00:00:00Z"})
        elif argv[0] == "gh" and argv[1] == "api":
            out = "\n".join(json.dumps(c) for c in self.existing)
        return subprocess.CompletedProcess(argv, 0, out + "\n", "")

    def gh_calls(self) -> list[tuple[str, ...]]:
        """Every gh invocation so far."""
        return [c for c in self.calls if c[0] == "gh"]


class PostCase(ArtifactCase):
    """A temp repo with origin/main, a feature branch and a smoke-run suite."""

    stub_level_gate = False

    def setUp(self) -> None:
        """Repository and branch; the suite lives in the repository directory, untracked."""
        super().setUp()
        self.base = self.repository()
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-qb", "feature/x")
        cwd = os.getcwd()
        os.chdir(self.directory)
        self.addCleanup(os.chdir, cwd)

    def commit(self, name: str) -> str:
        """Commit one file on the branch; return the new head."""
        (self.directory / name).parent.mkdir(parents=True, exist_ok=True)
        (self.directory / name).write_text(name)
        self.git("add", name)
        self.git("commit", "-qm", name)
        return self.git("rev-parse", "HEAD")

    def suite(self, head: str, level: int, **extra: object) -> None:
        """Write the suite for this head and freeze it exactly as smoke-run does."""
        self.data.update(
            verification_level=level, head_sha=head, frozen_sha=self.base, evals=[entry()] if level else [], **extra
        )
        self.save()
        record_smoke(self.path)

    def post(self, fake: FakeGh, *arguments: str) -> tuple[int, str, str]:
        """Run main(['post', ...]) over the fake gh; returns (rc, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(git, "run", side_effect=fake), redirect_stdout(out), redirect_stderr(err):
            code = post_evals.main(["post", *(arguments or ("7", str(self.path)))])
        return code, out.getvalue(), err.getvalue()


class ArgumentGateTests(PostCase):
    """The PR number is validated in code before any gh call."""

    def test_injected_number_makes_zero_gh_calls(self) -> None:
        """'7; id' is pr_number_invalid and nothing is called."""
        fake = FakeGh(["a" * 40])
        for bad in ("7; id", "$(id)", "0", "07", "", "-1", "7 8"):
            with self.subTest(bad=bad):
                code, _, err = self.post(fake, bad, str(self.path))
                self.assertEqual(code, 1)
                self.assertIn("pr_number_invalid", err)
        self.assertEqual(fake.calls, [])

    def test_docs_have_no_arguments_recipe(self) -> None:
        """The Claude and Codex post-evals docs reduce to the call: no $ARGUMENTS in any code block."""
        for doc in ("commands/post-evals.md", "packages/codex/skills/post-evals/SKILL.md"):
            text = (REPO / doc).read_text()
            blocks = re.findall(r"```.*?```", text, re.DOTALL)
            with self.subTest(doc=doc):
                self.assertFalse([b for b in blocks if "$ARGUMENTS" in b])
                self.assertRegex(text, r"post_evals\.py[\"`>]* post ")


class LevelTests(PostCase):
    """The derived minimum level is enforced at post time."""

    def test_install_py_at_level_zero_is_refused(self) -> None:
        """Acceptance 1: an irreversible surface at level 0 is level_below_derived and nothing is posted."""
        head = self.commit("install.py")
        self.suite(head, 0)
        fake = FakeGh([head])
        code, _, err = self.post(fake)
        self.assertEqual(code, 1)
        self.assertIn("level_below_derived", err)
        self.assertEqual(fake.posted, [])

    def test_install_py_at_level_two_passes(self) -> None:
        """Negative control 1: the same PR at level 2 posts."""
        head = self.commit("install.py")
        self.suite(head, 2)
        fake = FakeGh([head])
        code, out, err = self.post(fake)
        self.assertEqual((code, len(fake.posted)), (0, 1), err)
        self.assertIn(URL, out)

    def test_self_assigned_lower_level_after_freeze_is_refused(self) -> None:
        """Negative control 2: lowering verification_level in the file after the freeze changes the oracle hash."""
        head = self.commit("install.py")
        self.suite(head, 2)
        self.data = self.reload()
        self.data["verification_level"] = 0
        self.save()
        code, _, err = self.post(FakeGh([head]))
        self.assertEqual(code, 1)
        self.assertRegex(err, "suite_hash_mismatch|level_below_derived")

    def test_three_work_units_at_level_one_is_refused(self) -> None:
        """Acceptance 1: progress.json units >= 3 force level 2 on a docs-only diff."""
        head = self.commit("docs/a.md")
        self.suite(head, 1)
        progress = self.directory / "p.json"
        progress.write_text(json.dumps({"work_units": {"1": {}, "2": {}, "3": {}}}))
        code, _, err = self.post(FakeGh([head]), "7", str(self.path), "--progress", str(progress))
        self.assertEqual(code, 1)
        self.assertIn("level_below_derived", err)

    def test_declared_facts_are_a_lower_bound_only(self) -> None:
        """Negative control 4: declared work_units 1 cannot lower the install.py minimum; 3 can raise a docs PR."""
        head = self.commit("install.py")
        self.suite(head, 1, facts={"work_units": 1, "surfaces": []})
        self.assertIn("level_below_derived", self.post(FakeGh([head]))[2])

    def test_docs_only_at_level_zero_is_accepted(self) -> None:
        """Negative control 5 / acceptance 1: docs and tests never force a level."""
        head = self.commit("docs/a.md")
        self.suite(head, 0)
        fake = FakeGh([head])
        code, _, err = self.post(fake)
        self.assertEqual((code, len(fake.posted)), (0, 1), err)


class IntegrityTests(PostCase):
    """verify_suite and frozen_hash are enforced at PR scope."""

    def level_two(self) -> str:
        """An install.py PR with a frozen level-2 suite."""
        head = self.commit("install.py")
        self.suite(head, 2)
        return head

    def test_oracle_edit_without_amend(self) -> None:
        """Acceptance 2: a cmd edited after smoke-run is suite_hash_mismatch; the untouched suite posts (control 3)."""
        head = self.level_two()
        original = self.reload()
        edited = json.loads(json.dumps(original))
        edited["evals"][0]["cmd"] = edited["evals"][0]["cmd"].replace("check", "weak")
        self.data = edited
        self.save()
        code, _, err = self.post(FakeGh([head]))
        self.assertEqual(code, 1)
        self.assertIn("suite_hash_mismatch", err)
        self.data = original
        self.save()
        fake = FakeGh([head])
        self.assertEqual((self.post(fake)[0], len(fake.posted)), (0, 1))

    def test_amendment_is_accepted(self) -> None:
        """Acceptance 2: the same edit recorded with `amend` posts."""
        head = self.level_two()
        data = self.reload()
        data["evals"][0]["cmd"] = data["evals"][0]["cmd"].replace("check", "weak")
        self.data = data
        self.save()
        self.assertEqual(post_evals.main(["amend", str(self.path), "E1", "tighten", "me"]), 0)
        self.data = self.reload()
        self.data["evals"][0]["smoke"] = {"cmd_exit": 0, "negative_control_exit": 1}
        self.save()
        fake = FakeGh([head])
        code, _, err = self.post(fake)
        self.assertEqual((code, len(fake.posted)), (0, 1), err)

    def test_stripped_frozen_hash(self) -> None:
        """Acceptance 2: deleting frozen_hash at level >= 1 is refused (not_frozen, or integrity_stripped if signed)."""
        head = self.level_two()
        data = self.reload()
        del data["frozen_hash"]
        self.data = data
        self.save()
        code, _, err = self.post(FakeGh([head]))
        self.assertEqual(code, 1)
        self.assertRegex(err, "not_frozen|integrity_stripped")


class LateFreezeTests(PostCase):
    """A freeze commit made after branching is computed late and must be disclosed, then is stamped."""

    def stamped_late(self, fake: FakeGh) -> bool | None:
        """The late_freeze value on line 2 of the first posted body, None when the line does not parse."""
        facts = eval_artifact.parse_facts(fake.posted[0].splitlines()[1])
        return None if facts is None else facts[1]

    def late_suite(self, head: str, justification: str) -> None:
        """A level-2 suite whose frozen_sha is a commit on the branch."""
        self.suite(head, 2, verification_justification=justification)
        data = self.reload()
        data["frozen_sha"] = head
        self.data = data
        self.save()

    def test_undisclosed_is_refused_and_disclosed_is_stamped(self) -> None:
        """Acceptance 3: refused with an empty disclosure; accepted with one and stamped late_freeze=1."""
        head = self.commit("install.py")
        self.late_suite(head, "2 work-units, irreversible surface")
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        self.late_suite(head, "irreversible surface; late freeze, frozen after the first commit")
        fake = FakeGh([head])
        code, _, err = self.post(fake)
        self.assertEqual((code, len(fake.posted)), (0, 1), err)
        self.assertEqual(self.stamped_late(fake), True)

    def test_on_time_freeze_is_stamped_zero(self) -> None:
        """Negative control: a freeze at the base is late_freeze=0."""
        head = self.commit("install.py")
        self.suite(head, 2)
        fake = FakeGh([head])
        self.post(fake)
        self.assertEqual(self.stamped_late(fake), False)


class BodyTests(PostCase):
    """Body shape, dedupe and stale-head handling."""

    def test_body_shape(self) -> None:
        """Line 1 is the unchanged v1 marker, line 2 the facts line, then the summary and one fenced embed."""
        head = self.commit("install.py")
        self.suite(head, 2)
        fake = FakeGh([head])
        self.assertEqual(self.post(fake)[0], 0)
        lines = fake.posted[0].splitlines()
        self.assertEqual(lines[0], eval_artifact.marker("7", head, "GO", "2"))
        derived, late, suite = eval_artifact.parse_facts(lines[1]) or (None, None, None)
        self.assertEqual((derived, late), (2, False))
        data = self.reload()
        self.assertEqual(suite, suite_hash(data)[:16])
        embed = json.loads(fake.posted[0].split("```json\n")[1].split("\n```")[0])
        self.assertEqual(
            embed["gate_facts"],
            {"work_units": 1, "surfaces": ["irreversible"], "derived_min_level": 2, "late_freeze": False,
             "suite_hash": suite_hash(data)},
        )  # fmt: skip
        self.assertEqual(fake.posted[0].count("```json"), 1)

    def test_gate_facts_cannot_be_forged_in_the_file(self) -> None:
        """A gate_facts block hand-written into evals.json is overwritten by the code-stamped one."""
        head = self.commit("install.py")
        self.suite(head, 2)
        data = self.reload()
        data["gate_facts"] = {"derived_min_level": 0, "late_freeze": False}
        self.data = data
        self.save()
        fake = FakeGh([head])
        self.post(fake)
        embed = json.loads(fake.posted[0].split("```json\n")[1].split("\n```")[0])
        self.assertEqual(embed["gate_facts"]["derived_min_level"], 2)

    def test_duplicate_is_skipped(self) -> None:
        """An identical marker and facts line already posted by this login: no second comment."""
        head = self.commit("docs/a.md")
        self.suite(head, 0)
        first = FakeGh([head])
        self.post(first)
        existing = [{"url": URL, "author": "me", "created": "t", "body": first.posted[0]}]
        second = FakeGh([head], existing)
        code, out, _ = self.post(second)
        self.assertEqual((code, second.posted), (0, []))
        self.assertIn("already posted", out)

    def test_head_moving_before_post_is_refused(self) -> None:
        """A head that changes between validation and posting is stale; nothing is posted."""
        head = self.commit("docs/a.md")
        self.suite(head, 0)
        fake = FakeGh([head, "d" * 40])
        code, _, err = self.post(fake)
        self.assertEqual((code, fake.posted), (1, []))
        self.assertIn("stale", err)


if __name__ == "__main__":
    unittest.main()
