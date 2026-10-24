"""Exercise the EXISTING memory adapter against the hermetic fake Muninn store (real sqlite file, schema v2).

Covers round trip, restart, search, expiry, sensitivity, supersession and the read-only schema probe, plus the negative
controls that prove the fixture and the rules are load-bearing. Nothing here touches the live Muninn store.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import memory_schema  # noqa: E402
from scripts.tests import fake_muninn  # noqa: E402
from scripts.tests import fake_muninn_store as fs  # noqa: E402
from scripts.tests.fake_muninn_case import LATER, PROMPT, PROPOSAL, SESSION, StoreCase  # noqa: E402


class AdapterOverFakeStore(StoreCase):
    """The existing adapter, unchanged, against the fake."""

    def test_round_trip(self) -> None:
        """(a) add then list returns the K-id, cite ref and quote."""
        self.assertIsNone(ma.add(self.record("Run targeted tests first", tags=["run-a"])))
        (got,) = self.listed()
        self.assertEqual(
            (got.id, got.cite, got.quote, got.claim),
            ("K1", f"claude:{SESSION}:1.1", PROMPT, "Run targeted tests first"),
        )
        self.assertEqual((got.type, got.tags), ("lesson", ["run-a"]))

    def test_restart_keeps_ids_cites_quotes(self) -> None:
        """(b) a fresh process with a cleared probe cache sees the same rows."""
        self.assertIsNone(ma.add(self.record("first")))
        self.assertIsNone(ma.add(self.record("second", quote=LATER, cite=f"claude:{SESSION}:4.1")))
        before = [(r.id, r.cite, r.quote) for r in self.listed()]
        ma.PROBE_CACHE.clear()
        p = subprocess.run(
            [sys.executable, str(REPO / "scripts/lib/memory_adapter.py"), "list", "--scope", "loop", "--loop", "L1"],
            capture_output=True,
            text=True,
            env=dict(os.environ),
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        after = [(r["id"], r["cite"], r["quote"]) for r in json.loads(p.stdout)]
        self.assertEqual(sorted(after), sorted(before))
        self.assertEqual(sorted(i for i, _, _ in after), ["K1", "K2"])

    def test_search_finds_only_the_written_record(self) -> None:
        """(c) a claim word reaches knowledge through `search --all-projects` and matches one record only."""
        self.assertIsNone(ma.add(self.record("zebrafish migration notes")))
        self.assertIsNone(ma.add(self.record("unrelated adapter lesson")))
        rc, out = self.muninn("search", "zebrafish", "--all-projects")
        self.assertEqual(rc, 0)
        self.assertEqual([k["id"] for k in out["knowledge"]], ["K1"])

    def test_expiry(self) -> None:
        """(d) past valid_until is refused, future round-trips, a later drift into the past hides the row."""
        self.assertIsInstance(ma.add(self.record("old", valid_until="2020-01-01")), ma.Degraded)
        rc, out = self.muninn(*self.add_argv("old", "--valid-until", "2020-01-01"))
        self.assertEqual((rc, out), (2, {"error": "bad_valid_until"}))
        self.assertEqual(self.listed(), [])
        future = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 86400 * 400))
        self.assertIsNone(ma.add(self.record("fresh", valid_until=future)))
        (got,) = self.listed()
        self.assertEqual(got.valid_until, f"{future}T00:00:00Z")
        self.sql("UPDATE knowledge SET valid_until = ? WHERE id = 1", time.time() - 60)
        self.assertEqual(self.listed(), [])

    def test_sensitivity(self) -> None:
        """(e) a restricted row is hidden by list_records and the adapter refuses to write restricted."""
        rc, _ = self.muninn(*self.add_argv("secret lesson", "--sensitivity", "restricted"))
        self.assertEqual(rc, 0)
        self.assertEqual(
            self.muninn("know", "list", "--scope-loop", "L1")[1]["entries"][0]["sensitivity"], "restricted"
        )
        self.assertEqual(self.listed(), [])
        res = ma.add(self.record("secret", sensitivity="restricted"))
        self.assertEqual(res, ma.Degraded("restricted_refused"))

    def test_supersession(self) -> None:
        """(f) K2 supersedes K1: only K2 is listed and `know show K1` reports superseded_by=K2."""
        self.assertIsNone(ma.add(self.record("v1 wording")))
        self.assertIsNone(ma.add(self.record("v2 wording", supersedes="K1")))
        self.assertEqual([r.id for r in self.listed()], ["K2"])
        rc, out = self.muninn("know", "show", "K1")
        self.assertEqual(rc, 0)
        self.assertEqual((out["entry"]["status"], out["entry"]["superseded_by"]), ("superseded", "K2"))
        self.assertEqual([c["id"] for c in out["chain"]["superseded_by"]], ["K2"])

    def add_argv(self, text: str, *extra: str) -> list[str]:
        """Direct `know add` argv for loop L1 citing the first prompt."""
        return [
            "know",
            "add",
            "--kind",
            "lesson",
            "--text",
            text,
            "--cite",
            f"claude:{SESSION}:1.1",
            "--quote",
            PROMPT,
            "--scope-loop",
            "L1",
            *extra,
        ]

    def test_search_stays_fresh_after_supersede_and_edit(self) -> None:
        """Index freshness: a direct text edit after a supersede is searchable (needs the knowledge_au trigger)."""
        self.assertIsNone(ma.add(self.record("alpha wording")))
        self.assertIsNone(ma.add(self.record("beta wording", supersedes="K1")))
        self.sql("UPDATE knowledge SET text = 'gamma wording' WHERE id = 2")
        self.assertEqual([k["id"] for k in self.muninn("search", "gamma", "--all-projects")[1]["knowledge"]], ["K2"])
        self.assertEqual(self.muninn("search", "beta", "--all-projects")[1]["knowledge"], [])


class RefusalsAndRules(StoreCase):
    """The fake refuses with {"error": code} rc 2 using knowledge_cite.py's rules."""

    def refused(self, *args: str, code: str, extra_env: dict[str, str] | None = None) -> None:
        """Assert one refusal."""
        self.assertEqual(self.muninn(*args, extra_env=extra_env), (2, {"error": code}), args)

    def test_refusal_codes(self) -> None:
        """Every documented refusal code is reachable."""
        base = ["know", "add", "--kind", "lesson", "--text", "x", "--scope-loop", "L1"]
        ok = ["--cite", f"claude:{SESSION}:1.1", "--quote", PROMPT]
        self.refused(*base, code="uncited")
        self.refused(*base, "--cite", f"claude:{SESSION}:99.1", "--quote", PROMPT, code="not_found")
        self.refused(*base, "--cite", f"claude:{SESSION}:1.1", "--quote", "Always run", code="quote_length")
        self.refused(*base, "--cite", f"claude:{SESSION}:1.1", "--quote", "x" * 301, code="quote_length")
        self.refused(
            *base,
            "--cite",
            f"claude:{SESSION}:1.1",
            "--quote",
            "this sentence is not in the prompt",
            code="quote_not_found",
        )
        self.refused(*base, "--cite", f"claude:{SESSION}:3.1", "--quote", "yes", code="approval_needs_reply")
        self.refused(
            "know",
            "add",
            "--kind",
            "preference",
            "--text",
            "x",
            "--cite",
            f"claude:{SESSION}:2.1",
            "--quote",
            "record the lesson that targeted",
            code="preference_needs_user",
        )
        self.refused(*base, *ok, "--supersedes", "K7", code="bad_supersedes")
        self.refused(*base, *ok, "--valid-until", "2020-01-01", code="bad_valid_until")
        self.refused(*base, *ok, "--tag", "Bad Tag", code="bad_tags")
        self.refused(*base, *ok, "--global", code="bad_loop_scope")
        self.refused(
            "know", "add", "--kind", "lesson", "--text", "x", "--scope-loop", "bad/loop", *ok, code="bad_loop_scope"
        )
        self.assertEqual(self.muninn("know", "show", "K1")[0], 2)

    def test_approval_needs_reply_then_accepted_with_reply(self) -> None:
        """A bare 'yes' is only valid with the reply it answers cited too."""
        self.refused(
            "know",
            "add",
            "--kind",
            "decision",
            "--text",
            "approved",
            "--cite",
            f"claude:{SESSION}:3.1",
            "--quote",
            "yes",
            "--scope-loop",
            "L1",
            code="approval_needs_reply",
        )
        rc, out = self.muninn(
            "know",
            "add",
            "--kind",
            "decision",
            "--text",
            "approved",
            "--cite",
            f"claude:{SESSION}:2.1",
            "--quote",
            PROPOSAL,
            "--cite",
            f"claude:{SESSION}:3.1",
            "--quote",
            "yes",
            "--scope-loop",
            "L1",
        )
        self.assertEqual(rc, 0)
        self.assertEqual(len(out["entry"]["cites"]), 2)

    def test_control_dropping_approval_rule_is_detected(self) -> None:
        """Negative control 2: without the reply rule a bare yes is accepted, so the dedicated test would fail."""
        buf = io.StringIO()
        argv = [
            "--kind",
            "decision",
            "--text",
            "approved",
            "--cite",
            f"claude:{SESSION}:3.1",
            "--quote",
            "yes",
            "--scope-loop",
            "L1",
        ]

        def no_rule(*_args: object) -> None:
            return None

        with mock.patch.object(fake_muninn, "require_proposals", no_rule), contextlib.redirect_stdout(buf):
            rc = fake_muninn.cmd_add(self.home, argv)
        self.assertEqual(rc, 0, "mutated fake no longer refuses: the approval rule is load-bearing")

    def test_quote_only_uses_callers_own_prompt(self) -> None:
        """`--quote` alone cites the caller session's latest matching user prompt."""
        env = {"CLAUDE_CODE_SESSION_ID": SESSION}
        rc, out = self.muninn(
            "know",
            "add",
            "--kind",
            "lesson",
            "--text",
            "x",
            "--quote",
            "targeted tests before committing",
            "--scope-loop",
            "L1",
            extra_env=env,
        )
        self.assertEqual((rc, out["entry"]["cites"][0]["ref"]), (0, f"claude:{SESSION}:1.1"))
        self.refused(
            "know",
            "add",
            "--kind",
            "lesson",
            "--text",
            "x",
            "--quote",
            "nothing like that was ever typed",
            "--scope-loop",
            "L1",
            code="quote_not_found",
            extra_env=env,
        )

    def test_session_and_doctor(self) -> None:
        """`session` lists synthetic events with refs; `doctor` reports ok; `--version` stays stale."""
        out = self.muninn("session", SESSION)[1]
        self.assertEqual([e["ref"] for e in out["events"]][:2], [f"claude:{SESSION}:1.1", f"claude:{SESSION}:2.1"])
        self.assertTrue(self.muninn("doctor")[1]["ok"])
        p = subprocess.run(["muninn", "--version"], capture_output=True, text=True)
        self.assertEqual(p.stdout.strip(), "muninn 0.1.0")


