"""Exercise capability_extra: worktree allowlist, the new repo.inspect ops, cmd.run, and the reason-code counters."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.lib import capability_counters  # noqa: E402

TREE_FILES = (
    "scripts/capability.py",
    "scripts/capability_mcp.py",
    "scripts/lib/capability_extra.py",
    "capabilities/profiles.json",
    "hooks/scripts/lib/trace_row.py",
)


def git(repo: Path, *argv: str) -> None:
    """Run git in repo with a throwaway identity."""
    cmd = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *argv]
    subprocess.run(cmd, check=True, capture_output=True)


def make_tree(base: Path, name: str = "tree", doctor: dict[str, tuple[str, str]] | None = None) -> Path:
    """Copy the capability scripts into base/name, optionally rewriting text per file, so a variant can be run."""
    tree = base / name
    for rel in TREE_FILES:
        target = tree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (ROOT / rel).read_text(encoding="utf-8")
        old, new = (doctor or {}).get(rel, ("", ""))
        if old:
            assert old in text, f"doctor target missing in {rel}"
            text = text.replace(old, new)
        target.write_text(text, encoding="utf-8")
    return tree


def call(tree: Path, repo: Path, tool: str, args: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Run tree's capability.py with cwd=repo; return (exit code, parsed envelope)."""
    env = {"PATH": os.environ["PATH"], "CLAUDE_AGENTIC_LOOP_DIR": str(repo.parent / "loop"), "CLAUDE_SESSION_ID": "s"}
    done = subprocess.run(
        [sys.executable, str(tree / "scripts/capability.py"), tool, "--json-args", json.dumps(args)],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return done.returncode, json.loads(done.stdout)


class ExtraCase(unittest.TestCase):
    """A scratch repo (two files, one commit, one linked worktree) plus a pristine copy of the scripts."""

    def setUp(self) -> None:
        """Build repo, a linked worktree and an outside file."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.repo = self.base / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
        (self.repo / "sub").mkdir()
        (self.repo / "sub/b.py").write_text("x = 1\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "init")
        self.linked = self.base / "linked"
        git(self.repo, "worktree", "add", "-q", "-b", "other", str(self.linked))
        (self.linked / "only_here.txt").write_text("hi\n", encoding="utf-8")
        (self.base / "outside.txt").write_text("secret\n", encoding="utf-8")
        self.tree = make_tree(self.base)

    def inspect(self, tree: Path | None = None, /, **args: object) -> tuple[int, dict[str, Any]]:
        """repo.inspect through the CLI."""
        return call(tree or self.tree, self.repo, "repo.inspect", args)

    def test_new_ops_work(self) -> None:
        """show, blame, wc, sha256, glob and read offset return typed results."""
        _, show = self.inspect(op="show", spec="HEAD:a.txt")
        self.assertEqual(show["result"]["text"], "one\ntwo\nthree\n")
        _, blame = self.inspect(op="blame", path="a.txt")
        self.assertEqual(len(blame["result"]["lines"]), 3)
        _, wc = self.inspect(op="wc", path="a.txt")
        self.assertEqual((wc["result"]["lines"], wc["result"]["bytes"]), (3, 14))
        _, digest = self.inspect(op="sha256", path="a.txt")
        self.assertEqual(len(digest["result"]["sha256"]), 64)
        _, found = self.inspect(op="glob", pattern="**/*.py")
        self.assertEqual(found["result"]["paths"], ["sub/b.py"])
        _, part = self.inspect(op="read", path="a.txt", offset=4, max_bytes=3)
        self.assertEqual(part["result"]["text"], "two")

    def test_new_ops_refuse_escapes(self) -> None:
        """Every path-taking op refuses '..', absolute paths and bad refs."""
        outside = str(self.base / "outside.txt")
        cases: list[tuple[str, dict[str, Any], str]] = [
            ("show", {"spec": "HEAD:../outside.txt"}, "capability_path_denied"),
            ("show", {"spec": "HEAD;rm:a.txt"}, "capability_bad_ref"),
            ("show", {"spec": "nocolon"}, "capability_args_invalid"),
            ("blame", {"path": "../outside.txt"}, "capability_path_denied"),
            ("wc", {"path": "../outside.txt"}, "capability_path_denied"),
            ("wc", {"path": outside}, "capability_path_denied"),
            ("sha256", {"path": "../outside.txt"}, "capability_path_denied"),
            ("glob", {"pattern": "../*"}, "capability_path_denied"),
            ("glob", {"pattern": ":(top)*"}, "capability_path_denied"),
            ("read", {"path": "../outside.txt", "offset": 0}, "capability_path_denied"),
            ("wc", {"path": "a.txt", "role": "source-auditor"}, "capability_args_invalid"),
        ]
        for op, args, code in cases:
            with self.subTest(op=op, args=args):
                status, env = self.inspect(op=op, **args)
                self.assertEqual((status, env["refusal"]), (2, code))

    def test_negative_control_without_safe_path_escape_succeeds(self) -> None:
        """Control: a copy without safe_path DOES read outside the repo, so the escape test above bites."""
        doctor = {"scripts/lib/capability_extra.py": ("cap.safe_path(", "(lambda r, p: r / p)(")}
        tree = make_tree(self.base, "doctored", doctor)
        status, env = self.inspect(tree, op="wc", path="../outside.txt")
        self.assertEqual((status, env.get("ok")), (0, True))
        status, _ = self.inspect(tree, op="sha256", path="../outside.txt")
        self.assertEqual(status, 0)

    def test_worktree_allowlist(self) -> None:
        """A listed linked worktree is usable; an unlisted directory is refused for every repo tool."""
        _, env = self.inspect(op="list", worktree=str(self.linked))
        self.assertIn("only_here.txt", env["result"]["entries"])
        for tool, args in (
            ("repo.inspect", {"op": "list"}),
            ("diff.read", {"base": "HEAD"}),
            ("tests.run", {"name": "scripts"}),
            ("cmd.run", {"name": "file-lines", "args": {"path": "a.txt"}}),
        ):
            with self.subTest(tool=tool):
                status, env = call(self.tree, self.repo, tool, {**args, "worktree": str(self.base)})
                self.assertEqual((status, env["refusal"]), (2, "capability_path_denied"))
        _, env = self.inspect(op="list", worktree=5)
        self.assertEqual(env["refusal"], "capability_args_invalid")

    def test_cmd_run_named_commands_only(self) -> None:
        """Declared commands run; unknown names, extra keys, bad paths and bad refs refuse."""
        git(self.repo, "tag", "v1")
        _, env = call(self.tree, self.repo, "cmd.run", {"name": "file-lines", "args": {"path": "a.txt"}})
        self.assertIn("3", env["result"]["stdout_tail"])
        _, env = call(self.tree, self.repo, "cmd.run", {"name": "git-rev-count", "args": {"ref": "v1"}})
        self.assertEqual(env["result"]["stdout_tail"].strip(), "1")
        _, env = call(self.tree, self.repo, "cmd.run", {"name": "file-sha256", "args": {"path": "a.txt"}})
        self.assertEqual(env["exit_status"], 0)
        outside = str(self.base / "outside.txt")
        bad: list[tuple[dict[str, Any], str]] = [
            ({"name": "rm", "args": {}}, "capability_args_invalid"),
            ({"name": "file-lines", "args": {"path": "a.txt", "extra": "x"}}, "capability_args_invalid"),
            ({"name": "file-lines", "args": {}}, "capability_args_invalid"),
            ({"name": "file-lines", "args": {"path": "../outside.txt"}}, "capability_path_denied"),
            ({"name": "file-lines", "args": {"path": outside}}, "capability_path_denied"),
            ({"name": "git-rev-count", "args": {"ref": "HEAD;touch x"}}, "capability_bad_ref"),
            ({"name": "git-rev-count", "args": {"ref": "$(id)"}}, "capability_bad_ref"),
            ({"name": "file-lines", "args": {"path": "a.txt"}, "role": "x"}, "capability_args_invalid"),
        ]
        for args, code in bad:
            with self.subTest(args=args):
                status, env = call(self.tree, self.repo, "cmd.run", args)
                self.assertEqual((status, env["refusal"]), (2, code))

    def test_counters_count_reason_codes(self) -> None:
        """The counter helper counts capability rows by reason code and ignores other commands."""
        loop = self.base / "loop"
        (loop / "s").mkdir(parents=True)
        rows = [
            ("capability", "refused", "capability_wrong_role"),
            ("capability", "ok", "repo.inspect"),
            ("other", "refused", "capability_wrong_role"),
        ]
        lines = [json.dumps({"command": c, "outcome": o, "reason_code": r, "ts": "2026"}) for c, o, r in rows]
        (loop / "s/trace.jsonl").write_text("\n".join(lines) + "\ntorn{\n", encoding="utf-8")
        counts = capability_counters.count_reasons(loop)
        self.assertEqual((counts["capability_wrong_role"], counts["ok"], counts["capability_args_invalid"]), (1, 1, 0))


if __name__ == "__main__":
    unittest.main()
