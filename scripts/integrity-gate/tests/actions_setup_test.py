"""A ruleset must bind integrity-review to GitHub Actions before activation."""

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_setup import configure_ruleset, ruleset_matches, ruleset_payload, verify_candidate


class ActionsSetupTests(unittest.TestCase):
    """Require a real Actions source before a ruleset can be activated."""

    def valid_status(self) -> dict[str, object]:
        """Return one exact-head GitHub Actions status."""
        sha = "a" * 40
        return {
            "context": "integrity-review",
            "state": "success",
            "creator": {"login": "github-actions[bot]"},
            "description": f"integrity=pass sha={sha}",
        }

    def test_ruleset_uses_expected_app_and_no_bypass(self) -> None:
        """The rule pins the expected app and keeps bypass actors empty."""
        payload = ruleset_payload(15368)
        self.assertTrue(ruleset_matches(payload, 15368))
        self.assertFalse(ruleset_matches(payload, -1))
        returned = copy.deepcopy(payload)
        returned["id"] = 24
        returned["rules"][0]["parameters"]["allowed_merge_methods"] = ["merge", "squash"]
        self.assertTrue(ruleset_matches(returned, 15368))
        self.assertEqual(payload["bypass_actors"], [])
        checks = payload["rules"][1]["parameters"]["required_status_checks"]
        self.assertEqual(checks, [{"context": "integrity-review", "integration_id": 15368}])

    def test_candidate_requires_current_head_actions_success(self) -> None:
        """A stale, failed, or foreign status cannot activate the rule."""
        sha = "a" * 40
        good = {
            "context": "integrity-review",
            "state": "success",
            "creator": {"login": "github-actions[bot]"},
            "description": f"integrity=pass sha={sha}",
        }
        with patch("integrity_setup.gh_json", side_effect=[{"head": {"sha": sha}}, [good]]):
            self.assertEqual(verify_candidate("owner/repo", 7), sha)
        for bad in (
            {**good, "creator": {"login": "writer"}},
            {**good, "state": "failure"},
            {**good, "description": "integrity=pass sha=" + "b" * 40},
        ):
            with (
                patch("integrity_setup.gh_json", side_effect=[{"head": {"sha": sha}}, [bad]]),
                self.assertRaises(ValueError),
            ):
                verify_candidate("owner/repo", 7)

    def test_preview_never_creates_a_ruleset(self) -> None:
        """A preview reads GitHub but sends no POST."""
        responses = [{"enabled": True}, {"id": 15368}, {"head": {"sha": "a" * 40}}, [self.valid_status()], []]
        with patch("integrity_setup.gh_json", side_effect=responses) as api:
            self.assertTrue(ruleset_matches(configure_ruleset("owner/repo", 7, apply=False), 15368))
            self.assertTrue(all(call.kwargs.get("method", "GET") == "GET" for call in api.call_args_list))

    def test_disabled_actions_prevents_ruleset_creation(self) -> None:
        """The rule cannot activate before Actions is enabled."""
        with patch("integrity_setup.gh_json", return_value={"enabled": False}) as api:
            with self.assertRaisesRegex(ValueError, "disabled"):
                configure_ruleset("owner/repo", 7, apply=True)
            self.assertEqual(api.call_count, 1)

    def test_apply_reads_back_the_created_rule(self) -> None:
        """A POST alone is not proof that GitHub installed the expected rule."""
        payload = ruleset_payload(15368)
        detail = {**payload, "id": 42}
        responses = [
            {"enabled": True},
            {"id": 15368},
            {"head": {"sha": "a" * 40}},
            [self.valid_status()],
            [],
            detail,
            [{"id": 42, "name": "coderails-integrity-review"}],
            detail,
        ]
        with patch("integrity_setup.gh_json", side_effect=responses) as api:
            self.assertEqual(configure_ruleset("owner/repo", 7, apply=True), detail)
            self.assertEqual(api.call_args_list[5].kwargs["method"], "POST")
            self.assertEqual(api.call_args_list[5].kwargs["body"], payload)


if __name__ == "__main__":
    unittest.main()
