# Phase 2 API map

Running record of the in-PT JavaScript API surface as we discover it. Each
section corresponds to a Phase 2 milestone in the project plan. Append-only —
record what works *and* what fails so future iterations don't re-probe the
same ground.

## M1 — Device-type integer map

**Status:** done. All five Phase 2 targets (SWITCH, PC, SERVER, HUB,
WIRELESS_ROUTER) are runtime-confirmed.

### How `addDevice` reports a bad model

`addDevice(devType, model, x, y)` does **not** throw when the model string is
unrecognized — it returns an empty string and creates nothing. So the
distinguishing signal in the probe log is `-> <Name0>` (success) vs `-> `
(model rejected). Errors only surface when the *devType int itself* is
invalid; in iter1 of M1, no probe in the 1..20 range threw.

### Confirmed device types

Targets called out by the Phase 2 plan are bolded.

| int  | enum                | working model       | runtime confirmation |
|------|---------------------|---------------------|----------------------|
| 0    | ROUTER              | `"2911"`            | Phase 1B             |
| **1**  | **SWITCH**          | `"2960-24TT"` *(also accepts `"Switch-PT"` generic)* | M1 iter2 |
| 2    | CLOUD               | `"Cloud-PT"`        | M1 iter1             |
| 3    | BRIDGE              | `"Bridge-PT"`       | M1 iter1             |
| **4**  | **HUB**             | `"Hub-PT"`          | M1 iter1             |
| 5    | REPEATER            | `"Repeater-PT"`     | M1 iter1             |
| 7    | ACCESS_POINT        | `"AccessPoint-PT"`  | M1 iter1             |
| **8**  | **PC**              | `"PC-PT"`           | M1 iter1             |
| **9**  | **SERVER**          | `"Server-PT"`       | M1 iter1             |
| 10   | PRINTER             | `"Printer-PT"`      | M1 iter1             |
| **11** | **WIRELESS_ROUTER** | `"Linksys-WRT300N"` | M1 iter2             |
| 13   | DSL_MODEM           | `"DSL-Modem-PT"`    | M1 iter1             |
| 14   | CABLE_MODEM         | `"Cable-Modem-PT"`  | M1 iter1             |
| **16** | **MULTI_LAYER_SWITCH** | `"3560-24PS"` *(also `"3560-24PH"`, `"3560H"`; supports `ip routing`, SVIs `interface vlan N`)* | portfolio-network probe (2026-05) |
| 18   | LAPTOP              | `"Laptop-PT"`       | M1 iter1             |
| 19   | TABLET_PC           | `"TabletPC-PT"`     | M1 iter1             |

### Open (devType valid per Java enum, but no model string accepted yet)

These integers didn't error in iter1 either, but the guessed model string was
rejected. None are needed for Phase 2's MVP, so we left them. If a later
phase needs them, grep `$PT_HOME/bin/PacketTracer` for plausible model
substrings the same way M1 iter2 found `2960-24TT` and `Linksys-WRT300N`.

| int | enum               | guess that failed         |
|-----|--------------------|---------------------------|
| 6   | CO_AXIAL_SPLITTER  | `"CoaxialSplitter-PT"`    |
| 12  | IP_PHONE           | `"IP-Phone"`              |
| 15  | REMOTE_NETWORK     | `"Remote-Network"`        |
| 17  | SWITCH3650         | `"3650"`                  |
| 20  | PDA                | `"PDA-PT"`                |

(Java enum 21 = WIRELESS_END_DEVICE and 22 = WIRED_END_DEVICE — never probed
since the plan stopped at N=20.)

### Lookup technique that worked

When a guessed model is rejected, model strings live as plaintext in the PT
binary. The `2960-24TT` / `Linksys-WRT300N` confirmations came from:

```
strings $PT_HOME/bin/PacketTracer | grep -E '^[A-Za-z0-9-]*2960[A-Za-z0-9-]*$'
strings $PT_HOME/bin/PacketTracer | grep -E '(Linksys-|WRT[0-9])'
```

Bake this into the workflow for any future device type that doesn't accept
its `<Name>-PT` generic.

## M2 — R1 + SW1 on the canvas

**Status:** done, via the bridge (see "Phase 2 interlude" below).

The bridge invocation that landed M2:

