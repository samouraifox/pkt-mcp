# Phase 1 investigation log

Running record of every path tried while finding a way to drive PT 9.0.0
programmatically. Append-only — do not delete entries when paths fail.

## Environment as observed

- PT 9.0.0 build `9.0.0.0810` (confirmed via PTMP `:PTVER9.0.0.0810` in handshake response).
- Distributed as a single AppImage at `/usr/lib/packettracer/packettracer.AppImage`.
- Runs out of an auto-mounted FUSE squashfs at `/tmp/.mount_packet*/opt/pt/` (path is randomized per launch).
- Process env exposes `PT9HOME=/usr/lib/packettracer`.
- Listens on `localhost:39000` (IPC enabled, default port).
- Java framework JAR: `<runtime-mount>/opt/pt/help/default/ipc/pt-cep-java-framework-9.0.0.0.jar`.
- Javadoc: `<runtime-mount>/opt/pt/help/default/ipc/pt-cep-java-framework-9.0.0.0-docs.zip`.
- C++ IPC reference docs: `<runtime-mount>/opt/pt/help/default/IpcAPI/`.
- NetconRestAPI docs (not yet read): `<runtime-mount>/opt/pt/help/default/NetconRestAPI/`.

## Initial Java IPC spike (Phase 1 — failed at auth)

**Code:** committed on branch `phase1-spike-failed`, pushed to origin.

**API path verified by reading the framework Javadoc:**

```
PacketTracerSessionFactoryImpl.getInstance().openSession("localhost", 39000)
  → PacketTracerSession
new IPCFactory(session).getIPC()
  → IPC                                     (in com.cisco.pt.ipc.ui — NOT com.cisco.pt.ipc)
factory.appWindow(ipc)                      → AppWindow
factory.getActiveWorkspace(appWindow)       → Workspace
factory.getLogicalWorkspace(workspace)      → LogicalWorkspace
logical.addDevice(DeviceType.ROUTER, "2911", x, y)   → String (assigned name)
factory.getMainNetwork(appWindow.getActiveFile())    → Network
network.getDevice(name).setName("R1")
session.close()
```

**Runtime classpath gotchas (for any future bridge build):**

The framework's `system`-scoped JAR pulls in nothing automatically; the
following are required at runtime (not declared by the JAR):

- `commons-logging` (slf4j-api also works if bound)
- `commons-lang` 2.6 (the *old* `org.apache.commons.lang.*`, not `lang3`)
- `commons-codec` 1.x (`org.apache.commons.codec.binary.Hex`)

**PTMP handshake — succeeds.** The framework completes connection negotiation:

```
INFO: Successfully negotiated connection
INFO: ... reserved=:PTVER9.0.0.0810
```

So the connection layer + framework version match the running PT.

**Authentication — fails.** PT IPC uses `auth_type=4`
(challenge–response, MD5). The flow (per decompile of
`com.cisco.pt.ptmp.task.AuthenticationTask`):

1. Client sends `AuthRequestLTV(app_id)`
2. Server replies `AuthChallengeLTV(<random 32-char nonce>)`
3. Client computes `Hex(MD5(challenge + shared_secret))`
4. Client sends `AuthResponseLTV(app_id, hex_md5)`
5. Server looks up `app_id` in its registered ExApp list, recomputes the MD5
   with the registered secret, compares. Mismatch → disconnect.

`ConnectionNegotiationPropertiesImpl` has `app_id` and `shared_secret` fields,
both default `""`. The framework exposes them via:

- `setAuthenticationApplication(String)` → app_id
- `setAuthenticationSecret(String)` → shared_secret

So the framework is willing to send credentials — we just don't have any
that the running PT accepts.

## What blocks credential acquisition

ExApps register with PT via **`.pta`** ("App Meta File") loaded through
`Options → Preferences → Misc → IPC → Configure Apps → Add Application Meta File`.

- Bundled `.pta` example: `extensions/ptaplayer/ptaplayer.pta`
- File is binary and AES-style encrypted — not parseable without PT's key
- No CLI flag to register one inline. PT's `--help` only exposes:
  `--no-gui`, `--ipc-port`, `--pt-ipc-port`, `--ipc-arg:`,
  `--ipc-save-data-id`, `--pt-uuid`, `--no-sandbox`, `--log`,
  `--progress-bar-server`, `--autoloadptsa`, `--no-ssl-enforce`,
  `--nointernalsmcertcheck`
