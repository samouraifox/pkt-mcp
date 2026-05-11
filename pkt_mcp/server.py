"""pkt-mcp FastMCP server — drives Cisco Packet Tracer through the typed
Bridge client over the file-mailbox transport.

Each @mcp.tool() below is a 1:1 wrapper over a Bridge method
(tools/pkt_bridge.py) — the Bridge handles JSON I/O with the in-PT Script
Module; FastMCP handles the MCP wire protocol with Claude Code. Tool
docstrings are the LLM-facing API documentation: they describe when to
call each tool, what the args mean, and what failure modes exist.

Run:
    uv run python -m pkt_mcp.server          # stdio, what Claude Code launches
    uv run mcp dev pkt_mcp/server.py         # interactive inspector
"""

from __future__ import annotations

import ipaddress
import os
import re
import sys
import time

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

# pkt_bridge lives in tools/, not under pkt_mcp/, so the smoke test and the
# MCP server can both import it from a single source. Mirror the path-shim
# the smoke test uses so behavior stays consistent.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
)

from pkt_bridge import Bridge, BridgeError, PtNotFound  # noqa: E402
from pkt_services import (  # noqa: E402
    set_pkt_services as _set_pkt_services,
    SERVICE_NAMES as _SERVICE_NAMES,
)

mcp = FastMCP("pkt-mcp")

# Module-level Bridge — the device-type cache that powers run_command's
# terminal auto-dispatch (ios vs desktop) lives on the instance, so all
# tool calls within a session must share it.
_bridge = Bridge()


def _call(fn, *args, **kwargs):
    """Translate Bridge typed exceptions into MCP ToolError so the LLM gets
    a clean, prefixed error message instead of an unhandled traceback. The
    error_type prefix (PT_NOT_FOUND, BAD_ARGS, …) lets the LLM recognize
    the failure kind from the error string alone."""
    try:
        return fn(*args, **kwargs)
    except BridgeError as e:
        raise ToolError(f"{e.error_type}: {e}") from e
    except TimeoutError as e:
        # Mailbox round-trip never completed — usually means the SE
        # listener isn't running. Surface as its own kind.
        raise ToolError(f"BRIDGE_TIMEOUT: {e}") from e


# ── helper-tool support ──────────────────────────────────────────────────

_HOST_TYPES = frozenset({"PC", "SERVER", "LAPTOP", "PRINTER"})
_SWITCH_TYPES = frozenset({"SWITCH"})

# Curated port probe sets for summarize_topology. There's no list_ports op
# yet, so we probe a small fixed set per device type and silently skip
# ports that don't exist (PtNotFound). For the demo topologies Phase 4
# targets, these cover everything; high-port-number switches (Fa0/9+) need
# explicit get_port_state calls. Add a list_ports JS op in a later phase
# if this becomes a real limitation.
#
# Phase 4.7 additions: Access Point uses "Port 0"/"Port 1" (radio + ethernet,
# probe-confirmed). Laptop/Printer share PC's FastEthernet0 layout.
# Smartphone/Tablet/TV/WirelessEndDevice are wireless-only; their wireless
# port doesn't carry an IP on the IOS-style port API so we skip them — they
# show up in list_devices but not in active-port summaries.
_PORT_PROBE: dict[str, list[str]] = {
    "ROUTER":            [f"GigabitEthernet0/{i}" for i in range(3)] +
                         [f"Serial0/0/{i}" for i in range(2)] +
                         [f"FastEthernet0/{i}" for i in range(2)],
    "SWITCH":            [f"FastEthernet0/{i}" for i in range(1, 9)] +
                         ["GigabitEthernet0/1", "GigabitEthernet0/2"],
    "MULTILAYER_SWITCH": [f"FastEthernet0/{i}" for i in range(1, 9)] +
                         ["GigabitEthernet0/1", "GigabitEthernet0/2"],
    "ASA":               [f"GigabitEthernet1/{i}" for i in range(1, 9)] +
                         ["Management1/1"],
    "PC":                ["FastEthernet0"],
    "SERVER":            ["FastEthernet0"],
    "LAPTOP":            ["FastEthernet0"],
    "PRINTER":           ["FastEthernet0"],
    "WIRELESS_ROUTER":   ["Internet", "Ethernet1", "Ethernet2",
                          "Ethernet3", "Ethernet4"],
    "ACCESS_POINT":      ["Port 0", "Port 1"],
    "HUB":               [],
    # Wireless-only / IoT / modem / specialty types — placeable + cabled but
    # not probed by the IOS-style port API.
    "SMARTPHONE":          [],
    "TABLET":              [],
    "TV":                  [],
    "WIRED_END_DEVICE":    [],
    "WIRELESS_END_DEVICE": [],
    "HOME_VOIP":           [],
    "ANALOG_PHONE":        [],
    "CELL_TOWER":          [],
    "DSL_MODEM":           [],
    "CABLE_MODEM":         [],
    "BRIDGE":              [],
    "REPEATER":            [],
    "CLOUD":               [],
}


