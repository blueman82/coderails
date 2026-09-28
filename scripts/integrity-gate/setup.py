#!/usr/bin/env python3
"""Owner-run setup of the optional product-neutral integrity attestor."""

import getpass
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from integrity_http import Client, IntegrityError
from integrity_install import resolve_repo_slug
from integrity_setup import RULESET_NAME, configure_ruleset, recovery


def install_with_credentials(installer: Path, slug: str) -> None:
    """Verify the machine token and securely pass a temporary credentials file."""
    login = input("Machine-user GitHub login: ")
    if not re.fullmatch(r"[A-Za-z0-9-]+", login):
        raise IntegrityError("invalid GitHub login")
    token = getpass.getpass("Machine-user token: ")
    if not token or "\n" in token or "\r" in token:
        raise IntegrityError("token cannot be empty or contain line breaks")
    actual = Client(slug, token, login).get_object("https://api.github.com/user").get("login")
    if actual != login:
        raise IntegrityError(f"token belongs to '{actual}', not '{login}'")
    with tempfile.NamedTemporaryFile(prefix="coderails-integrity-credentials.", mode="w") as creds:
        os.fchmod(creds.fileno(), 0o600)
        creds.write(f"GH_TOKEN={token}\nMACHINE_USER={login}\n")
        creds.flush()
        token = ""
        print("The next command installs a root-owned launchd daemon and protected credentials.")
        input("Press Enter to continue; sudo may ask for your password (Ctrl-C cancels): ")
        subprocess.run(["sudo", "-v"], check=True)
        environment = dict(os.environ, TGI_CREDS_SRC=creds.name)
        subprocess.run([sys.executable, str(installer)], env=environment, check=True)


def main() -> int:
    """Keep dry-run free of writes, credentials, ruleset mutations and activation."""
    try:
        installer = Path(__file__).resolve().with_name("install.py")
        if not installer.is_file() or not os.access(installer, os.X_OK):
            raise IntegrityError(f"missing executable {installer}")
        for tool in ("gh", "curl", "git"):
            if not shutil.which(tool):
                raise IntegrityError(f"{tool} is required")
        try:
            slug = resolve_repo_slug()
        except IntegrityError:
            recovery()
            try:
                slug = resolve_repo_slug()
            except IntegrityError as error:
                raise IntegrityError("gh retry failed; check GitHub connectivity and repository access") from error
        if sys.argv[1:2] == ["--dry-run"]:
            print(f"Would configure the product-neutral integrity gate for {slug}.")
            print(f"Would offer to create/verify the GitHub ruleset {RULESET_NAME} on main.")
            print(
                "The owner would be prompted for the machine-user token, then sudo would install the root-owned daemon."
            )
            return 0
        configure_ruleset(slug)
        print(f"Optional integrity gate for {slug}; protects merges for Claude, Codex, or any other client.")
        print("Use a dedicated GitHub machine-user login with status-write access only.")
        install_with_credentials(installer, slug)
        print(f"Installed the independent integrity gate for {slug}.")
        print("GitHub must still require integrity-review on main for server-side enforcement.")
        return 0
    except (OSError, EOFError, ValueError, IntegrityError, subprocess.CalledProcessError) as error:
        print(f"setup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
