"""Existing-unit disposition guards preserve graph bytes on refusal."""

from __future__ import annotations

import json
import unittest

from packages.tests.test_provider_controller_commands import ControllerCase


class ExistingDispositionGuards(ControllerCase):
    """Exercise both provider CLIs against independent adverse graph states."""

    def test_context_and_pair_refusals_leave_state_unchanged(self) -> None:
        """Reject stale/foreign callers and incomplete compatibility choices."""
        for c in self.each():
            c.start()
            c.add("1")
            revision = str(c.read()["revision"])
            common = ("--unit", "1", "--source-ref", "PR #504")
            cases = (
                ("sess-1", "loop-a", "0", "clean-break", ()),
                ("sess-1", "foreign", revision, "clean-break", ()),
                ("sess-1", "loop-a", revision, "preserve-compat", ()),
                ("sess-1", "loop-a", revision, "preserve-compat", ("--named-blocker", "frozen API")),
                ("sess-1", "loop-a", revision, "preserve-compat", ("--removal-ticket", "OPS-42")),
                ("sess-1", "loop-a", revision, "clean-break", ("--removal-ticket", "OPS-42")),
            )
            before = c.path.read_bytes()
            for session, loop, version, kind, extra in cases:
                with self.subTest(provider=c.name, loop=loop, revision=version, kind=kind, extra=extra):
                    result = c.run(
                        "set-unit-disposition",
                        "--session",
                        session,
                        "--loop-id",
                        loop,
                        "--revision",
                        version,
                        "--disposition",
                        kind,
                        *common,
                        *extra,
                    )
                    self.refused(result, "set_disposition_refused")
                    self.assertEqual(c.path.read_bytes(), before)

    def test_repeated_disposition_is_refused_in_both_orders(self) -> None:
        """Contradictory choices cannot silently select the final flag."""
        for c in self.each():
            c.start()
            c.add("1")
            before = c.path.read_bytes()
            for first, second in (("clean-break", "preserve-compat"), ("preserve-compat", "clean-break")):
                result = c.run(
                    "set-unit-disposition",
                    "--session",
                    "sess-1",
                    "--loop-id",
                    "loop-a",
                    "--revision",
                    str(c.read()["revision"]),
                    "--unit",
                    "1",
                    "--source-ref",
                    "PR #504",
                    "--disposition",
                    first,
                    "--disposition",
                    second,
                )
                self.refused(result, "set_disposition_refused")
                self.assertEqual(c.path.read_bytes(), before)

    def test_nonpending_existing_choice_and_active_wave_are_refused(self) -> None:
        """A closed unit, prior choice or active dispatch cannot be rewritten."""
        for c in self.each():
            c.start()
            c.add("1")
            original = c.path.read_text()
            for condition in ("done", "dropped", "existing-choice", "active-wave"):
                state = json.loads(original)
                if condition in {"done", "dropped"}:
                    state["work_units"]["1"].update(status=condition, dropped_reason="fixture")
                elif condition == "existing-choice":
                    state["work_units"]["1"]["disposition"] = {"kind": "clean-break"}
                else:
                    state["graph"]["nodes"]["U3[1]"]["status"] = "running"
                    state["graph"]["active_wave"] = {
                        "wave_id": "wave-1",
                        "revision": state["revision"],
                        "nodes": ["U3[1]"],
                        "transcript_cursor": 0,
                    }
                c.path.write_text(json.dumps(state))
                before = c.path.read_bytes()
                with self.subTest(provider=c.name, condition=condition):
                    result = c.run(
                        "set-unit-disposition",
                        "--session",
                        "sess-1",
                        "--loop-id",
                        "loop-a",
                        "--revision",
                        str(state["revision"]),
                        "--unit",
                        "1",
                        "--disposition",
                        "clean-break",
                        "--source-ref",
                        "PR #504",
                    )
                    self.refused(result, "set_disposition_refused")
                    self.assertEqual(c.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