def _ensure_device_type(name: str) -> str | None:
    """Look up a device's type from the Bridge cache; refresh from PT if
    the cache misses (the cache is populated by add_device, but devices
    placed in a previous session aren't there until list_devices runs)."""
    t = _bridge._device_types.get(name)
    if t is None:
        try:
            _bridge.list_devices()
        except BridgeError:
            return None
        t = _bridge._device_types.get(name)
    return t


def _last_ping_section(output: str, target: str) -> str:
    """Slice the buffer to the most recent `Pinging <target>` header so a
    retry isn't fooled by an earlier successful batch still in scrollback."""
    idx = output.rfind(f"Pinging {target}")
    return output[idx:] if idx >= 0 else output


_PING_SUMMARY_RE = re.compile(
    r"Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+),"
    r"\s*Lost\s*=\s*(\d+)\s*\((\d+)%\s*loss\)"
)


def _parse_ping_summary(section: str) -> tuple[int, int, int, int] | None:
    """(sent, received, lost, loss_pct) or None if PT hasn't printed the
    summary line yet — caller polls again."""
    m = _PING_SUMMARY_RE.search(section)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)),
            int(m.group(3)), int(m.group(4)))


def _subnet_of(ip: str | None, mask: str | None) -> str | None:
    """e.g. ("192.168.1.1", "255.255.255.0") -> "192.168.1.0/24". Returns
    None on garbage input rather than raising — the data comes from PT."""
    if not ip or not mask:
        return None
    try:
        net = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
    except (ValueError, ipaddress.AddressValueError, ipaddress.NetmaskValueError):
        return None
    return str(net)


# ── plumbing ─────────────────────────────────────────────────────────────


@mcp.tool()
def ping_self() -> str:
    """Health check. Returns the literal string "ok" if the MCP server is
    alive and the tool dispatcher is working. Use this to verify the
    pkt-mcp server is reachable before attempting real PT operations.

    This tool does NOT touch Packet Tracer — it only confirms the MCP
    layer itself. To check the Bridge → PT path is alive, call
    list_devices instead."""
    return "ok"


# ── 1:1 Bridge op wrappers ───────────────────────────────────────────────


