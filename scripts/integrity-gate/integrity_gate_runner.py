#!/usr/bin/env python3
"""Poll open PRs once using the root-owned mechanical integrity attestor."""

import os
from pathlib import Path

from integrity_http import Client, IntegrityError, credentials, log, repo_slug
from integrity_policy import gate_pr


def main() -> int:
    """Run one isolated poll; transport failure logs a failed tick without crashing."""
    try:
        values = credentials(Path(os.environ.get("INTEGRITY_GATE_CREDS", "")))
        client = Client(repo_slug(), values["GH_TOKEN"], values["MACHINE_USER"])
        prs = client.get_array("pulls?state=open&per_page=100")
        maximum = int(os.environ.get("INTEGRITY_GATE_MAX_DIFF_BYTES", "204800"))
        ttl = int(os.environ.get("INTEGRITY_GATE_PENDING_TTL", "720"))
        log(f"tick: prs={len(prs)}")
        for item in prs:
            number = item.get("number")
            if isinstance(number, int) and not isinstance(number, bool):
                gate_pr(client, number, maximum, ttl)
    except (OSError, ValueError, IntegrityError):
        log("tick: pr_fetch=FAILED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
