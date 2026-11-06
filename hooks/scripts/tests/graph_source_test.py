"""Assigned-source reads ignore Git selectors and executable configuration."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
PATHS = (
    "packages/graph-semantics/graph_source.py",
    "skills/agentic-loop/scripts/graph_source.py",
    "packages/codex/skills/agentic-loop/scripts/graph_source.py",
)


class GraphSourceTests(unittest.TestCase):
    """Exercise real local Git with private fixture repositories, never providers."""

    def setUp(self) -> None:
        """Create distinct clean checkouts and load each shipped source reader."""
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.repo = self.root / "assigned"
        self.foreign = self.root / "foreign"
        for repo in (self.repo, self.foreign):
            repo.mkdir()
            self.git(repo, "init", "-q")
            (repo / "source.txt").write_text(repo.name)
            self.git(repo, "add", "source.txt")
            self.git(repo, "commit", "-qm", repo.name)
        self.head = self.git(self.repo, "rev-parse", "HEAD")
        self.modules: list[ModuleType] = []
        for index, path in enumerate(PATHS):
            spec = importlib.util.spec_from_file_location(f"source_reader_{index}", ROOT / path)
            assert spec and isinstance(spec.loader, SourceFileLoader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.modules.append(module)

    def git(self, repo: Path, *args: str) -> str:
        """Fixture setup cannot execute inherited or repository-configured helpers."""
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS="1")
        return subprocess.check_output(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@test",
                *args,
            ],
            env=env,
            text=True,
        ).strip()

    def helper(self) -> tuple[Path, Path]:
        """An inert fsmonitor helper leaves only a private marker if executed."""
        marker, helper = self.root / "executed", self.root / "fsmonitor"
        helper.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\nprintf '\\n'\n")
        helper.chmod(0o700)
        return marker, helper

    def assert_binding(self) -> None:
        """Every independent provider reads this assigned checkout's real HEAD."""
        for module in self.modules:
            with self.subTest(reader=module.__name__):
                value = module.source_binding(str(self.repo), ["source.txt"])
                self.assertEqual(value["source_head_sha"], self.head)
                self.assertEqual(len(value["source_manifest_sha256"]), 64)

    def test_repository_fsmonitor_is_not_executed(self) -> None:
        """A status read cannot execute a repository's configured helper."""
        marker, helper = self.helper()
        self.git(self.repo, "config", "core.fsmonitor", str(helper))
        self.assert_binding()
        self.assertFalse(marker.exists())

    def assert_filter_refused(self, kind: str) -> None:
        """Refuse an effective conversion before any helper or index side effect."""
        (self.repo / ".gitattributes").write_text("source.txt filter=probe\n")
        self.git(self.repo, "add", ".gitattributes")
        self.git(self.repo, "commit", "-qm", "attributes")
        marker, helper = self.helper()
        helper.write_text(
            f"#!/bin/sh\nprintf invoked > '{marker}'\n" + ("/bin/cat\n" if kind == "clean" else "exit 1\n")
        )
        self.git(self.repo, "config", f"filter.probe.{kind}", str(helper))
        before = {name: (self.repo / name).read_bytes() for name in (".git/index", ".git/config", ".gitattributes")}
        for module in self.modules:
            os.utime(self.repo / "source.txt", ns=(2_000_000_000, 2_000_000_000))
            error = ""
            try:
                module.source_binding(str(self.repo), ["source.txt"])
            except ValueError as failure:
                error = str(failure)
            self.assertFalse(marker.exists(), f"{module.__name__} executed {kind} filter")
            self.assertIn("attribute filters are unsupported", error)
        self.assertEqual(before, {name: (self.repo / name).read_bytes() for name in before})

    def test_active_clean_filter_is_refused_without_execution(self) -> None:
        """A fresh-stat status must not invoke a configured clean filter."""
        self.assert_filter_refused("clean")

    def test_active_process_filter_is_refused_without_execution(self) -> None:
        """A process filter is refused before its protocol or command can start."""
        self.assert_filter_refused("process")

    def test_unused_filter_configuration_does_not_refuse_normal_source(self) -> None:
        """An installed but unused filter driver is not an active conversion."""
        marker, helper = self.helper()
        self.git(self.repo, "config", "filter.lfs.clean", str(helper))
        self.git(self.repo, "config", "filter.lfs.process", str(helper))
        self.assert_binding()
        global_config = self.root / "global-git-config"
        global_config.write_text(f'[filter "lfs"]\n clean = {helper}\n process = {helper}\n')
        before = global_config.read_bytes()
        with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(global_config)}):
            self.assert_binding()
        self.assertEqual(global_config.read_bytes(), before)
        self.assertFalse(marker.exists())

    def test_active_attribute_without_local_driver_is_not_treated_as_raw_source(self) -> None:
        """A suppressed global or absent driver must not silently change source semantics."""
        (self.repo / ".git/info/attributes").write_text("source.txt filter=lfs\n")
        for module in self.modules:
            with (
                self.subTest(reader=module.__name__),
                self.assertRaisesRegex(ValueError, "attribute filters are unsupported"),
            ):
                module.source_binding(str(self.repo), ["source.txt"])

    def test_effectively_reset_filter_allows_plain_source(self) -> None:
        """An actual unspecified reset removes a lower-priority filter attribute."""
        (self.repo / ".gitattributes").write_text("source.txt filter=probe\n")
        self.git(self.repo, "add", ".gitattributes")
        self.git(self.repo, "commit", "-qm", "attributes")
        self.head = self.git(self.repo, "rev-parse", "HEAD")
        marker, helper = self.helper()
        self.git(self.repo, "config", "filter.probe.clean", str(helper))
        (self.repo / ".git/info/attributes").write_text("source.txt !filter\n")
        self.assert_binding()
        self.assertFalse(marker.exists())

    def test_literal_sentinel_driver_names_are_refused_without_execution(self) -> None:
        """Protocol values set/unset/unspecified are also legal literal driver names."""
        marker, helper = self.helper()
        helper.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\n/bin/cat\n")
        for name in ("set", "unset", "unspecified"):
            self.git(self.repo, "config", f"filter.{name}.clean", str(helper))
            (self.repo / ".git/info/attributes").write_text(f"source.txt filter={name}\n")
            for module in self.modules:
                os.utime(self.repo / "source.txt", ns=(2_000_000_000, 2_000_000_000))
                with (
                    self.subTest(reader=module.__name__, driver=name),
                    self.assertRaisesRegex(ValueError, "attribute filters are unsupported"),
                ):
                    module.source_binding(str(self.repo), ["source.txt"])
                self.assertFalse(marker.exists())

    def test_explicit_unset_refuses_protocol_ambiguity(self) -> None:
        """-filter aliases literal filter=unset in check-attr and is conservatively refused."""
        (self.repo / ".git/info/attributes").write_text("source.txt -filter\n")
        for module in self.modules:
            with (
                self.subTest(reader=module.__name__),
                self.assertRaisesRegex(ValueError, "attribute filters are unsupported"),
            ):
                module.source_binding(str(self.repo), ["source.txt"])

    def test_submodule_filters_cannot_execute_through_parent_status(self) -> None:
        """Gitlinks are refused before status can recurse into nested filter configuration."""
        (self.foreign / ".gitattributes").write_text("source.txt filter=probe\n")
        self.git(self.foreign, "add", ".gitattributes")
        self.git(self.foreign, "commit", "-qm", "child attributes")
        self.git(self.repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(self.foreign), "child")
        self.git(self.repo, "commit", "-qm", "submodule")
        marker, helper = self.helper()
        helper.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\n/bin/cat\n")
        self.git(self.repo / "child", "config", "filter.probe.clean", str(helper))
        before = (self.repo / ".git/index").read_bytes()
        for module in self.modules:
            os.utime(self.repo / "child/source.txt", ns=(2_000_000_000, 2_000_000_000))
            error = ""
            try:
                module.source_binding(str(self.repo), ["**"])
            except ValueError as failure:
                error = str(failure)
            self.assertFalse(marker.exists(), f"{module.__name__} executed nested filter")
            self.assertIn("Git submodules are unsupported", error)
        self.assertEqual(before, (self.repo / ".git/index").read_bytes())

    def test_environment_git_selectors_do_not_redirect_source(self) -> None:
        """Caller Git directory and worktree cannot replace the explicit assignment."""
        with patch.dict(os.environ, {"GIT_DIR": str(self.foreign / ".git"), "GIT_WORK_TREE": str(self.foreign)}):
            self.assert_binding()

    def test_environment_index_cannot_change_cleanliness(self) -> None:
        """An unrelated index cannot make the assigned clean checkout look dirty."""
        with patch.dict(os.environ, {"GIT_INDEX_FILE": str(self.foreign / ".git/index")}):
            self.assert_binding()

    def test_environment_configuration_cannot_execute_helper(self) -> None:
        """Inherited command-scope Git configuration is not source authority."""
        marker, helper = self.helper()
        with patch.dict(
            os.environ,
            {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": str(helper)},
        ):
            self.assert_binding()
        self.assertFalse(marker.exists())

    def test_replace_refs_do_not_change_inspected_source(self) -> None:
        """Git replacement objects cannot substitute another tree for source HEAD."""
        (self.repo / "source.txt").write_text("later tree")
        self.git(self.repo, "commit", "-qam", "later")
        later = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "checkout", "-q", "--detach", self.head)
        self.git(self.repo, "replace", self.head, later)
        self.assert_binding()

    def test_inspection_does_not_refresh_the_index(self) -> None:
        """A clean status read remains read-only even when file stat data changed."""
        index = self.repo / ".git/index"
        before = index.read_bytes()
        os.utime(self.repo / "source.txt", ns=(1_000_000_000, 1_000_000_000))
        self.assert_binding()
        self.assertEqual(index.read_bytes(), before)

    def test_dispatch_refuses_dirty_source_but_publication_allows_later_root(self) -> None:
        """Fresh dispatch checks HEAD/cleanliness; publication keeps the static assignment."""
        with patch.object(sys, "path", [str(ROOT), *sys.path]):
            from scripts.lib import source_manifest
        self.assert_binding()
        record = {
            "worktree": str(self.repo),
            "manifest": ["source.txt"],
            "source_manifest_sha256": source_manifest.digest(str(self.repo), ["source.txt"]),
        }
        (self.repo / "source.txt").write_text("owned root edit")
        for module in self.modules:
            with self.subTest(reader=module.__name__), self.assertRaisesRegex(ValueError, "must be clean"):
                module.source_binding(str(self.repo), ["source.txt"])
        source_manifest.validate(record)
        self.git(self.repo, "commit", "-qam", "root publication")
        self.assertNotEqual(self.git(self.repo, "rev-parse", "HEAD"), self.head)
        source_manifest.validate(record)
        with self.assertRaises(ValueError):
            source_manifest.validate({**record, "manifest": ["other.txt"]})


if __name__ == "__main__":
    unittest.main()
