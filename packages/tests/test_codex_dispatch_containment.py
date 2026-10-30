"""Default worker containment remains additive to native dispatch authorization."""

from __future__ import annotations

import unittest
from pathlib import Path

from packages.tests.codex_dispatch_fixture import DispatchFixture


class NativeContainmentTests(DispatchFixture):
    """Exercise containment settings through the actual native guard fixture."""

    def test_invalid_typed_config_blocks_native_worker_dispatch(self) -> None:
        """A misspelled sandbox control cannot reach Codex's actual spawn gate."""
        config = Path(self.scratch.name) / "workflow.config.yaml"
        config.write_text("sandbox_workerz: true\n", encoding="utf-8")
        self.assertEqual(self._run(config=config), (True, 0))

    def test_valid_default_sandbox_setting_preserves_scout_dispatch(self) -> None:
        """The containment rule applies to implementation work, not scout dispatch."""
        config = Path(self.scratch.name) / "workflow.config.yaml"
        config.write_text("sandbox_workers: true\n", encoding="utf-8")
        self.assertEqual(self._run(config=config), (False, 1))

    def test_default_containment_refuses_native_implementation(self) -> None:
        """Native implementation inherits the parent sandbox and must not bypass the separate process."""
        self.tool_input["message"] = self.tool_input["message"].replace('"S2"', '"U3[1]"')
        self.assertEqual(self._run(), (True, 0))

    def test_explicit_containment_off_allows_native_implementation(self) -> None:
        """The owner can make the documented opt-out in the workflow config."""
        self.tool_input["message"] = self.tool_input["message"].replace('"S2"', '"U3[1]"')
        config = Path(self.scratch.name) / "workflow.config.yaml"
        config.write_text("sandbox_workers: false\n", encoding="utf-8")
        self.assertEqual(self._run(config=config), (False, 1))

    def test_opaque_implementation_cannot_bypass_containment(self) -> None:
        """Resolve an encrypted worker's node from the graph's issued task mapping."""
        self.tool_input["message"] = "gAAAAABopaque"
        self.assertEqual(self._run(inspection_node="U3[1]"), (True, 0))
        config = Path(self.scratch.name) / "workflow.config.yaml"
        config.write_text("sandbox_workers: false\n", encoding="utf-8")
        self.assertEqual(self._run(config=config, inspection_node="U3[1]"), (False, 1))


if __name__ == "__main__":
    unittest.main()