@mcp.tool()
def add_device(type: str, name: str, model: str, x: float, y: float) -> dict:
    """Place a new device on the PT canvas.

    Args:
        type: One of the supported device types. Confirmed working types
              and their typical models (probe-verified in phase 4.7):
                "ROUTER" — "2911" (IPbase, no crypto/CME),
                           "2811" (advipservicesk9 — CRYPTO + CME — the
                              go-to for VPN+voice portfolio builds),
                           "1841" (advipservicesk9 — CRYPTO, no CME),
                           "2901" (universalk9 lite — no crypto),
                           "ISR4321", "ISR4331" (universalk9 — modern
                              crypto, no classic CME).
                "SWITCH" — "2960-24TT".
                "MULTILAYER_SWITCH" — "3560-24PS", "3560-24PH", "3650-24PS".
                "ASA" — "5506-X" (9 ports + Management), "5505".
                "PC" — "PC-PT".
                "SERVER" — "Server-PT".
                "LAPTOP" — "Laptop-PT".
                "PRINTER" — "Printer-PT".
                "TABLET" — "TabletPC-PT".
                "SMARTPHONE" — "SMARTPHONE-PT" (note uppercase).
                "ACCESS_POINT" — "AccessPoint-PT", "AccessPoint-PT-A",
                                 "AccessPoint-PT-AC", "AccessPoint-PT-N".
                "HUB" — "Hub-PT".
                "WIRELESS_ROUTER" — "Linksys-WRT300N".
                "IP_PHONE" — "7960", "IPPhone-PT".
                "BRIDGE" — "Bridge-PT".
                "REPEATER" — "Repeater-PT".
                "DSL_MODEM" — "DSL-Modem-PT".
                "CABLE_MODEM" — "Cable-Modem-PT".
                "WIRED_END_DEVICE" — "WiredEndDevice-PT" (generic IoT).
                "WIRELESS_END_DEVICE" — "WirelessEndDevice-PT" (generic IoT).
                "TV" — "TV-PT".
                "HOME_VOIP" — "Home-VoIP-PT".
                "ANALOG_PHONE" — "Analog-Phone-PT".
                "CELL_TOWER" — "Cell-Tower".
                "CLOUD" — "Cloud-PT", "Cloud-PT-Empty".
              Bad type/model is rejected silently by PT and returns
              PT_REJECTED here.
        name: Unique device name (e.g. "R1", "SW1", "PC1"). Fails with
              PT_REJECTED if a device with the same name already exists —
              call delete_device first if you need to replace it.
        model: PT model string. Must match a real PT model exactly (see
               the type list above for known working values).
        x, y: Canvas coordinates in pixels. Conventional spacing is ~200
              units between devices; pick something readable.

    Returns: {"uuid": "<PT uuid>", "name": "<echoed>"}.

    Notes:
    - Routers and 3560/3650 multilayer switches boot into the System
      Configuration Dialog and take up to ~30s on first add — this tool
      transparently skips that dialog and waits until the device lands in
      user mode before returning. MULTILAYER_SWITCH supports `ip routing`
      and SVIs (`interface vlan N`) — use it for L3 switches.
    - ASA boots from ROMMON → POST → user mode at "ciscoasa>" with NO
      Configuration Dialog. Boot is slow — observed 90-150s; this tool
      waits up to 180s. The 5506-X has 9 ports (GigabitEthernet1/1..1/8 +
      Management1/1). ASA OS is a different syntax from IOS:
      `configure_interface` only emits `enable / configure terminal /
      interface ... / ip address ... / no shutdown / end`, which is NOT
      enough on a fresh ASA — interfaces also need `nameif <name>` and
      `security-level <0-100>` before they pass traffic, and
      `access-list` / `access-group` for ACL policy. Compose those via
      `run_commands` (one-shot pipelined sequence). configure_interface
      will succeed at the IP/up/up level but the interface stays
      ineffective until nameif/security-level land.
    - IP_PHONE places a phone with three ports (Vlan1 / Switch / PC). The
      `Switch` port is the upstream link; cable it to a switch access
      port with `connect`. Phones register with CME, which was REMOVED
      from PT 9.0.0 — phones can be placed and cabled but will never
      register, and run_command on a phone raises BAD_ARGS (no useful
      terminal). Switchport voice VLAN + DHCP option 150 still apply at
      the switch side."""
    return _call(
        _bridge.add_device, type=type, name=name, model=model, x=x, y=y
    )


@mcp.tool()
def delete_device(name: str) -> dict:
    """Remove a device from the canvas by name.

    Args:
        name: The device name as set in add_device (e.g. "R1").

    Returns: {"ok": true} on success. Raises PT_NOT_FOUND if no device
    with that name exists.

    Use this to clean up before re-creating a device, or to undo a
    mistake. Links incident to the device are cleaned up automatically."""
    _call(_bridge.delete_device, name)
    return {"ok": True}


