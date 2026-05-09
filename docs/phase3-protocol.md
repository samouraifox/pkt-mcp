# Phase 3 protocol — structured op/args bridge

Phase 2 used `{"id", "code": "<raw JS>"}` over the file mailbox and `eval()`'d the
code in the SE listener. That worked for milestone discovery but ships the JS
surface to every caller — Phase 4's MCP layer would have to invent the schema
itself while wrapping FastMCP.

Phase 3 replaces the eval payload with a structured op/args envelope. The
in-PT dispatcher resolves `op` to a function in `api.js`, validates `args`, and
returns a typed result. The Python bridge becomes a thin client whose methods
mirror the ops 1:1.

## Wire envelope

**Command** (Python → SE):

```json
{ "id": "<uuid>", "op": "<op_name>", "args": { ... } }
```

**Result** (SE → Python):

```json
{
  "id":     "<echoed>",
  "result": <op-specific|null>,
  "error":  null | { "error_type": "<TYPE>", "error_message": "<msg>", "error_data": <obj?> },
  "logs":   [<dprint strings>]
}
```

The mailbox transport (`/tmp/pkt-mcp/cmd.json` ↔ `result.json`, atomic rename,
500 ms SE poll, 50 ms Python poll) is unchanged. Only the payload schema
changes.

The mailbox is **single-slot**; the bridge processes one op at a time.
Out-of-order or pipelined commands are not supported in Phase 3 — a caller
must wait for `result.json` (or its own request id to come back) before
writing the next `cmd.json`.

## Error model

`error` is `null` on success. On failure it's a structured object:

```json
{ "error_type": "<TYPE>", "error_message": "<human detail>", "error_data": { ... } }
```

`error_data` is optional and op-specific (e.g. `configure_interface` puts the
observed `port_state` there on a `PT_TIMEOUT`). The Python client maps
`error_type` 1:1 to an exception class — no string parsing.

| `error_type`   | meaning                                                    |
|----------------|------------------------------------------------------------|
| `UNKNOWN_OP`   | `op` not registered in the dispatcher                      |
| `BAD_ARGS`     | required arg missing, wrong type, or unknown enum value    |
| `PT_NOT_FOUND` | named device or port doesn't exist on the canvas           |
| `PT_REJECTED`  | a PT API call returned an empty/false sentinel (M1 quirk)  |
| `PT_TIMEOUT`   | a paced multi-step op didn't converge (reserved for M5-style CLI sequences) |
| `INTERNAL`     | unexpected JS exception inside the op handler              |

## Op:"raw" escape hatch

```json
{ "op": "raw", "args": { "code": "<js source>" } }
```

Falls back to the Phase 2 eval path. **Debug only.** Production callers (the
typed bridge client, the Phase 4 MCP server) must not use it; it exists so we
can keep probing PT's API surface from Python without re-loading the listener.

## Ops

### `add_device`

**Input**

```json
{
  "type":  "ROUTER|SWITCH|PC|SERVER|HUB|WIRELESS_ROUTER",
  "name":  "<unique device name>",
  "model": "<model string from phase2-api-map.md M1 table>",
  "x":     <number>,
  "y":     <number>
}
```

**Output**

```json
{ "uuid": "<PT-assigned uuid>", "name": "<echoed>" }
```

**Failure modes**

- `BAD_ARGS` — missing field or unknown `type` enum
- `PT_REJECTED` — `addDevice` returned `""` (the M1 model-rejection quirk)
- `PT_REJECTED` — `name` collides with an existing device. `error_data` is
  `{ "existing_uuid": "<uuid>"|null }` so callers can decide whether to
  delete-then-add. The JS layer **does not** auto-rename — failing loud on
  collision is the default; PT's silent `R1 → R1-1` rename would desync any
  caller-side name cache.

**Notes**

- `type` is a string enum; the JS layer maps it to the int from the M1 table.
  Callers don't see the magic numbers.
