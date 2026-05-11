#!/usr/bin/env python3
"""Phase 4.7 probe runner.

Loads probes/phase47_probe.js, ships it via Bridge.raw(), pretty-prints
the structured report.

Usage:
    cd ~/Work/Projects/pkt-mcp
    uv run python probes/run_phase47_probe.py
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from pkt_bridge import Bridge


def main() -> None:
    js_path = os.path.join(ROOT, "probes", "phase47_probe.js")
    with open(js_path) as f:
        code = f.read()

    bridge = Bridge(timeout=120)
    print(f"shipping probe ({len(code)} bytes) ...", file=sys.stderr)
    result = bridge.raw(code)

    # Pretty-print. The probe returns a dict; structure for readability.
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