@mcp.tool()
def connect(
    dev_a: str,
    port_a: str,
    dev_b: str,
    port_b: str,
    cable_type: str,
    auto_portfast: bool = True,
) -> dict:
    """Create a cable link between two device ports, with optional
    spanning-tree portfast auto-configuration on switch↔host links.

    Args:
        dev_a, port_a: First endpoint. Port names are the canonical PT
                       form: routers/switches use slot/port like
                       "GigabitEthernet0/0" or "FastEthernet0/1"; PC hosts
                       use no-slash form "FastEthernet0".
        dev_b, port_b: Second endpoint, same conventions.
        cable_type: One of "ETHERNET_STRAIGHT" (the workhorse:
                    router↔switch, switch↔host, AND router↔host direct
                    — PT models auto-MDIX, so the classical DTE↔DTE
                    crossover rule is academic here), "ETHERNET_CROSS"
                    (switch↔switch on legacy access switches,
                    router↔router direct), "FIBER" (fiber-optic),
                    "SERIAL" (DTE-DCE serial), "AUTO" (let PT pick the
                    cable based on the port pair — safe default when
                    uncertain), "WIRELESS", plus the rest of the PT
                    cable enum.
        auto_portfast: If True (default) AND exactly one endpoint is a
                       SWITCH AND the other is a host (PC/SERVER), the
                       switch port is automatically taken into IOS config
                       mode and `spanning-tree portfast` is applied. This
                       skips the ~30s STP listening+learning convergence
                       on access ports — without it, the first ping
                       attempts after a switch↔host link drop entirely.
                       The ping helper still retries on STP loss as a
                       belt-and-suspenders, but portfast removes the
                       wait for the common case. Set False to skip
                       (e.g. for trunk ports or non-host endpoints).

    Returns: {"ok": true, "auto_portfast_applied": <bool>,
              "portfast_target": "<switch>/<port>"|null}. Raises
    PT_REJECTED if the link can't be made (port already linked, type
    mismatch, etc.) or PT_NOT_FOUND if a device or port name is wrong.

    Notes: Right after connecting a router port the link will visually
    appear red on the router end — that's the router's interface being
    admin-down by default, NOT a connection failure. The next
    configure_interface(..., no_shutdown=True) clears it."""
    _call(
        _bridge.connect,
        dev_a=dev_a, port_a=port_a,
        dev_b=dev_b, port_b=port_b,
        cable_type=cable_type,
    )

    portfast_target = None
    if auto_portfast:
        a_type = _ensure_device_type(dev_a)
        b_type = _ensure_device_type(dev_b)
        switch_dev, switch_port = None, None
        if a_type in _SWITCH_TYPES and b_type in _HOST_TYPES:
            switch_dev, switch_port = dev_a, port_a
        elif b_type in _SWITCH_TYPES and a_type in _HOST_TYPES:
            switch_dev, switch_port = dev_b, port_b

        if switch_dev:
            try:
                for cmd in (
                    "enable",
                    "configure terminal",
                    f"interface {switch_port}",
                    "spanning-tree portfast",
                    "exit",
                    "end",
                ):
                    _bridge.run_command(switch_dev, cmd, terminal="ios")
            except BridgeError as e:
                # Link landed but portfast didn't — surface as ToolError
                # so the LLM knows the side-effect failed, but include
                # which side was being configured.
                raise ToolError(
                    f"connect: link OK, but auto_portfast on "
                    f"{switch_dev}/{switch_port} failed: "
                    f"{e.error_type}: {e}"
                ) from e
            portfast_target = f"{switch_dev}/{switch_port}"

    return {
        "ok": True,
        "auto_portfast_applied": portfast_target is not None,
        "portfast_target": portfast_target,
    }


@mcp.tool()
def configure_interface(
    device: str,
    interface: str,
    ip: str,
    mask: str,
    no_shutdown: bool = True,
) -> dict:
    """Configure an IOS device interface with an IPv4 address and bring it
    up. Only valid for routers/switches/IOS gear — for PC/Server hosts use
    configure_host.

    Args:
        device: IOS device name (e.g. "R1").
        interface: Port name in PT canonical form (e.g.
                   "GigabitEthernet0/0", "FastEthernet0/1").
        ip: IPv4 address as dotted quad (e.g. "192.168.1.1").
        mask: Subnet mask as dotted quad (e.g. "255.255.255.0").
        no_shutdown: If True (default), also issue `no shutdown` so the
                     interface comes up. Set False to leave it admin-down.

    Returns: {"ok": true, "port_state": {"ip", "mask", "up", "protocol_up"}}
    where the port_state reflects what PT actually shows post-configure.
    Raises PT_TIMEOUT (with observed state in the message) if the IOS
    sequence didn't converge.

    Notes: The Bridge handles the full IOS sequence inline — enable →
    configure terminal → interface ... → ip address ... → no shutdown →
    end — pacing each step against terminal state instead of fixed
    sleeps, so the call returns once the port reads up/up. Don't try to
    drive these commands manually via run_command."""
    return _call(
        _bridge.configure_interface,
        device=device, interface=interface,
        ip=ip, mask=mask, no_shutdown=no_shutdown,
    )


@mcp.tool()
def configure_host(
    device: str,
    ip: str | None = None,
    mask: str | None = None,
    gateway: str | None = None,
    dhcp: bool = False,
) -> dict:
    """Configure a host (PC, Server) with a static IPv4 address or DHCP.

    Args:
        device: Host device name (e.g. "PC1").
        ip: IPv4 address. Required when dhcp=False.
        mask: Subnet mask. Required when dhcp=False.
        gateway: Default gateway. Optional but almost always needed for
                 anything beyond the local subnet.
        dhcp: If True, set the host to DHCP client mode and ignore
              ip/mask/gateway. Defaults to False (static).

    Returns: {"ok": true}. Raises BAD_ARGS if dhcp=False and ip/mask are
    missing, or PT_NOT_FOUND if the device doesn't have the expected
    FastEthernet0 host port (single index, no slash — the Bridge assumes
    the standard PC port layout).

    Notes: For multi-NIC hosts (e.g. laptop with wireless + wired) only
    the FastEthernet0 wired port is configured. Wireless setup is not
    yet exposed."""
    _call(
        _bridge.configure_host,
        device=device, ip=ip, mask=mask, gateway=gateway, dhcp=dhcp,
    )
    return {"ok": True}


