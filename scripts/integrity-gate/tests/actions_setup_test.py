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

    def valid_pr(self) -> dict[str, object]:
        """Return an open PR against main with a fixed head."""
        return {"state": "open", "base": {"ref": "main"}, "head": {"sha": "a" * 40}}

    def valid_workflow(self) -> dict[str, object]:
        """Return the active trusted workflow metadata."""
        return {"state": "active", "path": ".github/workflows/integrity-review.yml"}

    def valid_status(self) -> dict[str, object]:
        """Return one exact-head GitHub Actions status."""
        sha = "a" * 40
        return {
            "context": "integrity-review",
            "state": "success",
            "creator": {"login": "github-actions[bot]"},
            "description": f"integrity=pass sha={sha}",
        }

    def valid_event_policy(self) -> tuple[dict[str, object], dict[str, object]]:
        """Use one active policy scoped to the trusted workflow's four triggers."""
        listing: dict[str, object] = {
            "total_count": 1,
            "policies": [{"id": 9, "name": "coderails-integrity-review-events"}],
        }
        detail: dict[str, object] = {
            "id": 9,
            "name": "coderails-integrity-review-events",
            "target": "actions",
            "enforcement": "active",
            "conditions": {"workflow_path": {"include": [".github/workflows/integrity-review.yml"], "exclude": []}},
            "rules": [
                {
                    "type": "restrict_action_events",
                    "parameters": {
                        "allowed_events": ["pull_request_target", "issue_comment", "schedule", "workflow_dispatch"]
                    },
                }
            ],
        }
        return listing, detail

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

    def test_excluded_main_is_not_a_matching_ruleset(self) -> None:
        """A same-name rule that excludes main leaves the branch unprotected."""
        payload = ruleset_payload(15368)
        payload["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
        self.assertFalse(ruleset_matches(payload, 15368))

    def test_creation_bypass_is_not_a_matching_ruleset(self) -> None:
        """The status rule must also cover the branch's first commit."""
        payload = ruleset_payload(15368)
        payload["rules"][1]["parameters"]["do_not_enforce_on_create"] = True
        self.assertFalse(ruleset_matches(payload, 15368))

    def test_candidate_requires_current_head_actions_success(self) -> None:
        """A stale, failed, or foreign status cannot activate the rule."""
        sha = "a" * 40
        good = {
            "context": "integrity-review",
            "state": "success",
            "creator": {"login": "github-actions[bot]"},
            "description": f"integrity=pass sha={sha}",
        }
        with patch("integrity_setup.gh_json", side_effect=[self.valid_pr(), [good]]):
            self.assertEqual(verify_candidate("owner/repo", 7), sha)
        for bad in (
            {**good, "creator": {"login": "writer"}},
            {**good, "state": "failure"},
            {**good, "description": "integrity=pass sha=" + "b" * 40},
        ):
            with (
                patch("integrity_setup.gh_json", side_effect=[self.valid_pr(), [bad]]),
                self.assertRaises(ValueError),
            ):
                verify_candidate("owner/repo", 7)

    def test_candidate_must_be_open_and_target_main(self) -> None:
        """A closed or differently based PR cannot authorize the branch rule."""
        for change in ("closed", "other_base"):
            with self.subTest(change=change):
                pr = self.valid_pr()
                if change == "closed":
                    pr["state"] = "closed"
                else:
                    pr["base"] = {"ref": "release"}
                with (
                    patch("integrity_setup.gh_json", side_effect=[pr, [self.valid_status()]]),
                    self.assertRaisesRegex(ValueError, "candidate PR"),
                ):
                    verify_candidate("owner/repo", 7)

    def test_workflow_must_be_active_at_expected_path(self) -> None:
        """A candidate status cannot authorize a disabled or unrelated workflow."""
        for change in ("disabled", "wrong_path"):
            with self.subTest(change=change):
                workflow = self.valid_workflow()
                if change == "disabled":
                    workflow["state"] = "disabled_manually"
                else:
                    workflow["path"] = ".github/workflows/other.yml"
                responses: list[object] = [
                    {"enabled": True},
                    {"id": 15368},
                    self.valid_pr(),
                    [self.valid_status()],
                    *self.valid_event_policy(),
                    workflow,
                    [],
                ]
                with (
                    patch("integrity_setup.gh_json", side_effect=responses),
                    self.assertRaisesRegex(ValueError, "workflow"),
                ):
                    configure_ruleset("owner/repo", 7, apply=False)

    def test_page_two_existing_ruleset_blocks_creation(self) -> None:
        """A same-name legacy rule beyond the first page must not be duplicated."""
        first_page = [{"id": index, "name": f"other-{index}"} for index in range(1, 101)]
        old_rule = {"id": 101, "name": "coderails-integrity-review"}
        responses: list[object] = [
            {"enabled": True},
            {"id": 15368},
            self.valid_pr(),
            [self.valid_status()],
            *self.valid_event_policy(),
            self.valid_workflow(),
            first_page,
            [old_rule],
            old_rule,
        ]
        with (
            patch("integrity_setup.gh_json", side_effect=responses) as api,
            self.assertRaisesRegex(ValueError, "existing integrity ruleset differs"),
        ):
            configure_ruleset("owner/repo", 7, apply=True)
        self.assertTrue(all(call.kwargs.get("method", "GET") == "GET" for call in api.call_args_list))

    def test_page_two_created_ruleset_is_read_back(self) -> None:
        """A newly created rule beyond page one must be verified by ID."""
        first_page = [{"id": index, "name": f"other-{index}"} for index in range(1, 101)]
        detail = {**ruleset_payload(15368), "id": 101}
        responses: list[object] = [
            {"enabled": True},
            {"id": 15368},
            self.valid_pr(),
            [self.valid_status()],
            *self.valid_event_policy(),
            self.valid_workflow(),
            first_page,
            [],
            detail,
            first_page,
            [{"id": 101, "name": "coderails-integrity-review"}],
            detail,
        ]
        with patch("integrity_setup.gh_json", side_effect=responses):
            self.assertEqual(configure_ruleset("owner/repo", 7, apply=True), detail)

    def test_preview_never_creates_a_ruleset(self) -> None:
        """A preview reads GitHub but sends no POST."""
        responses = [
            {"enabled": True},
            {"id": 15368},
            self.valid_pr(),
            [self.valid_status()],
            *self.valid_event_policy(),
            self.valid_workflow(),
            [],
        ]
        with patch("integrity_setup.gh_json", side_effect=responses) as api:
            self.assertTrue(ruleset_matches(configure_ruleset("owner/repo", 7, apply=False), 15368))
            self.assertTrue(all(call.kwargs.get("method", "GET") == "GET" for call in api.call_args_list))

    def test_disabled_actions_prevents_ruleset_creation(self) -> None:
        """The rule cannot activate before Actions is enabled."""
        with patch("integrity_setup.gh_json", return_value={"enabled": False}) as api:
            with self.assertRaisesRegex(ValueError, "disabled"):
                configure_ruleset("owner/repo", 7, apply=True)
            self.assertEqual(api.call_count, 1)

    def test_missing_event_allow_prevents_future_dead_gate(self) -> None:
        """A candidate status today cannot prove pull_request_target will run later."""
        responses: list[object] = [
            {"enabled": True},
            {"id": 15368},
            self.valid_pr(),
            [self.valid_status()],
            {"total_count": 0, "policies": []},
        ]
        with (
            patch("integrity_setup.gh_json", side_effect=responses),
            self.assertRaisesRegex(ValueError, "event policy"),
        ):
            configure_ruleset("owner/repo", 7, apply=False)

    def test_event_policy_must_be_active_and_allow_all_workflow_events(self) -> None:
        """An evaluate-only or malformed event rule cannot back the status gate."""
        for change in ("evaluate", "wrong_path", "missing_trigger", "malformed_event"):
            with self.subTest(change=change):
                listing, detail = self.valid_event_policy()
                if change == "evaluate":
                    detail["enforcement"] = "evaluate"
                elif change == "wrong_path":
                    detail["conditions"] = {"workflow_path": {"include": ["other.yml"], "exclude": []}}
                elif change == "missing_trigger":
                    detail["rules"] = [
                        {
                            "type": "restrict_action_events",
                            "parameters": {"allowed_events": ["issue_comment", "schedule", "workflow_dispatch"]},
                        }
                    ]
                else:
                    detail["rules"] = [
                        {"type": "restrict_action_events", "parameters": {"allowed_events": [["pull_request_target"]]}}
                    ]
                responses = [
                    {"enabled": True},
                    {"id": 15368},
                    self.valid_pr(),
                    [self.valid_status()],
                    listing,
                    detail,
                ]
                with (
                    patch("integrity_setup.gh_json", side_effect=responses),
                    self.assertRaisesRegex(ValueError, "event policy"),
                ):
                    configure_ruleset("owner/repo", 7, apply=False)

    def test_apply_reads_back_the_created_rule(self) -> None:
        """A POST alone is not proof that GitHub installed the expected rule."""
        payload = ruleset_payload(15368)
        detail = {**payload, "id": 42}
        responses = [
            {"enabled": True},
            {"id": 15368},
            self.valid_pr(),
            [self.valid_status()],
            *self.valid_event_policy(),
            self.valid_workflow(),
            [],
            detail,
            [{"id": 42, "name": "coderails-integrity-review"}],
            detail,
        ]
        with patch("integrity_setup.gh_json", side_effect=responses) as api:
            self.assertEqual(configure_ruleset("owner/repo", 7, apply=True), detail)
            self.assertEqual(api.call_args_list[8].kwargs["method"], "POST")
            self.assertEqual(api.call_args_list[8].kwargs["body"], payload)

    def test_apply_refuses_readback_that_excludes_main(self) -> None:
        """GitHub readback must prove main is covered after rule creation."""
        detail = copy.deepcopy(ruleset_payload(15368))
        detail["id"] = 42
        detail["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
        responses = [
            {"enabled": True},
            {"id": 15368},
            self.valid_pr(),
            [self.valid_status()],
            *self.valid_event_policy(),
            self.valid_workflow(),
            [],
            detail,
            [{"id": 42, "name": "coderails-integrity-review"}],
            detail,
        ]
        with (
            patch("integrity_setup.gh_json", side_effect=responses),
            self.assertRaisesRegex(ValueError, "does not match"),
        ):
            configure_ruleset("owner/repo", 7, apply=True)


if __name__ == "__main__":
    unittest.main()