- The framework's `LinuxPacketTracerLauncher` only adds `--no-gui` and
  `--ipc-port` when launching PT; no creds are passed.

Conclusion: **client-side credential setting is solved**, but PT-side
registration of an accepted `(app_id, shared_secret)` pair requires either
a `.pta` file we can decrypt/forge, or an external creation tool, or a
side-channel that bypasses ExApp registration.

## Sub-spike 1A — $PT_HOME inventory (FAILED, no usable creds)

### Locations checked

- `$PT_HOME/help/default/ipc/` — only the JAR + docs zip. **No `.properties`, no README,
  no sample creds, no dev `.pta`.**
- `$PT_HOME/extensions/` — bundled extensions:
  - `ptaplayer/ptaplayer.pta` — 1727 bytes, encrypted/binary
  - All other entries (`*.pts`, `*.pkp`, `*.ptst`) are encrypted Script Modules / Packages
    / Script Templates, not ExApps. **No additional `.pta`, no plaintext samples.**
- `$PT_HOME/help/default/IpcAPI/` — Doxygen-generated docs (C++ side). The `*-example.html`
  pages are empty shell pages — they only render the search box, no actual code is embedded.
- `$PT_HOME/help/default/files/CiscoPacketTracerPTMPSpecification.pdf` — local copy of
  the PTMP spec; describes the wire protocol but not authoring-tool workflow.
- `~/pt/` — user's PT data dir.
  - `~/pt/extensions/` — empty (no user-installed ExApps).
  - `~/pt/PT.conf` and `~/pt/PT-*.conf` — fully encrypted blob; no plaintext IPC creds.
  - `~/pt/logs/pt_05.09.2026_11.47.47.219.log` — current PT session log; **every line is
    Cisco-encrypted base64 blocks**, so we can't read the server-side rejection reason.
  - `~/.local/.packettracer/` — only contains `active-version` and `eula-*` (no creds).

### Hardcoded framework defaults — confirmed

`com.cisco.pt.impl.OptionsManager.setDefaultProps()` (decompiled) bakes these in:

```
pt.cep.ptmp.uid          = {c6fbf435-3234-48bb-af04-debc4e4cf9f3}
pt.cep.ptmp.signature    = PTMP
pt.cep.ptmp.version      = 1
pt.cep.encoding          = TEXT_ENCODING
pt.cep.encryption        = NO_ENCRYPTION
pt.cep.compression       = NOT_COMPRESSED
pt.cep.authentication    = MD5_AUTH
pt.cep.auth.secret       = cisco
pt.cep.auth.application  = net.netacad.cisco.ipctest
pt.cep.keepAlivePeriod   = 2000000
```

`ConnectionNegotiationProperties` exposes `setAuthenticationApplication(...)` and
`setAuthenticationSecret(...)` on top of the public `setAuthenticationSecret(...)` we'd
seen — so the framework is willing to send any creds. The original Phase 1 spike already
ran with these defaults (loaded by `OptionsManager.getInstance().getConnectOpts()`) and
PT still rejected — so `net.netacad.cisco.ipctest` / `cisco` is **not** registered in
this PT install. The defaults presumably worked against a NetAcad-distributed test
`.pta` that we don't have.

### Trying CLEAR_TEXT auth path — also fails

`PtmpAuthentication` enum has `CLEAR_TEXT (1)`, `SIMPLE_AUTHENTICATION (2)`,
`MD5AUTHENTICATION (4)`. Tried opening a session with `setAuthentication(1)` and empty
creds. Server answered with token `<3 7  >` (status code 7 = disconnect) at the
negotiation stage — no auth challenge issued. Server enforces MD5 regardless of what
the client offers.

### Other dead-ends checked

- `PacketTracerLauncher` (Linux/Win/Mac) — only adds `--no-gui` and `--ipc-port` to the
  PT command line. No `--register-app` / `--app-id` / `--shared-secret` flags.
