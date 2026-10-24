"""Receipt preflight, provenance, save durability and physical owned-source boundaries."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.tests import fake_muninn_store as fs  # noqa: E402
from scripts.tests.fake_muninn_case import PROMPT  # noqa: E402
from scripts.tests.orders_lifecycle_test import retrospective  # noqa: E402
from scripts.tests.orders_recovery_test import PRIOR, RecoveryCase  # noqa: E402

NO_CALLS: list[list[str]] = []
NO_OPENS: list[str] = []
PROBE = r"""
import hashlib, json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.lib import orders, orders_ledger as ol, orders_lifecycle as lifecycle, memory_adapter as ma
canonical, mode, script = sys.argv[2:5]
opens, external, events, temporaries, synced = [], [], [], {}, set()
real_open, real_run = Path.open, ma._run
real_temp, real_sync, real_replace = tempfile.mkstemp, os.fsync, os.replace
def opened(path, *args, **kwargs):
    if str(path) == canonical or str(path).startswith(canonical.rstrip('/') + '/'):
        opens.append(str(path))
    return real_open(path, *args, **kwargs)
def run(argv, *args, **kwargs):
    external.append(argv)
    return real_run(argv, *args, **kwargs)
def temporary(*args, **kwargs):
    fd, path = real_temp(*args, **kwargs)
    temporaries[fd] = path
    return fd, path
def sync(fd):
    path = temporaries.get(fd, '')
    if path:
        events.append({'event': 'fsync', 'path': path})
        if mode == 'fsync-fail' and Path(path).name.startswith(Path(canonical).name + '.'):
            raise OSError('injected local save fsync failure')
    real_sync(fd)
    synced.add(path)
