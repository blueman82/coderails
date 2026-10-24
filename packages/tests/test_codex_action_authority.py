"""Codex action-authority hook, its mirrored receipt modules, and parity with the Claude copies."""

from __future__ import annotations

import filecmp
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"
HOOKS = CODEX / "hooks/scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HOOKS))
from lib import action_match as codex_match  # noqa: E402  # isort: skip
from hooks.scripts.lib import pr_workflow_match as claude_match  # noqa: E402  # isort: skip
from hooks.scripts.tests.receipt_test_support import (  # noqa: E402  # isort: skip
    REPOSITORY,
    git,
    make_owner,
    make_repo,
    signed_receipt,
    store,
)
from scripts.lib import action_binding as ab  # noqa: E402  # isort: skip

MERGE_SHA = "f" * 40
PIN = f"--match-head-commit {MERGE_SHA}"
MERGE = f"gh pr merge 12 --squash {PIN}"
MIRRORS = (
    "scripts/lib/action_receipt.py", "scripts/lib/receipt_signing.py", "scripts/lib/action_binding.py",
    "scripts/action_receipt_cli.py", "scripts/authority_keys.py",
)  # fmt: skip

# Runs with ONLY the Codex package on sys.path, so every import resolves to packages/codex/scripts/lib.
PROBE = """
import json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.lib import action_receipt as ar, receipt_signing as rs
assert "packages/codex" in ar.__file__, ar.__file__
case = json.loads(sys.argv[2])
rec, prop, signers = case["rec"], case["prop"], Path(case["signers"])
now = datetime.now(timezone.utc)
if case["mode"] == "verify":
    print(json.dumps(ar.verify(rec, prop, now, "s1", None, signers=signers)))
else:
    base = Path(case["base"])
    r, c = ar.find_valid("s1", prop, now, None, base, True, signers)
    print(r["receipt_id"] if r else "NONE:" + c)
"""


class MirrorTests(unittest.TestCase):
    """The Codex copies of the receipt modules are the Claude files, byte for byte."""

    def test_mirrors_byte_identical(self) -> None:
        """Every mirrored file matches its Claude source."""
        for name in MIRRORS:
            with self.subTest(name):
                self.assertTrue(filecmp.cmp(ROOT / name, CODEX / name, shallow=False), name)

    def test_hook_common_has_no_vendored_receipt_code(self) -> None:
        """The vendored receipt_* functions are gone and the file is under its 400-line ceiling."""
        text = (HOOKS / "hook_common.py").read_text()
        for vendored in ("def receipt_", "RECEIPT_FIELDS", "_receipt_claim"):
            self.assertNotIn(vendored, text)
        self.assertLess(len(text.splitlines()), 400)


