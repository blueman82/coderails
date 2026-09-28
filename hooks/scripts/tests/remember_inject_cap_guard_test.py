#!/usr/bin/env python3
"""Preserve opt-in memory cap repair, exact patching, and warning suppression."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.hook_test_support import ROOT, HookTestCase


class RememberCapTests(HookTestCase):
    """Exercise immutable defaults and the explicitly opted-in third-party patch."""

    def setUp(self) -> None:
        """Prepare canonical vendor content and independent warning state."""
        super().setUp()
        self.vendor = (ROOT / "hooks/patches/remember_inject_cap.vendor.txt").read_text()
        self.patched = (ROOT / "hooks/patches/remember_inject_cap.patched.txt").read_text()
        self.target = self.directory / "session-start-hook"
        self.target.write_text("#!/bin/bash\nif true; then\n" + self.vendor + "fi\necho tail\n")
        self.target.chmod(0o700)
        self.environment.update(
            {
                "REMEMBER_HOOK_FILE": str(self.target),
                "REMEMBER_PLUGIN_VERSION": "9.9.9",
                "REMEMBER_INJECT_STATE_DIR": str(self.directory / "warnings"),
            }
        )
        self.environment.pop("REMEMBER_INJECT_CAP_AUTOWRITE", None)

    def run_guard(self, **environment: str) -> subprocess.CompletedProcess[str]:
        """Run the guard and require observe-only exit semantics."""
        result = self.run_hook("remember_inject_cap_guard", {}, **environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        if result.stdout:
            document = json.loads(result.stdout)
            self.assertEqual(document["hookSpecificOutput"]["hookEventName"], "SessionStart")
            self.assertEqual(document["systemMessage"], document["hookSpecificOutput"]["additionalContext"])
        return result

    def test_default_warning_is_immutable_and_version_scoped(self) -> None:
        """Default and explicit zero only warn once for each version without backups."""
        before = self.target.read_bytes()
        first = self.run_guard()
        for phrase in ("REMEMBER_INJECT_CAP_AUTOWRITE", "settings.json", "will NOT modify", "9.9.9"):
            self.assertIn(phrase, first.stdout)
        self.assertEqual(self.run_guard().stdout, "")
        self.assertIn(
            "9.9.10", self.run_guard(REMEMBER_PLUGIN_VERSION="9.9.10", REMEMBER_INJECT_CAP_AUTOWRITE="0").stdout
        )
        self.assertEqual(self.run_guard(REMEMBER_PLUGIN_VERSION="9.9.10").stdout, "")
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(list(self.directory.glob("*.coderails-*")), [])

    def test_opted_in_exact_patch_is_lossless_and_idempotent(self) -> None:
        """Only the canonical block changes; backup, permissions, and repeat behavior persist."""
        original = self.target.read_text()
        result = self.run_guard(REMEMBER_INJECT_CAP_AUTOWRITE="1", REMEMBER_INJECT_MAX_BYTES="1234")
        self.assertIn("1234 bytes", result.stdout)
        self.assertIn("9.9.9", result.stdout)
        self.assertEqual(self.target.read_text(), original.replace(self.vendor, self.patched))
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o700)
        backups = list(self.directory.glob("*.coderails-bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), original)
        self.assertEqual(self.run_guard(REMEMBER_INJECT_CAP_AUTOWRITE="1").stdout, "")
        self.assertEqual(self.target.read_text(), original.replace(self.vendor, self.patched))
        self.target.write_text(self.target.read_text().replace(self.patched, self.vendor))
        self.run_guard(REMEMBER_INJECT_CAP_AUTOWRITE="1")
        self.assertEqual(self.target.read_text(), original.replace(self.vendor, self.patched))

    def test_stale_backups_and_comment_only_sentinel(self) -> None:
        """A comment mentioning the cap does not prevent repair; only the rolling backup survives."""
        self.target.write_text("# REMEMBER_INJECT_MAX_BYTES\n" + self.target.read_text())
        for suffix in ("old", "older"):
            Path(f"{self.target}.coderails-bak-{suffix}").write_text("old")
        self.run_guard(REMEMBER_INJECT_CAP_AUTOWRITE="1")
        self.assertIn('head -c "$REMEMBER_INJECT_MAX_BYTES"', self.target.read_text())
        self.assertEqual(len(list(self.directory.glob("*.coderails-bak-*"))), 1)

    def test_changed_or_ambiguous_shapes_remain_untouched(self) -> None:
        """Zero or multiple canonical blocks warn on every run without any modification."""
        for content in ("no recognized block\n", self.vendor + self.vendor):
            self.target.write_text(content)
            for _ in range(2):
                result = self.run_guard(REMEMBER_INJECT_CAP_AUTOWRITE="1")
                self.assertIn("shape", result.stdout)
                self.assertEqual(self.target.read_text(), content)
            self.assertEqual(list(self.directory.glob("*.coderails-bak-*")), [])

    def test_missing_target_and_patch_text_fail_open(self) -> None:
        """Unreadable inputs do not create targets or rewrite unverified content."""
        before = self.target.read_text()
        missing = self.directory / "absent"
        self.run_guard(REMEMBER_HOOK_FILE=str(missing), REMEMBER_INJECT_CAP_AUTOWRITE="1")
        self.assertFalse(missing.exists())
        result = self.run_guard(REMEMBER_PATCH_DIR=str(missing), REMEMBER_INJECT_CAP_AUTOWRITE="1")
        self.assertIn("canonical patch text", result.stdout)
        self.assertEqual(self.target.read_text(), before)

    def test_unverified_rewrite_is_refused(self) -> None:
        """A replacement missing actual cap evidence never replaces the target."""
        patches = self.directory / "patches"
        patches.mkdir()
        (patches / "remember_inject_cap.vendor.txt").write_text(self.vendor)
        (patches / "remember_inject_cap.patched.txt").write_text("no cap\n")
        before = self.target.read_text()
        result = self.run_guard(REMEMBER_PATCH_DIR=str(patches), REMEMBER_INJECT_CAP_AUTOWRITE="1")
        self.assertIn("did not verify", result.stdout)
        self.assertEqual(self.target.read_text(), before)
        self.assertEqual(list(self.directory.glob("*.coderails-tmp.*")), [])

    def test_unwritable_stamp_location_still_warns(self) -> None:
        """Warning persistence failure never hides the notice or edits plugin content."""
        blocker = self.directory / "blocker"
        blocker.write_text("not a directory")
        before = self.target.read_text()
        result = self.run_guard(REMEMBER_INJECT_STATE_DIR=str(blocker / "child"))
        self.assertIn("does not have", result.stdout)
        self.assertEqual(self.target.read_text(), before)

    def test_manifest_user_scope_and_cache_version_resolution(self) -> None:
        """User install takes precedence, then numeric newest cache is selected."""
        plugins = self.directory / "plugins"
        plugins.mkdir()
        installs: list[dict[str, str]] = []
        for version, scope in (("0.1.0", "project"), ("2.0.0", "user")):
            path = plugins / version / "scripts"
            path.mkdir(parents=True)
            (path / "session-start-hook.sh").write_text(self.target.read_text())
            installs.append({"scope": scope, "version": version, "installPath": str(path.parent)})
        (plugins / "installed_plugins.json").write_text(json.dumps({"plugins": {"remember@test": installs}}))
        result = self.run_guard(
            REMEMBER_HOOK_FILE="", CLAUDE_PLUGINS_DIR=str(plugins), REMEMBER_INJECT_CAP_AUTOWRITE="1"
        )
        self.assertIn("2.0.0", result.stdout)
        self.assertNotIn("head -c", (plugins / "0.1.0/scripts/session-start-hook.sh").read_text())
        self.assertIn("head -c", (plugins / "2.0.0/scripts/session-start-hook.sh").read_text())
        (plugins / "installed_plugins.json").unlink()
        for version in ("0.8.3", "0.10.0"):
            path = plugins / "cache/test/remember" / version / "scripts"
            path.mkdir(parents=True)
            (path / "session-start-hook.sh").write_text(self.target.read_text())
        result = self.run_guard(
            REMEMBER_HOOK_FILE="", CLAUDE_PLUGINS_DIR=str(plugins), REMEMBER_INJECT_CAP_AUTOWRITE="1"
        )
        self.assertIn("0.10.0", result.stdout)
        self.assertNotIn("head -c", (plugins / "cache/test/remember/0.8.3/scripts/session-start-hook.sh").read_text())

    def test_absent_plugin_is_silent(self) -> None:
        """Machines without the third-party plugin receive no warning."""
        self.assertEqual(
            self.run_guard(REMEMBER_HOOK_FILE="", CLAUDE_PLUGINS_DIR=str(self.directory / "absent")).stdout, ""
        )

    def test_real_vendor_block_truncates_memory(self) -> None:
        """Execute the third-party block to verify byte caps and small-file preservation."""
        self.run_guard(REMEMBER_INJECT_CAP_AUTOWRITE="1")
        memory = self.directory / "memory"
        memory.mkdir()
        (memory / "now.md").write_text("x" * 50_000)
        (memory / "identity.md").write_text("small identity")
        source = self.patched
        # The block belongs to an external Bash plugin; executing it verifies the patch's actual target contract.
        for cap in (8000, 100):
            result = subprocess.run(
                ["/bin/bash", "-c", source],
                text=True,
                capture_output=True,
                check=False,
                env={
                    **self.environment,
                    "IDENTITY_FILE": str(memory / "identity.md"),
                    "REMEMBER_NOW": str(memory / "now.md"),
                    "REMEMBER_INJECT_MAX_BYTES": str(cap),
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("x" * cap, result.stdout)
            self.assertNotIn("x" * (cap + 1), result.stdout)
            self.assertIn("small identity", result.stdout)


if __name__ == "__main__":
    unittest.main()