def replace(src, dst):
    raw = Path(src).read_bytes()
    events.append({'event': 'replace', 'destination': str(dst), 'fsynced': str(src) in synced,
                   'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
    return real_replace(src, dst)
Path.open, ma._run = opened, run
tempfile.mkstemp, os.fsync, os.replace = temporary, sync, replace
if script == 'save':
    try:
        ol.save(Path(canonical), {**ol.empty(), 'caption': 'caf\u00e9'})
        rc = 0
    except OSError:
        rc = 2
    print(json.dumps({'saved': rc == 0}))
elif script == 'retro':
    try:
        print(json.dumps({'retro_count': lifecycle.retro_count(Path(sys.argv[5]))}))
        rc = 0
    except ValueError as error:
        print(json.dumps({'reason_code': str(error)}))
        rc = 2
else:
    if script == 'lessons.py':
        from scripts.lib import lessons
        rc = lessons.main(sys.argv[5:])
    else:
        rc = orders.main(sys.argv[5:])
print(json.dumps({'opens': opens, 'external': external, 'events': events, 'rc': rc}))
raise SystemExit(rc)
"""


class BoundaryCase(RecoveryCase):
    """Reuse real source/store fixtures; cwd also owns the genuine memory backend configuration."""

    def cli(self, *args: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:  # noqa: ANN401
        """Run the actual provider CLI from the same repository scope as every probe."""
        script, session = kwargs.get("script", "orders.py"), kwargs.get("session", "s1")
        argv, env = self.argv(script, session, *args), kwargs.get("env", self.native_env)
        got = subprocess.run(argv, cwd=self.repo, capture_output=True, text=True, env=env, timeout=15)
        self.assertEqual(got.stderr, "", got.stderr)
        return got.returncode, json.loads(got.stdout)

    def probe(self, path: Path, *args: str, mode: str = "pass", script: str = "orders.py") -> tuple[Any, ...]:
        """Instrument real file opens, adapter subprocesses and save publication without changing outcomes."""
        argv = [str(self.repo)] if script == "retro" else [] if script == "save" else self.argv(script, "s1", *args)[2:]
        command = [sys.executable, "-c", PROBE, str(self.root), str(path), mode, script, *argv]
        got = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, env=self.native_env, timeout=15)
        self.assertEqual(got.stderr, "", got.stderr)
        out, observed = map(json.loads, got.stdout.splitlines())
        self.assertEqual(observed["rc"], got.returncode)
        return got.returncode, out, observed

    def canonical(self) -> dict[str, bytes]:
        """Capture complete authoritative preparation/ledger/store bytes; traces are separate observations."""
        paths = [self.repo / "orders.json", fs.db_path(self.home), *self.repo.glob("*/orders-prepared-*.json")]
        return {str(p): p.read_bytes() for p in paths if p.exists()}

    def command(self, frontdoor: str) -> list[str]:
        """Prepare genuine ready sources, including empty/completed/idempotent applications."""
        self.assertEqual(self.stage("s0")[0], 0)
        self.complete("s0")
        self.assertEqual(self.cli("tick", "--loop", "logical-s0", session="s0")[0], 0)
        self.owner("s1")
        if frontdoor in ("tick", "retry"):
            self.assertEqual(self.stage("s1")[0], 0)
        elif frontdoor != "prepare-new":
            self.assertEqual(self.cli("prepare", "--loop", "logical-s1")[0], 0)
        if frontdoor in ("tick", "retry", "empty-tick", "empty-retry", "complete-record"):
            self.complete("s1")
        if frontdoor in ("retry", "empty-retry"):
            self.assertEqual(self.cli("tick", "--loop", "logical-s1")[0], 0)
        if frontdoor in ("record", "complete-record"):
            return ["record", "--id", "stable-mode", "--failure-mode", "stable-mode", "--lesson", "Replacement"] + [
                "--scope",
                "agnostic",
                "--quote",
                PROMPT,
                "--loop",
                "logical-s1",
            ]
        if frontdoor == "refresh":
            preparation = lifecycle.preparation_path(self.repo / "s1", "logical-s1")
            evidence = lifecycle.sha(json.loads(preparation.read_bytes()))
            progress = self.repo / "s1/progress.json"
            progress.write_text(json.dumps({**json.loads(progress.read_bytes()), "authorising_prompt_raw": "Advance."}))
            return ["prepare", "--loop", "logical-s1", "--refresh-from-sha256", evidence]
        return ["prepare" if frontdoor in ("prepare", "prepare-new") else "tick", "--loop", "logical-s1"]


class ReceiptPreflight(BoundaryCase):
    """Invalid prior evidence refuses before store and local lifecycle effects, rather than after them."""

    def test_invalid_receipts_refuse_before_every_effectful_frontdoor(self) -> None:
        """Complete physical LF objects and finite values are preconditions to record/prepare/apply/retry."""
        fronts = ("record", "complete-record", "prepare-new", "prepare", "refresh", "tick", "retry")
        for codex in (False, True):
            for front in (*fronts, "empty-tick", "empty-retry"):
                for n, raw in enumerate((b'{"partial":', b"{}", b'{"n":1e999}\n', b"[]\n")):
                    self.configure(codex, front + str(n))
                    args = self.command(front)
                    receipt = self.repo / "s1/teardown.jsonl"
                    receipt.write_bytes(raw)
                    before, store = self.canonical(), self.store_rows()
                    rc, out, seen = self.probe(receipt, *args)
                    for boundary, actual, expected in (
                        ("refusal", rc, 2),
                        ("before-store", seen["external"], NO_CALLS),
                        ("canonical-bytes", self.canonical(), before),
                        ("store-rows", self.store_rows(), store),
                        ("receipt-bytes", receipt.read_bytes(), raw),
                    ):
                        with self.subTest(codex=codex, front=front, raw=raw, boundary=boundary):
                            if boundary == "canonical-bytes":
                                self.assertTrue(actual == expected, out)
                            else:
                                self.assertEqual(actual, expected, out)

    def test_linked_receipt_or_sidecar_refuses_before_reads_or_effects(self) -> None:
        """Live and dangling links are rejected without opening their targets or replacing prepared inputs."""
        for codex in (False, True):
            for front in ("record", "prepare", "refresh", "tick", "retry", "empty-tick", "empty-retry"):
                for kind in ("receipt", "sidecar", "dangling-sidecar"):
                    self.configure(codex, front + kind)
                    args = self.command(front)
                    receipt = self.repo / "s1/teardown.jsonl"
                    path = receipt if kind == "receipt" else receipt.with_name("teardown.jsonl.lock")
                    target = self.tmp / ("outside-" + str(codex) + front + kind)
                    if kind != "dangling-sidecar":
                        path.rename(target)
                    else:
                        path.unlink()
                    raw = target.read_bytes() if target.exists() else None
                    path.symlink_to(target)
                    before = self.canonical()
                    rc, out, seen = self.probe(path, *args)
                    for boundary, actual, expected in (
                        ("refusal", rc, 2),
                        ("before-store", seen["external"], NO_CALLS),
                        ("before-open", seen["opens"], NO_OPENS),
                        ("canonical-bytes", self.canonical(), before),
                        ("target-bytes", target.read_bytes() if target.exists() else None, raw),
                        ("linked-path", path.is_symlink(), True),
                    ):
                        with self.subTest(codex=codex, front=front, kind=kind, boundary=boundary):
                            if boundary == "canonical-bytes":
                                self.assertTrue(actual == expected, out)
                            else:
                                self.assertEqual(actual, expected, out)


class DisabledProvenance(BoundaryCase):
    """Opt-out remains disabled while retaining previously established citation provenance."""

    def test_disabled_cite_cannot_turn_a_former_claim_into_a_first_attachment(self) -> None:
        """After retraction, off/on cite retains the K-id and refuses implicit cached-text reauthoring."""
        for codex in (False, True):
            self.configure(codex, "disabled-cite")
            self.assertEqual(self.stage("s1")[0], 0)
            self.complete("s1")
            self.assertEqual(self.cli("tick", "--loop", "logical-s1")[0], 0)
            known = ol.open_ledger(self.repo)["orders"][0]["muninn"]["id"]
            self.sql("UPDATE knowledge SET status = 'retracted'")
            config = self.repo / ".coderails/workflow.config.yaml"
            config.parent.mkdir()
            subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
            config.write_text("memory:\n  backend: off\n")
            before = self.store_rows()
            rc, out = self.cli("cite", "stable-mode", "--quote", PROMPT)
            self.assertEqual((rc, out["muninn"]["state"]), (0, "disabled"), out)
            with self.subTest(codex=codex, boundary="retain-id"):
                self.assertEqual(out["muninn"]["id"], known)
                self.assertEqual(ol.open_ledger(self.repo)["orders"][0]["muninn"]["id"], known)
            self.assertEqual(self.store_rows(), before)
            config.write_text("memory:\n  backend: muninn\n")
            rc, out = self.cli("cite", "stable-mode", "--quote", PROMPT)
            for boundary, actual, expected in (
                ("refusal", rc, 3),
                ("reason", out["muninn"]["reason_code"], "lesson_not_current"),
                ("no-add", self.store_rows(), before),
            ):
                with self.subTest(codex=codex, boundary=boundary):
                    self.assertEqual(actual, expected, out)
            self.assertEqual(self.stage("s2")[0], 0)

    def test_disabled_completed_tick_retains_saved_provenance(self) -> None:
        """Prepared metadata cannot erase an existing K-id when explicit off disables a completed fresh read."""
        for codex in (False, True):
            self.configure(codex, "disabled-tick")
            self.assertEqual(self.stage("s0")[0], 0)
            self.complete("s0")
            self.assertEqual(self.cli("tick", "--loop", "logical-s0", session="s0")[0], 0)
            known = ol.open_ledger(self.repo)["orders"][0]["muninn"]["id"]
            self.assertEqual(self.stage("s1")[0], 0)
            known = self.cli("cite", "stable-mode", "--quote", PROMPT)[1]["muninn"]["id"] or known
            config = self.repo / ".coderails/workflow.config.yaml"
            config.parent.mkdir()
            subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
            config.write_text("memory:\n  backend: off\n")
            before = self.store_rows()
            self.complete("s1")
            rc, out = self.cli("tick", "--loop", "logical-s1")
            field = ol.open_ledger(self.repo)["orders"][0]["muninn"]
            self.assertEqual((rc, field["state"], field["reason_code"]), (0, "disabled", "memory_backend_off"), out)
            with self.subTest(codex=codex):
                self.assertEqual(field["id"], known)
                self.assertEqual(self.store_rows(), before)


class SaveDurability(BoundaryCase):
    """Real fsync/replace observations bind local save durability to subsequent honest receipts."""

    def test_complete_serialization_is_fsynced_before_replace_and_receipt(self) -> None:
        """Both native preparations and ledgers use the exact established JSON bytes and file barrier."""
        for codex in (False, True):
            for command in ("save", "prepare", "tick"):
                self.configure(codex, command)
                self.owner("s1")
                target = self.repo / "orders.json"
                if command == "prepare":
                    target = lifecycle.preparation_path(self.repo / "s1", "logical-s1")
                if command == "tick":
                    self.assertEqual(self.stage("s1")[0], 0)
                    self.complete("s1")
                args = () if command == "save" else (command, "--loop", "logical-s1")
                rc, out, seen = self.probe(target, *args, script="save" if command == "save" else "orders.py")
                self.assertEqual(rc, 0, out)
                raw = target.read_bytes()
                self.assertEqual(raw, (json.dumps(json.loads(raw), indent=1, sort_keys=True) + "\n").encode())
                if command == "save":
                    self.assertIn(b"caf\\u00e9", raw)
                publications = [
                    e
                    for e in seen["events"]
                    if e["event"] == "replace"
                    and e["destination"] in (str(target), str(self.repo / "s1/teardown.jsonl"))
                ]
                self.assertEqual(publications[0]["destination"], str(target))
                with self.subTest(codex=codex, command=command, boundary="file-fsync"):
                    self.assertTrue(publications[0]["fsynced"], seen)
                if command != "save":
                    self.assertEqual(publications[-1]["destination"], str(self.repo / "s1/teardown.jsonl"))

    def test_failed_local_save_preserves_canonical_and_emits_no_success_receipt(self) -> None:
        """An injected state-file fsync failure leaves prior bytes untouched, including at real CLI boundaries."""
        for codex in (False, True):
            for command in ("save", "prepare", "tick"):
                self.configure(codex, command + "failure")
                self.owner("s1")
                receipt = self.repo / "s1/teardown.jsonl"
                receipt.write_bytes(PRIOR)
                target = self.repo / "orders.json"
                if command == "save":
                    target.write_bytes(b"prior canonical bytes")
                elif command == "prepare":
                    target = lifecycle.preparation_path(self.repo / "s1", "logical-s1")
                else:
                    self.assertEqual(self.stage("s1")[0], 0)
                    self.complete("s1")
                before, receipts = target.read_bytes() if target.exists() else None, receipt.read_bytes()
                args = () if command == "save" else (command, "--loop", "logical-s1")
                rc, out, seen = self.probe(
                    target, *args, mode="fsync-fail", script="save" if command == "save" else "orders.py"
                )
                for boundary, actual, expected in (
                    ("failure", rc, 3 if command == "tick" else 2),
                    ("canonical", target.read_bytes() if target.exists() else None, before),
                    ("no-receipt", receipt.read_bytes(), receipts),
                ):
                    with self.subTest(codex=codex, command=command, boundary=boundary):
                        self.assertEqual(actual, expected, (out, seen))


class PhysicalSources(BoundaryCase):
    """Logical hashes cannot replace canonical physical ownership before reads or initialization."""

    def test_linked_ledger_or_generated_view_refuses_before_read_or_tick(self) -> None:
        """Live/dangling canonical ledger and missing-ledger view links never enter reader or empty-ledger paths."""
        for codex in (False, True):
            for kind in ("ledger", "dangling-ledger", "view", "dangling-view"):
                self.configure(codex, kind)
                self.owner("s1")
                self.assertEqual(self.cli("prepare", "--loop", "logical-s1")[0], 0)
                self.complete("s1")
                target = self.tmp / ("outside-" + str(codex) + kind)
                path = self.repo / ("standing-orders.md" if "view" in kind else "orders.json")
                if not kind.startswith("dangling"):
                    target.write_text(ol.view(ol.empty(), False) if kind == "view" else json.dumps(ol.empty()))
                path.symlink_to(target)
                before = target.read_bytes() if target.exists() else None
                for script, args in (
                    ("orders.py", ("lessons",)),
                    ("orders.py", ("predicate",)),
                    ("lessons.py", ("query",)),
                    ("lessons.py", ("predicate",)),
                    ("orders.py", ("tick", "--loop", "logical-s1")),
                ):
                    rc, out, seen = self.probe(path, *args, script=script)
                    for boundary, actual, expected in (
                        ("refusal", rc, 2),
                        ("before-open", seen["opens"], NO_OPENS),
                        ("link", path.is_symlink(), True),
                        ("external", target.read_bytes() if target.exists() else None, before),
                    ):
                        with self.subTest(codex=codex, kind=kind, script=script, args=args, boundary=boundary):
                            self.assertEqual(actual, expected, out)

    def test_owned_history_excludes_linked_physical_sources_before_read(self) -> None:
        """Retro/session/progress and every accepted optional file source are checked before any target read."""
        names = ("retro.json", "session", "progress.json", "evals.json", "proof.json", "proof_results.jsonl")
        for codex in (False, True):
            for name in (*names, "teardown.jsonl"):
                self.configure(codex, name)
                retro = retrospective(self.repo, "history", "past-loop")
                state_path = retro.with_name("progress.json")
                state, data = json.loads(state_path.read_bytes()), json.loads(retro.read_bytes())
                if codex:
                    state.update(completion={"revision": 1}, revision=2)
                    state_path.write_text(json.dumps(state))
                    data["revision"] = 2
                    data["source_hashes"]["progress.json"] = hashlib.sha256(state_path.read_bytes()).hexdigest()
                path = retro.parent if name == "session" else retro.with_name(name)
                if name in ("evals.json", "proof.json", "proof_results.jsonl", "teardown.jsonl"):
                    path.write_bytes(b'{"fixture":"owned"}\n')
                    data["source_hashes"][name] = (
                        lifecycle.sha(json.loads(path.read_bytes()))
                        if name.endswith(".json")
                        else hashlib.sha256(path.read_bytes()).hexdigest()
                    )
                retro.write_text(json.dumps(data))
                self.assertEqual(self.probe(path, script="retro")[1]["retro_count"], 1)
                target = self.tmp / ("outside-history-" + str(codex) + name)
                path.rename(target)
                path.symlink_to(target, target_is_directory=name == "session")
                for script in ("retro", "orders.py", "lessons.py"):
                    rc, out, seen = self.probe(path, *("predicate",) if script != "retro" else (), script=script)
                    count = out["retro_count"] if script in ("retro", "orders.py") else out["graduation"]["retro_count"]
                    for boundary, actual, expected in (("exclude", count, 0), ("before-open", seen["opens"], NO_OPENS)):
                        with self.subTest(codex=codex, name=name, script=script, boundary=boundary):
                            self.assertEqual((rc, actual), (0, expected), out)


if __name__ == "__main__":
    unittest.main()