```python
python tools/pkt_bridge.py '
var win = ipc.appWindow();
var lw = win.getActiveWorkspace().getLogicalWorkspace();
var net = win.getActiveFile().getMainNetwork();
var r1 = lw.addDevice(0, "2911", 200, 200);
net.getDevice(r1).setName("R1");
var sw1 = lw.addDevice(1, "2960-24TT", 400, 200);
net.getDevice(sw1).setName("SW1");
({r1: r1, sw1: sw1});
'
# -> {"r1": "Router0", "sw1": "Switch0"}
```

**Workspace baseline note.** A fresh PT logical workspace already contains a
`Power Distribution Device0` (system entity for the IoE/power simulation
features). `getDeviceCount()` therefore reads `1` on what looks like an empty
workspace. Filter it out by name when iterating user-created devices.

## Phase 2 interlude — file-polling bridge

After M2 we paused milestone work to automate the GUI re-run loop. The PT
Script Engine sandbox has neither `fetch` nor `XMLHttpRequest`, so the
architecture-doc'd web-view-polls-HTTP design is deferred to Phase 3. For
now we use a file-mailbox bridge that runs entirely from inside the SE.

**Sandbox findings (relevant subset).**

| primitive             | available? | notes                                  |
|-----------------------|-----------:|----------------------------------------|
| `fetch`, `XMLHttpRequest` | no     | sandboxed Qt Script, not a browser     |
| `setTimeout` / `setInterval` | yes | event loop is real; timer fires        |
| `eval`, `Function`    | yes        | both return correct values             |
| `JSON.parse` / `stringify` | yes   | used by listener / driver              |
| `ipc.systemFileManager` | yes      | returns the file manager object        |
| `ipc.systemFileManager().getFileWatcher()` | yes | event-driven option for later if 500ms polling becomes a bottleneck |

**`SystemFileManager` gotchas.**

- `writeTextToFile(filename, contents64)` expects the *content* arg in
  base64 — passing raw text silently no-ops (returns true, file ends up
  garbage / empty).
- `writePlainTextToFile(filename, contents)` is the plain-UTF-8 variant.
  This is what the listener uses.
- `moveSrcFileToDestFile(srcFile, destFile, bReplace)` takes **three** args;
  the third is the overwrite flag. Pass `true` for our atomic-write protocol.
- Tilde paths (`~/...`) are *not* expanded — write returns true, but
  `fileExists` returns false. The mailbox lives at absolute `/tmp/pkt-mcp/`.
- Doxygen reference for the full surface:
  `$PT_HOME/help/default/IpcAPI/class_system_file_manager.html`.

**Mailbox protocol.**

```
Python writes  /tmp/pkt-mcp/cmd.json.tmp,    renames to cmd.json
SE     reads   /tmp/pkt-mcp/cmd.json,        deletes after read
SE     writes  /tmp/pkt-mcp/result.json.tmp, renames to result.json
Python reads   /tmp/pkt-mcp/result.json,     deletes after read
```

Command shape: `{"id": <str>, "code": <js source>}`.
Result  shape: `{"id": <same>, "result": <jsonable>, "error": null|str, "logs": [<dprint strings>]}`.

Listener: `pt-script-module/main.js`. Driver: `tools/pkt_bridge.py`. Poll
interval is 500 ms in the SE, 50 ms on the Python side.

**Going forward.** M3 onward send their probe code via `tools/pkt_bridge.py`.
The only PT GUI step that remains is the one-time Stop/Start of the listener
when `main.js` itself changes (which should be rare from here — the listener
is stable code, milestone-specific JS rides through `cmd.json`).

## M3 — link API + cable-type map

**Status:** done. Primary deliverable (R1 G0/0 ↔ SW1 Fa0/1, copper-straight)
created via the bridge in a single call, both port endpoints report a
non-null `getLink()` object.

The Doxygen detail page for `LogicalWorkspace::createLink` has the full
contract — no runtime API discovery needed. Reference:
`$PT_HOME/help/default/IpcAPI/class_logical_workspace.html`.

### Working call

```js
var lw = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace();
lw.createLink(deviceName1, portName1, deviceName2, portName2, connType);
// returns bool: true on success, false otherwise.
```

