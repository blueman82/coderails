#!/usr/bin/env python3
"""Owner-run installation of the complete root-owned mechanical integrity daemon."""

import subprocess
import sys
from pathlib import Path

from integrity_http import IntegrityError
from integrity_install import (
    LABEL,
    RUNTIME_FILES,
    classify_mode,
    diff_before_promote,
    other_instance_labels,
    preflight,
    promote,
    render_plist,
)


def main() -> int:
    """Prepare a reviewable promotion before any privileged install or activation."""
    try:
        source = Path(__file__).resolve().parent
        root, destination, creds, slug = preflight()
        rules = subprocess.run(
            ["gh", "api", "repos/{owner}/{repo}/rules/branches/main"], capture_output=True, text=True, check=False
        )
        print(classify_mode(rules.stdout))
        rendered = render_plist(source / f"{LABEL}.plist.template", root / RUNTIME_FILES[0], root / "credentials", slug)
        clean = True
        for filename in RUNTIME_FILES:
            clean = diff_before_promote(source / filename, root / filename, filename) and clean
        others = other_instance_labels(destination, "/Library/LaunchDaemons/com.coderails.integrity-gate*.plist")
        if others:
            print(f"WARNING: OTHER installed daemons share {root}; this updates their runner/credentials too:")
            print("\n".join(others))
        if not clean or others:
            try:
                approved = input("Promote the repo copy to the root-owned install? [y/N] ").strip().lower() == "y"
            except EOFError:
                approved = False
            if not approved:
                raise IntegrityError("Aborted — installed copy left unchanged.")
        promote(source, root, creds, destination, rendered)
        print(f"INSTALL COMPLETE — daemon: {LABEL}")
        print(f"Health check: sudo launchctl print system/{LABEL}")
        print("tail -n 50 /var/log/coderails-integrity-gate.log")
        return 0
    except (OSError, ValueError, IntegrityError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