class CodexModuleTests(unittest.TestCase):
    """(b)-(e) through the Codex package modules only, in a child process whose path has no Claude scripts/lib."""

    tmp: tempfile.TemporaryDirectory[str]
    key: Path
    signers: Path
    agent_key: Path
    bind: dict[str, str]
    command: str

    @classmethod
    def setUpClass(cls) -> None:
        """Owner and agent keys."""
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        base = Path(cls.tmp.name)
        cls.key, cls.signers = make_owner(base / "owner")
        cls.agent_key, _ = make_owner(base / "agent")
        cls.bind = {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": "a" * 40}
        cls.command = "git push origin feature:main"

    def receipt(self, key: Path | None = None, /, **over: object) -> dict[str, Any]:
        """A signed receipt for the command."""
        return signed_receipt(key or self.key, "git_push", self.command, "/repo", "feature", self.bind, **over)

    def proposed(self, **over: object) -> dict[str, Any]:
        """The action as the Codex hook would compute it, with overrides."""
        from scripts.lib import action_receipt as claude  # the hash function is identical in the mirror

        return {**claude.proposed_action("git_push", self.command, "/repo", "feature", self.bind), **over}

    def probe(self, **case: object) -> str:
        """Run PROBE against the Codex package only."""
        case.setdefault("signers", str(self.signers))
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        done = subprocess.run(
            [sys.executable, "-c", PROBE, str(CODEX), json.dumps(case)], capture_output=True, text=True, env=env,
            cwd=self.tmp.name, check=False,
        )  # fmt: skip
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def verify(self, rec: object, prop: dict[str, Any] | None = None) -> list[Any]:
        """Return the (ok, code) pair that the Codex copy of verify gives."""
        out: list[Any] = json.loads(self.probe(mode="verify", rec=rec, prop=prop or self.proposed()))
        return out

    def test_valid_and_self_minted(self) -> None:
        """(a)+(b) a signed receipt verifies; unsigned, agent-key and edited receipts do not."""
        self.assertEqual(self.verify(self.receipt()), [True, "ok"])
        self.assertEqual(self.verify({**self.receipt(), "signature": None}), [False, "signature_missing"])
        self.assertEqual(self.verify(self.receipt(self.agent_key)), [False, "signer_unknown"])
        self.assertEqual(self.verify({**self.receipt(), "ref": "refs/heads/release/x"}), [False, "signature_invalid"])

    def test_binding_and_malformed(self) -> None:
        """(c) stale sha, wrong repository/ref, missing artifact_sha."""
        for field, value, code in (
            ("artifact_sha", "b" * 40, "sha_mismatch"), ("repository", "github.com/evil/w", "repository_mismatch"),
            ("ref", "refs/heads/release/x", "ref_mismatch"),
        ):  # fmt: skip
            self.assertEqual(self.verify(self.receipt(**{field: value})), [False, code])
        self.assertEqual(self.verify(self.receipt(artifact_sha=None)), [False, "malformed"])

    def test_replay_and_concurrent_double_use(self) -> None:
        """(d)+(e) a second consume is refused; 16 Codex-module processes on one receipt give exactly one winner."""
        rec = self.receipt()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            store(base, rec)
            args = {"mode": "find", "rec": rec, "prop": self.proposed(), "base": tmp}
            self.assertEqual(self.probe(**args), rec["receipt_id"])
            self.assertEqual(self.probe(**args), "NONE:consumed")
            (base / "s1" / "receipts" / f"{rec['receipt_id']}.consumed").unlink()
            gate = f"import time, pathlib\nwhile not pathlib.Path({str(base / 'go')!r}).exists(): time.sleep(0.005)\n"
            argv = [sys.executable, "-c", gate + PROBE, str(CODEX), json.dumps({**args, "signers": str(self.signers)})]
            procs = [subprocess.Popen(argv, stdout=subprocess.PIPE, text=True, cwd=tmp) for _ in range(16)]
            time.sleep(0.5)
            (base / "go").write_text("")
            outs = [p.communicate()[0].strip() for p in procs]
        self.assertEqual(outs.count(rec["receipt_id"]), 1, outs)
        self.assertEqual(sum(o.startswith("NONE:") for o in outs), 15, outs)


class MatchParityTests(unittest.TestCase):
    """The vendored command matcher must guard exactly what the Claude one guards."""

    CORPUS = (
        "git push origin main", "git push", "git -C . push origin main",
        "git push origin feature && git push origin main",
        "cd sub && git push", "gh pr merge 5", "gh -R o/r pr merge 5", "gh pr merge 1 && gh pr merge 2",
        "git push --dry-run origin main", "ls", "git push origin HEAD:main", "git merge main", "bash merge.py 7",
        "GIT_DIR=x git push origin main", "git -c a=b push origin main", "git --no-pager push origin main",
        "git commit -m x && git push origin main", "git config a b; gh pr merge 5",
        'git push origin "main"', "git push origin 'HEAD:main'", "git push origin HEAD:$B", "git push --mirror origin",
        "/usr/bin/git push origin HEAD:main", 'eval "git push origin HEAD:main"', "/usr/bin/env git push origin main",
        "git push . evil:feature && git push origin feature:main", "echo x > .git/refs/heads/f; git push origin main",
        "git status 2>&1 && git push origin main", 'cd "sub" && git push origin main', "cd $X && git push origin main",
        "(cd sub); git push origin main", "(cd sub && git push origin main)",
        "cd sub && bash -c 'git push origin main'",
    )  # fmt: skip

    def test_guarded_segments_identical_on_main_and_feature(self) -> None:
        """Same corpus, same repo state, same (operation, segment, cwd) answers."""
        for branch in ("main", "feature/x"):
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(["git", "init", "-q", "-b", branch, tmp], check=True)
                (Path(tmp) / "sub").mkdir()
                for command in self.CORPUS:
                    with self.subTest(branch=branch, command=command):
                        for fn in ("guarded_segments", "state_mutated_before_guard"):
                            args = (command, tmp)[: 2 if fn == "guarded_segments" else 1]
                            self.assertEqual(getattr(claude_match, fn)(*args), getattr(codex_match, fn)(*args))


class HookTests(unittest.TestCase):
    """Native Codex PreToolUse payloads (command + session_id) drive the hook as a subprocess."""

    def setUp(self) -> None:
        """Repo on main with an origin, isolated loop dir and HOME, a fake gh and an owner key (user tier)."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.repo = make_repo(self.directory / "repo")
        self.loop = self.directory / "loops"
        keys = self.directory / "home" / ".coderails" / "keys"
        self.key, signers = make_owner(keys)
        signers.rename(keys / "receipt_signers")
        self.agent_key, _ = make_owner(self.directory / "agent")
        gh = self.directory / "bin" / "gh"
        gh.parent.mkdir()
        gh.write_text(f'#!/bin/sh\necho \'{{"baseRefName":"main","headRefOid":"{MERGE_SHA}"}}\'\n')
        gh.chmod(0o755)
        self.environment = os.environ | {
            "HOME": str(self.directory / "home"),
            "PATH": f"{gh.parent}:{os.environ['PATH']}",
            "PLUGIN_ROOT": str(CODEX),
            "PLUGIN_DATA": str(self.directory / "data"),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
        }

    def configure(self, value: str | None) -> None:
        """Write (or skip) the config line."""
        if value is not None:
            (self.repo / ".coderails").mkdir(exist_ok=True)
            (self.repo / ".coderails/workflow.config.yaml").write_text(f"action_authority: {value}\n")

    def run_hook(self, command: str, session: str = "s1") -> subprocess.CompletedProcess[str]:
        """Run the hook on one Bash event."""
        payload = {
            "session_id": session,
            "cwd": str(self.repo),
            "tool_name": "Bash",
            "hook_event_name": "PreToolUse",
            "tool_input": {"command": command},
        }
        return subprocess.run(
            [sys.executable, str(HOOKS / "action_authority_gate.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.environment,
            check=False,
        )

    def denied(self, command: str, session: str = "s1") -> bool:
        """True when the hook emitted a deny decision."""
        result = self.run_hook(command, session)
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return False
        return bool(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny")

    def mint(
        self, command: str = MERGE, kind: str = "merge", cwd: Path | None = None, rid: str = "r1",
        key: Path | None = None, **over: object,
    ) -> None:  # fmt: skip
        """Store a signed receipt for the hook's view of `command` run in `cwd` on main."""
        where = str(cwd or self.repo)
        bind = (
            {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": MERGE_SHA}
            if kind == "merge" else ab.binding(kind, command, where)
        )  # fmt: skip
        store(self.loop, signed_receipt(key or self.key, kind, command, where, "main", bind, receipt_id=rid, **over))

    def reasons(self) -> list[str]:
        """Reason codes traced for s1."""
        path = self.loop / "s1" / "trace.jsonl"
        return [json.loads(line)["reason_code"] for line in path.read_text().splitlines()] if path.exists() else []

    def test_one_receipt_cannot_authorise_two_identical_segments(self) -> None:
        """A single-use receipt is spent once; a repeated guarded segment is denied."""
        self.configure("enforce")
        self.mint()
        self.assertTrue(self.denied(f"{MERGE} && {MERGE}"))

    def test_common_wrappers_are_still_guarded(self) -> None:
        """Env prefix, sudo, subshell, bash -c and gh api merge are guarded like the bare command."""
        self.configure("enforce")
        for command in ("FOO=1 gh pr merge 12", "sudo gh pr merge 12", "(gh pr merge 12)",
                        "bash -c 'git push origin main'", "gh api repos/o/r/pulls/5/merge -X PUT"):  # fmt: skip
            with self.subTest(command=command):
                self.assertTrue(self.denied(command))

    def test_off_and_advisory(self) -> None:
        """No config, off, and invalid values are silent; advisory warns but does not deny."""
        self.assertFalse(self.denied(MERGE))  # no config at all
        self.configure("bogus")
        self.assertFalse(self.denied(MERGE))
        self.assertEqual(self.reasons(), [])
        self.configure("off")
        result = self.run_hook(MERGE, session="s2")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.configure("advisory")
        result = self.run_hook(MERGE)
        self.assertEqual((result.stdout, "advisory" in result.stderr), ("", True))
        self.assertEqual(self.reasons()[-1], "advisory_no_receipt")

    def test_enforce_deny_allow_consume_once(self) -> None:
        """No receipt denied; matching signed receipt allowed and consumed; replay denied; other args denied."""
        self.configure("enforce")
        self.assertTrue(self.denied(MERGE))
        self.mint()
        self.assertTrue(self.denied(f"gh pr merge 13 --squash {PIN}"))
        self.assertFalse(self.denied(MERGE))
        self.assertTrue(self.denied(MERGE))
        expected = ["denied_no_receipt", "denied_hash_mismatch", "trust_root_user_tier", "receipt_consumed"]
        expected.append("denied_consumed")
        self.assertEqual(self.reasons(), expected)
        self.assertFalse(self.denied("ls -la"))

    def test_self_minted_and_untrusted_are_denied(self) -> None:
        """Unsigned JSON, an agent-made key and a missing trust root are all denied with their own codes."""
        self.configure("enforce")
        self.mint(rid="a", signature=None)
        self.assertTrue(self.denied(MERGE))
        (self.loop / "s1" / "receipts" / "a.json").unlink()
        self.mint(rid="b", key=self.agent_key)
        self.assertTrue(self.denied(MERGE))
        (self.loop / "s1" / "receipts" / "b.json").unlink()
        self.mint(rid="c")
        (self.directory / "home" / ".coderails" / "keys" / "receipt_signers").unlink()
        self.assertTrue(self.denied(MERGE))
        self.assertEqual(
            self.reasons(), ["denied_signature_missing", "denied_signer_unknown", "denied_trust_root_missing"]
        )

    def test_binding_unknown_stale_sha_and_refspec_source(self) -> None:
        """No origin fails closed; a moved HEAD is sha_mismatch; `feature:main` binds feature, not HEAD."""
        self.configure("enforce")
        self.mint("git push origin main", "git_push")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "moved")
        self.assertTrue(self.denied("git push origin main"))
        (self.loop / "s1" / "receipts" / "r1.json").unlink()
        git(self.repo, "branch", "feature")
        command = "git push origin feature:main"
        git(self.repo, "switch", "-q", "feature")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "feature work")
        git(self.repo, "switch", "-q", "main")
        self.mint(command, "git_push", rid="r2", artifact_sha=git(self.repo, "rev-parse", "HEAD"))
        self.assertTrue(self.denied(command))
        self.mint(command, "git_push", rid="r3")
        self.assertFalse(self.denied(command))
        git(self.repo, "remote", "remove", "origin")
        self.assertTrue(self.denied("git push origin main"))
        self.assertEqual(
            self.reasons(),
            [
                "denied_sha_mismatch",
                "denied_sha_mismatch",
                "trust_root_user_tier",
                "receipt_consumed",
                "denied_binding_unknown",
            ],
        )

    def test_enforce_guards_push_on_main_only(self) -> None:
        """A push on main is guarded; on a feature branch it is not."""
        self.configure("enforce")
        self.assertTrue(self.denied("git push origin main"))
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/feature/x"], check=True)
        self.assertFalse(self.denied("git push origin feature/x"))

    def test_chain_cd_and_dash_c_are_guarded(self) -> None:
        """Chained second op, `cd other && git push` and `git -C . push origin main` all need their own receipt."""
        self.configure("enforce")
        other = make_repo(self.directory / "other")
        git(self.repo, "branch", "feature")
        self.mint("git push origin feature", "git_push")
        self.assertTrue(self.denied("git push origin feature && git push origin main"))
        self.mint("git push origin main", "git_push", rid="r2")
        self.assertTrue(self.denied(f"cd {other} && git push origin main"))
        self.assertTrue(self.denied("git -C . push origin main"))

    def test_env_prefix_global_options_and_moved_refs_are_denied(self) -> None:
        """Negative controls: env prefix, `-c`, and a ref moved earlier in the chain are denied despite a receipt."""
        self.configure("enforce")
        self.mint("git push origin main", "git_push")
        for command in ("GIT_DIR=/x git push origin main", "git -c a=b push origin main",
                        "git branch -f main HEAD~0 && git push origin main"):  # fmt: skip
            self.assertTrue(self.denied(command), command)
        self.assertEqual(self.reasons(), ["denied_binding_unknown"] * 2 + ["denied_state_mutated_before_guard"])
        self.assertFalse(self.denied("git push origin main"))

    def test_missing_session_and_owner_hint(self) -> None:
        """No session_id: a traced no_session denial; the hint gives the optional receipt command."""
        self.configure("enforce")
        result = self.run_hook("git push origin main", session="")
        self.assertIn("no_session", result.stdout)
        self.assertNotIn("--session  ", result.stdout)
        rows = (self.loop / "_no_session" / "trace.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(rows[0])["reason_code"], "denied_no_session")
        self.assertIn("sign one at a terminal", self.run_hook("git push origin main").stdout)

    def test_registered_with_timeout(self) -> None:
        """Appended last to the ^Bash$ group with a timeout of at least 5."""
        group = json.loads((CODEX / "hooks/hooks.json").read_text())["hooks"]["PreToolUse"][0]
        self.assertEqual(group["matcher"], "^Bash$")
        self.assertIn("action_authority_gate.py", group["hooks"][-1]["command"])
        self.assertGreaterEqual(group["hooks"][-1]["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
