#!/usr/bin/env python3
"""pkt-mcp Phase 2 throwaway driver.

Sends JS to the in-PT Script Module listener via the file mailbox at
/tmp/pkt-mcp/. Pairs with pt-script-module/main.js (the listener); the listener
must already be loaded and Started in PT.

usage:
    python tools/pkt_bridge.py '<js code>'
    python tools/pkt_bridge.py -f path/to/script.js

This is throwaway scaffolding for Phase 2. The Phase 4 MCP server will replace
this with a real FastMCP layer.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

MAILBOX = "/tmp/pkt-mcp"
CMD_PATH = os.path.join(MAILBOX, "cmd.json")
CMD_TMP = os.path.join(MAILBOX, "cmd.json.tmp")
RESULT_PATH = os.path.join(MAILBOX, "result.json")
TIMEOUT_S = 10.0
POLL_S = 0.05


def send(code: str, timeout: float = TIMEOUT_S) -> dict:
    os.makedirs(MAILBOX, exist_ok=True)
    cmd_id = str(uuid.uuid4())
    body = json.dumps({"id": cmd_id, "code": code})
    with open(CMD_TMP, "w") as f:
        f.write(body)
    os.replace(CMD_TMP, CMD_PATH)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(RESULT_PATH):
            with open(RESULT_PATH) as f:
                raw = f.read()
            os.remove(RESULT_PATH)
            resp = json.loads(raw)
            if resp.get("id") == cmd_id:
                return resp
            # Stale result from a previous run; ignore and keep polling.
        time.sleep(POLL_S)
    raise TimeoutError(f"no matching result within {timeout}s")


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] in {"-h", "--help"}:
        print("usage: pkt_bridge.py '<js>' | -f <path>", file=sys.stderr)
        sys.exit(2)
    if argv[1] == "-f":
        with open(argv[2]) as f:
            code = f.read()
    else:
        code = argv[1]
    resp = send(code)
    for line in resp.get("logs") or []:
        print(f"[se] {line}")
    if resp.get("error"):
        print(f"[error] {resp['error']}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(resp.get("result"), indent=2))


if __name__ == "__main__":
    main(sys.argv)
