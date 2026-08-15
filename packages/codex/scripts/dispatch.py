#!/usr/bin/env python3
"""JSON stdin: {"command":[...],"cwd":"..."}; JSON stdout result."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from runtime.dispatch import dispatch  # noqa: E402

request = json.load(sys.stdin)
try:
    outcome, output = dispatch(request["command"], request.get("cwd"))
    print(json.dumps({"outcome": outcome, "output": output}))
except (KeyError, TypeError, ValueError) as error:
    print(json.dumps({"outcome": "failed", "error": str(error)}))
    raise SystemExit(2)
