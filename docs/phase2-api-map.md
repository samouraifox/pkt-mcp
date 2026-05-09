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
| 16  | MULTI_LAYER_SWITCH | `"3560"`                  |
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

## M3..M6

_Stubbed; populate after each milestone lands._