- PT's own CLI (`strings PacketTracer | grep -E '^--'`) — `--ipc-arg:`, `--ipc-port`,
  `--pt-ipc-port`, `--ipc-save-data-id`, `--no-gui`, `--no-sandbox`, `--log`, `--pt-uuid`,
  `--progress-bar-server`, `--autoloadptsa`. None register an ExApp inline.
- `Configure Apps` GUI — only `Add Application Meta File`, `Remove`, `Launch`. No
  "New / Generate" wizard.
- PT memory scan for registered app ids (`/proc/$PID/mem`) — process memory not readable
  in a structured way; long-shot anyway.

### Conclusion

**1A fails.** No legitimately-acquirable dev credentials surface from the install. To use
the Java IPC path we'd need either (a) a dev `.pta` from Cisco's NetAcad / partner
program, or (b) to reverse-engineer PT's `.pta` decryption + AppID storage.

### Bonus discovery while inventorying

`$PT_HOME/help/default/scriptModules*.htm` document **PT Script Modules**, which are the
clear successor strategy:

- Run **inside** the PT process — same address space as the C++ engine — so they bypass
  the entire PTMP/ExApp authentication wall.
- Expose the same IPC surface: `ipc.network()`, `ipc.appWindow()`,
  `getActiveWorkspace().getLogicalWorkspace().addDevice(DeviceType.ROUTER, "2911", x, y)`.
  Symbols `addDevice`, `appWindow`, `getActiveWorkspace`, `getLogicalWorkspace`,
  `getMainNetwork` all present in the PT binary's exported symbols.
- Author them in PT itself: `Extensions → Scripting → New PT Script Module`. Saves to a
  user-chosen path as a `.pts` (encrypted, but we can rebuild from source any time).
- Have web views (QWebEngine, full HTML5) that can `fetch()`/`XMLHttpRequest` to a
  localhost HTTP server — that's the door for the Python MCP server to push commands.
- Web views ↔ Script Engine via the built-ins `$se(name, ...args)` (call) and
  `$seev("expr")` (eval, returns Promise).

This becomes Sub-spike 1B.

## Sub-spike 1B — Script Module path (SUCCESS)

Loaded `pt-script-module/main.js` into a new PT Script Module
(`Extensions → Scripting → New PT Script Module`), exported to
`~/pt/extensions/pkt-mcp-bridge.pts`, registered as a persistent module, started.

After granting privileges (see below) and switching the device-type argument from a
name string to the C-IPC enum int, the spike succeeded:

```
[pkt-mcp] start
[pkt-mcp] typeof ipc=object typeof DeviceType=undefined typeof appWindow=undefined
[pkt-mcp] ipc.network() ok, deviceCount=0
[pkt-mcp] ipc.appWindow() ok
[pkt-mcp] getActiveWorkspace() ok
[pkt-mcp] getLogicalWorkspace() ok
[pkt-mcp] addDevice returned: Router0
[pkt-mcp] OK created=Router0 renamed=R1
```

Visual confirmation: a Cisco 2911 labeled **R1** appeared in the logical workspace at
~(200, 300) px. (Position drifts slightly from the requested 200, 200 because PT
auto-snaps device origin; the exact offset comes from the icon's anchor point — not
load-bearing.)

### What the Script Engine actually exposes (resolved)

- `ipc` is a **global object**. `appWindow`, `network`, `DeviceType` are NOT bare
  globals — go through `ipc`.
- `ipc.network()` → `Network` (read-only deviceCount/getDevice).
- `ipc.appWindow()` → `AppWindow`.
- `appWindow.getActiveWorkspace()` → `Workspace`.
- `workspace.getLogicalWorkspace()` → `LogicalWorkspace` (the surface that supports
  `addDevice`, `removeDevice`, `createLink`).
- `appWindow.getActiveFile().getMainNetwork()` → `Network` (write-capable: lets us
  resolve the auto-name returned by `addDevice` and call `setName`).
- IPC calls in the **Script Engine** are synchronous — they return the result directly
  (no Promise/await needed). The async pattern only applies to web views via `$seev()`.

### `addDevice` signature, exactly as the engine wants it

```js
var name = lw.addDevice(devTypeInt, modelString, xPx, yPx);
//                       ^int        ^string      ^double, ^double
// returns: string — PT's auto-assigned device name (e.g. "Router0").
```