- **Device identifiers are name strings**, not handles or UUIDs. Pass `"R1"`,
  `"SW1"`, etc — exactly what `Device.getName()` returns. Eliminates the port-
  lookup mini-discovery the original M3 plan called for.
- **Port names are concatenated type+index strings.** Doxygen lists the
  accepted types: `Console`, `Aux`, `Ethernet`, `FastEthernet`,
  `GigabitEthernet`, `Serial`, `Wireless`, `Loopback`, `Vlan`, `Modem`,
  `Coaxial`, `Rs232`, `Async` — followed by the port index where applicable
  (`"FastEthernet0/0"`, `"GigabitEthernet0/0"`, `"Serial0/0/0"`).
- M3 verified call:
  `lw.createLink("R1", "GigabitEthernet0/0", "SW1", "FastEthernet0/1", 8100)`
  → `true`.
- **Visual link state right after `createLink` is RED on the router end.**
  This is not a bug — Cisco router physical interfaces default to `shutdown`,
  so the link is admin-down until M5 sends `no shutdown`. Switch ports are
  `no shutdown` by default; the moment R1's side comes up, both ends turn
  green. Don't chase this in M3.

### Cable-type integer table (`CONNECT_TYPES`)

From the same Doxygen `connType` parameter doc — authoritative, not probed.

| int  | enum                | use                                     |
|------|---------------------|-----------------------------------------|
| **8100** | **ETHERNET_STRAIGHT** | **copper-straight (router↔switch, switch↔host)** |
| **8101** | **ETHERNET_CROSS**    | **copper-crossover (same-type, e.g. switch↔switch on legacy gear)** |
| 8102 | ETHERNET_ROLL       | rollover                                |
| **8103** | **FIBER**             | **fiber-optic**                          |
| 8104 | PHONE               |                                         |
| 8105 | CABLE               | coax-cable to cable modem               |
| 8106 | SERIAL              | DTE-DCE serial                          |
| 8107 | AUTO                | PT auto-picks the right cable for the port pair |
| 8108 | CONSOLE             | console rollover                        |
| 8109 | WIRELESS            | wireless association                    |
| 8110 | COAXIAL             |                                         |
| 8111 | OCTAL               |                                         |
| 8112 | CELLULAR            |                                         |
| 8113 | USB                 |                                         |
| 8114 | CUSTOM_IO           | IoE / programmable I/O                  |

### Useful port introspection (from `Device.getPort(portName)`)

| method                  | returns          | use                              |
|-------------------------|------------------|----------------------------------|
| `getName()`             | string           | port name as canonical form      |
| `getLink()`             | Link \| null     | non-null ⇒ port is connected     |
| `getRemotePortName()`   | string           | other end's port name (observed empty in our test — may need a different traversal) |
| `deleteLink()`          | void             | drop this end's link             |

`Device.getPort(name)`, `Device.getPortAt(index)`, `Device.getPortCount()`,
`Device.getPorts()` are all present on the Device object — equivalent to
the Java framework's port accessors. We never needed `getInterface(...)` or
`getMainNetwork().getPort(uuid, idx)` — they may not exist or may be
internal.

### Tear-down primitive

`lw.deleteLink(deviceName, portName)` removes the link incident to the
named port. Useful when re-running a milestone without restarting PT.

## M4 — copper-straight link R1 ↔ SW1 on G0/0 ↔ Fa0/1

**Status:** absorbed into M3 (commit `505b2bf`).

The original plan separated M3 (discover the link API) from M4 (apply it to
the canonical R1↔SW1 pair). Doxygen handed us the full `createLink`
contract on the first read, so the verification call **was** the M4
deliverable — there was nothing left to apply. The green-link assertion M4
implied lands at M5 once `no shutdown` clears the admin-down state on R1.

## M5 — CLI configuration API

**Status:** done. R1 G0/0 configured to `192.168.1.1/24`, admin-up, line
protocol up. Verified through the API; visual green link to SW1 expected.

### Working API for sending commands

```js
var tl = device.getCommandLine();   // returns a TerminalLine
tl.enterCommand("<single line of CLI input>");
tl.getPrompt();                      // current prompt string, e.g. "Router(config-if)#"
tl.getMode();                        // current mode tag, e.g. "user", "enable", "global", "intG"
```

- `Device.getCommandLine()` returns a per-device `TerminalLine`. (Doxygen:
  `class_terminal_line.html`.)
