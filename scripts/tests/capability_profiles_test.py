"""Pin the single-source capability profiles against Claude frontmatter and Codex sandbox modes."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hooks.scripts.lib.capability_profiles import guarded_agents, load_profiles  # noqa: E402
from scripts.capability_profiles_validate import validate  # noqa: E402
from scripts.lib.capability_validation import check_mcp, expected_tools, mcp_config, mcp_name  # noqa: E402

OLD_GUARDED = {"deploy-safety-reviewer", "design-scout", "disposition-scout", "preflight-scout", "source-auditor"}


def drop_tools(text: str) -> str:
    """Delete the frontmatter `tools:` line."""
    return re.sub(r"(?m)^tools:.*\n", "", text)


def set_tools(text: str, replace: str | None, append: str = "") -> str:
    """Replace the `tools:` value with `replace`, or append `append` to it."""
    if replace is not None:
        return re.sub(r"(?m)^tools:.*$", lambda _m: "tools:" + replace, text)
    return re.sub(r"(?m)^tools:.*$", lambda m: m.group(0) + append, text)


class ProfileTests(unittest.TestCase):
    """Every shipped agent has a profile and each harness's declared limits agree with it."""

    def setUp(self) -> None:
        """Load the checked-in profiles once per case."""
        self.profiles = load_profiles(REPO)

    def test_checked_in_profiles_validate(self) -> None:
        """No drift between profiles.json, agents/*.md and packages/codex/agents/*.toml."""
        self.assertEqual(validate(REPO, self.profiles), [])

    def test_guarded_set_is_derived_and_unchanged(self) -> None:
        """Bash-bearing agents without shell.raw are exactly the pre-existing hard-coded set."""
        self.assertEqual(set(guarded_agents(self.profiles)), OLD_GUARDED)

    def test_string_capability_value_is_rejected_at_load(self) -> None:
        """A string where a list belongs would turn `in` into a substring test; refuse it."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "capabilities").mkdir()
            (Path(tmp) / "capabilities" / "profiles.json").write_text(json.dumps({"agents": {"a": "shell.raw"}}))
            with self.assertRaises(ValueError):
                load_profiles(Path(tmp))

    def test_missing_profile_is_red(self) -> None:
        """Negative control: deleting a profile is reported for both harnesses."""
        broken = copy.deepcopy(self.profiles)
        del broken["agents"]["design-scout"]
        errors = validate(REPO, broken)
        self.assertTrue(any("design-scout" in e and "no profile" in e for e in errors), errors)

    def test_write_on_read_only_agent_is_red(self) -> None:
        """Negative control: granting worktree.write to a read-only agent disagrees with frontmatter and sandbox."""
        broken = copy.deepcopy(self.profiles)
        broken["agents"]["design-scout"].append("worktree.write")
        errors = validate(REPO, broken)
        self.assertTrue(any("design-scout" in e and "claude" in e for e in errors), errors)
        self.assertTrue(any("design-scout" in e and "codex" in e for e in errors), errors)

    def test_unknown_capability_and_missing_instruction_are_red(self) -> None:
        """A made-up capability, or tests.run without agent text naming capability.py, fails."""
        broken = copy.deepcopy(self.profiles)
        broken["agents"]["design-scout"] += ["bogus.cap", "tests.run"]
        errors = validate(REPO, broken)
        self.assertTrue(any("bogus.cap" in e for e in errors), errors)
        self.assertTrue(any("design-scout" in e and "capability.py" in e for e in errors), errors)

    def _with_agent_edit(self, name: str, edit: Callable[[str], str]) -> list[str]:
        """Validate a scratch copy of the repo after `edit(text) -> text` is applied to agents/<name>.md."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO / "agents", root / "agents")
            shutil.copytree(REPO / "packages/codex/agents", root / "packages/codex/agents")
            path = root / "agents" / f"{name}.md"
            path.write_text(edit(path.read_text()))
            return validate(root, self.profiles)

    def test_missing_tools_line_is_red(self) -> None:
        """Negative control: no `tools:` line means ALL tools for the harness, so it must not pass."""
        errors = self._with_agent_edit("spec-reviewer", drop_tools)
        self.assertTrue(any("spec-reviewer" in e and "tools:" in e for e in errors), errors)

    def test_yaml_list_tools_is_red(self) -> None:
        """A block-list `tools:` parses as empty and is refused rather than read as zero tools."""
        errors = self._with_agent_edit("spec-reviewer", lambda t: set_tools(t, "\n  - Read"))
        self.assertTrue(any("spec-reviewer" in e and "tools:" in e for e in errors), errors)

    def test_extra_ungated_tools_are_red(self) -> None:
        """Negative control: Task/WebFetch/mcp__ on a guarded agent is drift, Skill is not allowed on a scout."""
        extra = ", Task, WebFetch, mcp__x__y, Skill"
        errors = self._with_agent_edit("design-scout", lambda t: set_tools(t, None, extra))
        joined = " ".join(errors)
        for tool in ("Task", "WebFetch", "mcp__x__y", "Skill"):
            self.assertIn(tool, joined)
        self.assertEqual(self._with_agent_edit("preflight-scout", lambda t: t), [])  # its Skill is allowlisted

    def test_source_auditor_has_tests_run_and_scouts_do_not(self) -> None:
        """The narrow execution capability is granted to exactly one agent."""
        holders = {a for a, caps in self.profiles["agents"].items() if "tests.run" in caps}
        self.assertEqual(holders, {"source-auditor"})


