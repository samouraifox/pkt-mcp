#!/usr/bin/env python3
"""Phase 4.11 zones probe runner — ships phase411_zones_probe.js."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from pkt_bridge import Bridge


def main() -> None:
    js_path = os.path.join(ROOT, "probes", "phase411_zones_probe.js")
    with open(js_path) as f:
        code = f.read()

    bridge = Bridge(timeout=60)
    print(f"shipping zones probe ({len(code)} bytes) ...", file=sys.stderr)
    result = bridge.raw(code)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
