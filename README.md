# pkt-mcp

MCP server that builds Cisco Packet Tracer networks from PDF requirements.

**Status:** Phase 1 done — Script Module path validated end-to-end (see
`docs/phase1-investigation.md`). Phase 2 not started.

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

## Repo layout

```
pkt-mcp/
├── README.md
├── LICENSE
├── docs/
│   ├── architecture.md            ← canonical architecture + pivot rationale
│   └── phase1-investigation.md    ← every path tried, every dead end, every finding
├── pt-script-module/
│   ├── main.js                    ← source-of-truth Script Module body (commit)
│   └── INSTALL.md                 ← step-by-step PT GUI walkthrough
├── pkt_mcp/                       ← Phase 4 (Python MCP server, not yet written)
└── tests/                         ← Phase 4
```

> The `.pts` file PT generates after Save/Export is a build artifact and is not
> tracked in git.
