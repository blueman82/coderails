"""Session authority summaries must match the provider authority reader."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.provider_fixture import Provider
from packages.tests.test_context_manifest import context


class ContextAuthorityTests(unittest.TestCase):
    """Exercise authority admission through both actual SessionStart hooks."""

    def setUp(self) -> None:
        """Keep provider state and authority files private to each test."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def test_authority_state(self) -> None:
        """Valid authority shows active; foreign-embedded, expired and torn files show none."""
        for provider in self.providers:
            path = Path(provider.environment["CODERAILS_AGENTIC_LOOP_DIR"]) / provider.session / "authority.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            body = {
                "authority_id": "A1",
                "loop_id": None,
                "session_id": provider.session,
                "scope": ["push"],
                "denied": [],
                "max_prs": 1,
                "expires_at": expires,
                "revocable": True,
                "approval_required_for": ["merge"],
                "granted_by": "command",
            }
            for value, expected in (
                (body, "authority: active id=A1 scope=push"),
                ({**body, "session_id": "other"}, "authority: none"),
                ({**body, "expires_at": "2000-01-01T00:00:00+00:00"}, "authority: none"),
                ("{torn", "authority: none"),
            ):
                path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
                self.assertIn(
                    expected,
                    context(provider, {"session_id": provider.session, "cwd": str(provider.home), "source": "startup"}),
                    (provider.name, value),
                )

    def test_legacy_authority_is_not_advertised(self) -> None:
        """Session context must not advertise grants rejected by the authority validator."""
        for provider in self.providers:
            path = Path(provider.environment["CODERAILS_AGENTIC_LOOP_DIR"]) / provider.session / "authority.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            body = {
                "authority_id": "legacy-grant",
                "loop_id": None,
                "session_id": provider.session,
                "scope": ["autonomous_decisions"],
                "denied": [],
                "max_prs": 1,
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "revocable": True,
                "approval_required_for": ["merge"],
            }
            for value in (body, {**body, "granted_by": "legacy_phrase"}):
                path.write_text(json.dumps(value), encoding="utf-8")
                text = context(
                    provider, {"session_id": provider.session, "cwd": str(provider.home), "source": "startup"}
                )
                self.assertIn("authority: none", text, provider.name)
                self.assertNotIn("legacy-grant", text, provider.name)


if __name__ == "__main__":
    unittest.main()