@mcp.tool()
def run_command(
    device: str, command: str, terminal: str | None = None
) -> dict:
    """Execute a single CLI command on a device's terminal.

    Args:
        device: Device name (e.g. "R1", "PC1").
        command: Single CLI line, no embedded newlines. Examples:
                 "show ip interface brief", "ping 192.168.1.1",
                 "configure terminal".
        terminal: Optional. Either "ios" (routers/switches/IOS gear) or
                  "desktop" (PC/Server Windows-flavored shell). Usually
                  omit — the Bridge auto-dispatches based on the device's
                  cached type (populated by add_device or list_devices).
                  Pass explicitly only to override.

    Returns: {"output": "<full terminal buffer>",
              "prompt": "<current prompt>",
              "mode":   "<current mode tag>"}.
    The output is the *entire* buffer, not just this command's reply —
    parse the tail or look for the most recent prompt to find the new
    output.

    Notes: Use this for ad-hoc inspection (`show running-config`,
    `ping`), not for scripted IOS configuration — for IP/mask/up there's
    configure_interface which handles the IOS pacing rule (commands
    chained too fast get silently dropped) automatically. For long
    commands like ping, the reply trickles in over a second or two; call
    run_command(device, "") to re-read the buffer without sending new
    input."""
    return _call(
        _bridge.run_command, device=device, command=command, terminal=terminal,
    )


@mcp.tool()
def run_commands(
    device: str,
    commands: list[str],
    terminal: str | None = None,
) -> dict:
    """Execute a list of CLI lines on a device's terminal in a single
    pipelined mailbox round-trip. Use this instead of N sequential
    run_command calls when you have a multi-line config to apply (VLAN +
    switchport stack, OSPF setup, subinterface block) — saves ~N×500ms
    of mailbox latency.

    Args:
        device: Device name.
        commands: List of CLI lines, no embedded newlines. Run in order
                  with prompt-or-output-growth pacing between each.
                  Empty list returns immediately with no work done.
        terminal: Optional, "ios" or "desktop". Auto-dispatched from the
                  device's cached type — usually omit.

    Returns:
        {
          "results": [
            {"command", "output", "prompt", "mode",
             "error_type"?, "error_message"?},
            ...
          ],
          "stopped_early": <bool>,    # True iff aborted before sending all
          "final_prompt":  <str>,
          "final_mode":    <str>
        }
    The i-th entry of `results` is the i-th command of `commands`.
    `output` is the slice of the terminal buffer this command produced
    (NOT the full scrollback — that would grow unboundedly across
    pipelined calls).

    Per-line error policy: detects IOS error markers ("% Invalid input
    detected ...", "% Incomplete command.", "% Ambiguous command:",
    etc.) in each command's output slice. On the first hit, the failing
    entry carries `error_type="PT_REJECTED"` + the error line as
    `error_message`, and subsequent commands are NOT attempted. IOS
    modes are fragile — continuing past a failure usually lands the
    next command in the wrong context, so the caller has to decide on
    recovery.

    Notes:
    - Does NOT auto-re-enable on console auto-logout demotion (that's
      run_command's job). If a long pause might cause auto-logout,
      include "enable" as the first line in your sequence.
    - For IOS sequences with state-change verification (configure
      interface IP), prefer configure_interface — it polls port_state
      until the interface reads up/up. run_commands fires-and-paces but
      doesn't verify outcomes beyond IOS error detection.
    - Pacing reuses the same pollUntil pattern op_configure_interface
      uses; no new logic. The signal is "prompt changed OR output
      buffer grew"; deadline expiry just proceeds (a no-op like
      `interface ...` in already-config-mode produces neither signal
      and that's fine).
    """
    return _call(_bridge.run_commands, device, commands, terminal=terminal)


@mcp.tool()
def list_devices() -> list[dict]:
    """Enumerate every user-visible device on the canvas.

    Returns: A list of {"name", "type", "model", "x", "y"} entries. The
    list is empty on a fresh workspace. PT's internal "Power Distribution
    Device" entity is filtered out automatically.

    Notes: Also refreshes the Bridge's local name→type cache, which is
    what makes run_command's terminal auto-dispatch work after a reload
    or fresh session. Call this once after server startup if you need to
    operate on devices that were placed in a previous session."""
    return _call(_bridge.list_devices)


