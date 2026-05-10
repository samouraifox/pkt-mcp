# pkt-mcp

MCP server that builds Cisco Packet Tracer networks from PDF requirements.

**Status:** Phases 1–4 done; Phase 4.5 patches landed. The MCP server
lives in `pkt_mcp/` and is registered with Claude Code per the section
below. The phase recap is in `docs/phase4-mcp.md`.

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

## Refreshing the PT bundle (when `main.js` or `api.js` changes)

The `.pts` blob loaded inside PT is a **build artifact** — PT encrypts
the JavaScript at Export time and runs that encrypted copy. Editing the
`.js` source on disk does NOT take effect until you re-bundle the
module in PT's GUI:

1. **Extensions → Scripting → Configure PT Script Module → `pkt-mcp Bridge`**
2. Click **Stop** if the listener is running.
3. **Edit** → for each changed file (`main.js`, `api.js`), replace the
   editor contents with the latest source from `pt-script-module/`.
4. Click **Save** so PT re-Exports the encrypted `.pts`.
5. Click **Start**.
6. Verify the listener is alive — from the repo root:

   ```
   uv run python -c 'from tools.pkt_bridge import Bridge; print(Bridge(timeout=5).list_devices())'
   ```

   A response (even `[]`) means the bundle is loaded and the dispatcher
   is the version on disk. A `TimeoutError` means the listener is not
   running — restart Step 2.

This is the **only** manual GUI step in the project; flag it loudly when
something looks wrong. Two symptoms that always mean "your bundle is
stale, reload it":

- A typed op returns the literal string `"... not implemented yet — Step
  N probe pending"`. That's a Phase 3-era stub from before
  `a689a99` / the op handler in question; the on-disk source has the
  real implementation.
- An op fails with `UNKNOWN_OP` for an op that exists in the on-disk
  `api.js` `DISPATCH` table.

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