- For `type: "ROUTER"`, the handler auto-skips the System Configuration Dialog
  by sending `enterCommand("no")` once on the new device's `CommandLine`
  before returning (M5 finding). Every router lands in `mode=user` ready for
  `enable`, no caller-side workaround.

### `delete_device`

**Input**: `{ "name": "<device name>" }`
**Output**: `{ "ok": true }`

**Failure modes**

- `PT_NOT_FOUND` — no device with that name (excluding the system
  `Power Distribution Device0` entity, which is not deletable)
- `BAD_ARGS` — missing name

**Notes**

- Implementation TBD: `LogicalWorkspace` exposes `removeDevice(uuid)` per
  Doxygen; if a name-keyed primitive exists we use it, otherwise the JS layer
  resolves name → uuid first.

### `connect`

**Input**

```json
{
  "dev_a":      "<name>",
  "port_a":     "<port name, e.g. GigabitEthernet0/0>",
  "dev_b":      "<name>",
  "port_b":     "<port name>",
  "cable_type": "ETHERNET_STRAIGHT|ETHERNET_CROSS|FIBER|SERIAL|WIRELESS|AUTO|..."
}
```

**Output**: `{ "ok": true }`

**Failure modes**

- `BAD_ARGS` — unknown `cable_type` enum or missing field
- `PT_NOT_FOUND` — device or port name absent
- `PT_REJECTED` — `createLink` returned `false` (port already linked, type
  mismatch, …)

**Notes**

- `cable_type` is a string enum mapped to the `CONNECT_TYPES` int per the
  phase2 M3 table. Full set supported, MVP focus on `ETHERNET_STRAIGHT`,
  `ETHERNET_CROSS`, `FIBER`, `SERIAL`, `AUTO`.
- Visible red-triangle on a router end immediately after connect is
  admin-down, not a failure (cleared by the next `configure_interface` with
  `no_shutdown: true`).

### `configure_interface`

**Input**

```json
{
  "device":      "<IOS device name>",
  "interface":   "GigabitEthernet0/0|FastEthernet0/1|...",
  "ip":          "<dotted quad>",
  "mask":        "<dotted quad>",
  "no_shutdown": true
}
```

`no_shutdown` defaults to `true`.

**Output**

```json
{
  "ok": true,
  "port_state": {
    "ip":          "<observed>",
    "mask":        "<observed>",
    "up":          <bool>,
    "protocol_up": <bool>
  }
}
```

**Failure modes**

- `PT_NOT_FOUND` — device or interface absent
- `BAD_ARGS` — malformed ip/mask
- `PT_TIMEOUT` — port introspection didn't reflect the configured IP within
  the handler's retry budget (CLI sequence raced — see M5 pacing rule)

**Notes**

- Implemented inside the JS layer as the sequenced M5 run:
  `enable → configure terminal → interface <name> → ip address <ip> <mask>
  → [no shutdown] → end`, **one `enterCommand` per step**, with `getPrompt()`
  / `getMode()` checked between to confirm each transition before sending the
  next line. Pacing is the listener's job, not the caller's — this is the
  whole point of doing dispatch in JS rather than Python (avoids one mailbox
  roundtrip per CLI line).
- After `end`, the handler reads `Port.getIpAddress()` / `getSubnetMask()` /
  `isPortUp()` / `isProtocolUp()` and returns them. If they don't match the
  requested values it raises `PT_TIMEOUT` with the observed state in the
  message.

### `configure_host`

**Input**

```json
{
  "device":  "<PC/laptop name>",
  "ip":      "<dotted quad>"|null,
  "mask":    "<dotted quad>"|null,
  "gateway": "<dotted quad>"|null,
  "dhcp":    false
}
```

`dhcp` defaults to `false`.

**Output**: `{ "ok": true }`

**Failure modes**

