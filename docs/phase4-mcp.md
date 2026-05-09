# Phase 4 — FastMCP wrapper

Phase 3 closed with a typed Python `Bridge` client whose 9 ops 1:1-mirrored
the JS dispatcher in `pt-script-module/api.js`, the M6 regression smoke test
green end-to-end, and a documented protocol (`docs/phase3-protocol.md`).
Phase 4 wraps that client as a FastMCP server so Claude Code can drive PT
directly through MCP tool calls — no Python script-writing per topology, no
intermediary glue. The demo prompt the phase was designed around — *"build
a 2911 router and a PC, configure 192.168.1.1/24, ping, save to
/tmp/demo.pkt"* — completes hands-off in a fresh Claude session and the
.pkt opens cleanly in the PT GUI.

## Final tool surface

12 tools land in `pkt_mcp/server.py`. The first 10 are 1:1 over the Bridge;
the last two are ergonomic helpers that bake in Phase 3 lessons. Argument
schemas and descriptions are produced by FastMCP from the type hints and
docstrings — the docstrings ARE the LLM-facing contract.

| tool | purpose |
|------|---------|
| `ping_self` | Health check — returns `"ok"`. Confirms the MCP layer is alive without touching PT. |
| `add_device` | Place a device on the canvas. Routers boot transparently (~30 s skip-dialog handshake). |
| `delete_device` | Remove a device by name. Auto-cleans incident links. |
| `connect` | Cable two ports. `auto_portfast=True` applies `spanning-tree portfast` on switch↔host links. |
| `configure_interface` | Paced IOS sequence: enable → conf t → int → ip → no shutdown → end. Returns observed port state. |
| `configure_host` | Static IP+mask+gateway (or DHCP) on a PC/Server `FastEthernet0`. |
| `run_command` | One CLI line; auto-dispatches `terminal=ios|desktop` from the cached device type. |
| `list_devices` | Enumerate the canvas. Refreshes the Bridge type cache. |
| `get_port_state` | Read-only port introspection (ip, mask, up/proto, link). |
| `save_pkt` | Headless save via `fileSaveAsNoPrompt` — does NOT touch PT's "current open file" pointer. |
| `ping` | Structured ICMP wrapper with the `Lost = 0` predicate and STP-convergence retry. |
| `summarize_topology` | Markdown snapshot of devices + active ports + inferred subnets. |

## Architecture (full picture, end of phase 4)

```
┌────────────────────┐
│ Claude Code (host) │
│   reads PDF specs  │
│   reasons topology │
└─────────┬──────────┘
          │ MCP / stdio JSON-RPC      ← the new layer Phase 4 added
          ▼
┌────────────────────┐
│  pkt_mcp/server.py │  FastMCP("pkt-mcp")
│   12 @mcp.tool()s  │  type hints → JSON schema
│   ToolError ⇐ typed Bridge exceptions
└─────────┬──────────┘
          │ Python call
          ▼
┌─────────────────────┐
│ tools/pkt_bridge.py │  typed client (phase 3)
│   Bridge.add_device │  validates args, builds
│   Bridge.connect ...│  {id, op, args} envelope
└─────────┬───────────┘
          │ /tmp/pkt-mcp/cmd.json  ⇄  result.json   (file mailbox, atomic rename)
          ▼
┌────────────────────────────────┐
│ Packet Tracer 9.0 (one process)│
│  ┌────────────────────────────┐│
│  │ Script Module (encrypted   ││
│  │ .pts, sourced from         ││
│  │ pt-script-module/main.js + ││
│  │ api.js)                    ││
│  │  - main.js: poll + dispatch││
│  │  - api.js:  9 op handlers  ││
│  │  - ipc.appWindow().*       ││
│  └────────────────────────────┘│
│         PT canvas + IPC engine │
└────────────────────────────────┘
```

