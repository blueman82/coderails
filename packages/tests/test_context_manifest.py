"""Context manifest, skill routing and compaction-resume identity across both providers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.provider_fixture import Provider

ROOT = Path(__file__).resolve().parents[2]
LIB = "hooks/scripts/lib"
CODEX_LIB = "packages/codex/hooks/scripts/lib"
SESSION_CEILING = 1200  # Codex SessionStart additionalContextLimit
PROMPT_CEILING = 500  # Codex UserPromptSubmit additionalContextLimit
OLD_CLAUDE_BYTES = 6288  # measured full-skill injection before this change (docs/graph-alignment-measurement.md)
EVIDENCE = ["ev-1", "ev-2"]


def run_hook(
    provider: Provider, name: str, payload: Mapping[str, object] | str, env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Run a provider hook, require exit 0, and return its JSON output."""
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    result = subprocess.run(
        [sys.executable, str(provider.plugin / "hooks/scripts" / (name + ".py"))],
        input=raw,
        capture_output=True,
        text=True,
        check=False,
        env=env or provider.environment,
        cwd=provider.home,
    )
    assert result.returncode == 0, result.stderr
    output: dict[str, Any] = json.loads(result.stdout)["hookSpecificOutput"]
    return output


def context(provider: Provider, payload: Mapping[str, object] | str, env: dict[str, str] | None = None) -> str:
    """Return SessionStart additionalContext."""
    return str(run_hook(provider, "inject_bootstrap", payload, env)["additionalContext"])


def identity(text: str) -> list[str]:
    """Return the manifest lines that carry loop identity (everything but the source line)."""
    return [line for line in text.splitlines() if line.split(":")[0] in {"loop", "evidence", "authority", "route"}]