@mcp.tool()
def get_port_state(device: str, interface: str) -> dict:
    """Read the current state of a port (IP, up/down, link presence).

    Args:
        device: Device name.
        interface: Port name in PT canonical form (e.g.
                   "GigabitEthernet0/0", "FastEthernet0").

    Returns: {"ip", "mask", "up" (admin state), "protocol_up" (line
    protocol), "link" (true if a cable is attached)}. Read-only — to
    *change* port config use configure_interface or configure_host.

    Use this to verify wiring after a connect, to confirm an interface
    came up after configure_interface, or to debug a failing ping
    (port down, no link, wrong IP)."""
    return _call(
        _bridge.get_port_state, device=device, interface=interface,
    )


@mcp.tool()
def save_pkt(path: str) -> dict:
    """Save the current PT workspace to a .pkt file at the given absolute
    path.

    Args:
        path: Absolute filesystem path (must start with "/"). Must end
              with .pkt by convention; PT does not enforce the suffix.

    Returns: {"ok": true, "path": "<echoed>", "size": <bytes>}. A
    suspiciously small size (<1 KB) usually means PT didn't actually
    flush — typical real saves for small topologies are 30-60 KB.

    Notes: Uses fileSaveAsNoPrompt — a true headless save that does NOT
    update PT's "current file" pointer, so you can snapshot to arbitrary
    paths without disturbing whatever workspace the user has open in the
    GUI. Also doesn't pop a Save As dialog. Relative paths are rejected
    with BAD_ARGS to prevent the file landing in PT's CWD."""
    return _call(_bridge.save, path)


# ── ergonomic helpers ────────────────────────────────────────────────────


@mcp.tool()
def ping(
    from_device: str,
    to_ip: str,
    count: int = 4,
    retries: int = 2,
) -> dict:
    """Send ICMP echoes from a host (or router) to an IP and return a
    structured pass/fail result.

    Args:
        from_device: Source device (typically a PC, but a router with
                     `ping` in privileged-exec works too — terminal kind
                     auto-dispatches from the device's cached type).
        to_ip: Destination IPv4 address as a dotted quad.
        count: Number of echoes to send. Defaults to 4 (PT's default).
               When != 4, the tool sends `ping -n <count> <ip>` (Windows
               desktop syntax); when == 4, it sends a bare `ping <ip>`
               for maximum compatibility.
        retries: How many times to re-issue the ping on TOTAL packet loss
                 (0/N replies). Defaults to 2 — i.e. 1 initial attempt +
                 up to 2 retries. Total loss usually means STP is still
                 converging on a switch access port; one retry typically
                 clears it. Partial loss (1/4, 2/4, …) is treated as a
                 real network issue and is NOT retried — it returns
                 success=False with the observed counts.

    Returns:
        {
          "success":         <bool>,           # True iff lost == 0
          "sent":            <int|null>,
          "received":        <int|null>,
          "lost":            <int|null>,
          "packet_loss_pct": <int|null>,       # 0-100
          "attempts":        <int>,            # how many batches were sent
          "output":          "<the relevant ping section>"
        }

    Raises BRIDGE_TIMEOUT if the SE listener never responds, or
    PT_NOT_FOUND if from_device is unknown to PT.

    Notes: Avoids the classic substring trap — `"0% loss"` is also a
    substring of `"100% loss"`, so we check `Lost = 0` instead. Buffer
    parsing slices to the most recent `Pinging <ip>` header so retries
    don't get fooled by an earlier successful batch in scrollback."""
    cmd = f"ping {to_ip}" if count == 4 else f"ping -n {count} {to_ip}"
    deadline_per_attempt = 15.0
    poll_s = 0.5
    max_attempts = 1 + max(0, retries)

    section = ""
    summary: tuple[int, int, int, int] | None = None
    attempts_done = 0

    try:
        for attempts_done in range(1, max_attempts + 1):
            _bridge.run_command(from_device, cmd)
            end = time.time() + deadline_per_attempt
            summary = None
            while time.time() < end:
                resp = _bridge.run_command(from_device, "")
                section = _last_ping_section(resp["output"], to_ip)
                summary = _parse_ping_summary(section)
                if summary is not None:
                    break
                time.sleep(poll_s)

            if summary is None:
                # No summary line within deadline — retry.
                continue

            sent, received, lost, pct = summary
            if lost == 0:
                return {
                    "success": True,
                    "sent": sent,
                    "received": received,
                    "lost": lost,
                    "packet_loss_pct": pct,
                    "attempts": attempts_done,
                    "output": section.strip(),
                }
            # Partial loss: don't mask a real problem with retries.
            if received > 0:
                break
            # Total loss: loop and retry (STP convergence absorber).
    except BridgeError as e:
        raise ToolError(f"{e.error_type}: {e}") from e
    except TimeoutError as e:
        raise ToolError(f"BRIDGE_TIMEOUT: {e}") from e

    if summary is None:
        sent = received = lost = pct = None
    else:
        sent, received, lost, pct = summary
    return {
        "success": False,
        "sent": sent,
        "received": received,
        "lost": lost,
        "packet_loss_pct": pct,
        "attempts": attempts_done,
        "output": section.strip(),
    }


