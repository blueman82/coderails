#!/usr/bin/env python3
"""Record bounded, provider-native teardown metadata."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from runtime.graph import write_json  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("state", type=Path)
args = parser.parse_args()
state = json.loads(args.state.read_text(encoding="utf-8"))
revision = state.get("revision", 0)
state["teardown"] = {"provider": "codex", "at": datetime.now(timezone.utc).isoformat()}
write_json(args.state, state, expected_revision=revision)