class ContextManifestTests(unittest.TestCase):
    """One fixture loop per provider; hooks run exactly as installed."""

    def setUp(self) -> None:
        """Create isolated providers with an evidence-bearing node."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]
        for provider in self.providers:
            state = provider.read()
            state["graph"]["nodes"]["U3[1]"]["evidence"] = list(EVIDENCE)
            provider.write(state)

    def session_dir(self, provider: Provider) -> Path:
        """Return <loop root>/<session id>, where authority.json and trace.jsonl live."""
        return Path(provider.environment["CODERAILS_AGENTIC_LOOP_DIR"]) / provider.session

    def payload(self, provider: Provider, source: str = "startup") -> dict[str, object]:
        """Return a SessionStart payload for the provider's own session."""
        return {"session_id": provider.session, "cwd": str(provider.home), "source": source}

    def test_lib_copies_are_byte_identical(self) -> None:
        """The Codex copies stay in step with the Claude originals."""
        for name in ("context_manifest.py", "trace_row.py"):
            self.assertEqual((ROOT / LIB / name).read_bytes(), (ROOT / CODEX_LIB / name).read_bytes(), name)

    def test_active_loop_manifest_is_small_and_names_the_loop(self) -> None:
        """Negative control: today's full-skill injection is neither small nor free of the 1% rule."""
        for provider in self.providers:
            text = context(provider, self.payload(provider))
            self.assertLessEqual(len(text.encode()), SESSION_CEILING, provider.name)
            self.assertLess(len(text.encode()), OLD_CLAUDE_BYTES)
            self.assertNotIn("1%", text)
            self.assertNotIn("EXTREMELY_IMPORTANT", text)
            for expected in ("coderails: active=yes", "id=fixture-loop", f"owner={provider.session}", "revision=1"):
                self.assertIn(expected, text, provider.name)
            self.assertIn("ready=U3[1]", text)
            self.assertIn("hard_stop=-", text)
            self.assertIn("skills: list via the Skill tool / native skill list", text)
            self.assertIn("route: ", text)

    def test_compaction_resume_preserves_identity(self) -> None:
        """Clear and compact yield identical loop id, owner, revision and evidence identity."""
        for provider in self.providers:
            first = identity(context(provider, self.payload(provider, "clear")))
            second = identity(context(provider, self.payload(provider, "compact")))
            self.assertEqual(first, second, provider.name)
            self.assertTrue(any(re.search(r"evidence: U3\[1\]=2:[0-9a-f]{8}", line) for line in first), first)
            progress = provider.read()
            self.assertEqual(progress["loop_id"], "fixture-loop")
            after = identity(context(provider, self.payload(provider, "compact")))
            self.assertEqual(after, first)

    def test_evidence_change_changes_the_manifest(self) -> None:
        """Evidence identity is real: different evidence yields a different digest."""
        provider = self.providers[0]
        before = identity(context(provider, self.payload(provider)))
        state = provider.read()
        state["graph"]["nodes"]["U3[1]"]["evidence"] = ["ev-1", "ev-3"]
        provider.write(state)
        self.assertNotEqual(before, identity(context(provider, self.payload(provider))))

    def test_foreign_session_never_sees_this_loop(self) -> None:
        """A different session id gets no loop, no authority and none of the owner's identifiers."""
        for provider in self.providers:
            text = context(provider, self.payload(provider) | {"session_id": "somebody-else"})
            self.assertIn("loop: none", text)
            self.assertIn("authority: none", text)
            self.assertNotIn("fixture-loop", text)
            self.assertNotIn(provider.session, text)

    def test_authority_state(self) -> None:
        """Valid authority shows active; foreign-embedded, expired and torn files show none."""
        for provider in self.providers:
            path = self.session_dir(provider) / "authority.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            body = {"authority_id": "A1", "session_id": provider.session, "scope": ["push"], "expires_at": expires}
            for value, expected in (
                (body, "authority: active id=A1 scope=push"),
                ({**body, "session_id": "other"}, "authority: none"),
                ({**body, "expires_at": "2000-01-01T00:00:00+00:00"}, "authority: none"),
                ("{torn", "authority: none"),
            ):
                path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
                self.assertIn(expected, context(provider, self.payload(provider)), (provider.name, value))

    def test_torn_state_fails_open_with_reason_code_and_trace_row(self) -> None:
        """A torn progress.json yields the static fallback, exit 0, and one reason-coded trace row."""
        for provider in self.providers:
            provider.path.write_text('{"loop_id": "fixture-loop", "gra', encoding="utf-8")
            text = context(provider, self.payload(provider))
            self.assertIn("loop: unknown", text)
            self.assertIn("skills: list via", text)
            rows = [json.loads(x) for x in (self.session_dir(provider) / "trace.jsonl").read_text().splitlines()]
            self.assertEqual(rows[-1]["reason_code"], "manifest_state_unreadable")
            self.assertEqual(rows[-1]["command"], "context_manifest")

    def test_malformed_payload_fails_open(self) -> None:
        """Garbage stdin still produces a manifest with the fail-safe line."""
        for provider in self.providers:
            for raw in ("not json", "[1, 2]", ""):
                text = context(provider, raw)
                self.assertIn("skills: list via", text, (provider.name, raw))

    def test_loop_dir_env_precedence_matches_each_provider(self) -> None:
        """Claude: CLAUDE_ wins over CODERAILS_. Codex reads only CODERAILS_ (as before the manifest)."""
        for provider in self.providers:
            state_dir = provider.environment["CODERAILS_AGENTIC_LOOP_DIR"]
            empty = str(provider.home / "empty")
            Path(empty).mkdir()
            base = {k: v for k, v in provider.environment.items() if "AGENTIC_LOOP_DIR" not in k}
            both = {**base, "CLAUDE_AGENTIC_LOOP_DIR": empty, "CODERAILS_AGENTIC_LOOP_DIR": state_dir}
            expected = "loop: none" if provider.name == "claude" else "id=fixture-loop"
            self.assertIn(expected, context(provider, self.payload(provider), both), provider.name)
            only_codex = context(provider, self.payload(provider), {**base, "CODERAILS_AGENTIC_LOOP_DIR": state_dir})
            self.assertIn("id=fixture-loop", only_codex, provider.name)
            only_claude = {**base, "CLAUDE_AGENTIC_LOOP_DIR": state_dir, "HOME": str(provider.home / "nohome")}
            expected = "id=fixture-loop" if provider.name == "claude" else "loop: none"
            self.assertIn(expected, context(provider, self.payload(provider), only_claude), provider.name)

    def test_canonical_slug_wins_over_glob_order(self) -> None:
        """The cwd's canonical slug dir is preferred to an earlier-sorting slug dir holding the same session id."""
        for provider in self.providers:
            repo = provider.home / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            common = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            root = Path(provider.environment["CODERAILS_AGENTIC_LOOP_DIR"])
            for slug, loop_id in (("--decoy", "decoy-loop"), (common.replace("/", "-"), "canonical-loop")):
                target = root / slug / provider.session / "progress.json"
                target.parent.mkdir(parents=True)
                state = provider.read() | {"loop_id": loop_id}
                target.write_text(json.dumps(state), encoding="utf-8")
            payload = self.payload(provider) | {"cwd": str(repo)}
            self.assertIn("id=canonical-loop", context(provider, payload), provider.name)

    def test_hard_rules_survive_in_the_manifest(self) -> None:
        """Skills-mandatory, process-first and subagent-skip stay in the injected text (without the 1% wording)."""
        for provider in self.providers:
            text = context(provider, self.payload(provider))
            for rule in ("must invoke", "process skills first", "subagents skip"):
                self.assertIn(rule, text, (provider.name, rule))

    def test_route_phrasing_variants_and_negation(self) -> None:
        """Mid-prompt slash commands and plain verbs route; a negated keyword does not."""
        cases = (
            ("please MERGE it", "merge"),
            ("git push the thing", "push"),
            ("run /workflow", "workflow"),
            ("/Merge", "merge"),
            ("do not ingest anything", None),
            ("don't merge yet", None),
            ("please ingest PR 5", "wiki-ingest"),
        )
        for provider in self.providers:
            prefix = "coderails" if provider.name == "claude" else "coderails-codex"
            for prompt, skill in cases:
                payload = {"session_id": "no-loop-session", "cwd": str(provider.home), "prompt": prompt}
                text = str(run_hook(provider, "inject_context", payload)["additionalContext"])
                if skill is None:
                    self.assertNotIn("route:", text, (provider.name, prompt))
                else:
                    self.assertIn(f"{prefix}:{skill}", text, (provider.name, prompt))

    def test_unattributed_fail_open_events_leave_trace_rows(self) -> None:
        """Malformed payloads and a missing session_id are still counted (under the _unattributed bucket)."""
        for provider in self.providers:
            context(provider, "{bad")
            context(provider, {"cwd": "/x", "source": "startup"})
            path = self.session_dir(provider).parent / "_unattributed" / "trace.jsonl"
            reasons = [json.loads(x)["reason_code"] for x in path.read_text().splitlines()]
            self.assertEqual(reasons, ["manifest_payload_malformed", "manifest_no_session"], provider.name)
            if provider.name == "claude":
                run_hook(provider, "inject_context", "{bad")
                last = json.loads(path.read_text().splitlines()[-1])
                self.assertEqual(last["reason_code"], "route_payload_malformed")

    def test_runbook_lists_every_reason_code(self) -> None:
        """Code and RUNBOOK agree on the reason-code set."""
        source = (ROOT / LIB / "context_manifest.py").read_text()
        codes = set(re.findall(r'"((?:manifest|route)_[a-z_]+)"', source))
        runbook = (ROOT / "docs/RUNBOOK.md").read_text()
        for code in codes:
            self.assertIn(f"`{code}`", runbook, code)

    def test_claude_resume_matcher_matches_codex(self) -> None:
        """Resumed sessions get the manifest on both providers."""
        for path in ("hooks/hooks.json", "packages/codex/hooks/hooks.json"):
            matcher = json.loads((ROOT / path).read_text())["hooks"]["SessionStart"][0]["matcher"]
            self.assertIn("resume", matcher.split("|"), path)

    def test_user_prompt_route_is_small_and_only_on_a_match(self) -> None:
        """Table-driven triggers; no match adds nothing; every output stays under the Codex cap."""
        cases = (
            ("/workflow ship it", "workflow"),
            ("please crack on with the plan", "agentic-loop"),
            ("run a premortem on this", "premortem"),
            ("what is the weather", None),
        )
        for provider in self.providers:
            prefix = "coderails" if provider.name == "claude" else "coderails-codex"
            for prompt, skill in cases:
                payload = {"session_id": "no-loop-session", "cwd": str(provider.home), "prompt": prompt}
                text = str(run_hook(provider, "inject_context", payload)["additionalContext"])
                self.assertLessEqual(len(text.encode()), PROMPT_CEILING, text)
                if skill is None:
                    self.assertNotIn("route:", text)
                else:
                    self.assertIn(f"route: {prefix}:{skill}", text, (provider.name, prompt))
            active = {"session_id": provider.session, "cwd": str(provider.home), "prompt": "hello"}
            self.assertIn(
                f"route: {prefix}:agentic-loop", str(run_hook(provider, "inject_context", active)["additionalContext"])
            )
            for raw in ("not json", "[]"):
                self.assertNotIn("route:", str(run_hook(provider, "inject_context", raw)["additionalContext"]))

    def test_claude_user_prompt_uses_payload_cwd(self) -> None:
        """The branch reported is the payload cwd's, not the hook process's."""
        provider = self.providers[0]
        repo = provider.home / "repo"
        subprocess.run(["git", "init", "-q", "-b", "payload-branch", str(repo)], check=True)
        text = str(run_hook(provider, "inject_context", {"cwd": str(repo), "prompt": "x"})["additionalContext"])
        self.assertIn("branch=payload-branch", text)
        self.assertIn(f"cwd={repo}", text)

    def test_one_percent_rule_removed_from_both_skills(self) -> None:
        """Advisory text only: the skill files remain and stay model-invoked-only."""
        for path in ("skills/using-coderails/SKILL.md", "packages/codex/skills/using-coderails/SKILL.md"):
            body = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("1%", body, path)
        self.assertIn("user-invocable: false", (ROOT / "skills/using-coderails/SKILL.md").read_text())


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
