#!/usr/bin/env python3
"""Phase 3 smoke test — rebuilds the M6 topology end-to-end and asserts
PC1 → R1 ICMP reachability, going through the typed Bridge client only
(no raw eval, no out-of-band JS).

This is the regression suite from Phase 3 onward. Runs against a live PT
with the pkt-mcp Script Module loaded and Started; doesn't mock anything.
The test deletes R1/SW1/PC1 first if they exist, so it's rerunnable.

Run:
    python tests/test_smoke.py
or:
    pytest tests/test_smoke.py -v -s
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from pkt_bridge import Bridge, PtNotFound  # noqa: E402

PING_DEADLINE_S = 15.0     # one ping batch (~5s) + buffer
PING_POLL_S = 0.5
PING_ATTEMPTS = 4          # STP convergence on a fresh 2960 access port is
                           # ~30 s (listening + learning); the first 1–2
                           # batches drop / partially drop until it lands.


def _reset_topology(b: Bridge) -> None:
    for name in ("PC1", "SW1", "R1"):
        try:
            b.delete_device(name)
        except PtNotFound:
            pass


def _last_ping_section(output: str, target: str) -> str:
    """Slice from the last 'Pinging <target>' header to the end — so we
    only look at the most recent ping batch when retrying."""
    idx = output.rfind(f"Pinging {target}")
    return output[idx:] if idx >= 0 else output


def _ping_with_retry(b: Bridge, host: str, target: str) -> str:
    """Issue ping, poll buffer for the batch's outcome. Retry until we get
    a 4/4 batch (the M6 success criterion) — partial-loss batches mean STP
    is still converging on the freshly-connected switchport. Returns the
    full buffer either way."""
    output = ""
    for _ in range(PING_ATTEMPTS):
        b.run_command(host, f"ping {target}")
        deadline = time.time() + PING_DEADLINE_S
        while time.time() < deadline:
            resp = b.run_command(host, "")  # empty enter refreshes buffer
            output = resp["output"]
            section = _last_ping_section(output, target)
            # "Lost = 0" only — "0% loss" is a substring of "100% loss".
            if "Packets: Sent" in section:
                if "Lost = 0" in section:
                    return output
                break  # any loss → retry
            time.sleep(PING_POLL_S)
    return output


def test_m6_topology_and_ping() -> None:
    b = Bridge()
    _reset_topology(b)

    # ── topology ────────────────────────────────────────────────────────
    r1 = b.add_device(type="ROUTER", name="R1", model="2911", x=200, y=200)
    sw1 = b.add_device(type="SWITCH", name="SW1", model="2960-24TT", x=400, y=200)
    pc1 = b.add_device(type="PC", name="PC1", model="PC-PT", x=600, y=200)
    assert r1["name"] == "R1"
    assert sw1["name"] == "SW1"
    assert pc1["name"] == "PC1"

    devices = {d["name"]: d for d in b.list_devices()}
    assert {"R1", "SW1", "PC1"} <= set(devices), f"missing devices: {devices.keys()}"
    assert devices["R1"]["type"] == "ROUTER"
    assert devices["PC1"]["type"] == "PC"

    # ── links (R1 G0/0 ↔ SW1 Fa0/1, SW1 Fa0/2 ↔ PC1 Fa0) ────────────────
    b.connect("R1", "GigabitEthernet0/0", "SW1", "FastEthernet0/1", "ETHERNET_STRAIGHT")
    b.connect("SW1", "FastEthernet0/2", "PC1", "FastEthernet0", "ETHERNET_STRAIGHT")

    # ── R1 G0/0 IP + admin-up (paced IOS sequence inside the JS handler) ─
    r1_result = b.configure_interface(
        device="R1", interface="GigabitEthernet0/0",
        ip="192.168.1.1", mask="255.255.255.0", no_shutdown=True,
    )
    assert r1_result["ok"] is True
    ps = r1_result["port_state"]
    assert ps["ip"] == "192.168.1.1", ps
    assert ps["mask"] == "255.255.255.0", ps
    assert ps["up"] is True, ps
    assert ps["protocol_up"] is True, ps

    # ── PC1 static IP + default gateway ─────────────────────────────────
    b.configure_host(device="PC1", ip="192.168.1.10",
                     mask="255.255.255.0", gateway="192.168.1.1")
    pc_port = b.get_port_state("PC1", "FastEthernet0")
    assert pc_port["ip"] == "192.168.1.10", pc_port
    assert pc_port["mask"] == "255.255.255.0", pc_port

    # ── PC1 → R1 ping (auto-dispatches terminal="desktop" from cache) ───
    output = _ping_with_retry(b, "PC1", "192.168.1.1")
    section = _last_ping_section(output, "192.168.1.1")

    assert "Reply from 192.168.1.1" in section, f"no ICMP replies:\n{output}"
    assert "Lost = 0" in section, f"ping not 4/4:\n{output}"


if __name__ == "__main__":
    test_m6_topology_and_ping()
    print("PASS — M6 topology rebuilt via typed Bridge, ping verified")
