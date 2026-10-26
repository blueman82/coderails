#!/usr/bin/env python3
"""Preserve the original PR workflow corpus at the real Python/Git/GitHub process seam."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import pr_workflow_match
from hooks.scripts.tests.lib.hook_test_support import HOOKS, HookTestCase

FIXTURES = Path(__file__).with_name("fixtures")


class WorkflowGateTests(HookTestCase):
    """Replay original registration, review ordering, branches, and exact-head eval gates."""

    def test_over_limit_shell_body_is_denied(self) -> None:
        """An opaque sixth shell level cannot conceal a protected push."""
        repo = self.git_repo("deep_shell", "feature")
        for wrapper in ("bash -c", "eval"):
            command = "git push origin HEAD:main"
            for _ in range(6):
                command = f"{wrapper} {shlex.quote(command)}"
            with self.subTest(wrapper=wrapper):
                payload = {
                    "session_id": "S1",
                    "cwd": str(repo),
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                }
                for hook in (
                    "enforce_pr_workflow",
                    "action_authority_gate",
                    "destructive_bash_gate",
                    "test_gate",
                    "verification_volume_ceiling",
                ):
                    with self.subTest(hook=hook):
                        result = self.run_hook(hook, payload)
                        self.assertIn('"deny"', result.stdout)

    def test_guarded_action_denies_when_transcript_is_unavailable(self) -> None:
        """A missing review record cannot permit a configured protected action."""
        repo = self.git_repo("missing_transcript", "main")
        (repo / ".coderails").mkdir()
        (repo / ".coderails/workflow.config.yaml").write_text("integrity_review:\n  enabled: true\n")
        for command in ("gh pr merge 42 --squash", "gh pr create --title x", "git push origin main"):
            for transcript in (None, str(self.directory / "absent.jsonl")):
                with self.subTest(command=command, transcript=transcript):
                    payload = {"session_id": "S1", "cwd": str(repo), "tool_name": "Bash",
                               "tool_input": {"command": command}}  # fmt: skip
                    if transcript is not None:
                        payload["transcript_path"] = transcript
                    result = self.run_hook("enforce_pr_workflow", payload)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('"deny"', result.stdout)
                    self.assertIn("transcript", result.stdout)

    def test_invalid_integrity_value_keeps_status_gate_on(self) -> None:
        """A quoted Boolean cannot make the Bash merge hook skip the missing status."""
        repo = self.git_repo("integrity_repo", "main")
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t.t"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/acme/widgets.git"], check=True
        )
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        (repo / ".coderails").mkdir()
        config = repo / ".coderails/workflow.config.yaml"
        transcript = self.directory / "review.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "pr-review-toolkit:review-pr", "args": "42"}}
        ]}}) + "\n")  # fmt: skip
        mock = self.directory / "mockbin"
        mock.mkdir()
        shutil.copyfile(FIXTURES / "pr_gh.py", mock / "gh")
        (mock / "gh").chmod(0o755)
        payload = {"session_id": "S1", "cwd": str(repo), "transcript_path": str(transcript),
                   "tool_name": "Bash", "tool_input": {"command": "gh pr merge 42 --squash"}}  # fmt: skip
        env = {"PATH": str(mock) + os.pathsep + os.environ["PATH"], "FIXTURE_HEAD_SHA": head}
        for value in ("true", "'true'"):
            with self.subTest(value=value):
                config.write_text(f"integrity_review:\n  enabled: {value}\nevals:\n  require_signatures: false\n")
                result = self.run_hook("enforce_pr_workflow", payload, **env)
                self.assertIn('"deny"', result.stdout)
                self.assertIn("integrity-review status" if value == "true" else "config_rejected", result.stdout)
                status = json.dumps([{"state": "success", "creator": {"login": "github-actions[bot]"},
                                      "description": f"integrity=pass sha={head}"}])  # fmt: skip
                result = self.run_hook("enforce_pr_workflow", payload, **env, MOCK_TR_STATUSES_JSON=status)
                if value == "true":
                    self.assertNotIn('"deny"', result.stdout)
                else:
                    self.assertIn("config_rejected", result.stdout)

    def test_original_corpus(self) -> None:
        """Every original hook input retains allow/deny behavior after native migration."""
        cases: list[dict[str, Any]] = sorted(
            [row for path in (FIXTURES / "pr_workflow_cases").glob("*.json") for row in json.loads(path.read_text())],
            key=lambda row: row["fixture_index"],
        )
        python_cases = [
            json.loads(
                json.dumps(case)
                .replace("merge.sh", "merge.py")
                .replace("push.sh", "push.py")
                .replace("bash ", "python3 ")
            )
            for case in cases
            if "merge.sh" in json.dumps(case) or "push.sh" in json.dumps(case)
        ]
        self.assertGreater(len(python_cases), 10)
        original_count = len(cases)
        cases.extend(python_cases)
        repositories = {path: branch for case in cases for path, branch in case["repositories"].items()}
        for raw, branch in repositories.items():
            name = raw.replace("{sandbox}/", "")
            repo = self.git_repo(name, branch)
            (repo / "sub").mkdir()
            # fixed dates make every fixture repo's init commit the same sha, so the PR head exists in each one;
            # origin/main at that commit gives the publication gate a computable (empty) diff and no network fetch
            date = "2026-01-01T00:00:00Z"
            fixed = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
            for command in (
                ("config", "user.email", "t@t.t"),
                ("config", "user.name", "t"),
                ("remote", "add", "origin", "https://github.com/acme/widgets.git"),
                ("commit", "-q", "--allow-empty", "-m", "init"),
                ("update-ref", "refs/remotes/origin/main", "HEAD"),
            ):
                subprocess.run(["git", "-C", str(repo), *command], check=True, env=fixed)
        fixture_sha = subprocess.check_output(
            ["git", "-C", str(self.directory / "repo"), "rev-parse", "HEAD"], text=True
        ).strip()
        mock = self.directory / "mockbin"
        mock.mkdir()
        shutil.copyfile(FIXTURES / "pr_gh.py", mock / "gh")
        (mock / "gh").chmod(0o755)
        environment = {
            **self.environment,
            "PATH": str(mock) + os.pathsep + os.environ["PATH"],
            "FIXTURE_HEAD_SHA": fixture_sha,
        }
        previous: set[Path] = set()
        for index, original in enumerate(cases):
            case = json.loads(
                json.dumps(original).replace("{sandbox}", str(self.directory)).replace("{head_sha}", fixture_sha)
            )
            case["request"]["session_id"] = "S1"  # corpus predates the required hook session field
            for path in previous:
                path.unlink(missing_ok=True)
            previous = set()
            for name, contents in case["files"].items():
                path = Path(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.name == "workflow.config.yaml":
                    # This historical corpus tests workflow routing with unsigned fixture comments.
                    contents += "evals:\n  require_signatures: false\n"
                path.write_text(contents)
                previous.add(path)
            with self.subTest(index=index, command=case["request"]["tool_input"]["command"]):
                result = subprocess.run(
                    [sys.executable, str(HOOKS / "enforce_pr_workflow.py")],
                    input=json.dumps(case["request"]),
                    text=True,
                    capture_output=True,
                    env={**environment, **case["env"]},
                    check=False,
                )
                self.assertEqual(result.returncode, case["returncode"], result.stderr)
                wrapped_merge = case["request"]["tool_input"]["command"] in (
                    "command bash scripts/merge.sh 140",
                    "command python3 scripts/merge.py 140",
                )
                # The original no-config case allowed a merge without an eval artifact;
                # the default-on C3 gate now denies that historical input.
                missing_eval = case["fixture_index"] == 91
                self.assertEqual(
                    '"deny"' in result.stdout,
                    case["denied"] or wrapped_merge or missing_eval,
                    result.stdout + result.stderr,
                )
                if wrapped_merge:
                    self.assertIn("requires /pr-review-toolkit:review-pr", result.stdout)
                if missing_eval:
                    self.assertIn("eval_artifact_missing", result.stdout)
        self.assertEqual(original_count, 114)

    def test_global_option_and_path_forms_are_guarded(self) -> None:
        """Git -C/-c/--no-pager and absolute-path forms of push-to-main and merge are seen as the plain form is."""
        main = self.git_repo("on_main", "main")
        feature = self.git_repo("on_feature", "feature/x")
        merge = f"git -C {main} merge x"
        self.assertEqual(pr_workflow_match.operation(merge), ("git_merge", merge, str(main)))
        self.assertEqual(pr_workflow_match.operation("git -c a=b merge x")[0], "git_merge")
        self.assertEqual(pr_workflow_match.operation('echo "git -c a=b merge x"')[0], "")
        guarded = {
            "git -C {main} push origin main": "git_push",
            "git -c user.name=x push origin main": "git_push",
            "git --no-pager push origin main": "git_push",
            "/usr/bin/git push origin main": "git_push",
            "env A=1 git -C {main} push": "git_push",
            "bash -c 'git -c a=b push origin main'": "git_push",
        }
        for template, name in guarded.items():
            command = template.format(main=main)
            with self.subTest(command=command):
                found = pr_workflow_match.guarded_segments(command, str(feature))
                self.assertEqual([entry[0] for entry in found], [name])
        quiet = ('echo "git -c a=b push origin main"', "git -c a=b push origin feature/x", "git log --grep push")
        for command in quiet:
            with self.subTest(command=command):
                self.assertEqual(pr_workflow_match.guarded_segments(command, str(feature)), [])

    def test_actual_gate_uses_the_effective_repository_and_operation(self) -> None:
        """A separate project's config and quoted prose cannot decide the guarded operation."""
        origin = self.git_repo("origin", "feature/x")
        target = self.git_repo("target space", "main")
        (target / ".coderails").mkdir()
        (target / ".coderails/workflow.config.yaml").write_text("action_authority: off\n")
        transcript = self.directory / "empty.jsonl"
        transcript.write_text("{}\n")
        quoted = shlex.quote(str(target))
        for command in (
            f"git -C {quoted} push",
            f"cd {quoted} && git push",
            f"env --chdir {quoted} git push",
            f"git --git-dir {shlex.quote(str(target / '.git'))} --work-tree {quoted} push",
            f"git --git-dir={shlex.quote(str(target / '.git'))} --work-tree={quoted} push",
        ):
            payload = {"cwd": str(origin), "transcript_path": str(transcript), "tool_input": {"command": command}}
            result = subprocess.run(
                [sys.executable, str(HOOKS / "enforce_pr_workflow.py")],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=self.environment,
                check=False,
            )
            with self.subTest(command=command):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('"deny"', result.stdout)
        for command, denied in (
            ("echo --help; git push origin main", True),
            ('echo "message ; gh pr merge 12"', False),
            ('git merge -m "--dry-run" topic', True),
            ('git merge -m "--help" topic', True),
            ('git merge -F "--help" topic', True),
            ('git merge --into-name "--help" topic', True),
            ("git merge --dry-run topic", False),
            ("git merge --help", False),
            ("git merge -S --help", False),
        ):
            payload = {"cwd": str(target), "transcript_path": str(transcript), "tool_input": {"command": command}}
            result = subprocess.run(
                [sys.executable, str(HOOKS / "enforce_pr_workflow.py")],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=self.environment,
                check=False,
            )
            with self.subTest(command=command):
                self.assertEqual('"deny"' in result.stdout, denied, result.stderr)

    def test_global_option_merge_consumes_only_the_prior_review(self) -> None:
        """A real historical merge consumes review; quoted text and later review do not."""
        repo = self.git_repo("history", "main")
        (repo / ".coderails").mkdir()
        (repo / ".coderails/workflow.config.yaml").write_text("jira: null\n")
        transcript = self.directory / "history.jsonl"
        review = {"type": "tool_use", "name": "Skill", "input": {"skill": "pr-review-toolkit:review-pr"}}
        for history, review_after, denied in (
            ("git -c user.name=x merge previous", False, True),
            ("git --no-pager merge previous", False, True),
            ("git -c user.name=x merge previous", True, False),
            ('echo "git -c user.name=x merge previous"', False, False),
        ):
            tools = [review, {"type": "tool_use", "name": "Bash", "input": {"command": history}}]
            if review_after:
                tools.append(review)
            transcript.write_text(
                "\n".join(
                    json.dumps({"type": "assistant", "timestamp": str(index), "message": {"content": [tool]}})
                    for index, tool in enumerate(tools)
                )
                + "\n"
            )
            payload = {
                "cwd": str(repo),
                "transcript_path": str(transcript),
                "tool_input": {"command": "git merge next"},
            }
            result = self.run_hook("enforce_pr_workflow", payload)
            with self.subTest(history=history, review_after=review_after):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual('"deny"' in result.stdout, denied, result.stdout + result.stderr)