@mcp.tool()
def summarize_topology() -> str:
    """Return a markdown snapshot of the current PT canvas: devices,
    active ports (those with an IP or a link), and inferred subnets.

    Use this to orient yourself in one call before reasoning about a
    topology — saves making N separate list_devices + get_port_state
    round-trips. The output is meant to be read by an LLM, not parsed:
    it's a markdown report.

    Returns: A markdown-formatted string. Empty workspace renders as
    "Topology: empty workspace.".

    Notes: There's no list_ports op yet; this helper probes a curated
    set of port names per device type and skips any that don't exist.
    For switches it covers FastEthernet0/1..0/8 + GigabitEthernet0/1..0/2,
    which is enough for typical demo topologies but truncates large
    24/48-port deployments. For ports outside that range, fall back to
    explicit get_port_state. Routers, PCs, servers, and wireless routers
    have their full standard port layouts probed."""
    try:
        devices = _bridge.list_devices()
    except BridgeError as e:
        raise ToolError(f"{e.error_type}: {e}") from e
    except TimeoutError as e:
        raise ToolError(f"BRIDGE_TIMEOUT: {e}") from e

    if not devices:
        return "Topology: empty workspace."

    # Probe ports per device.
    port_rows: list[dict] = []
    for d in devices:
        dtype = d.get("type") or ""
        probe = _PORT_PROBE.get(dtype, [])
        for port_name in probe:
            try:
                state = _bridge.get_port_state(d["name"], port_name)
            except PtNotFound:
                continue  # port doesn't exist on this model — silent skip
            except BridgeError:
                continue
            ip = state.get("ip")
            link = state.get("link")
            # Only include ports that show signs of life.
            if not ip and not link:
                continue
            port_rows.append({
                "device": d["name"],
                "port":   port_name,
                "ip":     ip,
                "mask":   state.get("mask"),
                "up":     state.get("up"),
                "proto":  state.get("protocol_up"),
                "link":   link,
            })

    # Group active IP'd ports by subnet.
    subnets: dict[str, list[tuple[str, str]]] = {}
    for r in port_rows:
        subnet = _subnet_of(r["ip"], r["mask"])
        if subnet:
            subnets.setdefault(subnet, []).append((r["device"], r["ip"]))

    # ── render markdown ─────────────────────────────────────────────────
    lines: list[str] = []
    lines.append("# Topology snapshot\n")
    lines.append(
        f"{len(devices)} device(s), {len(port_rows)} active port(s), "
        f"{len(subnets)} subnet(s).\n"
    )

    lines.append("## Devices\n")
    lines.append("| Name | Type | Model | Position |")
    lines.append("|------|------|-------|----------|")
    for d in devices:
        x, y = d.get("x"), d.get("y")
        pos = f"({x:.0f}, {y:.0f})" if x is not None and y is not None else "—"
        lines.append(
            f"| {d.get('name','')} | {d.get('type','')} | "
            f"{d.get('model','') or '—'} | {pos} |"
        )

    if port_rows:
        lines.append("\n## Active ports\n")
        lines.append("| Device | Port | IP | Up/Proto | Linked |")
        lines.append("|--------|------|------|----------|--------|")
        for r in port_rows:
            ip_str = f"{r['ip']}/{r['mask']}" if r["ip"] and r["mask"] else (r["ip"] or "—")
            up = "up" if r["up"] else ("down" if r["up"] is False else "?")
            pr = "up" if r["proto"] else ("down" if r["proto"] is False else "?")
            linked = "yes" if r["link"] else "no"
            lines.append(
                f"| {r['device']} | {r['port']} | {ip_str} | {up}/{pr} | {linked} |"
            )

    if subnets:
        lines.append("\n## Subnets\n")
        for subnet, members in sorted(subnets.items()):
            members_str = ", ".join(f"{dev} ({ip})" for dev, ip in members)
            lines.append(f"- **{subnet}** — {members_str}")

    return "\n".join(lines) + "\n"


