#!/usr/bin/env python3
"""Phase 5.1 end-to-end smoke test.

Skips the MCP layer (server.py was just edited and needs a restart to
register the new @mcp.tool() decorators) and drives the Bridge client
directly. Validates the full path:

    JS DISPATCH (add_module, power_device) → Bridge typed methods
        → connect with SERIAL cable → IOS clock-rate + IP config → ping.

Prerequisites: PT 9 open, Script Module Started, api.js hot-reloaded.

Run with:
    uv run python probes/run_phase51_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from pkt_bridge import Bridge, BridgeError, PtRejected


def log(msg: str) -> None:
    print(f"[smoke] {msg}", file=sys.stderr, flush=True)


def main() -> None:
    b = Bridge(timeout=120)

    # Clean slate.
    log("listing existing user devices")
    existing = b.list_devices()
    user_names = [d["name"] for d in existing if not d["name"].startswith("Power Distribution Device")]
    for name in user_names:
        log(f"deleting {name}")
        try: b.delete_device(name)
        except BridgeError as e: log(f"  ignored: {e}")

    # Place the two endpoints.
    log("add R1 (2811)")
    b.add_device(type="ROUTER", name="R1", model="2811", x=120, y=120)
    log("add R2 (2811)")
    b.add_device(type="ROUTER", name="R2", model="2811", x=320, y=120)

    # Phase 5.1 op #1: install WIC-1T on each. Expect Serial0/0/0 appears.
    log("add_module R1 ← WIC-1T")
    r1_mod = b.add_module("R1", "WIC-1T")
    log(f"  -> {json.dumps(r1_mod)}")
    assert r1_mod["new_ports"] == ["Serial0/0/0"], r1_mod
    log("add_module R2 ← WIC-1T")
    r2_mod = b.add_module("R2", "WIC-1T")
    log(f"  -> {json.dumps(r2_mod)}")
    assert r2_mod["new_ports"] == ["Serial0/0/0"], r2_mod

    # Verify the port exists from the device's perspective.
    log("get_port_state R1/Serial0/0/0")
    s1 = b.get_port_state("R1", "Serial0/0/0")
    log(f"  -> {json.dumps(s1)}")
    assert s1.get("link") in (None, "", False), f"R1 should not be linked yet: {s1}"

    # Cable.
    log("connect R1 Serial0/0/0 <-> R2 Serial0/0/0 (SERIAL)")
    b.connect("R1", "Serial0/0/0", "R2", "Serial0/0/0", "SERIAL")

    # Determine which side is DCE. `show controllers serial 0/0/0` reports
    # "DCE V.35" or "DTE V.35" — but its full output trips PT's `--More--`
    # paginator (PT 9.0.0 doesn't accept `terminal length 0`, so we can't
    # disable it). Pipe through `include` to keep it short.
    log("show controllers R1 (filtered)")
    r1_ctl_resp = b.run_commands("R1", [
        "enable",
        "show controllers Serial0/0/0 | include DCE|DTE",
    ])
    r1_ctl = "\n".join(r["output"] for r in r1_ctl_resp["results"])
    dce_is_r1 = "DCE" in r1_ctl
    dce, dte = ("R1", "R2") if dce_is_r1 else ("R2", "R1")
    log(f"  controllers tail: {r1_ctl[-200:]!r}")
    log(f"  DCE={dce}, DTE={dte}")

    # Configure both ends. DCE gets clock rate; both get IP + no shut.
    log(f"configure {dce} (DCE) Serial0/0/0 with clock + ip")
    b.run_commands(dce, [
        "enable", "configure terminal",
        "interface Serial0/0/0",
        "clock rate 64000",
        "ip address 10.0.0.1 255.255.255.252" if dce == "R1" else "ip address 10.0.0.2 255.255.255.252",
        "no shutdown", "end",
    ])
    log(f"configure {dte} (DTE) Serial0/0/0 with ip")
    b.run_commands(dte, [
        "enable", "configure terminal",
        "interface Serial0/0/0",
        "ip address 10.0.0.2 255.255.255.252" if dce == "R1" else "ip address 10.0.0.1 255.255.255.252",
        "no shutdown", "end",
    ])

    # Poll for line protocol up on both ends — serial link negotiation
    # can lag config commit by 2-10 s.
    log("waiting for line protocol up on both ends")
    deadline = time.time() + 30.0
    while time.time() < deadline:
        s1 = b.get_port_state("R1", "Serial0/0/0")
        s2 = b.get_port_state("R2", "Serial0/0/0")
        if s1["protocol_up"] and s2["protocol_up"]:
            break
        time.sleep(1.0)
    log(f"  R1: {json.dumps(s1)}")
    log(f"  R2: {json.dumps(s2)}")
    assert s1["protocol_up"] and s2["protocol_up"], "line protocol never came up"

    # Ping across. Issue the ping, then poll the terminal buffer with
    # empty run_command calls until the "Success rate" line appears or
    # we hit the deadline (cisco ping = 5 packets × ~2s per timeout).
    log("ping R2 -> R1 (across serial)")
    dst_ip = "10.0.0.1" if dce == "R1" else "10.0.0.2"
    b.run_command("R2", f"ping {dst_ip}")
    deadline = time.time() + 20.0
    final_out = ""
    while time.time() < deadline:
        time.sleep(1.0)
        final_out = b.run_command("R2", "")["output"]
        if "Success rate is" in final_out:
            break
    log("  ping output (tail 400):")
    log(final_out[-400:])
    assert "Success rate is 100 percent" in final_out, \
        f"ping did not succeed: {final_out[-400:]}"

    # Phase 5.1 op #2: power_device. Toggle R1 off and on.
    log("power_device R1 off")
    off = b.power_device("R1", False)
    log(f"  -> {json.dumps(off)}")
    assert off["power"] is False
    log("power_device R1 on")
    on = b.power_device("R1", True)
    log(f"  -> {json.dumps(on)}")
    assert on["power"] is True

    log("===== PHASE 5.1 SMOKE TEST PASSED =====")
    log("Both add_module and power_device round-trip end-to-end.")
    log("Serial WAN with SERIAL cable type works.")


if __name__ == "__main__":
    main()