- `enterCommand(string)` sends **one** logical input line (no embedded
  newlines). Treat it like the user pressing Enter once.
- The terminal name is `con0` — i.e. this is the **console line**, not VTY.
  It does not require an authenticated SSH/telnet session.
- Helpful introspection while scripting: `getPrompt()`, `getMode()`,
  `getCurrentHistory()`, `getConfigHistory()`, `getCommandInput()`.

### Mode transitions are NOT automatic

We must drive the IOS state machine ourselves — one Cisco command per
`enterCommand` call. Commands and the mode they leave the terminal in:

| command                             | resulting `getMode()` | resulting prompt    |
|-------------------------------------|-----------------------|---------------------|
| (empty / Enter)                     | `user`                | `Router>`           |
| `enable`                            | `enable`              | `Router#`           |
| `configure terminal`                | `global`              | `Router(config)#`   |
| `interface GigabitEthernet0/0`      | `intG`                | `Router(config-if)#`|
| `ip address 192.168.1.1 255.255.255.0` | `intG` (no transition) | `Router(config-if)#` |
| `no shutdown`                       | `intG` (no transition) | `Router(config-if)#` |
| `end`                               | `enable`              | `Router#`           |

### Send commands one-at-a-time, not as a block

**Critical pacing rule.** Chaining many `enterCommand` calls inside a
single bridge eval — even with no apparent delay between them — races the
IOS simulator: PT processes ~the first one or two and the rest are
silently lost (terminal even rolled to `mode=logout`, `prompt=""` in our
first chained attempt). The reliable pattern is **one `enterCommand` per
bridge call**, with `getPrompt()` / `getMode()` checked between to confirm
the transition landed.

For Phase 4's MCP tool, the natural shape is therefore one
`configure_interface(...)` MCP call → many sequential `enterCommand`
roundtrips inside Python, not one big JS payload. (Or queue commands
inside the SE listener with `setTimeout` between, but no need for that
yet.)

### Initial-boot dialog

A freshly-added Cisco router boots into the **System Configuration
Dialog** (`"Would you like to enter the initial configuration dialog?
[yes/no]: "`, `mode=""`). Send `enterCommand("no")` once to skip it before
any other commands. Future `add_device(router)` flows should bake this in.

### Reading config back

There is no `getRunningConfig()` on the JS API. Practical alternatives:

1. **Port-level introspection (used for M5 verification).** `Port` exposes
   structural getters that *are* the running-config view for that
   interface:
     - `getIpAddress()` / `getSubnetMask()`
     - `isPortUp()` (admin state) / `isProtocolUp()` (line protocol)
     - `getMacAddress()`, `getMtu()`, `getBandwidth()`, `getDescription()`
     - `getOspfCost()`, `getOspfHelloInterval()`, OSPF/EIGRP/RIP details
     - `getIpv6Addresses()`, `getNatMode()`, `getAclInID()`/`getAclOutID()`
2. **Issue `show running-config` via `enterCommand`.** Reading the output
   back requires registering for `TerminalLine.outputWritten(string, bool,
   int)` events — not needed for Phase 2 since structural getters cover
   the verification we want.
3. **`Device.getStartupFile()` / `setStartupFile()`** exists and is the
   path for persisting startup-config; haven't probed its content shape
   yet (not in scope for M5).

### M5 verified end-to-end

```
no  → enable → configure terminal → interface GigabitEthernet0/0
    → ip address 192.168.1.1 255.255.255.0 → no shutdown → end
```

Final state per the bridge:

```json
{
  "ip":         "192.168.1.1",
  "mask":       "255.255.255.0",
  "portUp":     true,
  "protocolUp": true,
  "prompt":     "Router#",
  "mode":       "enable"
}
```

`portUp && protocolUp` ⇒ R1 G0/0 is up/up. SW1 Fa0/1 was already up/up by
default. The cable rendering in the canvas should resolve from
red-triangles to solid green now.

## M6 — End-to-end smoke test

**Status:** done. PC1 added, linked to SW1 Fa0/2 on its `FastEthernet0`, IP
`192.168.1.10/24` + gateway `192.168.1.1` set, `ping 192.168.1.1` from the
desktop Command Prompt returned **4/4 replies, 0% loss**. Phase 2 closes here.

### PC port layout