class RoleBindingTests(unittest.TestCase):
    """U2: guarded agents hold exactly their per-role MCP tools, no shell, and the generated config matches."""

    def setUp(self) -> None:
        """Load the checked-in profiles once per case."""
        self.profiles = load_profiles(REPO)

    def scratch(self, edit: Callable[[Path], None]) -> list[str]:
        """Validate a scratch copy of agents, Codex agents and capabilities after `edit(root)`."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO / "agents", root / "agents")
            shutil.copytree(REPO / "packages/codex/agents", root / "packages/codex/agents")
            shutil.copytree(REPO / "capabilities", root / "capabilities")
            edit(root)
            return validate(root, self.profiles) + check_mcp(root, self.profiles)

    def test_every_guarded_agent_tools_equal_derived_mcp_names(self) -> None:
        """Positive: the five files carry exactly the derived names (+Skill for preflight-scout) and no Bash."""
        for role in sorted(guarded_agents(self.profiles)):
            tools = re.search(r"(?m)^tools:(.*)$", (REPO / "agents" / f"{role}.md").read_text())
            assert tools is not None
            listed = [t.strip() for t in tools.group(1).split(",")]
            want = expected_tools(role, self.profiles["agents"][role])
            self.assertEqual(sorted(listed), sorted(want), role)
            self.assertNotIn("Bash", listed)
            self.assertTrue(all(len(t) <= 64 for t in listed), role)
            self.assertTrue(all(t.startswith(f"mcp__plugin_coderails_cap-{role}__") or t == "Skill" for t in listed))

    def test_bash_added_back_is_a_named_error(self) -> None:
        """Negative control 1 (validator oracle): re-adding Bash to one guarded agent is reported by name."""
        errors = self.scratch(lambda r: self._edit(r, "design-scout", lambda t: set_tools(t, None, ", Bash")))
        self.assertTrue(any("design-scout" in e and "Bash" in e for e in errors), errors)

    def _edit(self, root: Path, name: str, edit: Callable[[str], str]) -> None:
        """Rewrite agents/<name>.md in the scratch root."""
        path = root / "agents" / f"{name}.md"
        path.write_text(edit(path.read_text()))

    def _with_extra_tool(self, name: str, tool: str) -> list[str]:
        """Validate a scratch copy where `tool` is appended to the agent's `tools:` line."""
        return self.scratch(lambda r: self._edit(r, name, lambda t: set_tools(t, None, f", {tool}")))

    def test_stale_mcp_name_and_forbidden_tools_are_named_errors(self) -> None:
        """A renamed tool, Read, Write, Agent or WebFetch on a guarded agent each produce an error naming the tool."""
        stale = self.scratch(
            lambda r: self._edit(r, "design-scout", lambda t: t.replace("cap-design-scout__repo_inspect", "cap-old__x"))
        )
        self.assertTrue(any("design-scout" in e and "cap-old__x" in e for e in stale), stale)
        for tool in ("Read", "Write", "Edit", "NotebookEdit", "Agent", "Task", "WebFetch", "Grep", "Glob"):
            errors = self._with_extra_tool("source-auditor", tool)
            self.assertTrue(any("source-auditor" in e and tool in e for e in errors), (tool, errors))

    def test_overlong_tool_name_is_a_named_error(self) -> None:
        """A role whose full MCP tool name exceeds 64 characters is refused (the API rejects it at runtime)."""
        broken = copy.deepcopy(self.profiles)
        broken["agents"]["x" * 40] = ["repo.inspect"]
        errors = validate(REPO, broken)
        self.assertTrue(any("64" in e and "x" * 40 in e for e in errors), errors)
        self.assertLessEqual(max(len(mcp_name(r, "repo.inspect")) for r in guarded_agents(self.profiles)), 64)

    def test_codex_toml_without_shell_tool_false_is_a_named_error(self) -> None:
        """Negative control 3: sandbox_mode alone is not enough; the [features] shell_tool=false line is required."""

        def strip(root: Path) -> None:
            path = root / "packages/codex/agents/design-scout.toml"
            path.write_text(path.read_text().replace("[features]\nshell_tool = false\n", ""))

        errors = self.scratch(strip)
        self.assertTrue(any("codex" in e and "design-scout" in e and "shell_tool" in e for e in errors), errors)

        def flipped(root: Path) -> None:
            path = root / "packages/codex/agents/design-scout.toml"
            path.write_text(path.read_text().replace("shell_tool = false", "shell_tool = true"))

        self.assertTrue(any("shell_tool" in e for e in self.scratch(flipped)))

    def test_codex_features_table_before_instructions_is_a_named_error(self) -> None:
        """A [features] table before developer_instructions would swallow the key; the validator refuses it."""

        def reorder(root: Path) -> None:
            path = root / "packages/codex/agents/design-scout.toml"
            text = path.read_text().replace("\n[features]\nshell_tool = false\n", "")
            early = "[features]\nshell_tool = false\ndeveloper_instructions ="
            path.write_text(text.replace("developer_instructions =", early, 1))

        errors = self.scratch(reorder)
        self.assertTrue(any("design-scout" in e and "after developer_instructions" in e for e in errors), errors)

    def test_codex_forged_features_table_inside_instructions_is_a_named_error(self) -> None:
        """Negative control: a fake [features] shell_tool pair inside the triple-quoted string is not a table."""

        def forge(root: Path) -> None:
            path = root / "packages/codex/agents/design-scout.toml"
            text = path.read_text().replace("\n[features]\nshell_tool = false\n", "")
            fake = '[features]\nshell_tool = false\n"""\n'
            path.write_text(text.rstrip("\n")[: -len('"""')] + fake)

        errors = self.scratch(forge)
        self.assertTrue(any("design-scout" in e and "shell_tool" in e for e in errors), errors)

    def test_codex_toml_keeps_sandbox_mode_and_features_before_instructions(self) -> None:
        """The table header must not swallow developer_instructions: it is a top-level key placed before [features]."""
        for role in guarded_agents(self.profiles):
            text = (REPO / "packages/codex/agents" / f"{role}.toml").read_text()
            self.assertIn('sandbox_mode = "read-only"', text)
            self.assertLess(text.index("developer_instructions"), text.index("[features]"), role)

    def test_checked_in_mcp_json_is_generated_output(self) -> None:
        """capabilities/mcp.json equals the generator output: one cap-<role> server per guarded role, nothing else."""
        on_disk = json.loads((REPO / "capabilities/mcp.json").read_text())
        self.assertEqual(on_disk, mcp_config(self.profiles))
        self.assertEqual(set(on_disk["mcpServers"]), {f"cap-{r}" for r in guarded_agents(self.profiles)})
        self.assertEqual(check_mcp(REPO, self.profiles), [])

    def test_doctored_mcp_json_fails_check_on_the_command_line(self) -> None:
        """Negative control 4: a server for a role not in the profile, or a changed command, fails `--check`."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO / "capabilities", root / "capabilities")
            path = root / "capabilities/mcp.json"
            doc = json.loads(path.read_text())
            doc["mcpServers"]["cap-ghost"] = {"command": "python3", "args": ["x", "--role", "ghost"]}
            path.write_text(json.dumps(doc))
            self.assertTrue(any("cap-ghost" in e for e in check_mcp(root, self.profiles)))
            doc["mcpServers"].pop("cap-ghost")
            doc["mcpServers"]["cap-design-scout"]["args"][-1] = "source-auditor"
            path.write_text(json.dumps(doc))
            self.assertTrue(any("cap-design-scout" in e for e in check_mcp(root, self.profiles)))
            path.unlink()
            self.assertTrue(any("missing" in e for e in check_mcp(root, self.profiles)))

    def test_check_flag_passes_on_the_repo_and_write_mcp_is_idempotent(self) -> None:
        """`--check` exits 0 on the checked-in tree; `--write-mcp` into a scratch root reproduces the file."""
        script = str(REPO / "scripts/capability_profiles_validate.py")
        done = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(
            json.loads((REPO / "capabilities/mcp.json").read_text()),
            mcp_config(self.profiles),
        )

    def test_plugin_manifest_points_at_the_generated_file(self) -> None:
        """The Claude plugin registers the generated servers; without this line the tool names do not exist."""
        manifest = json.loads((REPO / ".claude-plugin/plugin.json").read_text())
        self.assertEqual(manifest["mcpServers"], "./capabilities/mcp.json")


if __name__ == "__main__":
    unittest.main()
