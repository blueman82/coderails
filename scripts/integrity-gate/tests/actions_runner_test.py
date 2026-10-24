"""Keep trusted workflow dispatch scoped to PR numbers from GitHub events."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_actions import main, select_prs


class Pages:
    """Return numbered PR pages without network access."""

    def __init__(self, numbers: list[int]) -> None:
        """Keep a finite PR roster and the requested page list."""
        self.numbers = numbers
        self.calls: list[str] = []

    def get_array(self, target: str) -> list[dict[str, int]]:
        """Return the requested 100-row page."""
        self.calls.append(target)
        page = int(target.rsplit("page=", 1)[1])
        return [{"number": number} for number in self.numbers[(page - 1) * 100 : page * 100]]


class ActionsRunnerTests(unittest.TestCase):
    """Select only the PRs named by a trusted event field."""

    def test_comment_events_only_select_pull_requests(self) -> None:
        """Ignore comments on issues that are not PRs."""
        pages = Pages([])
        self.assertEqual(select_prs(pages, "issue_comment", {"issue": {"number": 7, "pull_request": {}}}), [7])
        self.assertEqual(select_prs(pages, "issue_comment", {"issue": {"number": 7}}), [])
        self.assertEqual(pages.calls, [])

    def test_schedule_reconciles_all_open_pages(self) -> None:
        """The hourly run reads every open PR page."""
        pages = Pages(list(range(1, 202)))
        self.assertEqual(select_prs(pages, "schedule", {}), list(range(1, 202)))
        self.assertEqual(len(pages.calls), 3)

    def test_untrusted_event_number_is_rejected(self) -> None:
        """A text value never becomes an API path number."""
        pages = Pages([])
        self.assertEqual(select_prs(pages, "pull_request_target", {"pull_request": {"number": "7"}}), [])

    def test_default_diff_limit_admits_current_roadmap_size(self) -> None:
        """The deployed entrypoint passes the 512 KiB bound to the policy."""
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "event.json"
            event.write_text(json.dumps({"pull_request": {"number": 7}}))
            context = {
                "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_TOKEN": "test-token",
                "GITHUB_EVENT_NAME": "pull_request_target",
                "GITHUB_EVENT_PATH": str(event),
            }
            with (
                patch.dict(os.environ, context),
                patch("integrity_actions.Client") as client,
                patch("integrity_actions.gate_pr", return_value=0) as gate,
            ):
                self.assertEqual(main(), 0)
            gate.assert_called_once_with(client.return_value, 7, 524288, 0)


if __name__ == "__main__":
    unittest.main()