- `PT_NOT_FOUND` — device absent, or no `FastEthernet0` port (wrong device
  type, e.g. a `Server-PT` whose port layout we haven't validated yet)
- `BAD_ARGS` — `dhcp: false` with `ip` or `mask` missing

**Notes**

- Targets the conventional host port `FastEthernet0` (no slash) per M6 finding.
- Static path: `setDhcpClientFlag(false) → setIpSubnetMask(ip, mask) →
  setDefaultGateway(gateway)` (device-level, matching the GUI's IP
  Configuration dialog).
- DHCP path: `setDhcpClientFlag(true)`; `ip`/`mask`/`gateway` ignored.
- Multi-NIC hosts (laptop wireless, etc.) need an `interface` arg — out of
  scope for Phase 3; add when a use case lands.

### `run_command`

**Input**

```json
{
  "device":   "<name>",
  "command":  "<single shell/IOS line, no embedded \\n>",
  "terminal": "ios" | "desktop"
}
```

**Output**

```json
{
  "output": "<full TerminalLine.getOutput() buffer after the command>",
  "prompt": "<getPrompt() after>",
  "mode":   "<getMode() after>"
}
```

**Failure modes**

- `PT_NOT_FOUND` — no device with that name, **or** the device doesn't
  expose the requested terminal (e.g. `terminal:"desktop"` on a router,
  `terminal:"ios"` on a PC)
- `BAD_ARGS` — multi-line command, missing `terminal`, or `terminal` not in
  `{"ios", "desktop"}`

**Notes**

- The JS API does NOT infer terminal kind from device type. `terminal:"ios"`
  uses `Device.getCommandLine()`; `terminal:"desktop"` uses
  `Pc.getCommandPrompt()`. One job, fail-fast — calling the wrong one for a
  given device raises `PT_NOT_FOUND`. This is deliberate: the JS surface
  stays predictable, and ergonomics live in the Python client.
- The Python client (`Bridge.run_command(device, command)`) hides this from
  callers — it caches `device → type` at `add_device` time and auto-fills
  `terminal` based on type ("ios" for routers/switches/IOS gear, "desktop"
  for hosts). Power-user override: `Bridge.run_command(..., terminal="ios")`
  passes through.
- M5 pacing rule still applies. One logical line per call. The op
  intentionally does NOT chain commands; that's the caller's loop.
- For long-running output (e.g. `ping`), the conventional pattern is a
  follow-up `run_command(device, "")` to re-read the buffer. A future
  `read_terminal_buffer` op without sending input is a clean refinement —
  deferred until a use case forces it.

### `list_devices`

**Input**: `{}`

**Output**

```json
[
  { "name": "R1",  "type": "ROUTER", "model": "2911",        "x": 200, "y": 200 },
  { "name": "SW1", "type": "SWITCH", "model": "2960-24TT",   "x": 400, "y": 200 }
]
```

**Failure modes**: none expected (empty list is valid).

**Notes**

- Excludes the system `Power Distribution Device0` entity per M2 finding.
- For device-type ints not in the M1 reverse-map (the open enums table), the
  `type` field returns the int as a decimal string (e.g. `"16"`) so the entry
  still round-trips.

### `get_port_state`

**Input**: `{ "device": "<name>", "interface": "<port name>" }`

**Output**

```json
{
  "ip":          "<addr>"|null,
  "mask":        "<mask>"|null,
  "up":          <bool>,
  "protocol_up": <bool>,
  "link":        <bool>
}
```

**Failure modes**

- `PT_NOT_FOUND` — device or port name missing

**Notes**

- `up` is `Port.isPortUp()` (admin state); `protocol_up` is
  `Port.isProtocolUp()` (line protocol); `link` is `getLink() !== null`.
- This is the read-only equivalent of what `configure_interface` returns in
  its `port_state` block.

### `save` — BLOCKER

**Input**: `{ "path": "<absolute filesystem path to .pkt>" }`
**Output**: `{ "ok": true, "path": "<echoed>" }`

**Status: not implemented in Step 2. Probed in Step 6.**

PT's headless save surface is unknown. Step 6 starts with an **introspection
scan** before falling back to documented candidates — Doxygen has been
incomplete before (`TerminalLine.getOutput()` in M6 was wrapper-only, not
documented). Run inside the SE:

```js
function scan(obj, label) {
    for (var k in obj) {
        if (/save|export|write/i.test(k)) ipc.print(label + "." + k);
    }
}
scan(ipc.appWindow(), "appWindow");
scan(ipc.systemFileManager(), "systemFileManager");
// also try the active workspace / file objects:
scan(ipc.appWindow().getActiveFile(), "activeFile");
scan(ipc.appWindow().getActiveWorkspace(), "activeWorkspace");
```

Any hit matching the regex is probed (call with a test path, check whether
a `.pkt` lands at the path, check for a GUI dialog).

If the scan turns up nothing usable, fall back to the doc'd candidates in
order of preference:

1. `ipc.systemFileManager().saveWorkspace(path)` (or similarly named) —
   if this exists and writes a `.pkt` blob, this is the answer.
2. `ipc.appWindow().saveAs(path)` / `.save()` — risk that it pops a GUI
   dialog rather than running headlessly; if so, ineligible.
3. `xdotool key ctrl+s` from the Python side — last resort. Pulls us back
   outside the SE sandbox and breaks the no-GUI invariant from Phase 2.

If none of (1)/(2) works headlessly, `save` becomes a documented Phase 4
prerequisite blocker. Step 6 returns a stop-and-decide rather than
implementing the keystroke fallback unilaterally.

## Why a JS dispatcher (not a Python one)

Two load-bearing reasons; documenting so the choice doesn't get re-litigated
in Phase 4.

1. **Validation lives next to the API surface.** The M1 quirk where
   `addDevice` returns `""` instead of throwing on a bad model — a Python
   dispatcher would have to roundtrip an introspection call to detect that.
   The JS layer checks the empty string and turns it into a typed
   `PT_REJECTED` before the result crosses the mailbox.

2. **Pacing is the listener's responsibility.** `configure_interface` needs
   the prompt/mode check between `enterCommand` calls (M5). Driving that
   pacing from Python means N mailbox roundtrips per CLI session at the
   500 ms SE poll = ~3 s per interface config. The JS layer does the pacing
   inline in microseconds and returns once the port reads back up/up.

The Python client stays deliberately thin: build `cmd.json`, poll
`result.json`, parse the typed error, raise/return. No business logic.

## What the Python client looks like (sketch)

For Step 4, not Step 1 — included here so the protocol shape can be sanity
checked against a realistic call site:

```python
class Bridge:
    def add_device(self, type: str, name: str, model: str, x: float, y: float) -> dict: ...
    def delete_device(self, name: str) -> None: ...
    def connect(self, dev_a, port_a, dev_b, port_b, cable_type) -> None: ...
    def configure_interface(self, device, interface, ip, mask, no_shutdown=True) -> dict: ...
    def configure_host(self, device, *, ip=None, mask=None, gateway=None, dhcp=False) -> None: ...
    def run_command(self, device, command) -> dict: ...
    def list_devices(self) -> list[dict]: ...
    def get_port_state(self, device, interface) -> dict: ...
    def save(self, path) -> None: ...    # raises Blocked until Step 6 lands

class BridgeError(Exception): ...           # base
class UnknownOp(BridgeError): ...
class BadArgs(BridgeError): ...
class PtNotFound(BridgeError): ...
class PtRejected(BridgeError): ...
class PtTimeout(BridgeError): ...
class BridgeInternal(BridgeError): ...
```

The error-prefix → exception map is mechanical (split on first `: `, look up
in a dict). Phase 4's MCP tool layer sits on top and translates these into
MCP error responses.
