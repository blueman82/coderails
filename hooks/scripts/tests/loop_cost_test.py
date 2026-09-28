#!/usr/bin/env python3
"""Verify linked Claude usage, deduplication, pricing, and malformed-record recovery."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_cost import mine_token_usage
from hooks.scripts.tests.lib.hook_test_support import HookTestCase


class LoopCostTests(HookTestCase):
    """Keep native message IDs, linked worker attribution, and pricing provenance."""

    def setUp(self) -> None:
        """Create a price table and one private project transcript directory."""
        super().setUp()
        self.projects = self.directory / "projects"
        self.project = self.projects / "project"
        self.project.mkdir(parents=True)
        self.prices = self.directory / "prices.json"
        self.prices.write_text(
            json.dumps(
                {
                    "prices_as_of": "2026-09-01",
                    "price_source": "fixture",
                    "per_mtok": {
                        "opus": {
                            "input": 5,
                            "output": 25,
                            "cache_read": 0.5,
                            "cache_write_5m": 6.25,
                            "cache_write_1h": 10,
                        },
                        "haiku": {
                            "input": 1,
                            "output": 5,
                            "cache_read": 0.1,
                            "cache_write_5m": 1.25,
                            "cache_write_1h": 2,
                        },
                    },
                }
            )
        )
        self.environment.update(
            {"CLAUDE_PROJECTS_DIR": str(self.projects), "CLAUDE_MODEL_PRICES_FILE": str(self.prices)}
        )

    def write_usage(self, path: Path, identifier: str, model: str, **usage: object) -> None:
        """Append one native assistant usage record."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as stream:
            stream.write(
                json.dumps({"type": "assistant", "message": {"id": identifier, "model": model, "usage": usage}}) + "\n"
            )

    def test_dedupe_linked_workers_and_model_rollup(self) -> None:
        """Repeated message IDs count once and recursively linked worker models are included."""
        parent = self.project / "S1.jsonl"
        for _ in range(10):
            self.write_usage(parent, "m1", "opus", input_tokens=100, output_tokens=50)
        worker = self.project / "S1/subagents/nested/worker.jsonl"
        self.write_usage(worker, "m2", "haiku", input_tokens=200, output_tokens=75)
        self.write_usage(parent, "synthetic", "<synthetic>", input_tokens=1_000_000)
        with patch.dict(os.environ, self.environment):
            result = mine_token_usage("S1")
        self.assertEqual(result["models_used"], ["haiku", "opus"])
        self.assertEqual(result["transcripts_scanned"], 2)
        self.assertEqual(result["per_model"]["opus"]["input_tokens"], 100)
        self.assertEqual(result["per_model"]["opus"]["output_tokens"], 50)
        self.assertEqual(result["total_tokens"], 425)
        self.assertAlmostEqual(result["total_usd_estimate"], 0.002325)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["prices_as_of"], "2026-09-01")

    def test_cache_split_flat_cache_and_dated_price_lookup(self) -> None:
        """Each cache bucket uses its own rate and dated IDs retain their native keys."""
        parent = self.project / "S1.jsonl"
        self.write_usage(parent, "5m", "opus", cache_creation={"ephemeral_5m_input_tokens": 1_000_000})
        self.write_usage(parent, "1h", "opus", cache_creation={"ephemeral_1h_input_tokens": 1_000_000})
        self.write_usage(parent, "flat", "opus", cache_creation_input_tokens=1_000_000)
        self.write_usage(parent, "dated", "haiku-20251001", input_tokens=1_000_000)
        self.write_usage(parent, "unknown", "other", input_tokens=111)
        with patch.dict(os.environ, self.environment):
            result = mine_token_usage("S1")
        opus = result["per_model"]["opus"]
        self.assertEqual(opus["cache_write_5m_tokens"], 2_000_000)
        self.assertEqual(opus["cache_write_1h_tokens"], 1_000_000)
        self.assertEqual(opus["usd_estimate"], 22.5)
        self.assertEqual(result["per_model"]["haiku-20251001"]["usd_estimate"], 1)
        self.assertEqual(result["per_model"]["other"]["input_tokens"], 111)
        self.assertEqual(result["per_model"]["other"]["usd_estimate"], 0)
        self.assertEqual(result["unpriced_models"], ["other"])

    def test_malformed_lines_and_numeric_leaves_are_local(self) -> None:
        """Garbage, wrong-shaped records, missing IDs, and bad leaves do not wipe good usage."""
        parent = self.project / "S1.jsonl"
        parent.write_text('bad\n"scalar"\n{"type":"assistant","message":"wrong"}\n')
        self.write_usage(parent, "good", "opus", input_tokens=100, output_tokens=50)
        self.write_usage(
            parent,
            "wrong",
            "opus",
            input_tokens="bad",
            output_tokens=5,
            cache_creation="bad",
            cache_creation_input_tokens=500,
        )
        with parent.open("a") as stream:
            stream.write('{"type":"assistant","message":{"model":"opus","usage":{"input_tokens":999}}}\n')
        with patch.dict(os.environ, self.environment):
            result = mine_token_usage("S1")["per_model"]["opus"]
        self.assertEqual(result["input_tokens"], 100)
        self.assertEqual(result["output_tokens"], 55)
        self.assertEqual(result["cache_write_5m_tokens"], 500)

    def test_headless_sibling_window_boundaries_and_default(self) -> None:
        """Sibling counts use absolute time distance, inclusive bounds and a safe default."""
        parent = self.project / "S1.jsonl"
        self.write_usage(parent, "parent", "opus", input_tokens=42)
        stamp = 1_700_000_000
        os.utime(parent, (stamp, stamp))
        with patch.dict(os.environ, self.environment):
            self.assertEqual(mine_token_usage("S1")["headless_children_excluded_count"], 0)
        sibling = self.project / "other.jsonl"
        self.write_usage(sibling, "unlinked", "opus", input_tokens=9999)
        for setting, width in (("3600", 3600), ("invalid", 3600), ("-1", 3600), ("", 3600), ("10", 10)):
            for delta in (-width - 1, -width, -1, 0, width, width + 1):
                with self.subTest(setting=setting, delta=delta):
                    os.utime(sibling, (stamp + delta, stamp + delta))
                    environment = self.environment | {"CLAUDE_HEADLESS_WINDOW_SECS": setting}
                    with patch.dict(os.environ, environment):
                        result = mine_token_usage("S1")
                    self.assertEqual(result["headless_children_excluded_count"], int(abs(delta) <= width))
                    self.assertEqual(result["total_tokens"], 42)

    def test_missing_inputs_traversal_and_headless_exclusion(self) -> None:
        """Errors remain advisory; sanitized IDs and activity-window siblings stay bounded."""
        self.write_usage(self.project / "__S1.jsonl", "good", "opus", input_tokens=42)
        self.write_usage(self.project / "other.jsonl", "sibling", "opus", input_tokens=9999)
        with patch.dict(os.environ, self.environment):
            self.assertIn("error", mine_token_usage(""))
            self.assertIn("error", mine_token_usage("missing"))
            result = mine_token_usage("../../S1")
            self.assertEqual(result["total_tokens"], 42)
            self.assertEqual(result["headless_children_excluded_count"], 1)
            self.prices.unlink()
            self.assertEqual(mine_token_usage("__S1"), {})


if __name__ == "__main__":
    unittest.main()