A fresh `PC-PT` (devType=8) exposes **two** ports:

| index | name             | use                              |
|-------|------------------|----------------------------------|
| 0     | `FastEthernet0`  | the host's Ethernet NIC          |
| 1     | `Bluetooth`      | wireless PAN, ignored for Phase 2 |

Note the host port name is `FastEthernet0` (single index, no slash) — *not*
`FastEthernet0/0` like router/switch line cards. Trips up assumptions
inherited from M3.

### End-host configuration API

End hosts (PCs, presumably Laptops/Servers/Tablets) do **not** use IOS CLI.
They configure through structural setters on `Pc` and `HostPort`:

| call                                          | effect                                      |
|-----------------------------------------------|---------------------------------------------|
| `pc.getPort("FastEthernet0").setIpSubnetMask(ip, mask)` | Static IPv4 + mask on the host port |
| `pc.getPort("FastEthernet0").setDhcpClientFlag(false)` | Disable DHCP (required for static to stick) |
| `pc.setDefaultGateway(ip)`                    | Default gateway at the **device** level     |
| `port.setDhcpClientFlag(true)`                | DHCP client mode (skip static)              |

Verified on PC1: after `setIpSubnetMask("192.168.1.10","255.255.255.0")` and
`setDefaultGateway("192.168.1.1")`, `port.getIpAddress()` and
`getSubnetMask()` reflect the values immediately, port up/up.

`HostPort.setDefaultGateway(ip)` also exists at the port level (different
from the device-level setter on `Pc`); the device-level call is the
ergonomic match for what the GUI's IP Configuration dialog does.

### `Pc.getCommandPrompt()` — desktop Command Prompt

```js
var tl = pc.getCommandPrompt();   // distinct from device.getCommandLine()
tl.getName();                      // "con0"
tl.getMode();                      // "user"
tl.getPrompt();                    // "C:\\>"
tl.enterCommand("ping 192.168.1.1");
```

This is the desktop's Windows-flavored shell, returned as the same
`TerminalLine` type used for IOS lines. Same `enterCommand` interface; same
mode/prompt introspection. Pacing rule from M5 still applies — one logical
line per call.

### Output capture: `TerminalLine.getOutput()`

The Doxygen page for `TerminalLine` lists `outputWritten(string, bool, int)`
as the IPC event for new terminal output, but Qt-Script wrappers do **not**
expose IPC events as connectable signals (`tl.outputWritten` is `undefined`).
The script-only convenience method that *does* exist on the wrapper is:

```js
tl.getOutput();   // returns the full terminal buffer as a string
```

This isn't in the C++ Doxygen — it's added in the wrapper layer. Polling it
between bridge calls is dramatically simpler than registering for events.
For Phase 2 this is the way; if a Phase-N use case needs streaming
(progressive output for a long-running command), the event-registration path
through `ipc.registerObjectEvent(uuid, eventName, callback)` is still
available — `registerObjectEvent` and `unregisterObjectEvent` are present on
both `ipc.*` and the terminal wrapper.

### Ping verification

```python
# in Python after enterCommand("ping 192.168.1.1") on the PC's Command Prompt:
buf = bridge.eval('pc.getCommandPrompt().getOutput()')
assert re.search(r"Reply from 192\.168\.1\.1", buf)
```

PT's simulator runs in real-time mode by default — for the simple
single-router single-switch topology, all four ICMP echoes complete inside
~1 s wall time (the t=1s poll already saw the closing
`Packets: Sent = 4, Received = 4, Lost = 0 (0% loss)` summary). Plan for
longer waits on multi-hop routed paths or when convergence is in flight.

### Phase 2 close-out

Topology in PT after M1–M6 is exactly the spec from the original Phase 2
plan:

```
[R1] G0/0 ---copper-straight--- Fa0/1 [SW1] Fa0/2 ---copper-straight--- FastEthernet0 [PC1]
 192.168.1.1/24                                                            192.168.1.10/24, gw 192.168.1.1
```

End-to-end IPv4 reachability proven by PC1 ICMP replies. The JS API now has
documented coverage for: device creation, links, IOS CLI configuration, host
configuration, terminal output capture. That's the surface the Phase 4 MCP
tools (`add_device`, `connect`, `configure_interface`, `configure_host`,
`run_command`) will lean on.
