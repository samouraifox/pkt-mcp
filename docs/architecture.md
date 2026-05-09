# Architecture

```
┌──────────────────────┐                          ┌────────────────────────────────┐
│  Claude Code (host)  │                          │   Packet Tracer 9.0.0 process  │
│                      │                          │                                │
│  reads PDF requirements                         │   ┌─────────────────────────┐  │
│  reasons about topology                         │   │  pkt-mcp Script Module  │  │
│                      │                          │   │  (encrypted .pts)       │  │
│         │  stdio JSON-RPC                       │   │                         │  │
│         ▼                                       │   │  - Script Engine (JS)   │  │
│  ┌──────────────────┐                           │   │    full ipc.* surface   │  │
│  │  pkt-mcp-server  │                           │   │  - Web View             │  │
│  │  (Python,        │                           │   │    long-polls localhost │  │
│  │   FastMCP)       │                           │   │    HTTP, forwards cmds  │  │
│  └──────────────────┘                           │   │    via $seev() to the   │  │
│         │                                       │   │    Script Engine        │  │
│         │  HTTP/JSON  (loopback only)           │   └────────────┬────────────┘  │
│         └────────────────────────────────────── │ ◀──────────────┘               │
│                                                 │                                │
│                                                 │   PT canvas + IPC engine       │
│                                                 │   (in-process, no auth wall)   │
│                                                 └────────────────────────────────┘
```

## Components

### Claude Code

The user's local Claude Code session. Reads the PDF requirements doc, reasons about
the topology, and calls MCP tools on `pkt-mcp-server` to materialize devices, links,
and configs.

### `pkt-mcp-server` (Python, FastMCP)

A FastMCP server (`mcp` SDK ≥ 1.27) launched over stdio by Claude Code. Exposes tools
like `add_device`, `connect`, `configure_interface`, `save_pkt`. Internally translates
each call into a JSON command and dispatches it to the in-PT Script Module via a tiny
loopback HTTP endpoint.

### `pkt-mcp` Script Module (JavaScript, in-process inside PT)

The bridge to PT's IPC engine. The `.pts` is built once via PT's Scripting Interface
(`Extensions → Scripting`). Source of truth lives in `pt-script-module/main.js`;
everything PT generates from it (`*.pts`) is a build artifact. The module's web view
long-polls the Python server's HTTP endpoint, receives commands, and forwards each one
to the Script Engine using `$seev()` so the actual `ipc.appWindow().getActive...`
calls happen synchronously next to PT's C++ engine.

### Why the Python server talks HTTP to a webview, not the other way around

PT's Script Engine is sandboxed Qt Script — no `QTcpServer`, no `socket`, no
`spawn`. It cannot accept inbound connections. But its **web views** are full
QWebEngine instances and can `fetch()` arbitrary loopback URLs. So we flip the
direction of control: the Python MCP server is the listener, the in-PT web view is
the long-polling client. Latency is sub-millisecond on loopback and there's exactly
one connection — fine for our use case.

## Why not the Java bridge

The original plan was to build a small Java service that opens a PTMP session to PT
on `localhost:39000` and drives the IPC API. We tried that path first
(branch `phase1-spike-failed`) and it turned out to be a dead end:

- PTMP connection negotiation succeeds (we see `:PTVER9.0.0.0810` come back).
- Authentication enforces `auth_type=4` (challenge-response, MD5 of
  `challenge + shared_secret`). The server compares against a registered ExApp's
  `(app_id, shared_secret)` pair.
- ExApps are registered only by loading a `.pta` (App Meta File) through
  `Options → Preferences → Misc → IPC → Configure Apps → Add`. `.pta` files are
  AES-encrypted blobs (we inspected the only bundled one,
  `extensions/ptaplayer/ptaplayer.pta`, and they are completely opaque to anything
  outside PT). PT has no CLI flag, no GUI wizard, no API to mint a `.pta`.
- The official Java framework's hardcoded defaults
  (`app_id=net.netacad.cisco.ipctest`, `secret=cisco`, decompiled from
  `OptionsManager.setDefaultProps()`) only authenticate against a corresponding
  test `.pta` distributed only through the Cisco NetAcad partner program. Cisco's
  EULA forbids redistributing it.
- Switching to `CLEAR_TEXT` auth at the client doesn't help: the server enforces MD5
  regardless of what the client offers in negotiation.

Full notes in `docs/phase1-investigation.md`. Anyone tempted to revisit the Java
framework path in the future should re-read that file first; the bypass options that
remain are (a) acquire dev credentials through Cisco channels, or (b) reverse the
`.pta` decryption + re-implement registration.

The Script Module path sidesteps the entire wall — Script Modules run in the same
process as PT's IPC engine, so privilege grants are local and the auth flow doesn't
exist. We pay for that with the build-artifact loop (edit JS → Export `.pts` →
restart module), which is fine for our single-developer cadence.

## What `pt-bridge/` is and why it stays

The Java spike code (`pt-bridge/pom.xml`, `pt-bridge/src/main/java/Spike.java`) lives
on `phase1-spike-failed`. It is **not** part of the build on `main` and won't be
revived. Keeping the branch around is purely as evidence of why we pivoted, so the
"can't we just use the Java framework?" question has a concrete answer.
