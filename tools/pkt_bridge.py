#!/usr/bin/env python3
"""pkt-mcp Phase 3 typed bridge client.

Mirrors the JS DISPATCH ops in pt-script-module/api.js 1:1. Each method
writes {id, op, args} to /tmp/pkt-mcp/cmd.json, polls for result.json,
parses the structured envelope, and either returns the result dict or
raises a typed BridgeError subclass keyed off the result's error_type.

Pairs with pt-script-module/main.js (the dispatcher) and api.js (the
op handlers); the Script Module must be loaded and Started in PT.

Library usage:

    from pkt_bridge import Bridge
    b = Bridge()
    b.add_device(type="ROUTER", name="R1", model="2911", x=200, y=200)
    b.run_command("R1", "show ip interface brief")    # auto terminal="ios"

CLI usage (debug):

    python tools/pkt_bridge.py <op> [<json-args>]
    python tools/pkt_bridge.py -e '<js>'              # raw eval
    python tools/pkt_bridge.py -f <path>              # raw eval from file
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any

MAILBOX = "/tmp/pkt-mcp"
CMD_PATH = os.path.join(MAILBOX, "cmd.json")
CMD_TMP = os.path.join(MAILBOX, "cmd.json.tmp")
RESULT_PATH = os.path.join(MAILBOX, "result.json")
TIMEOUT_S = 10.0
POLL_S = 0.05


# ── typed errors ──────────────────────────────────────────────────────────


class BridgeError(Exception):
    """Base class for all bridge errors. Subclasses correspond 1:1 to the
    error_type values from docs/phase3-protocol.md."""

    error_type: str = "BRIDGE_ERROR"

    def __init__(self, message: str, *, error_data: dict | None = None) -> None:
        super().__init__(message)
        self.error_data = error_data or {}


class UnknownOp(BridgeError):
    error_type = "UNKNOWN_OP"


class BadArgs(BridgeError):
    error_type = "BAD_ARGS"


class PtNotFound(BridgeError):
    error_type = "PT_NOT_FOUND"


class PtRejected(BridgeError):
    error_type = "PT_REJECTED"


class PtTimeout(BridgeError):
    error_type = "PT_TIMEOUT"


class BridgeInternal(BridgeError):
    error_type = "INTERNAL"


_ERROR_CLASSES: dict[str, type[BridgeError]] = {
    cls.error_type: cls
    for cls in (UnknownOp, BadArgs, PtNotFound, PtRejected, PtTimeout, BridgeInternal)
}


# ── name → terminal-kind dispatch ────────────────────────────────────────
#
# Power-user override: pass terminal=... to run_command explicitly. This
# table is just the default when the caller didn't ask. HUB intentionally
# absent — layer-1 dumb device with no console; calling run_command on one
# raises BadArgs locally before round-tripping.

_TERMINAL_BY_TYPE: dict[str, str] = {
    "ROUTER": "ios",
    "SWITCH": "ios",
    "WIRELESS_ROUTER": "ios",
    "PC": "desktop",
    "SERVER": "desktop",
}


# ── client ────────────────────────────────────────────────────────────────


class Bridge:
    """Phase 3 typed client over the file-mailbox transport.

    Single-slot end-to-end: each call writes cmd.json, blocks until
    result.json (or timeout). Concurrent calls from multiple Bridge
    instances against the same mailbox would race — don't do that.
    """

    def __init__(self, mailbox: str = MAILBOX, timeout: float = TIMEOUT_S) -> None:
        self._mailbox = mailbox
        self._cmd_path = os.path.join(mailbox, "cmd.json")
        self._cmd_tmp = os.path.join(mailbox, "cmd.json.tmp")
        self._result_path = os.path.join(mailbox, "result.json")
        self._timeout = timeout
        self._device_types: dict[str, str] = {}

    # ── transport ────────────────────────────────────────────────────────

    def send(self, op: str, args: dict | None = None, *,
             timeout: float | None = None) -> dict:
        """Roundtrip a single op. Returns the full envelope:
        {id, result, error, logs}. Does NOT raise on error_type — use call()
        for that. Useful in the CLI / debug paths where logs matter."""
        os.makedirs(self._mailbox, exist_ok=True)
        cmd_id = str(uuid.uuid4())
        body = json.dumps({"id": cmd_id, "op": op, "args": args or {}})
        with open(self._cmd_tmp, "w") as f:
            f.write(body)
        os.replace(self._cmd_tmp, self._cmd_path)

        deadline = time.time() + (timeout if timeout is not None else self._timeout)
        while time.time() < deadline:
            if os.path.exists(self._result_path):
                with open(self._result_path) as f:
                    raw = f.read()
                os.remove(self._result_path)
                resp = json.loads(raw)
                if resp.get("id") == cmd_id:
                    return resp
                # Stale result from a previous run — keep polling.
            time.sleep(POLL_S)
        raise TimeoutError(
            f"no matching result within {timeout or self._timeout}s for op={op}"
        )

    def call(self, op: str, args: dict | None = None, *,
             timeout: float | None = None) -> Any:
        """Roundtrip an op and return the result, or raise the typed
        exception matching error_type. Discards logs."""
        resp = self.send(op, args, timeout=timeout)
        err = resp.get("error")
        if err:
            cls = _ERROR_CLASSES.get(err.get("error_type", ""), BridgeError)
            msg = f"{op}: {err.get('error_message', '')}"
            raise cls(msg, error_data=err.get("error_data"))
        return resp.get("result")

    # ── ops (1:1 with api.js DISPATCH) ───────────────────────────────────

    def add_device(self, type: str, name: str, model: str,
                   x: float, y: float) -> dict:
        """Returns {uuid, name}. Caches device type for run_command
        auto-dispatch. Raises PtRejected on name collision (with
        error_data.existing_uuid) or M1 model rejection."""
        result = self.call("add_device", {
            "type": type, "name": name, "model": model, "x": x, "y": y,
        })
        self._device_types[name] = type
        return result

    def delete_device(self, name: str) -> None:
        self.call("delete_device", {"name": name})
        self._device_types.pop(name, None)

    def connect(self, dev_a: str, port_a: str, dev_b: str, port_b: str,
                cable_type: str) -> None:
        self.call("connect", {
            "dev_a": dev_a, "port_a": port_a,
            "dev_b": dev_b, "port_b": port_b,
            "cable_type": cable_type,
        })

    def configure_interface(self, device: str, interface: str,
                            ip: str, mask: str,
                            no_shutdown: bool = True) -> dict:
        """Returns {ok, port_state: {ip, mask, up, protocol_up}}.
        Raises PtTimeout with error_data.observed if convergence fails."""
        return self.call("configure_interface", {
            "device": device, "interface": interface,
            "ip": ip, "mask": mask, "no_shutdown": no_shutdown,
        })

    def configure_host(self, device: str, *,
                       ip: str | None = None, mask: str | None = None,
                       gateway: str | None = None, dhcp: bool = False) -> None:
        self.call("configure_host", {
            "device": device, "ip": ip, "mask": mask,
            "gateway": gateway, "dhcp": dhcp,
        })

    def run_command(self, device: str, command: str, *,
                    terminal: str | None = None) -> dict:
        """Returns {output, prompt, mode}. Auto-dispatches terminal kind
        from the cached device type populated by add_device / list_devices.
        Override with terminal="ios" or "desktop"."""
        if terminal is None:
            dtype = self._device_types.get(device)
            if dtype is None:
                raise BadArgs(
                    f"run_command: no cached type for device {device!r}; "
                    "call add_device or list_devices first, or pass "
                    "terminal=\"ios\"|\"desktop\" explicitly"
                )
            mapped = _TERMINAL_BY_TYPE.get(dtype)
            if mapped is None:
                raise BadArgs(
                    f"run_command: device {device!r} has type {dtype!r} which "
                    "has no terminal; pass terminal explicitly if you have one"
                )
            terminal = mapped
        return self.call("run_command", {
            "device": device, "command": command, "terminal": terminal,
        })

    def list_devices(self) -> list[dict]:
        """Refreshes the local name→type cache from PT's view of the
        canvas — robust to manual edits in the GUI or restart-after-load."""
        result = self.call("list_devices", {}) or []
        for d in result:
            n, t = d.get("name"), d.get("type")
            if n and t and t in _TERMINAL_BY_TYPE:
                self._device_types[n] = t
        return result

    def get_port_state(self, device: str, interface: str) -> dict:
        return self.call("get_port_state", {
            "device": device, "interface": interface,
        })

    def save(self, path: str) -> None:
        """Phase 3 blocker — JS handler raises BridgeInternal until Step 6's
        introspection scan resolves the headless-save question."""
        self.call("save", {"path": path})

    # ── debug escape hatch ───────────────────────────────────────────────

    def raw(self, code: str) -> Any:
        """Phase 2 raw-eval path. Debug only; production callers must not
        use this. Persists for ad-hoc API probing (e.g. Step 6 introspection)."""
        return self.call("raw", {"code": code})


# ── CLI ──────────────────────────────────────────────────────────────────


_USAGE = """\
usage:
  pkt_bridge.py <op> [<json-args>]      # structured op call
  pkt_bridge.py -e '<js>'               # raw eval (debug)
  pkt_bridge.py -f <path>               # raw eval from file (debug)
"""


def _print_logs(resp: dict) -> None:
    for line in resp.get("logs") or []:
        print(f"[se] {line}", file=sys.stderr)


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] in {"-h", "--help"}:
        sys.stderr.write(_USAGE)
        sys.exit(2)

    bridge = Bridge()

    if argv[1] == "-e":
        if len(argv) < 3:
            sys.stderr.write(_USAGE)
            sys.exit(2)
        resp = bridge.send("raw", {"code": argv[2]})
    elif argv[1] == "-f":
        if len(argv) < 3:
            sys.stderr.write(_USAGE)
            sys.exit(2)
        with open(argv[2]) as f:
            resp = bridge.send("raw", {"code": f.read()})
    else:
        op = argv[1]
        args = json.loads(argv[2]) if len(argv) >= 3 else {}
        resp = bridge.send(op, args)

    _print_logs(resp)
    err = resp.get("error")
    if err:
        sys.stderr.write(json.dumps(err, indent=2) + "\n")
        sys.exit(1)
    print(json.dumps(resp.get("result"), indent=2, default=str))


if __name__ == "__main__":
    main(sys.argv)
