#!/usr/bin/env python3
"""Replace this process with one provider-local queue sweep using the fixed Node runtime."""

import os
from pathlib import Path

NODE = "/opt/homebrew/bin/node"
TARGET = Path(__file__).resolve().parent.parent / "src/main.ts"


def main() -> None:
    """Keep the fixed Node runtime independent of the caller's inherited PATH."""
    os.execv(NODE, [NODE, str(TARGET)])


if __name__ == "__main__":
    main()
