"""Local vault Git fixtures with explicit inert GitHub responses for wiki-debt gates."""

from __future__ import annotations

import io
import json
import os
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from hooks.scripts.tests.git_common_sync_test import git
from hooks.scripts.tests.run_all import isolated_environment
from scripts.lib import git_common, wiki_debt


class WikiFixture:
    """Keep source config, vault and remote entirely below a temporary root."""

    def __init__(self, root: Path) -> None:
        """Create a committed blank wiki with a local bare origin/main."""
        self.root = root
        self.project = root / "project"
        self.project.mkdir()
        self.vault = root / "vault"
        self.origin = root / "origin.git"
        self.config = self.project / ".coderails/workflow.config.yaml"
        self.config.parent.mkdir()
        self.configure()
        git(root, "init", "--bare", str(self.origin))
        git(root, "clone", str(self.origin), str(self.vault))
        git(self.vault, "config", "user.name", "Fixture")
        git(self.vault, "config", "user.email", "fixture@example.invalid")
        git(self.vault, "checkout", "-b", "main")
        (self.vault / "log.md").write_text("fixture wiki\n")
        git(self.vault, "add", "log.md")
        git(self.vault, "commit", "-m", "fixture initial")
        git(self.vault, "push", "-u", "origin", "main")
        self.repository = "test-repo"
        self.merged: list[int] = [85]
        self.open_heads: list[str] = []
        self.mode = ""

    def configure(self, content: str = "wiki_debt_epoch_pr: 80\nwiki_path: ../vault\n") -> None:
        """Write only the synthetic project's workflow settings."""
        self.config.write_text(content)

    def coverage(self, text: str, *, source: bool = False, branch: str = "main") -> None:
        """Commit durable coverage or an open ingest branch to the local vault origin."""
        if branch != "main":
            git(self.vault, "checkout", "-b", branch)
        path = self.vault / ("sources/fixture.md" if source else "log.md")
        path.parent.mkdir(exist_ok=True)
        path.write_text(text + "\n")
        git(self.vault, "add", str(path.relative_to(self.vault)))
        git(self.vault, "commit", "-m", "fixture coverage")
        git(self.vault, "push", "origin", branch)
        if branch != "main":
            git(self.vault, "checkout", "main")

    def command(self, *arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        """Intercept all gh calls; permit actual Git only with the file protocol."""
        if arguments[0] == "gh":
            opened = "open" in arguments
            text = "\n".join(self.open_heads) if opened else json.dumps([{"number": number} for number in self.merged])
            failed = self.mode == ("open-fail" if opened else "merged-fail")
            if not opened and self.mode == "empty-merged":
                text = ""
            result = subprocess.CompletedProcess(
                arguments, int(failed), text, "fixture fetch refused" if failed else ""
            )
        elif arguments[-3:] == ("remote", "get-url", "origin"):
            result = subprocess.CompletedProcess(arguments, 0, "https://github.com/o/vault.git", "")
        elif "fetch" in arguments and self.mode in ("fetch-fail", "fetch-noop"):
            result = subprocess.CompletedProcess(arguments, int(self.mode == "fetch-fail"), "", "fixture fetch refused")
        else:
            environment = dict(
                isolated_environment(), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_ALLOW_PROTOCOL="file"
            )
            result = subprocess.run(
                arguments, cwd=self.project, env=environment, capture_output=True, text=True, check=False
            )
        if check and result.returncode:
            raise git_common.WorkflowError(result.stderr or "fixture command failed")
        return result

    def gate(self, number: str = "99") -> tuple[bool, str]:
        """Run the real wiki gate and capture its actionable acceptance/refusal text."""
        stream = io.StringIO()
        with (
            patch.object(wiki_debt, "config_path", return_value=str(self.config)),
            patch.object(git_common, "repo", return_value=f"o/{self.repository}" if self.repository else ""),
            patch.object(git_common, "run", side_effect=self.command),
            redirect_stdout(stream),
            redirect_stderr(stream),
        ):
            try:
                wiki_debt.has_wiki_ingest_for_merged_prs(number)
            except git_common.WorkflowError as error:
                return False, str(error)
        return True, stream.getvalue()