The MCP layer adds no PT-side surface — it's a thin facade over the Phase 3
Bridge. All PT API calls still cross the file mailbox; the dispatcher in
`api.js` is unchanged. That's by design: PT-side complexity (typed errors,
paced IOS sequences, async router boot) was solved once in Phase 3, and
Phase 4 reuses it.

## Phase 4 step-by-step

### Step 1 — FastMCP scaffolding (`39c0ab2`)

`pyproject.toml` (uv-managed, `mcp[cli]>=1.27.0`) + `pkt_mcp/__init__.py`
+ `pkt_mcp/server.py` with `FastMCP("pkt-mcp")` and a single
`ping_self()` tool returning `"ok"`. Scaffolding only — exists to verify
the MCP plumbing is wired up before adding real surface.

Verified end-to-end via the `mcp` Python client over stdio:
```
SERVER : pkt-mcp 1.27.1
TOOLS  : ['ping_self']
CALL   : ok           isError: False
```

`pyproject.toml` declares `[tool.uv] package = false` — dependency
management only, no build hooks. `python -m pkt_mcp.server` puts the CWD on
`sys.path` so the import resolves without an editable install.

### Step 2 — Register with Claude Code (`1444ed4`)

Top-level `mcpServers` entry in `~/.claude.json`:

```json
"pkt-mcp": {
  "type": "stdio",
  "command": "uv",
  "args": ["run", "--directory", "<ABSOLUTE_PATH_TO_REPO>",
           "python", "-m", "pkt_mcp.server"]
}
```

Global registration — `pkt-mcp` is available in every Claude Code session
regardless of CWD. `~/.claude.json` is per-user state and is NOT in the
repo; the README has the canonical snippet for re-pasting.

Restart the Claude Code session for the registration to take effect; verify
with `/mcp` (entry should show `connected`) or by calling `ping_self`.

### Step 3 — Map 9 Bridge ops as MCP tools (`e140df5`)

Each Bridge method gets a `@mcp.tool()` wrapper with type-hinted args
(FastMCP turns them into JSON schema for Claude) and a docstring written as
LLM-facing API documentation — when to call it, what the args mean, what
the failure modes are, and the non-obvious behaviors callers should know
(router boot dialog handled transparently by `add_device`, IOS pacing
handled by `configure_interface`, `fileSaveAsNoPrompt` doesn't touch the
"current file" pointer, etc.).

Bridge typed errors map to MCP `ToolError` with the `error_type` prefixed:

```python
def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except BridgeError as e:
        raise ToolError(f"{e.error_type}: {e}") from e
    except TimeoutError as e:
        raise ToolError(f"BRIDGE_TIMEOUT: {e}") from e
```

The `error_type` prefix (`PT_NOT_FOUND`, `BAD_ARGS`, …) lets the LLM
recognize the failure kind from the error string alone, without parsing
JSON or registering custom error classes on the MCP wire.

The Bridge instance is a **module-level singleton** because the
`_device_types` cache that powers `run_command`'s terminal auto-dispatch
lives on the instance — every tool call within a session must share it.

### Step 4 — Ergonomic helpers (`f0aaba2`)

Three additions that bake in Phase 3 lessons:

#### `connect(..., auto_portfast=True)`

Detects the host↔switch case from the Bridge type cache. When exactly one
endpoint is a `SWITCH` and the other is a host (`PC` / `SERVER`), the
switch port is automatically taken into config mode and
`spanning-tree portfast` is applied. Skips the ~30 s STP listening +
learning convergence on access ports — without it, the first ping batches
after a fresh switch↔host link drop entirely.

The `_ensure_device_type` helper falls back to a `list_devices()` refresh
if the cache misses — so Phase 4 sessions started against a previously-
loaded canvas (devices placed in a prior session) still benefit from
auto_portfast.

#### `ping(from_device, to_ip, count=4, retries=2)`

Structured wrapper over `run_command`. Implements the M6 lessons:

- **Buffer slicing.** `_last_ping_section` slices to the most recent
  `Pinging <ip>` header so retries aren't fooled by an earlier successful
  batch in scrollback.