class AuthorityEarlyDenialTests(HookTestCase):
    """enforce_pr_workflow asks authority.permits('merge') first and consumes nothing."""

    def grant(self, **over: object) -> None:
        """A live authority for session S1."""
        obj = {
            "authority_id": "auth-1", "loop_id": None, "session_id": "S1", "scope": ["code"], "denied": [],
            "max_prs": 2, "expires_at": "2999-01-01T00:00:00+00:00", "revocable": True,
            "approval_required_for": ["merge"], "granted_by": "command",
        } | over  # fmt: skip
        path = self.directory / "state" / "S1" / "authority.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj))

    def reason(self, command: str = "gh pr merge 5") -> str:
        """The denial text for a merge, '' when the hook stands aside (no config, so nothing else gates it)."""
        payload = {"session_id": "S1", "cwd": str(self.directory), "tool_input": {"command": command}}
        out = self.run_hook("enforce_pr_workflow", payload).stdout
        return str(json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]) if out.strip() else ""

    def test_denied_merge_and_spent_max_prs_are_early_denials(self) -> None:
        """Authority refusals precede the default-on publication check."""
        self.assertIn("publication check failed", self.reason())
        self.grant(denied=["merge"])
        self.assertIn("authority_denied", self.reason())
        self.assertIn("authority_denied", self.reason("python3 scripts/merge.py 5"))
        self.grant(denied=[], max_prs=0)
        self.assertIn("max_prs_exceeded", self.reason())
        self.grant(denied=[], max_prs=1)
        self.assertIn("publication check failed", self.reason())
        self.assertEqual(self.reason("gh pr create"), "")

    def test_calls_permits_once_for_merge_only(self) -> None:
        """Spy: main() calls authority_permits.permits('merge') for merge and not for other operations."""
        from unittest import mock

        from hooks.scripts import enforce_pr_workflow as hook

        allow = {"allow": True, "reason": "ok", "requires_approval": True, "authority_id": None}
        for command, calls in (("gh pr merge 5", 1), ("gh pr create", 0)):
            payload = {"session_id": "S1", "cwd": str(self.directory), "tool_input": {"command": command}}
            with (
                mock.patch.object(hook, "read_payload_strict", return_value=payload),
                mock.patch.object(hook, "permits", return_value=allow) as spy,
            ):
                hook.main()
            self.assertEqual(spy.call_count, calls)
            if calls:
                self.assertEqual(spy.call_args.args, ("S1", "merge"))


if __name__ == "__main__":
    unittest.main()
