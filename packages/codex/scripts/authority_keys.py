#!/usr/bin/env python3
"""Owner-run key setup for signed action receipts. Never run by an agent: it needs the owner at a terminal.

init          create the PASSPHRASE-PROTECTED ed25519 receipt key (ssh-keygen prompts on /dev/tty; refuses when
              there is no tty) and write the user-tier signers file (a cooperating-agent safeguard: the same user,
              hence an agent, can edit that file).
install-root  only PRINTS the sudo command that installs the signers file as the root-owned trust root (the real
              boundary); this tool never runs sudo.
show          print the fingerprints of the key and of both trust-root tiers.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import receipt_signing as rs


def key_path(directory: Path | None = None) -> Path:
    """The private receipt key path."""
    return (directory or rs.keys_dir()) / "receipt_ed25519"


def init(directory: Path | None = None, tty_ok: Callable[[], bool] = rs.have_tty, extra: tuple[str, ...] = ()) -> int:
    """Create the key (ssh-keygen asks for the passphrase on the tty) and the user-tier signers file.

    `extra` is a function argument for tests (for example an empty passphrase); the command line has no such flag.
    """
    if not tty_ok():
        print("authority_keys: refused (receipt_refused_no_tty): init needs the owner at a terminal", file=sys.stderr)
        return 2
    directory = directory or rs.keys_dir()
    key = key_path(directory)
    if key.exists():
        print(f"authority_keys: refused (key_exists): {key} already exists; not overwriting", file=sys.stderr)
        return 2
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    made = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-C", rs.PRINCIPAL, "-f", str(key), *extra], check=False, timeout=300
    )
    if made.returncode:
        print("authority_keys: refused (keygen_failed)", file=sys.stderr)
        return 2
    public = key.with_name(key.name + ".pub").read_text().strip()
    signers = directory / "receipt_signers"
    signers.write_text(f'{rs.PRINCIPAL} namespaces="{rs.NAMESPACE}" {public}\n')
    signers.chmod(0o600)
    print(f"created {key} and {signers} (user tier: cooperating-agent safeguard). For the real boundary run:")
    print(f"  python3 {Path(__file__).name} install-root")
    return 0


def install_root(directory: Path | None = None) -> int:
    """Print (never run) the sudo commands that install the signers file as the root-owned trust root."""
    src = (directory or rs.keys_dir()) / "receipt_signers"
    dest = rs.ROOT_SIGNERS
    print("# run these yourself; they make the signers file root-owned and not group/other writable:")
    print(f"sudo install -d -o root -g wheel -m 755 {_quote(dest.parent)}")
    print(f"sudo install -o root -g wheel -m 644 {_quote(src)} {_quote(dest)}")
    return 0


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "'\\''") + "'"


def _fingerprint(line: str) -> str:
    """ssh-keygen -l for the `ssh-... AAAA...` part of a public-key or signers line."""
    words = line.split()
    start = next((i for i, w in enumerate(words) if w.startswith(("ssh-", "sk-", "ecdsa-"))), None)
    if start is None:
        return "unparseable line"
    done = subprocess.run(
        ["ssh-keygen", "-l", "-f", "-"], input=" ".join(words[start : start + 2]), capture_output=True, text=True,
        check=False,
    )  # fmt: skip
    return done.stdout.strip() or done.stderr.strip()


def show(directory: Path | None = None) -> int:
    """Print the fingerprints of the key and of each trust-root tier that exists."""
    where = directory or rs.keys_dir()
    for label, path in (("key", where / "receipt_ed25519.pub"), ("user tier", where / "receipt_signers"),
                        ("root tier", rs.ROOT_SIGNERS)):  # fmt: skip
        if not path.is_file():
            print(f"{label}: absent ({path})")
            continue
        for line in path.read_text().splitlines():
            print(f"{label}: {_fingerprint(line)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch one subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "install-root", "show"))
    args = parser.parse_args(argv)
    if args.command == "init":
        return init()
    return install_root() if args.command == "install-root" else show()


if __name__ == "__main__":
    raise SystemExit(main())