@mcp.tool()
def set_pkt_services(
    pkt_path: str,
    services: dict,
) -> dict:
    """Toggle Server-PT services in a previously-saved .pkt file.

    The PT 9 GUI Services tab (HTTP, DNS, DHCP, SMTP, NTP, Syslog, AAA, etc.)
    is NOT reachable through PT's JS bridge — the C++ service classes
    (CServerHttp, CServerDns, …) exist but aren't exposed at the device
    level. The only programmatic path is the saved .pkt file itself: decrypt,
    patch the enable flag in XML, re-encrypt. This tool wraps that pipeline
    using the vendored Unpacket library (tools/unpacket/, MIT licensed).

    Args:
        pkt_path: Absolute path to an existing .pkt file (will be decrypted).
                  Typically the file you just save_pkt'd.
        services: Nested dict {device_name: {service_name: enabled_bool, ...}}.
                  Service names (case-insensitive): "HTTP", "HTTPS", "DNS",
                  "TFTP", "NTP", "FTP", "SYSLOG", "AAA" / "RADIUS", "SMTP",
                  "POP3", "NETFLOW". Defaults you usually want to flip:
                  DNS (off by default) and AAA/RADIUS (off by default); HTTP/
                  HTTPS/NTP/SMTP/POP3/Syslog/FTP/TFTP are already on by
                  default on a fresh Server-PT.

    Returns:
        {
          "input":  <pkt_path>,
          "output": <pkt_path>,
          "report": {device: {service: status, ...}, ...},
          "size":   <output bytes>,
        }
        Status values: "applied" (flag flipped), "no_change" (already at
        target), "block_missing" (device exists but lacks that service
        block), "device_missing" (no device by that name), "unknown_service".

    Workflow:
        1. Build the topology with the other MCP tools.
        2. save_pkt("/tmp/foo.pkt").
        3. set_pkt_services("/tmp/foo.pkt", {"SRV-DNS": {"DNS": True}, ...})
        4. File → Open /tmp/foo.pkt in PT — services are now toggled.

    Limitations:
        - Top-level on/off only. Doesn't add DNS records, HTTP files, DHCP
          pools, POP3 mailboxes — those need richer XML manipulation, not yet
          implemented.
        - DHCP service is per-port and structured differently; not exposed.
        - Operates on the file, not the live in-memory state. PT must reopen
          the .pkt for the change to take effect.
    """
    if not pkt_path.startswith("/"):
        raise ToolError("BAD_ARGS: pkt_path must be absolute (start with '/')")
    if not isinstance(services, dict) or not services:
        raise ToolError("BAD_ARGS: services must be a non-empty dict")
    # Validate service names early — better error than the patcher's
    # downstream "unknown_service" entry buried in the report.
    valid = {s.upper() for s in _SERVICE_NAMES}
    for dev, svcs in services.items():
        if not isinstance(svcs, dict):
            raise ToolError(f"BAD_ARGS: services[{dev!r}] must be a dict")
        for svc in svcs:
            if svc.upper() not in valid:
                raise ToolError(
                    f"BAD_ARGS: unknown service {svc!r}; "
                    f"valid: {sorted(valid)}"
                )
    try:
        return _set_pkt_services(pkt_path, services)
    except FileNotFoundError as e:
        raise ToolError(f"PT_NOT_FOUND: {e}") from e
    except (ValueError, IOError) as e:
        raise ToolError(f"INTERNAL: {e}") from e


@mcp.tool()
def reload_api(path: str | None = None) -> dict:
    """Hot-reload the in-PT api.js handler module without re-Exporting the
    .pts bundle through PT's Scripting GUI. Use this after editing
    pt-script-module/api.js so the new handlers take effect on the next op
    call.

    Args:
        path: Optional absolute path to the api.js file. Defaults to the
              copy in this repo (pt-script-module/api.js, resolved relative
              to the bridge module). Pass an explicit path only for
              experiments.

    Returns: {"ok": true, "ops": [<op names>]} — the live op list after
    reload. If your new op name isn't in `ops`, the reload didn't pick it
    up (probably a syntax error or a missing entry in the DISPATCH map at
    the bottom of api.js). Raises INTERNAL with the eval error message
    if the new code fails to parse / evaluate.

    Scope: ONLY for api.js (handler-level changes — adding/editing ops,
    helpers, constants). Edits to main.js (the listener / dispatcher /
    mailbox transport) STILL require a manual GUI reload (Extensions →
    Scripting → Configure → Stop, Edit both files, Save, Start). The
    listener can't hot-reload its own structure."""
    return _call(_bridge.reload_api, path=path)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
