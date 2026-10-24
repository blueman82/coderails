"""Set up a source-bound GitHub ruleset after a live Actions status exists."""

from __future__ import annotations

import json
import re
import subprocess
from typing import cast

from integrity_http import IntegrityError, JsonObject, array_value, object_value

RULESET_NAME = "coderails-integrity-review"


def gh_json(endpoint: str, *, method: str = "GET", body: object = None) -> object:
    """Fetch one checked JSON response through the owner's existing gh login."""
    command = ["gh", "api", endpoint]
    if method != "GET":
        command.extend(["--method", method, "--input", "-"])
    result = subprocess.run(
        command,
        input=json.dumps(body) if body is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"GitHub request failed: {endpoint}")
    try:
        return cast(object, json.loads(result.stdout))
    except ValueError as error:
        raise ValueError(f"GitHub returned invalid JSON: {endpoint}") from error


def ruleset_payload(app_id: int) -> JsonObject:
    """Require a PR and one status from the GitHub Actions app, with no bypass."""
    if app_id < 1:
        raise ValueError("GitHub Actions app id must be positive")
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
                    "required_status_checks": [{"context": "integrity-review", "integration_id": app_id}],
                },
            },
        ],
    }


def ruleset_matches(value: object, app_id: int) -> bool:
    """Refuse a weaker or different same-name ruleset."""
    if not isinstance(value, dict) or app_id < 1:
        return False
    data = object_value(cast(object, value))
    reference = data.get("conditions")
    reference = cast(JsonObject, reference).get("ref_name") if isinstance(reference, dict) else None
    if (
        data.get("name") != RULESET_NAME
        or data.get("target") != "branch"
        or data.get("enforcement") != "active"
        or data.get("bypass_actors") != []
        or not isinstance(reference, dict)
        or "refs/heads/main" not in cast(JsonObject, reference).get("include", [])
    ):
        return False
    rules = data.get("rules")
    if not isinstance(rules, list):
        return False
    try:
        typed_rules = array_value(cast(object, rules))
    except IntegrityError:
        return False
    pr = [rule for rule in typed_rules if rule.get("type") == "pull_request"]
    checks = [rule for rule in typed_rules if rule.get("type") == "required_status_checks"]
    if len(pr) != 1 or len(checks) != 1:
        return False
    pr_parameters = pr[0].get("parameters")
    check_parameters = checks[0].get("parameters")
    if not isinstance(pr_parameters, dict) or not isinstance(check_parameters, dict):
        return False
    pr_parameters = cast(JsonObject, pr_parameters)
    check_parameters = cast(JsonObject, check_parameters)
    required_pr = cast(JsonObject, cast(JsonObject, ruleset_payload(app_id)["rules"][0])["parameters"])
    return (
        all(pr_parameters.get(key) == part for key, part in required_pr.items())
        and check_parameters.get("strict_required_status_checks_policy") is False
        and check_parameters.get("required_status_checks")
        == [{"context": "integrity-review", "integration_id": app_id}]
    )


def verify_candidate(slug: str, number: int) -> str:
    """Require a live exact-head status from GitHub Actions before activation."""
    pr = object_value(gh_json(f"repos/{slug}/pulls/{number}"))
    head = pr.get("head")
    sha = cast(JsonObject, head).get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("candidate PR head is unavailable")
    statuses = array_value(gh_json(f"repos/{slug}/commits/{sha}/statuses?per_page=100"))
    status = next((item for item in statuses if item.get("context") == "integrity-review"), None)
    if not isinstance(status, dict) or status.get("state") != "success":
        raise ValueError("candidate lacks a successful integrity-review status")
    creator = status.get("creator")
    if not isinstance(creator, dict) or cast(JsonObject, creator).get("login") != "github-actions[bot]":
        raise ValueError("candidate status was not posted by GitHub Actions")
    description = status.get("description")
    if (
        not isinstance(description, str)
        or not re.search(r"(^|\s)integrity=pass(\s|$)", description)
        or not re.search(r"(^|\s)sha=" + re.escape(sha) + r"(\s|$)", description)
    ):
        raise ValueError("candidate status is not a valid SHA-bound pass")
    return sha


def configure_ruleset(slug: str, number: int, *, apply: bool) -> JsonObject:
    """Prepare or create the rule only after Actions and its status are live."""
    permissions = object_value(gh_json(f"repos/{slug}/actions/permissions"))
    if permissions.get("enabled") is not True:
        raise ValueError("GitHub Actions is disabled")
    app = object_value(gh_json("apps/github-actions"))
    app_id = app.get("id")
    if not isinstance(app_id, int) or isinstance(app_id, bool):
        raise ValueError("GitHub Actions app id is invalid")
    payload = ruleset_payload(app_id)
    verify_candidate(slug, number)
    rulesets = array_value(gh_json(f"repos/{slug}/rulesets?per_page=100"))
    existing = next((item for item in rulesets if item.get("name") == RULESET_NAME), None)
    if existing is not None:
        detail = object_value(gh_json(f"repos/{slug}/rulesets/{existing['id']}"))
        if not ruleset_matches(detail, app_id):
            raise ValueError("existing integrity ruleset differs; no overwrite was made")
        return detail
    if not apply:
        return payload
    gh_json(f"repos/{slug}/rulesets", method="POST", body=payload)
    updated = array_value(gh_json(f"repos/{slug}/rulesets?per_page=100"))
    rule = next((item for item in updated if item.get("name") == RULESET_NAME), None)
    if not isinstance(rule, dict) or not isinstance(rule.get("id"), int):
        raise ValueError("created ruleset could not be verified")
    detail = object_value(gh_json(f"repos/{slug}/rulesets/{rule['id']}"))
    if not ruleset_matches(detail, app_id):
        raise ValueError("created ruleset does not match expected policy")
    return detail