- **Substring trap avoidance.** Predicate is `Lost = 0`, **never** `0% loss`
  — the latter is also a substring of `100% loss`.
- **Retry policy.** Total loss (`received == 0`) triggers retry (STP
  convergence absorber). Partial loss (`received > 0`) returns
  `success=False` immediately, because partial loss is usually a real
  issue we shouldn't mask.

Returns `{success, sent, received, lost, packet_loss_pct, attempts, output}`.

#### `summarize_topology()`

Markdown snapshot — devices table, active-ports table, inferred subnets.
Lets Claude orient itself in one call instead of N round-trips.

There is no `list_ports` op (yet), so the helper probes a curated port
set per device type and silently catches `PT_NOT_FOUND`:

```python
_PORT_PROBE = {
    "ROUTER":          GE0/0..GE0/2 + Se0/0/0..Se0/0/1 + Fa0/0..Fa0/1,
    "SWITCH":          Fa0/1..Fa0/8 + GE0/1..GE0/2,
    "PC":              FastEthernet0,
    "SERVER":          FastEthernet0,
    "WIRELESS_ROUTER": Internet, Ethernet1..4,
    "HUB":             [],
}
```

Covers the small/demo topologies Phase 4 targets. High-port switches
(Fa0/9+) need explicit `get_port_state`. A real `list_ports` op is in
the open-follow-ups list.

### Step 5 — Skipped

The optional typed `load_pkt` op was punted. The Step 6 demo only needs
`save_pkt` on the critical path; the smoke test's existing `Bridge.raw()`
fileOpen still works for round-trip verification. Adding `load_pkt` would
require an `api.js` change and a manual PT GUI Stop/Start of the listener,
which the deliverable doesn't justify yet. Deferred to a phase that
genuinely needs reload.

### Step 6 — End-to-end demo (PASS)

Fresh Claude session, no manual prep beyond:

1. Restart Claude Code so the `~/.claude.json` registration loads.
2. Confirm `/mcp` shows `pkt-mcp ✔ connected`.
3. Paste:

   > Use the pkt-mcp tools to build a network with a 2911 router (R1) and
   > a PC (PC1). Configure R1 G0/0 as 192.168.1.1/24, PC1 as
   > 192.168.1.10/24 gateway 192.168.1.1. Verify connectivity. Save to
   > /tmp/demo.pkt.

Outcome (verified by user, screenshot confirmed): R1 (2911) + PC1 (PC-PT)
on the canvas with a green link, R1 G0/0 = 192.168.1.1/24 Up, PC1 reachable,
`/tmp/demo.pkt` opens cleanly in the PT GUI when manually verified.

## Lessons learned

### Cable-type guidance: textbook vs. PT empirical (the embarrassing one)

Mid-Phase 4 the `connect` docstring went through three revisions on the
router↔PC direct case. The trajectory:

1. **Step 4 initial.** Docstring described `ETHERNET_STRAIGHT` as
   "router↔switch, switch↔host; the most common case" and `ETHERNET_CROSS`
   as "same-type legacy gear". Silent on the router↔host case.
2. **Pre-demo polish (`ffa5363`).** Reframed `ETHERNET_CROSS` in DTE↔DTE
   terms, explicitly bucketing router↔host into CROSS per Cisco textbook
   theory. **This was wrong empirically.**
3. **Post-demo correction (this commit).** Demo evidence + PT auto-MDIX
   behavior: `ETHERNET_STRAIGHT` works for router↔PC. PT models modern
   auto-MDIX, which negotiates polarity automatically — the classical
   DTE↔DTE crossover rule is academic in PT. `AUTO` is also fine.

The lesson is general: **PT's behavior is the authoritative reference, not
Cisco textbook theory.** When a docstring claim about cable types, port
behavior, or convergence timing has no test or demo backing it, treat it as
a hypothesis. The `connect` docstring's first version asserted a rule that
worked for the M6 scenarios it was tested against (router↔switch,
switch↔host) and silently extrapolated. Future cable-type or behavior
guidance should be backed by either a smoke test or a recorded probe.

