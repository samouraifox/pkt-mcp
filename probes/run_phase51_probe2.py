#!/usr/bin/env python3
"""Phase 5.1 Step 1 probe — iteration 2 runner."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from pkt_bridge import Bridge


def main() -> None:
    js_path = os.path.join(ROOT, "probes", "phase51_module_probe2.js")
    with open(js_path) as f:
        code = f.read()
    bridge = Bridge(timeout=180)
    print(f"shipping probe ({len(code)} bytes) ...", file=sys.stderr)
    result = bridge.raw(code)
    out_path = os.path.join(ROOT, "probes", "phase51_probe2_result.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"wrote {out_path}", file=sys.stderr)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