- **First arg must be the integer enum value, not a name string.** Strings produce
  `IPC Call ERROR: LogicalWorkspace - Invalid arguments for IPC call "addDevice"`.
- Model string for PT 9 of the Cisco 2911 router: `"2911"`. (Did not have to fall back
  to `"ISR2911"`.)
- Coordinates: **absolute pixels in the logical workspace**, not normalized [0,1] and
  not grid cells. This matters for the future MCP `place_device(x, y)` tool — values
  like `(200, 200)` work; small canvas, common values are roughly `0..1500` x `0..900`.

### `DeviceType` integer mapping (extracted from `pt-cep-java-framework-9.0.0.0.jar` → `com.cisco.pt.ipc.enums.DeviceType.class`)

Confirmed-working: `0` for the Cisco 2911 router. The remaining values come from the
same `<clinit>` block (decompiled with `javap -c`):

| int | enum                            |
|-----|---------------------------------|
| 0   | ROUTER                          |
| 1   | SWITCH                          |
| 2   | CLOUD                           |
| 3   | BRIDGE                          |
| 4   | HUB                             |
| 5   | REPEATER                        |
| 6   | CO_AXIAL_SPLITTER               |
| 7   | ACCESS_POINT                    |
| 8   | PC                              |
| 9   | SERVER                          |
| 10  | PRINTER                         |
| 11  | WIRELESS_ROUTER                 |
| 12  | IP_PHONE                        |
| 13  | DSL_MODEM                       |
| 14  | CABLE_MODEM                     |
| 15  | REMOTE_NETWORK                  |
| 16  | MULTI_LAYER_SWITCH              |
| 17  | SWITCH3650                      |
| 18  | LAPTOP                          |
| 19  | TABLET_PC                       |
| 20  | PDA                             |
| 21  | WIRELESS_END_DEVICE             |
| 22  | WIRED_END_DEVICE                |

**Known unknown:** the Java enum has 50+ entries; only 0-22 are decoded above (those
are what `javap -c` printed in the first window). The rest (ASA, ANALOG_PHONE, HOME_GATEWAY,
HOME_VOIP, ANTENNA-related, IoT THING, MERAKI_*, IO_E, MCU, PLC, NETWORK_CONTROLLER, SBC,
SECURITY_APPLIANCE, SNIFFER, WIRELESS_LAN_CONTROLLER, ...) need their integer values
extracted before Phase 2 builds the full device-type table for the MCP tool surface.
Re-run `javap -c` on `DeviceType.class` and finish the table when needed.

### Privilege the Script Module needs

In the General tab → Security section, **Change Network Info** (`PrivChangeNetwork`)
is required for `addDevice` / `setName` to succeed. Without it:

```
IPC Call ERROR: LogicalWorkspace - ExApp or Script Module does not have the necessary
privilege for IPC call "getLogicalWorkspace"
```

For the spike I ticked all 11 privilege boxes (Application / Multiuser / Simulation /
Activity / IPC / User Preferences / File Operations / Get Network Info / Miscellaneous
UI / Change User Interface / Change Network Info) — none of the broader ones cause
issues, and several will be needed anyway in Phase 2 (e.g. `Application` to drive the
canvas viewport, `File Operations` to trigger save/export). Future Script Modules built
from this codebase should default to the same wide grant; narrow it later if needed.

### Operational notes

- PT 9's editor enforces **Export → register-as-persistent → Start**. There is no "run
  this in-place" affordance — `Start` is greyed out for unsaved modules. So the dev
  loop is: edit `main.js` → in PT's editor `Import` (or paste) → `Save` → `Export` over
  the same `.pts` → `Stop` if running → `Start`. The encrypted `.pts` is a build
  artifact; the `.js` is source-of-truth.
- The dprint output goes to `Extensions → Scripting → Debug Dialog`, filtered by
  module ID.
- Restarting PT picks up the registered `.pts` automatically (its path is saved in
  `~/pt/PT*.conf`).

## Sub-spike 1C — NetconRestAPI (NOT ATTEMPTED)

1B succeeded, so 1C was skipped. If a future need arises (e.g. a use case that benefits
from a REST endpoint independent of the Script Module), open
`$PT_HOME/help/default/NetconRestAPI/index.html` and continue from there.
