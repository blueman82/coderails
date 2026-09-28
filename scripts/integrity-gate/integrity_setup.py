"""Owner-authenticated GitHub ruleset setup with explicit review before creation."""

import json
import subprocess
import sys

from integrity_http import IntegrityError, JsonObject, array_value, object_value

RULESET_NAME = "coderails-integrity-review"


def ruleset_payload() -> JsonObject:
    """Describe the PR and integrity status policy without bypass actors."""
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 0,
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": False,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [{"context": "integrity-review", "integration_id": -1}],
                },
            },
        ],
    }


def ruleset_matches(value: JsonObject) -> bool:
    """Require the existing policy's essential branch, bypass and gate constraints."""
    try:
        conditions = object_value(object_value(value.get("conditions")).get("ref_name"))
        rules = array_value(value.get("rules"))
        checks = [
            check
            for rule in rules
            if rule.get("type") == "required_status_checks"
            for check in array_value(object_value(rule.get("parameters")).get("required_status_checks"))
            if check.get("context") == "integrity-review"
        ]
        return (
            value.get("name") == RULESET_NAME
            and value.get("target") == "branch"
            and value.get("enforcement") == "active"
            and value.get("bypass_actors", []) == []
            and "refs/heads/main" in conditions.get("include", [])
            and len([rule for rule in rules if rule.get("type") == "pull_request"]) == 1
            and len(checks) == 1
        )
    except (IntegrityError, TypeError):
        return False


def recovery() -> None:
    """Offer one interactive credential/connectivity recovery before retrying."""
    print(
        "GitHub access needs recovery. Run:\n  gh auth status\n  gh auth login --hostname github.com", file=sys.stderr
    )
    try:
        input("Complete gh recovery, then press Enter to retry (Ctrl-C cancels): ")
    except EOFError as error:
        raise IntegrityError("gh recovery cancelled; setup stopped") from error


def gh_array(endpoint: str) -> list[JsonObject]:
    """Fetch a rules array, recovering once from transport or malformed JSON."""
    for attempt in range(2):
        result = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, check=False)
        try:
            if result.returncode:
                raise IntegrityError("gh request failed")
            return array_value(json.loads(result.stdout))
        except (ValueError, IntegrityError):
            if attempt:
                raise IntegrityError("gh retry failed or returned malformed JSON; setup stopped") from None
            print("Could not read valid JSON from GitHub; check access before retrying.", file=sys.stderr)
            recovery()
    raise IntegrityError("GitHub response unavailable")


def configure_ruleset(slug: str) -> None:
    """Verify a matching ruleset or present the exact proposed creation to its owner."""
    endpoint = f"repos/{slug}/rulesets?per_page=100"
    existing = next((rule for rule in gh_array(endpoint) if rule.get("name") == RULESET_NAME), None)
    if existing is not None:
        if not ruleset_matches(existing):
            raise IntegrityError(f"ruleset {RULESET_NAME} exists but differs; refusing to overwrite it")
        print(f"GitHub ruleset {RULESET_NAME} already exists and matches the required policy.")
        return
    payload = json.dumps(ruleset_payload(), indent=2)
    print(f"Proposed GitHub ruleset for main:\n{payload}")
    try:
        approved = input("Create this ruleset using the owner gh account? [y/N] ").strip().lower() == "y"
    except EOFError:
        approved = False
    if not approved:
        raise IntegrityError("ruleset creation cancelled; validator installation not started")
    result = subprocess.run(
        ["gh", "api", f"repos/{slug}/rulesets", "--method", "POST", "--input", "-"],
        input=payload,
        text=True,
        stdout=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise IntegrityError(
            "GitHub rejected ruleset creation; check owner administration permission and repository plan"
        )
    created = next((rule for rule in gh_array(endpoint) if rule.get("name") == RULESET_NAME), None)
    if created is None or not ruleset_matches(created):
        raise IntegrityError("created ruleset failed verification")
    print(f"GitHub ruleset created and verified: {RULESET_NAME}")
