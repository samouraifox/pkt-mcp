#!/usr/bin/env python3
"""Phase 5.2 smoke + benchmark.

Drives Bridge directly (skips MCP — server needs a restart to register
add_devices / connect_many @mcp.tool() decorators).

Sequence:
  1. Clean any leftover devices from previous tests.
  2. add_devices for 6 routers + 1 switch (one MCP call). Times wall
     clock; expect ~30-45s (parallel boot window), NOT 7 × 30s = 210s
     (what serial add_device would take).
  3. connect_many for 5 ETHERNET_STRAIGHT cables (one MCP call).
  4. Sanity-check: list_devices shows all 7 placed, each cable created
     a link.
  5. Cleanup.

Run with:
    uv run python probes/run_phase52_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from pkt_bridge import Bridge


def log(msg: str) -> None:
    print(f"[smoke52] {msg}", file=sys.stderr, flush=True)


def main() -> None:
    b = Bridge(timeout=180)

    # Reload api.js so the new ops are live in PT's DISPATCH.
    log("reload_api")
    ops = b.reload_api()["ops"]
    log(f"  live ops: {ops}")
    assert "add_devices" in ops, f"add_devices not in DISPATCH: {ops}"
    assert "connect_many" in ops, f"connect_many not in DISPATCH: {ops}"

    # Clean slate — drop any user devices from prior tests.
    existing = b.list_devices()
    user = [d["name"] for d in existing if not d["name"].startswith("Power Distribution Device")]
    if user:
        log(f"cleaning up {len(user)} leftover devices: {user}")
        for name in user:
            try:
                b.delete_device(name)
            except Exception as e:
                log(f"  ignored delete failure for {name}: {e}")

    # === add_devices benchmark ===
    devices = [
        {"type": "ROUTER", "name": "R1", "model": "2811", "x": 100, "y": 100},
        {"type": "ROUTER", "name": "R2", "model": "2811", "x": 250, "y": 100},
        {"type": "ROUTER", "name": "R3", "model": "2811", "x": 400, "y": 100},
        {"type": "ROUTER", "name": "R4", "model": "2911", "x": 550, "y": 100},
        {"type": "ROUTER", "name": "R5", "model": "2911", "x": 700, "y": 100},
        {"type": "ROUTER", "name": "R6", "model": "2911", "x": 850, "y": 100},
        {"type": "SWITCH", "name": "SW1", "model": "2960-24TT", "x": 475, "y": 300},
    ]

    log(f"add_devices: placing {len(devices)} devices in one call …")
    t0 = time.monotonic()
    result = b.add_devices(devices)
    dt = time.monotonic() - t0
    log(f"  wall clock: {dt:.1f}s")

    rows = result["results"]
    assert len(rows) == len(devices), f"result count mismatch: {len(rows)} vs {len(devices)}"
    failures = [(i, r) for i, r in enumerate(rows) if "error" in r]
    if failures:
        log(f"FAILURES:")
        for i, r in failures:
            log(f"  row {i} ({devices[i]['name']}): {r['error']}")
        sys.exit(1)

    for i, r in enumerate(rows):
        log(f"  row {i}: ok={r.get('ok')} uuid={r.get('uuid')} name={r.get('name')}")

    # Sanity check: list_devices sees all 7
    listed = b.list_devices()
    names_listed = {d["name"] for d in listed}
    for d in devices:
        assert d["name"] in names_listed, f"{d['name']} not in list_devices output"

    # Compare against serial baseline. 6 routers × ~30s = 180s serial; the
    # switch adds ~3s. So serial expectation is ~180-210s. Anything below
    # 60s means substantial parallelism, below 45s means full parallelism.
    serial_estimate = 6 * 30 + 3
    speedup = serial_estimate / dt if dt > 0 else float("inf")
    log(f"  serial baseline estimate: ~{serial_estimate}s; observed speedup ≈ {speedup:.1f}x")
    if dt < 60:
        log(f"  ✅ parallel boot CONFIRMED (well under serial baseline)")
    else:
        log(f"  ⚠ slower than expected — check for serialization in PT or JS event loop")

    # === connect_many ===
    # Star topology: SW1 ↔ each router via Fa0/2 (router) ↔ Fa0/1..Fa0/6 (switch).
    # 2811 has Fa0/0..Fa0/1; 2911 has Gi0/0..Gi0/2. Use the right port per model.
    def router_uplink_port(model: str) -> str:
        if model.startswith("28") or model.startswith("18"):
            return "FastEthernet0/0"
        # 2911 and modern ISRs
        return "GigabitEthernet0/0"

    # Switch has Fa0/1..0/24 + Gi0/1..0/2. Pair Fa to 2811 (Fa-Fa) and Gi to 2911 (Gi-Gi).
    # SW1 only has Gi0/1 and Gi0/2 so we can't connect 3× 2911s via Gi. Mix:
    # R1/R2/R3 (2811, Fa) → SW1.Fa0/1..0/3
    # R4 (2911, Gi)        → SW1.Gi0/1
    # R5 (2911, Gi)        → SW1.Gi0/2
    # R6 (2911, Gi)        → skip (no more Gi uplinks on SW1).
    links = [
        {"dev_a": "R1", "port_a": "FastEthernet0/0", "dev_b": "SW1",
         "port_b": "FastEthernet0/1", "cable_type": "ETHERNET_STRAIGHT"},
        {"dev_a": "R2", "port_a": "FastEthernet0/0", "dev_b": "SW1",
         "port_b": "FastEthernet0/2", "cable_type": "ETHERNET_STRAIGHT"},
        {"dev_a": "R3", "port_a": "FastEthernet0/0", "dev_b": "SW1",
         "port_b": "FastEthernet0/3", "cable_type": "ETHERNET_STRAIGHT"},
        {"dev_a": "R4", "port_a": "GigabitEthernet0/0", "dev_b": "SW1",
         "port_b": "GigabitEthernet0/1", "cable_type": "ETHERNET_STRAIGHT"},
        {"dev_a": "R5", "port_a": "GigabitEthernet0/0", "dev_b": "SW1",
         "port_b": "GigabitEthernet0/2", "cable_type": "ETHERNET_STRAIGHT"},
    ]
    log(f"connect_many: creating {len(links)} cables in one call …")
    t1 = time.monotonic()
    cresult = b.connect_many(links)
    dt2 = time.monotonic() - t1
    log(f"  wall clock: {dt2:.2f}s ({dt2 * 1000 / len(links):.0f}ms / link)")

    crows = cresult["results"]
    cfails = [(i, r) for i, r in enumerate(crows) if "error" in r]
    if cfails:
        log(f"FAILURES:")
        for i, r in cfails:
            log(f"  row {i}: {r['error']}")
        sys.exit(1)
    log(f"  all {len(crows)} links OK")

    # Test that one bad row doesn't abort the others.
    log("partial-failure test: mix one good row + one bad row (unknown device)")
    mixed = [
        {"dev_a": "R6", "port_a": "GigabitEthernet0/1", "dev_b": "DOES_NOT_EXIST",
         "port_b": "FastEthernet0/1", "cable_type": "ETHERNET_STRAIGHT"},
        {"dev_a": "R6", "port_a": "GigabitEthernet0/2", "dev_b": "SW1",
         "port_b": "FastEthernet0/6", "cable_type": "ETHERNET_STRAIGHT"},
    ]
    mresult = b.connect_many(mixed)
    mrows = mresult["results"]
    assert "error" in mrows[0], f"row 0 should have errored: {mrows[0]}"
    assert mrows[1].get("ok") is True, f"row 1 should have succeeded: {mrows[1]}"
    log(f"  row 0 errored cleanly: {mrows[0]['error']['type']}")
    log(f"  row 1 succeeded — partial-failure isolation works")

    log(f"===== PHASE 5.2 SMOKE PASSED =====")
    log(f"  add_devices(7 devices): {dt:.1f}s vs ~{serial_estimate}s serial ({speedup:.1f}x)")
    log(f"  connect_many(5 cables): {dt2:.2f}s")


if __name__ == "__main__":
    main()
