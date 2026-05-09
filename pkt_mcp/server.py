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

import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

# pkt_bridge lives in tools/, not under pkt_mcp/, so the smoke test and the
# MCP server can both import it from a single source. Mirror the path-shim
# the smoke test uses so behavior stays consistent.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
)

from pkt_bridge import Bridge, BridgeError  # noqa: E402

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
        type: One of "ROUTER", "SWITCH", "PC", "SERVER", "HUB",
              "WIRELESS_ROUTER". Other types exist in PT but are not yet
              wired through the Bridge.
        name: Unique device name (e.g. "R1", "SW1", "PC1"). Fails with
              PT_REJECTED if a device with the same name already exists —
              call delete_device first if you need to replace it.
        model: PT model string. Must match a real PT model exactly. Known
               working values: "2911" (ROUTER), "2960-24TT" (SWITCH),
               "PC-PT" (PC), "Server-PT" (SERVER), "Hub-PT" (HUB),
               "Linksys-WRT300N" (WIRELESS_ROUTER). A bad model is rejected
               silently by PT and returns PT_REJECTED here.
        x, y: Canvas coordinates in pixels. Conventional spacing is ~200
              units between devices; pick something readable.

    Returns: {"uuid": "<PT uuid>", "name": "<echoed>"}.

    Notes: Routers boot into the System Configuration Dialog and take up
    to ~30s on first add — this tool transparently skips that dialog and
    waits until the router lands in user mode before returning, so the
    next call (e.g. configure_interface) can proceed immediately."""
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
    dev_a: str, port_a: str, dev_b: str, port_b: str, cable_type: str
) -> dict:
    """Create a cable link between two device ports.

    Args:
        dev_a, port_a: First endpoint. Port names are the canonical PT
                       form: routers/switches use slot/port like
                       "GigabitEthernet0/0" or "FastEthernet0/1"; PC hosts
                       use no-slash form "FastEthernet0".
        dev_b, port_b: Second endpoint, same conventions.
        cable_type: One of "ETHERNET_STRAIGHT" (router↔switch, switch↔host;
                    the most common case), "ETHERNET_CROSS" (same-type
                    legacy gear: switch↔switch on old hardware),
                    "FIBER" (fiber-optic), "SERIAL" (DTE-DCE serial),
                    "AUTO" (let PT pick), "WIRELESS", plus the rest of
                    the PT cable enum.

    Returns: {"ok": true}. Raises PT_REJECTED if the link can't be made
    (port already linked, type mismatch, etc.) or PT_NOT_FOUND if a
    device or port name is wrong.

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
    return {"ok": True}


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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
