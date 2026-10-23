"""Pin the exact argv, prompt wiring and scrubbed env of the contained Codex role session launcher."""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts import codex_role_session as crs  # noqa: E402

GUARDED = ("deploy-safety-reviewer", "design-scout", "disposition-scout", "preflight-scout", "source-auditor")


class IsolatedTrace(unittest.TestCase):
    """Keep trace rows out of the real loop directory."""

    def setUp(self) -> None:
        """Point the loop dir at a private temp directory for the case."""
        loop = tempfile.TemporaryDirectory()
        self.addCleanup(loop.cleanup)
        patcher = patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": loop.name})
        patcher.start()
        self.addCleanup(patcher.stop)


class ArgvTests(IsolatedTrace):
    """The launched command must carry every containment flag and exactly one MCP server."""

    def test_exact_argv_for_source_auditor(self) -> None:
        """--ignore-user-config, read-only sandbox, shell tool off, one mcp_servers entry for the role."""
        argv = crs.build_argv("source-auditor", REPO)
        self.assertEqual(argv[:2], ["codex", "exec"])
        self.assertIn("--ignore-user-config", argv)
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        overrides = [argv[i + 1] for i, token in enumerate(argv) if token == "-c"]
        self.assertIn("features.shell_tool=false", overrides)
        servers = [o for o in overrides if o.startswith("mcp_servers.")]
        self.assertEqual(len(servers), 1)
        self.assertTrue(servers[0].startswith("mcp_servers.cap-source-auditor="), servers)
        self.assertIn("--role", servers[0])
        self.assertIn('"source-auditor"', servers[0])
        self.assertIn(str(REPO / "scripts/capability_mcp.py"), servers[0])
        self.assertIn('default_tools_approval_mode = "approve"', servers[0])
        self.assertEqual(argv[-1], "-")  # prompt comes from stdin (a file), never from argv

    def test_every_guarded_role_gets_only_its_own_server(self) -> None:
        """No role's argv names another role's server."""
        for role in GUARDED:
            with self.subTest(role=role):
                text = " ".join(crs.build_argv(role, REPO))
                self.assertIn(f"mcp_servers.cap-{role}=", text)
                self.assertEqual(text.count("mcp_servers."), 1)
                for other in GUARDED:
                    if other == role:
                        continue
                    self.assertNotIn(f"cap-{other}", text.replace(f"cap-{role}", ""))

    def test_unknown_and_unguarded_roles_are_refused(self) -> None:
        """A role with raw shell or write access, a read-only agent with no tools, or a typo never launches."""
        for role in ("loop-worker", "docs-auditor", "spec-reviewer", "nope", "", "../source-auditor"):
            with self.subTest(role=role), self.assertRaises(ValueError):
                crs.build_argv(role, REPO)

    def test_stripping_a_containment_flag_is_caught_by_the_assertion_helper(self) -> None:
        """Negative control: the argv check used above fails when shell_tool=false is removed."""
        argv = crs.build_argv("design-scout", REPO)
        stripped = [t for t in argv if t != "features.shell_tool=false"]
        self.assertNotIn("features.shell_tool=false", stripped)
        self.assertNotEqual(argv, stripped)
        self.assertFalse(crs.contained(stripped, "design-scout"))
        self.assertTrue(crs.contained(argv, "design-scout"))

    def test_approval_mode_is_required_by_the_containment_check(self) -> None:
        """A missing or downgraded MCP approval setting cannot count as contained."""
        argv = crs.build_argv("source-auditor", REPO)
        self.assertTrue(crs.contained(argv, "source-auditor"))
        for replacement in ("", 'default_tools_approval_mode = "prompt"'):
            with self.subTest(replacement=replacement):
                altered = [value.replace('default_tools_approval_mode = "approve"', replacement) for value in argv]
                self.assertFalse(crs.contained(altered, "source-auditor"))


class EnvAndRunTests(IsolatedTrace):
    """The child gets an allowlisted env and the prompt on stdin."""

    def test_env_is_scrubbed(self) -> None:
        """Credentials and loop-state variables are dropped; PATH/HOME/CODEX_HOME survive."""
        dirty = {
            "PATH": "/usr/bin",
            "HOME": "/h",
            "CODEX_HOME": "/c",
            "GH_TOKEN": "x",
            "GITHUB_TOKEN": "x",
            "ANTHROPIC_API_KEY": "x",
            "AWS_SECRET_ACCESS_KEY": "x",
            "CLAUDE_AGENTIC_LOOP_DIR": "/l",
        }
        with patch.dict(os.environ, dirty, clear=True):
            env = crs.scrubbed_env()
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["CODEX_HOME"], "/c")
        for leaked in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY"):
            self.assertNotIn(leaked, env)

    def test_run_passes_prompt_file_on_stdin_with_scrubbed_env(self) -> None:
        """A fake `codex` on PATH records its argv, stdin and env; the launcher forwards exactly the contract."""
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "codex"
            out = Path(tmp) / "seen.json"
            fake.write_text(
                "#!/usr/bin/env python3\nimport json,os,sys\n"
                "seen = {'argv': sys.argv[1:], 'stdin': sys.stdin.read(), 'env': dict(os.environ)}\n"
                f"json.dump(seen, open({str(out)!r}, 'w'))\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            prompt = Path(tmp) / "prompt.txt"
            prompt.write_text("audit claim 1")
            with patch.dict(os.environ, {"PATH": f"{bin_dir}:/usr/bin:/bin", "GH_TOKEN": "secret", "HOME": tmp}):
                code = crs.main(["--role", "source-auditor", "--prompt-file", str(prompt), "--cwd", tmp])
            seen = json.loads(out.read_text())
        self.assertEqual(code, 0)
        self.assertTrue(crs.contained(["codex", *seen["argv"]], "source-auditor"))
        self.assertEqual(seen["stdin"], "audit claim 1")
        self.assertNotIn("GH_TOKEN", seen["env"])
        self.assertIn("-C", seen["argv"])

    def test_main_refuses_bad_role_and_missing_prompt_without_launching(self) -> None:
        """Exit 2, nothing spawned."""
        with patch.object(subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(crs.main(["--role", "loop-worker", "--prompt-file", "/dev/null"]), 2)
            self.assertEqual(crs.main(["--role", "source-auditor", "--prompt-file", "/nonexistent/p"]), 2)
            self.assertEqual(crs.main(["--role", "source-auditor"]), 2)
            run.assert_not_called()
            self.assertIn("not a guarded role", err.getvalue())

    def test_project_codex_config_in_cwd_is_refused(self) -> None:
        """--ignore-user-config keeps project .codex/ config: a cwd tree (to the repo root) holding one is refused."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            sub = root / "a" / "b"
            sub.mkdir(parents=True)
            self.assertIn("-C", crs.build_argv("source-auditor", REPO, str(sub)))  # negative control: clean tree passes
            (root / ".codex").mkdir()
            with self.assertRaises(ValueError):
                crs.build_argv("source-auditor", REPO, str(sub))


if __name__ == "__main__":
    unittest.main()
