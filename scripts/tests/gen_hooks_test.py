"""The hook registry owns both registrations and the marked source tables."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from collections.abc import Callable
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from scripts import gen_hooks

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "hooks/registry.json",
    "hooks/messages.json",
    "hooks/overlays/claude.json",
    "hooks/overlays/codex.json",
    "hooks/hooks.json",
    "packages/codex/hooks/hooks.json",
    "packages/codex/hooks/messages.json",
    "scripts/lib/memory_reasons.py",
    "AGENTS.md",
    "README.md",
    "docs/RUNBOOK.md",
)


class HookGenerationTests(unittest.TestCase):
    """Check source coverage and generated-byte drift."""

    def setUp(self) -> None:
        """Copy generated inputs and outputs into an isolated fixture."""
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        catalog = json.loads((ROOT / "hooks/messages.json").read_text())
        reason_sources = {item["source"] for item in catalog["reasons"].values()}
        for directory in ("hooks/scripts", "packages/codex/hooks/scripts"):
            reason_sources.update(str(path.relative_to(ROOT)) for path in (ROOT / directory).glob("*.py"))
        for name in (*FILES, *sorted(reason_sources)):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)

    def check(self) -> int:
        """Run the generator in read-only check mode."""
        with redirect_stdout(StringIO()):
            return gen_hooks.main(["--root", str(self.root), "--check"])

    def edit_json(self, name: str, change: Callable[[dict[str, Any]], object]) -> None:
        """Change one fixture source and keep it valid JSON."""
        path = self.root / name
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data, indent=2) + "\n")

    def test_current_generated_files_match_registry(self) -> None:
        """The committed outputs match the canonical registry."""
        self.assertEqual(self.check(), 0)
        catalog = json.loads((self.root / "hooks/messages.json").read_text())
        self.assertEqual(catalog["memory_source"], "scripts/lib/memory_reasons.py")
        self.assertIn("| memory | `muninn_absent` |", (self.root / "docs/RUNBOOK.md").read_text())

    def test_missing_provider_refuses(self) -> None:
        """A missing provider cannot silently drop its hooks."""
        self.edit_json("hooks/registry.json", lambda data: data["provider_overlays"].pop("codex"))
        self.assertEqual(self.check(), 2)

    def test_missing_hook_refuses(self) -> None:
        """A control must remain registered for its declared provider."""
        self.edit_json("hooks/overlays/claude.json", lambda data: data["hooks"]["SessionStart"][0]["hooks"].pop())
        self.assertEqual(self.check(), 2)

    def test_missing_reason_refuses(self) -> None:
        """Every control must have a reason and action."""
        self.edit_json("hooks/messages.json", lambda data: data["hooks"].pop("inject_bootstrap"))
        self.assertEqual(self.check(), 2)

    def test_omitted_emitted_reason_refuses(self) -> None:
        """Deleting a source-emitted reason must invalidate the catalog."""
        self.edit_json("hooks/messages.json", lambda data: data["reasons"].pop("authority_deny"))
        self.assertEqual(self.check(), 2)

    def test_explicit_hook_emitter_keeps_reason_coverage(self) -> None:
        """The routed autonomous hook stays covered with either its local alias or explicit API name."""
        path = self.root / "hooks/scripts/autonomous_gate.py"
        source = path.read_text()
        self.assertIn("import append_hook_row as append_row", source)
        self.assertIn("authority_deny", gen_hooks.emitted_reasons(path))
        path.write_text(
            source.replace("append_hook_row as append_row", "append_hook_row").replace(
                "append_row(", "append_hook_row("
            )
        )
        self.assertIn("authority_deny", gen_hooks.emitted_reasons(path))
        self.edit_json("hooks/messages.json", lambda data: data["reasons"].pop("authority_deny"))
        self.assertEqual(self.check(), 2)

    def test_registered_source_missing_refuses(self) -> None:
        """A registered hook must have an actual implementation."""
        (self.root / "hooks/scripts/inject_bootstrap.py").unlink()
        self.assertEqual(self.check(), 2)

    def test_unemitted_reason_refuses(self) -> None:
        """The reason view cannot assert a code absent from its source."""
        self.edit_json(
            "hooks/messages.json",
            lambda data: data["reasons"].update(
                {"made_up_code": {"source": "hooks/scripts/autonomous_gate.py", "remediation": "Retry."}}
            ),
        )
        self.assertEqual(self.check(), 2)

    def test_codex_reason_source_is_checked(self) -> None:
        """Codex-only reasons must come from a real native hook source."""
        self.edit_json(
            "hooks/messages.json",
            lambda data: data["reasons"]["codex_native_worker_uncontained"].update(
                {"source": "packages/codex/hooks/scripts/autonomous_gate.py"}
            ),
        )
        self.assertEqual(self.check(), 2)

    def test_malformed_entry_refuses(self) -> None:
        """Invalid timeout values cannot enter the registration."""
        self.edit_json(
            "hooks/overlays/codex.json",
            lambda data: data["hooks"]["Stop"][0]["hooks"][0].update({"timeout": 0}),
        )
        self.assertEqual(self.check(), 2)

    def test_unhashable_mode_refuses_without_crashing(self) -> None:
        """Malformed structured fields return the documented refusal code."""
        self.edit_json("hooks/registry.json", lambda data: data["controls"]["test_gate"].update({"mode": []}))
        self.assertEqual(self.check(), 2)

    def test_shell_text_after_command_refuses(self) -> None:
        """A registered command cannot append shell operations after the script."""
        self.edit_json(
            "hooks/overlays/claude.json",
            lambda data: data["hooks"]["SessionStart"][0]["hooks"][0].update(
                {"command": '"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/inject_bootstrap.py" && echo MALFORMED'}
            ),
        )
        self.assertEqual(self.check(), 2)

    def test_wrong_order_or_hand_edit_is_stale(self) -> None:
        """The check detects reordered hooks and edited prose."""
        path = self.root / "hooks/hooks.json"
        data = json.loads(path.read_text())
        hooks = data["hooks"]["Stop"][0]["hooks"]
        hooks[0], hooks[1] = hooks[1], hooks[0]
        path.write_text(json.dumps(data, indent=2) + "\n")
        self.assertEqual(self.check(), 1)
        shutil.copyfile(ROOT / "hooks/hooks.json", path)
        readme = self.root / "README.md"
        readme.write_text(readme.read_text().replace("registered for its provider event", "hand edited", 1))
        self.assertEqual(self.check(), 1)

    def test_default_and_advisory_modes_are_declared(self) -> None:
        """The catalog preserves optional controls and advisory modes."""
        registry = json.loads((self.root / "hooks/registry.json").read_text())
        controls = registry["controls"]
        self.assertIn("off by default", controls["action_authority_gate"]["activation"])
        self.assertIn("off unless", controls["test_gate"]["activation"])
        self.assertEqual(controls["check_confidence_labels"]["mode"], "advisory")
        self.assertEqual(controls["check_verify_loop"]["mode"], "advisory")

    def test_matcher_pipe_is_escaped_once(self) -> None:
        """A generated Markdown matcher stays in one table cell."""
        table = (self.root / "AGENTS.md").read_text()
        self.assertIn("startup\\|resume\\|clear\\|compact", table)
        self.assertNotIn("startup\\\\|resume", table)


if __name__ == "__main__":
    unittest.main()
