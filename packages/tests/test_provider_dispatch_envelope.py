"""One attack table against both providers' dispatch guards: every defect is denied with its own reason code."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/graph-semantics"))
from hooks.scripts.tests.lib import claude_transcript_fixture as claude
from packages.tests.provider_fixture import Provider

SECTIONS = 'model_role: "default"'


def field(provider: Provider) -> str:
    """The provider's prompt field."""
    return "prompt" if provider.name == "claude" else "message"


def envelope_edit(request: dict[str, Any], provider: Provider, **changes: object) -> None:
    """Rewrite fields of the first-line envelope in place."""
    text = request["tool_input"][field(provider)]
    first, rest = text.split("\n", 1)
    key, raw = first.split("=", 1)
    parsed = json.loads(raw)
    parsed.update(changes)
    request["tool_input"][field(provider)] = key + "=" + json.dumps(parsed, sort_keys=True) + "\n" + rest


def edit_prompt(request: dict[str, Any], provider: Provider, old: str, new: str) -> None:
    """Replace text in the pasted prompt, asserting the replacement happened."""
    text = request["tool_input"][field(provider)]
    assert old in text, old
    request["tool_input"][field(provider)] = text.replace(old, new)


class DispatchEnvelopeTests(unittest.TestCase):
    """The same table, run through the real hook of each provider."""

    def setUp(self) -> None:
        """Isolated provider homes."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.count = 0

    def opened(self, name: str, nodes: tuple[str, ...] = ("U3[1]",)) -> Provider:
        """A provider with an active wave over `nodes` (one fresh home per call)."""
        provider = self.fresh(name)
        provider.write(provider.state(nodes))
        provider.success("begin-wave")
        return provider

    def fresh(self, name: str) -> Provider:
        """A provider in its own numbered directory."""
        self.count += 1
        base = self.root / str(self.count)
        base.mkdir()
        return Provider(base, name)

    def reason(self, provider: Provider) -> str:
        """The reason code of the last trace row."""
        rows = provider.path.with_name("recovery-trace.jsonl").read_text().splitlines()
        return str(json.loads(rows[-1])["reason_code"])

    def verdict(self, provider: Provider, request: dict[str, Any]) -> bool:
        """True when the real hook denied the request."""
        result = provider.hook("loop_dispatch_guard", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        return bool(result.stdout) and json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"

    def refuse(self, provider: Provider, request: dict[str, Any], code: str) -> None:
        """Denied with this reason code and zero state change."""
        before = provider.path.read_bytes()
        self.assertTrue(self.verdict(provider, request), (provider.name, code))
        self.assertEqual(provider.path.read_bytes(), before, (provider.name, code))
        self.assertEqual(self.reason(provider), code, provider.name)

    def typed(self, provider: Provider, request: dict[str, Any], role: str) -> None:
        """Dispatch as the provider's typed agent for `role`."""
        if provider.name == "claude":
            request["tool_input"]["subagent_type"] = "coderails:" + role
        else:
            request["tool_input"]["agent_type"] = role

    def untyped(self, provider: Provider, request: dict[str, Any], kind: str) -> None:
        """Dispatch as an untyped / other-role agent."""
        if provider.name == "claude":
            request["tool_input"]["subagent_type"] = kind
        else:
            request["tool_input"].pop("agent_type", None)
            if kind != "general-purpose":
                request["tool_input"]["agent_type"] = kind.split(":")[-1]

    def each(self, case: Callable[[Provider], None]) -> None:
        """Run a case on both providers."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                case(self.opened(name))

    def test_correct_dispatch_passes_and_is_recorded(self) -> None:
        """A faithful dispatch is allowed once and the record notes its authorization."""

        def case(provider: Provider) -> None:
            provider.environment["CODERAILS_A6_EVIDENCE_WRITE"] = "off"
            self.assertFalse(self.verdict(provider, provider.request()))
            state = provider.read()
            record = next(iter(state["graph"]["dispatches"].values()))
            self.assertEqual(record["authorized"], {"tool_use_id": None})
            self.assertEqual(record["envelope_version"], 2)
            self.assertEqual(record["contract"]["role"], "loop-worker")
            self.assertEqual(self.reason(provider), "dispatch_authorized")

        self.each(case)

    def test_codex_authorization_binds_call_id_after_rollout(self) -> None:
        """The enabled reader records the exact native call ID."""
        provider = self.opened("codex")
        request = provider.request()
        provider.environment["CODERAILS_A6_EVIDENCE_WRITE"] = "on"
        self.assertFalse(self.verdict(provider, request))
        record = next(iter(provider.read()["graph"]["dispatches"].values()))
        self.assertEqual(record["authorized"], {"tool_use_id": request["tool_use_id"]})

    def test_missing_contract_field_in_the_stored_record(self) -> None:
        """A record whose contract lost a field no longer authorizes anything."""

        def case(provider: Provider) -> None:
            request = provider.request()
            state = provider.read()
            record = next(iter(state["graph"]["dispatches"].values()))
            del record["contract"]["write_scope"]
            provider.write(state)
            self.refuse(provider, request, "dispatch_contract_altered")

        self.each(case)

    def test_altered_stored_contract_value_fails_the_sha_recompute(self) -> None:
        """A changed stored value (sha not updated) is caught by recomputing the digest from the stored contract."""

        def case(provider: Provider) -> None:
            request = provider.request()
            state = provider.read()
            next(iter(state["graph"]["dispatches"].values()))["contract"]["scope"] = "widened"
            provider.write(state)
            self.refuse(provider, request, "dispatch_contract_altered")

        self.each(case)

    def test_tampered_rendered_section_in_the_prompt(self) -> None:
        """One changed character inside the pasted block is a missing-sections denial."""

        def case(provider: Provider) -> None:
            request = provider.request()
            edit_prompt(request, provider, SECTIONS, 'model_role: "frontier"')
            self.refuse(provider, request, "dispatch_sections_missing")

        self.each(case)

    def test_removed_sections_with_a_valid_first_line(self) -> None:
        """A prompt keeping only the first envelope line (the old check) is refused."""

        def case(provider: Provider) -> None:
            request = provider.request()
            first = request["tool_input"][field(provider)].split("\n", 1)[0]
            request["tool_input"][field(provider)] = first + "\nWorker instructions."
            self.refuse(provider, request, "dispatch_sections_missing")

        self.each(case)

    def test_stale_revision(self) -> None:
        """An envelope minted for an older revision is stale."""

        def case(provider: Provider) -> None:
            request = provider.request()
            envelope_edit(request, provider, revision=1)
            self.refuse(provider, request, "dispatch_stale_revision")

        self.each(case)

    def test_foreign_session_loop_node_and_wave(self) -> None:
        """Every ownership field is cross-checked against the record and state."""
        for name in ("claude", "codex"):
            for key, value in (
                ("session_id", "other"),
                ("loop_id", "other"),
                ("node_id", "U3[2]"),
                ("wave_id", "wave-99"),
            ):
                with self.subTest(provider=name, key=key):
                    provider = self.opened(name)
                    request = provider.request()
                    envelope_edit(request, provider, **{key: value})
                    self.refuse(provider, request, "dispatch_foreign")

    def test_unknown_dispatch_id(self) -> None:
        """An id begin-wave never issued is unknown."""

        def case(provider: Provider) -> None:
            request = provider.request()
            envelope_edit(request, provider, dispatch_id="disp_forged")
            self.refuse(provider, request, "dispatch_unknown_id")

        self.each(case)

    def test_replayed_dispatch_id(self) -> None:
        """A second distinct tool use of an already authorized dispatch id is a replay."""

        def case(provider: Provider) -> None:
            request = provider.request()
            request["tool_use_id"] = "toolu_first"
            self.assertFalse(self.verdict(provider, request))
            replay = copy.deepcopy(request)
            replay["tool_use_id"] = "toolu_second"
            self.refuse(provider, replay, "dispatch_replayed")

        self.each(case)

    def test_missing_envelope(self) -> None:
        """In a graph-bound session even an arbitrary task name with no envelope is denied."""

        def case(provider: Provider) -> None:
            request = provider.request()
            request["tool_input"][field(provider)] = "Read the documentation."
            if provider.name == "codex":
                request["tool_input"]["task_name"] = "ordinary"
            self.refuse(provider, request, "dispatch_missing_envelope")

        self.each(case)

    def test_role_substitution_is_denied_and_the_typed_role_passes(self) -> None:
        """Guarded scouts need their own type; a worker node cannot run as a scout."""
        for name in ("claude", "codex"):
            for kind in ("general-purpose", "coderails:loop-worker"):
                with self.subTest(provider=name, kind=kind):
                    provider = self.opened(name, ("S2",))
                    request = provider.request()
                    self.untyped(provider, request, kind)
                    self.refuse(provider, request, "role_mismatch")
            with self.subTest(provider=name, kind="typed scout"):
                provider = self.opened(name, ("S2",))
                request = provider.request()
                self.typed(provider, request, "preflight-scout")
                self.assertFalse(self.verdict(provider, request))
            with self.subTest(provider=name, kind="worker as scout"):
                provider = self.opened(name)
                request = provider.request()
                self.typed(provider, request, "source-auditor")
                self.refuse(provider, request, "role_mismatch")

    def test_omitted_subagent_type_is_refused_before_native_evidence(self) -> None:
        """Claude cannot bind a native Agent call whose provider role is missing."""
        provider = self.opened("claude")
        request = provider.request()
        del request["tool_input"]["subagent_type"]
        self.refuse(provider, request, "role_mismatch")
        scout = self.opened("claude", ("S2",))
        request = scout.request()
        del request["tool_input"]["subagent_type"]
        self.refuse(scout, request, "role_mismatch")
        attempted = self.opened("claude")
        report = attempted.launch()
        lines = attempted.parent.read_text().splitlines()
        native = json.loads(lines[1])
        del native["message"]["content"][0]["input"]["subagent_type"]
        lines[1] = json.dumps(native)
        attempted.parent.write_text("\n".join(lines) + "\n")
        before = attempted.path.read_bytes()
        failed = attempted.call("record-wave", json.dumps(report))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("provider role", failed.stderr)
        self.assertEqual(attempted.path.read_bytes(), before)

    def test_codex_named_native_role_is_not_generic(self) -> None:
        """An unguarded worker may omit agent_type, but cannot silently become explorer."""
        provider = self.opened("codex")
        request = provider.request()
        request["tool_input"]["agent_type"] = "explorer"
        self.refuse(provider, request, "role_mismatch")

    def test_off_switch_preserves_v2_ownership_with_a_trace_row(self) -> None:
        """Off bypasses role policy, while a graph spawn still needs its current v2 ownership envelope."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.opened(name, ("S2",))
                request = provider.request()
                self.untyped(provider, request, "general-purpose")
                self.assertTrue(self.verdict(provider, request))  # control: denied while the switch is unset
                provider.environment = {**provider.environment, "CODERAILS_GRAPH_DISPATCH": "off"}
                original = request["tool_input"][field(provider)]
                request["tool_input"][field(provider)] = "Read the documentation."
                self.refuse(provider, request, "dispatch_missing_envelope")
                first, body = original.split("\n", 1)
                old = json.loads(first.split("=", 1)[1])
                old.pop("envelope_version")
                old.pop("dispatch_id")
                request["tool_input"][field(provider)] = first.split("=", 1)[0] + "=" + json.dumps(old) + "\n" + body
                self.refuse(provider, request, "dispatch_missing_envelope")
                request["tool_input"][field(provider)] = original
                self.assertFalse(self.verdict(provider, request))
                self.assertEqual(self.reason(provider), "dispatch_check_off")

    def test_claude_off_records_one_owned_native_wave_without_authorization(self) -> None:
        """An explicitly disabled policy still binds a real v2 native spawn and rejects losing its ownership."""
        provider = self.opened("claude")
        provider.environment = {**provider.environment, "CODERAILS_GRAPH_DISPATCH": "off"}
        report = provider.launch()
        self.unauthorize(provider)
        provider.success("record-wave", json.dumps(report))

        missing = self.opened("claude")
        missing.environment = {**missing.environment, "CODERAILS_GRAPH_DISPATCH": "off"}
        report = missing.launch()
        native = json.loads(missing.parent.read_text().splitlines()[1])
        native["message"]["content"][0]["input"]["prompt"] = "No graph envelope"
        lines = missing.parent.read_text().splitlines()
        lines[1] = json.dumps(native)
        missing.parent.write_text("\n".join(lines) + "\n")
        failed = missing.call("record-wave", json.dumps(report))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("no native spawn", failed.stderr)

    def launched(self, nodes: tuple[str, ...] = ("U3[1]",)) -> tuple[Provider, dict[str, Any]]:
        """A Claude provider whose wave was begun and spawned, plus the wave report."""
        provider = self.opened("claude", nodes)
        return provider, provider.launch()

    def unauthorize(self, provider: Provider) -> None:
        """Forget the guard's consumption, as if the PreToolUse hook never saw the spawn."""
        state = provider.read()
        for record in state["graph"]["dispatches"].values():
            record["authorized"] = None
        provider.write(state)

    def test_evidence_side_rejects_spawns_the_guard_never_authorized(self) -> None:
        """Claude record-wave and completion re-check consumption, role and single use; the off-switch bypasses them."""
        provider, report = self.launched()
        self.unauthorize(provider)
        failed = provider.call("record-wave", json.dumps(report))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("dispatch_unauthorized", failed.stderr)
        provider.environment = {**provider.environment, "CODERAILS_GRAPH_DISPATCH": "off"}
        provider.success("record-wave", json.dumps(report))

    def test_evidence_side_rejects_a_scout_that_ran_untyped(self) -> None:
        """A guarded scout whose spawn was general-purpose fails binding even though the record is authorized."""
        provider, report = self.launched(("S2",))
        failed = provider.call("record-wave", json.dumps(report))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("role_mismatch", failed.stderr)

    def test_evidence_side_rejects_two_spawns_of_one_dispatch_id(self) -> None:
        """A replayed envelope with a distinct tool_use id cannot bind a second time."""
        provider, report = self.launched()
        claude.spawn(provider.parent, provider.read(), "U3[1]", suffix="_again")
        failed = provider.call("record-wave", json.dumps(report))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("dispatch_replayed", failed.stderr)

    def test_unconverted_state_cannot_begin_a_wave(self) -> None:
        """begin-wave needs state_minor >= 2."""
        for name in ("claude", "codex"):
            with self.subTest(provider=name):
                provider = self.fresh(name)
                state = provider.read()
                state["state_minor"] = 1
                provider.write(state)
                before = provider.path.read_bytes()
                self.assertNotEqual(provider.call("begin-wave").returncode, 0)
                self.assertEqual(provider.path.read_bytes(), before)

    def test_current_minor_requires_a_bounded_contract_stamp(self) -> None:
        """A v2 state cannot evade native dispatch checks by losing or advancing the cutoff."""
        for name in ("claude", "codex"):
            for stamp in (None, "2", 0, 10**9):
                with self.subTest(provider=name, stamp=stamp):
                    provider = self.opened(name)
                    state = provider.read()
                    if stamp is None:
                        del state["graph"]["contract_from_revision"]
                    else:
                        state["graph"]["contract_from_revision"] = stamp
                    provider.write(state)
                    result = provider.call("inspect")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("dispatch_state_unconverted", result.stderr)


if __name__ == "__main__":
    unittest.main()
