#!/usr/bin/env python3
"""Retain cost-report shape, honest failure, date staleness, and sanitization contracts."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_completion import cost_message, validate_completion
from hooks.scripts.lib.loop_state_common import LoopState
from hooks.scripts.tests.lib import assembled_retro
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib import retro, teardown_steps


def prepared_retro(state_dir: Path, session: str) -> dict[str, Any]:
    """Create a real retro whose preparation receipt binds the fixture's current owner and source."""
    assembled_retro.write(state_dir, session)
    path = state_dir / "progress.json"
    state: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    loop_id = str(state["loop_id"])
    source = dict(state)
    for key in ("status", "completion", "completed_marker"):
        source.pop(key, None)
    if isinstance(source.get("loop_stop_counts"), dict):
        source["loop_stop_counts"].pop("complete", None)
    binding = {
        "repo_dir": str(state_dir.parent.resolve()),
        "state_dir": str(state_dir.resolve()),
        "session_id": session,
        "loop_id": loop_id,
        "revision": state["revision"],
        "progress_sha256": teardown_steps.sha_json(source),
    }
    prepared: dict[str, Any] = {"schema": 1, "binding": binding, "records": []}
    prep_path = state_dir / f"orders-prepared-{hashlib.sha256(loop_id.encode()).hexdigest()}.json"
    prep_path.write_text(json.dumps(prepared), encoding="utf-8")
    row = {
        "step": "orders_prepared",
        "session_id": session,
        "loop_id": loop_id,
        "revision": state["revision"],
        "binding": binding,
        "evidence_sha256": teardown_steps.sha_json(prepared),
        "ts": "2026-10-19T00:00:00+00:00",
    }
    with (state_dir / teardown_steps.NAME).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    with patch.dict(os.environ, {"PATH": "/nonexistent"}):
        payload, code = retro.assemble(state_dir, session)
    if code == 2:
        raise AssertionError(payload)
    return cast("dict[str, Any]", json.loads((state_dir / "retro.json").read_text(encoding="utf-8")))


class CostReportTests(HookTestCase):
    """Cost output never fabricates missing figures or promotes a date check to rate verification."""

    def test_schema_and_cost_presence(self) -> None:
        """Version and absent/empty/incomplete distinctions remain externally observable."""
        for version in (None, "2", True, 0, 1, 1.9):
            self.assertEqual(cost_message({"schema_version": version}), "")
        for version in (2, 2.0, 2.5, 99):
            self.assertEqual(cost_message({"schema_version": version}), "cost not recorded")
            self.assertIn("miner returned no data", cost_message({"schema_version": version, "cost": {}}))
        for missing in ("total_tokens", "total_usd_estimate"):
            cost: dict[str, Any] = {"total_tokens": 500, "total_usd_estimate": 0.123456}
            cost.pop(missing)
            message = cost_message({"schema_version": 2, "cost": cost})
            self.assertIn("incomplete", message)
            self.assertIn(missing, message)
            self.assertNotIn("$", message)

    def test_scalar_shape_controls_and_rounding(self) -> None:
        """Containers, booleans, and missing fields cannot become a fabricated cost."""
        invalid: list[object] = [[], {}, True, None, ""]
        cost: dict[str, Any]
        for name in ("total_tokens", "total_usd_estimate"):
            for value in invalid:
                cost = {"total_tokens": 500, "total_usd_estimate": 1.23456, name: value}
                self.assertIn("incomplete", cost_message({"schema_version": 2, "cost": cost}))
        cost = {"total_tokens": 500, "total_usd_estimate": 1.23456, "prices_as_of": []}
        message = cost_message({"schema_version": 2, "cost": cost})
        self.assertIn("$1.23", message)
        self.assertNotIn("1.23456", message)
        self.assertEqual(len(message.splitlines()), 1)
        cost["total_usd_estimate"] = "not numeric"
        self.assertIn("not numeric", cost_message({"schema_version": 2, "cost": cost}))
        self.assertNotIn("$0.00", cost_message({"schema_version": 2, "cost": cost}))

    def test_dates_and_control_character_stripping(self) -> None:
        """Fresh/stale/future/malformed dates preserve figures and truthful caveats."""
        for age in (5, 45, -5):
            date = (datetime.now(timezone.utc) - timedelta(days=age)).strftime("%Y-%m-%d")
            message = cost_message(
                {"schema_version": 2, "cost": {"total_tokens": 500, "total_usd_estimate": 1.25, "prices_as_of": date}}
            )
            self.assertIn("$1.25", message)
            self.assertEqual("verify at" in message, age == 45)
            self.assertEqual("future" in message, age == -5)
            self.assertNotIn("rates are wrong", message)
        for date in ("bad-date", "2020-01-01junk", "\x1b[31m\nhello\t\v\f"):
            message = cost_message(
                {"schema_version": 2, "cost": {"total_tokens": 500, "total_usd_estimate": 1.25, "prices_as_of": date}}
            )
            self.assertIn("$1.25", message)
            self.assertNotIn("days old", message)
            self.assertNotIn("verify at", message)
            self.assertTrue(all(character.isprintable() for character in message))

    def test_shipped_price_date_and_staleness_boundary(self) -> None:
        """The shipped table's date warns only after fourteen complete days."""
        table = Path(__file__).resolve().parents[1] / "lib/model_prices.json"
        date = json.loads(table.read_text())["prices_as_of"]
        stamp = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        retro = {"schema_version": 2, "cost": {"total_tokens": 42, "total_usd_estimate": 1, "prices_as_of": date}}
        for age in (14, 15):
            with self.subTest(age=age), patch("hooks.scripts.lib.loop_completion.datetime") as clock:
                clock.strptime.side_effect = datetime.strptime
                clock.now.return_value = stamp + timedelta(days=age)
                message = cost_message(retro)
                self.assertIn(f"prices as of {date}, {age} days old", message)
                self.assertEqual("verify at" in message, age > 14)
        actual = cost_message(retro)
        age = int((datetime.now(timezone.utc) - stamp).total_seconds() / 86400)
        self.assertIn(date, actual)
        self.assertEqual("verify at" in actual, age > 14)

    def test_outcome_logs_are_fixed_tokens_without_retro_injection(self) -> None:
        """Every report class logs a bounded outcome and no untrusted artifact values."""
        path = self.progress(proof_disposition="none: no executable surface")
        state = LoopState(path, self.session, 1, json.loads(path.read_text()))
        base = prepared_retro(path.parent, self.session)  # cost is not hashed, so it can vary after assembly
        absent = {key: value for key, value in base.items() if key != "cost"}
        rows: list[tuple[dict[str, Any], str]] = [
            (absent, "cost_absent"),
            ({**base, "cost": {}}, "miner_failed_open"),
            ({**base, "cost": {"total_tokens": 42}}, "cost_incomplete"),
            (
                {
                    **base,
                    "cost": {"total_tokens": 42, "total_usd_estimate": 1, "prices_as_of": "hostile\nkey=value"},
                },
                "reported",
            ),
        ]  # a schema below 2 can no longer reach the reporter: the retro gate refuses it first
        with patch.dict(os.environ, self.environment):
            for retro, outcome in rows:
                path.with_name("retro.json").write_text(json.dumps(retro))
                validate_completion(state, "unused")
                text = (self.directory / "discipline.log").read_text()
                self.assertIn("cost_report=" + outcome, text)
                self.assertNotIn("hostile", text)
                self.assertNotIn("key=value", text)


if __name__ == "__main__":
    unittest.main()