### `_device_types` is private state that crosses the MCP boundary

The Bridge's `_device_types` cache is populated by `add_device` and read by
`run_command`'s terminal auto-dispatch. With a single Python script as the
caller (Phase 3 smoke test), this is fine — the script `add_device`s
everything it later `run_command`s. With MCP, the LLM may operate on
devices it didn't place this session (canvas reloaded, fresh session
against existing topology). The fix is `_ensure_device_type` falling back
to a `list_devices()` refresh on cache miss.

This generalizes: **state that a Phase 3 caller "knew" implicitly (because
the same script set it) becomes a coordination problem when an LLM is
making one tool call at a time across an MCP boundary.** The MCP server has
to either (a) refresh from PT on demand or (b) reject calls that need
state the LLM hasn't established. We picked (a) for `_device_types`
because it's a minor refresh; for `_PORT_PROBE` we picked (b) implicitly
(callers who need ports outside the probe set must call `get_port_state`
explicitly).

### Docstrings are the user-facing surface, treat them like API docs

FastMCP turns `@mcp.tool()` docstrings into the descriptions Claude sees
when picking tools. Terse one-liners are not enough — the docstring needs
to convey:

- When to call this tool vs. an alternative (e.g.,
  `configure_interface` vs. driving `enable / conf t / ...` through
  `run_command`).
- Failure modes and how to recover from them.
- Non-obvious side effects (transparent router boot dialog skip,
  `save_pkt` not changing the "current file" pointer).
- Buffer-tail patterns (`run_command(device, "")` to re-read for ping
  output).

The 12 tools' docstrings ended up averaging ~25 lines each. That's a lot of
prose, but it's load-bearing — the LLM picks tools and recovers from
errors based on what's in those docstrings.

### `package = false` + `python -m` is the cleanest uv layout

The `pkt-mcp` repo is a runnable application, not a distributable package.
`[tool.uv] package = false` skips build hooks; `python -m pkt_mcp.server`
puts the CWD on `sys.path`, so `pkt_mcp/server.py` resolves without an
editable install. Saves a hatchling dependency and a wheel build step that
serves no one. Good default for "MCP server in a repo".

## Open follow-ups (deferred)

- **`load_pkt` typed op.** Replace the smoke test's `Bridge.raw('ipc.appWindow().fileOpen(...)')`
  with a typed op. Requires `api.js` change + listener reload.
- **`list_ports` typed op.** Would let `summarize_topology` enumerate ports
  exhaustively instead of probing a curated set. Same `api.js` change cost
  as `load_pkt`; bundle them if either lands.
- **HUB / WIRELESS_ROUTER full coverage.** `_PORT_PROBE` for `WIRELESS_ROUTER`
  is a guess (Internet + Ethernet1..4) and `HUB` is empty. Validate when a
  use case needs them.
- **Listener-globals reset edge case (Phase 3 carry-over).** If `main.js` is
  re-Exported and Stop/Started, `DISPATCH` is rebuilt cleanly, but any
  module-scope state in `api.js` is reset — handlers that lazy-init module
  state need to tolerate that. Phase 4 didn't introduce any such state, so
  no concrete bug yet, but future op authors should know.
- **Multi-NIC hosts.** `configure_host` only touches `FastEthernet0`.
  Laptops with wireless + wired need an `interface` arg.
- **Bridge concurrency.** The mailbox is single-slot; the Bridge instance
  is a singleton. Two concurrent MCP tool calls (if FastMCP ever supports
  that) would race on `cmd.json`. Add a Python-level mutex in the Bridge
  if/when concurrency lands.
- **`run_command` for long output (e.g. `show running-config`).** Currently
  returns the full buffer; for genuinely streaming use cases the
  `outputWritten` IPC event path noted in `phase2-api-map.md` M6 is the
  cleaner approach.
