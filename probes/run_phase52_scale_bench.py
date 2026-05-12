#!/usr/bin/env python3
"""Phase 5.2 scale benchmark.

Goal: validate the kickoff acceptance criterion ("100-device topology
builds in under 5 minutes") by measuring add_devices at N=20. If wall
clock stays roughly constant as N grows (vs. linear in N), parallelism
holds and the 5-min/100-device target is comfortably met. If wall clock
climbs with N, there's an internal PT serialization point worth
investigating.

Sequence:
  1. Clean workspace (delete the smoke residue: R1/R2/R3/SW1 if present).
  2. Build a 20-router batch: 10× 2811 + 10× 2911 in a 5×4 grid.
  3. Time add_devices.
  4. Compare to two baselines:
       - serial estimate: 20 × 30s = 600s
       - phase 5.2 baseline (6 routers @ 31.1s): linear ≈ 31.1s,
         extrapolation-to-N=100 cutoff at 5min = ~5x of 6-router time.
  5. Report per-device effective cost; flag any rows that failed.
  6. Clean up so the workspace is empty.

Run with:
    uv run python probes/run_phase52_scale_bench.py
"""

from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from pkt_bridge import Bridge


def log(msg: str) -> None:
    print(f"[scale] {msg}", file=sys.stderr, flush=True)


def main() -> None:
    b = Bridge(timeout=300)

    # Clean any residue.
    existing = b.list_devices()
    user = [d["name"] for d in existing
            if not d["name"].startswith("Power Distribution Device")]
    if user:
        log(f"cleaning up {len(user)} leftover devices")
        for name in user:
            try:
                b.delete_device(name)
            except Exception as e:
                log(f"  ignored delete failure for {name}: {e}")

    # Build the 20-router batch in a 5×4 grid.
    N = 20
    devices = []
    for i in range(N):
        col = i % 5
        row = i // 5
        x = 100 + col * 150
        y = 100 + row * 150
        # Alternate 2811 and 2911 to exercise both Fa-default and Gi-default
        # boot paths similarly.
        model = "2811" if i % 2 == 0 else "2911"
        devices.append({
            "type": "ROUTER",
            "name": f"BR{i+1:02d}",
            "model": model,
            "x": x,
            "y": y,
        })

    log(f"add_devices: placing {N} routers (10× 2811 + 10× 2911) in one call …")
    t0 = time.monotonic()
    result = b.add_devices(devices)
    dt = time.monotonic() - t0
    log(f"  wall clock: {dt:.1f}s")

    rows = result["results"]
    ok = sum(1 for r in rows if r.get("ok"))
    failed = [(i, r) for i, r in enumerate(rows) if "error" in r]
    log(f"  rows: {ok}/{N} ok, {len(failed)} failed")
    for i, r in failed:
        log(f"    row {i} ({devices[i]['name']}): {r['error']}")

    if failed:
        log("FAILURES present — benchmark inconclusive")
        sys.exit(1)

    # Compare baselines.
    serial = N * 30
    phase52_6router = 31.1
    speedup_vs_serial = serial / dt
    multiplier_vs_6 = dt / phase52_6router
    per_dev = dt / N
    log("---")
    log(f"  serial baseline (N × 30s):       {serial}s")
    log(f"  speedup vs serial:               {speedup_vs_serial:.1f}×")
    log(f"  vs 6-router baseline (31.1s):    {multiplier_vs_6:.2f}×")
    log(f"  effective per-device cost:       {per_dev:.2f}s")
    log("---")

    # Project to N=100 — the kickoff acceptance criterion.
    # If wall clock is ~constant with N (full parallelism), projection is
    # roughly the same dt. If it scales linearly with N, projection is
    # dt × (100/N).
    if multiplier_vs_6 < 1.3:
        log(f"  ✅ parallelism HOLDS at N={N} (within 30% of 6-router baseline)")
        log(f"     projected N=100: ~{dt:.0f}s (well under 300s acceptance)")
    elif multiplier_vs_6 < 2.5:
        log(f"  ⚠ partial slowdown at N={N} ({multiplier_vs_6:.1f}× baseline)")
        log(f"     projected N=100 (linear-in-N model): ~{dt * 100 / N:.0f}s")
    else:
        log(f"  ❌ significant slowdown at N={N} ({multiplier_vs_6:.1f}× baseline)")
        log(f"     PT may have an internal serialization point — investigate")

    # Cleanup.
    log("cleaning up …")
    for d in devices:
        try:
            b.delete_device(d["name"])
        except Exception as e:
            log(f"  ignored delete failure for {d['name']}: {e}")

    log("===== PHASE 5.2 SCALE BENCHMARK DONE =====")


if __name__ == "__main__":
    main()
