# pkt-mcp

MCP server that builds Cisco Packet Tracer networks from PDF requirements.

**Status:** Phases 1–3 done. Phase 4 (FastMCP wrapper) in progress —
the MCP server scaffolding lives in `pkt_mcp/` and is registered with
Claude Code per the section below.

## Architecture

```
Claude Code  ── stdio ──▶  pkt-mcp-server (Python, FastMCP)
                                      │
                                      │  HTTP/JSON on loopback
                                      ▼
                          pkt-mcp Script Module (JS, runs inside PT)
                                      │
                                      │  ipc.appWindow().getActiveWorkspace()...
                                      ▼
                          Packet Tracer 9.0.0 — canvas + .pkt save
```

The earlier plan (Java bridge → PTMP/TCP:39000) was scrapped after the Phase 1 spike
revealed that PTMP IPC requires a registered ExApp and Cisco doesn't ship one.
`docs/architecture.md` has the full rationale; the failed Java spike is preserved on
branch [`phase1-spike-failed`](https://github.com/samouraifox/pkt-mcp/tree/phase1-spike-failed).

## Requirements

- Linux (tested on Arch), Python 3.11+, [uv](https://docs.astral.sh/uv/)
- Cisco Packet Tracer 9.0.0 (build 9.0.0.0810) running with IPC enabled on
  `localhost:39000` (default)
- The `pkt-mcp` Script Module loaded into PT (one-time GUI step, see
  `pt-script-module/INSTALL.md`)

## Setup

```
git clone https://github.com/samouraifox/pkt-mcp
cd pkt-mcp
uv sync
```

`uv sync` creates the `.venv` and installs `mcp[cli]`. The Script Module
must be loaded inside PT separately (`pt-script-module/INSTALL.md`).

## Register with Claude Code

Add the entry below to your `~/.claude.json`, replacing
`<ABSOLUTE_PATH_TO_REPO>` with the absolute path you cloned to. The MCP
server runs over stdio — Claude Code spawns it on demand via `uv run`, so
no daemon, no port to manage.

```json
{
  "mcpServers": {
    "pkt-mcp": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "<ABSOLUTE_PATH_TO_REPO>",
               "python", "-m", "pkt_mcp.server"]
    }
  }
}
```

The registration is global — `pkt-mcp` becomes available in every Claude
Code session, regardless of CWD. Restart your Claude Code session for the
change to take effect, then verify with `/mcp` (the entry should show as
`connected`) or by calling the `ping_self` tool — it returns the literal
string `"ok"`.

`~/.claude.json` is per-user state and lives outside the repo; the
snippet above is the source of truth that other operators (or you in
six months) need to paste in.

## Repo layout

```
pkt-mcp/
├── README.md
├── LICENSE
├── pyproject.toml                 ← uv-managed, mcp[cli] dependency
├── docs/
│   ├── architecture.md            ← canonical architecture + pivot rationale
│   ├── phase1-investigation.md    ← every path tried, every dead end, every finding
│   ├── phase2-api-map.md          ← in-PT JS API surface as we discovered it
│   └── phase3-protocol.md         ← typed op/args wire protocol over the mailbox
├── pt-script-module/
│   ├── main.js                    ← dispatcher (file-mailbox listener)
│   ├── api.js                     ← op handlers (Phase 3 typed ops)
│   └── INSTALL.md                 ← step-by-step PT GUI walkthrough
├── tools/
│   └── pkt_bridge.py              ← Python typed Bridge client over the mailbox
├── pkt_mcp/                       ← FastMCP server (Phase 4)
│   └── server.py                  ← @mcp.tool() entrypoints
└── tests/
    └── test_smoke.py              ← M6 regression — rebuild + ping via the typed Bridge
```

> The `.pts` file PT generates after Save/Export is a build artifact and is not
> tracked in git.