class SchemaProbe(StoreCase):
    """memory_schema.check reads the schema, never the version string."""

    def test_v2_store_is_ok(self) -> None:
        """(g) the v2 fixture passes, even though `muninn --version` says 0.1.0."""
        fs.create(self.home)
        self.assertIsNone(memory_schema.check(self.home))
        self.assertIsNone(memory_schema.check())  # via $MUNINN_HOME
        self.assertEqual(
            subprocess.run(["muninn", "--version"], capture_output=True, text=True).stdout.strip(), "muninn 0.1.0"
        )

    def test_failures(self) -> None:
        """(g) old version, dropped typed column, missing fts, missing file."""
        self.assertEqual(memory_schema.check(self.tmp / "nowhere"), "muninn_store_missing")
        cases: dict[str, tuple[dict[str, Any], str]] = {
            "old": ({"user_version": 1}, "muninn_schema_old"),
            "nosens": ({"drop_column": "sensitivity"}, "muninn_schema_incomplete"),
            "notags": ({"drop_column": "tags"}, "muninn_schema_incomplete"),
            "nofts": ({"fts": False}, "muninn_schema_incomplete"),
        }
        for name, (kw, want) in cases.items():
            home = self.tmp / name
            fs.create(home, **kw)
            self.assertEqual(memory_schema.check(home), want, name)

    def test_not_sqlite_and_read_only(self) -> None:
        """A garbage file is incomplete, and check never modifies the store."""
        junk = self.tmp / "junk"
        junk.mkdir()
        fs.db_path(junk).write_text("not a database")
        self.assertEqual(memory_schema.check(junk), "muninn_schema_incomplete")
        fs.create(self.home)
        before = fs.db_path(self.home).read_bytes()
        memory_schema.check(self.home)
        self.assertEqual(fs.db_path(self.home).read_bytes(), before)

    def test_control_fresh_version_string_does_not_hide_v1(self) -> None:
        """Negative control 1: a fake claiming a fresh version over a v1 store is still muninn_schema_old."""
        fs.create(self.home, user_version=1)
        env = {**os.environ, "FAKE_MUNINN_VERSION": "9.9.9"}
        self.assertEqual(
            subprocess.run(["muninn", "--version"], capture_output=True, text=True, env=env).stdout.strip(),
            "muninn 9.9.9",
        )
        self.assertEqual(memory_schema.check(self.home), "muninn_schema_old")

    def test_control_old_kind_check_store_refuses_lesson(self) -> None:
        """Negative control 4: typed columns but the pre-v2 kind CHECK -> a lesson add fails (fixture is really v2)."""
        old = self.tmp / "oldkind"
        fs.create(old, old_kind=True)
        self.assertEqual(memory_schema.check(old), "muninn_schema_incomplete")
        rc, out = self.muninn(*self.add_argv_for("lesson"), extra_env={"MUNINN_HOME": str(old)})
        self.assertEqual((rc, out), (1, {"error": "store_constraint"}))
        rc, _ = self.muninn(*self.add_argv_for("lesson"))  # default v2 home
        self.assertEqual(rc, 0)
        rc, _ = self.muninn(*self.add_argv_for("fact"), extra_env={"MUNINN_HOME": str(old)})
        self.assertEqual(rc, 0)

    def add_argv_for(self, kind: str) -> list[str]:
        """`know add` argv of the given kind citing the first prompt."""
        return [
            "know",
            "add",
            "--kind",
            kind,
            "--text",
            "x",
            "--cite",
            f"claude:{SESSION}:1.1",
            "--quote",
            PROMPT,
            "--scope-loop",
            "L1",
        ]

    def test_control_missing_update_trigger_leaves_index_stale(self) -> None:
        """Negative control 3: without knowledge_au a text edit is invisible to search."""
        fs.create(self.home, drop_triggers=("knowledge_au",))
        self.assertEqual(memory_schema.check(self.home), "muninn_schema_incomplete")
        self.assertIsNone(ma.add(self.record("alpha wording")))
        self.assertIsNone(ma.add(self.record("beta wording", supersedes="K1")))
        self.sql("UPDATE knowledge SET text = 'gamma wording' WHERE id = 2")
        self.assertEqual(
            self.muninn("search", "gamma", "--all-projects")[1]["knowledge"], [], "stale index must miss the new word"
        )

    def test_live_help_shape_is_a_known_adapter_defect(self) -> None:
        """Known defect for U2: live --help goes to stderr with rc 2, which probe() reads as muninn_old_ledger."""
        fs.create(self.home)
        with mock.patch.dict(os.environ, {"FAKE_MUNINN_HELP": "real"}):
            ma.PROBE_CACHE.clear()
            self.assertEqual(ma.probe(), ma.Degraded("muninn_old_ledger"))
        ma.PROBE_CACHE.clear()
        self.assertIsNone(ma.probe())

    def test_codex_mirror_is_byte_identical(self) -> None:
        """(h) the Codex copy of memory_schema.py equals the Claude one."""
        a = (REPO / "scripts/lib/memory_schema.py").read_bytes()
        self.assertEqual(a, (REPO / "packages/codex/scripts/lib/memory_schema.py").read_bytes())

    def test_new_files_listed_and_small(self) -> None:
        """(i) new modules are in python_entrypoint_modes.json and each file stays under 400 lines."""
        modes = json.loads((REPO / "hooks/scripts/tests/fixtures/python_entrypoint_modes.json").read_text())
        files = [
            "scripts/tests/fake_muninn.py",
            "scripts/tests/fake_muninn_store.py",
            "scripts/tests/fake_muninn_read.py",
            "scripts/tests/fake_muninn_case.py",
            "scripts/lib/memory_schema.py",
        ]
        for f in files:
            self.assertIn(f, modes)
        for f in [*files, "packages/codex/scripts/lib/memory_schema.py", "scripts/tests/memory_store_test.py"]:
            self.assertLess(len((REPO / f).read_text().splitlines()), 400, f)


if __name__ == "__main__":
    unittest.main()
