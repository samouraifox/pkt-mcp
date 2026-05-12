# Phase 5.1 — Module + power JS API map

Running record of PT's physical-assembly JS surface, parallel to
`docs/phase2-api-map.md`. Step 1 of Phase 5.1 — surface mapping only;
the bridge ops (`add_module`, `power_device`) go in Step 2 once this is
nailed down. Append-only.

## Source of truth

PT ships the C++ Doxygen for the IPC API under `$PT_HOME/help/default/
IpcAPI/`. The Phase 5.1 surface was reconstructed from these pages and
verified live via two probes (`probes/phase51_module_probe.js` and
`probes/phase51_module_probe2.js`).

Key Doxygen pages used:
- `class_i_p_c.html` — `ipc.hardwareFactory() → HardwareFactory`
- `class_hardware_factory.html` — `modules() → ModuleFactory`,
  `devices() → DeviceFactory`
- `class_module_factory.html` — global catalog accessors
- `class_module.html` — per-Module slot/port/child tree
- `class_module_descriptor.html` — module-model metadata
- `class_device.html` — `getRootModule()`, `getSupportedModule()`,
  `setPower(bool)` / `getPower()`, `addModule(...)`, `removeModule(...)`
- `class_host_port.html` — port-level `setPower(bool)` / `getPower()` /
  `isPowerOn()`

## M1 — Global module catalog (`ModuleFactory`)

**Status:** done. 199 modules confirmed live in PT 9.0.0.

The catalog is reachable through:

```js
var moduleFactory = ipc.hardwareFactory().modules();
var n = moduleFactory.getAvailableModuleCount();         // 199 in PT 9.0.0
for (var i = 0; i < n; i++) {
    var md = moduleFactory.getAvailableModuleAt(i);      // ModuleDescriptor
    md.getModel();        // e.g. "WIC-1T"
    md.getType();         // ModuleType int (see table below)
    md.getSlotCount();    // for modules that themselves accept sub-modules
    md.getSlotTypeAt(0);  // ModuleType ints of those sub-slots
}
```

Also useful:

| call | returns | use |
|---|---|---|
| `moduleFactory.getAvailableModuleForTypeCount(typeInt)` | `int` | size of the filtered list |
| `moduleFactory.getAvailableModuleForTypeAt(typeInt, i)` | `ModuleDescriptor` | i-th module of that type |
| `moduleFactory.getDescriptor(typeInt, model)` | `ModuleDescriptor` \| null | lookup by (type, model) pair |
| `moduleFactory.addModuleModel(typeInt, model)` | `ModuleDescriptor` | factory mutator — untested, not needed for Phase 5.1 |

### ModuleType integer table (deduced from runtime probe)

The `ModuleType` enum is an opaque int. Phase 5.1 enumerated which int
holds which module model strings. The high-confidence assignments:

| int | label (proposed) | example models |
|---:|---|---|
| 1 | NM (Cisco Network Module, full-width) | `NM-1E`, `NM-1FE-TX`, `NM-2W`, `NM-ESW-161`, `NM-Cover` |
| 2 | WIC/HWIC/NIM (small-form-factor) | `WIC-1T`, `WIC-2T`, `HWIC-2T`, `HWIC-4ESW`, `HWIC-8A`, `HWIC-1GE-SFP`, `HWIC-AP-AG-B`, `NIM-2T`, `NIM-ES2-4`, `NIM-Cover`, `WIC-Cover`, `1240-Cellular` |
| 3 | PT-ROUTER-NM (generic PT router modules) | `PT-ROUTER-NM-1CGE`, `PT-ROUTER-NM-1S`, `P-LTEA18-GL`, `P-5GS6-GL` |
| 4 | PT-SWITCH-NM + power supplies (used internally) | `PT-SWITCH-NM-1CGE`, `AC-POWER-SUPPLY`, `9320-AC-POWER-SUPPLY`, `POWER-COVER-PLATE` |
| 5 | PT-CLOUD-NM | `PT-CLOUD-NM-1CE`, `PT-CLOUD-NM-1CX` (cloud uplinks) |
| 6 | PT-REPEATER-NM (AP/repeater modules) | `PT-REPEATER-NM-1CGE`, `PT-REPEATER-NM-1FGE`, `PT-REPEATER-NM-COVER` |
| 7 | PT-HOST-NM (PC/Server NICs, incl. Linksys) | `Linksys-WMP300N`, `PT-HOST-NM-1CGE`, `PT-HOST-NM-1W`, `PT-HOST-NM-1W-AC`, `PT-HOST-NM-5G`, `PT-HOST-NM-COVER` |
| 8 | PT-MODEM-NM (DSL/cable modem uplinks) | `PT-MODEM-NM-1CE`, `PT-MODEM-NM-1CFE`, `PT-MODEM-NM-1CGE` |
| 9 | PT-LAPTOP-NM (laptop wireless NICs, incl. Linksys) | `Linksys-WPC300N`, `PT-LAPTOP-NM-1W-AC`, `PT-LAPTOP-NM-5G` |
| 10 | PT-CLOUD-NM-1CX (single member; coax cloud uplink) | `PT-CLOUD-NM-1CX` |
| 11 | IP-phone power adapter | `IP_PHONE_POWER_ADAPTER` |
| 12 | PT-TABLETPC-NM | `PT-TABLETPC-NM-1W-AC`, `Linksys-WPC300N` |
| 13 | PT-PDA-NM (smartphone NICs) | `PT-PDA-NM-1W-AC`, `Linksys-WPC300N` |
| 14 | PT-WIRELESSENDDEVICE-NM (IoT wireless) | `PT-WIRELESSENDDEVICE-NM-1W-AC`, `Linksys-WPC300N` |
| 15 | PT-WIREDENDDEVICE-NM (IoT wired) | `PT-WIREDENDDEVICE-NM-1CGE`, `Linksys-WPC300N` |
| 16 | PC peripherals (audio) | `PT-HEADPHONE`, `PT-MICROPHONE` |
| 18 | Chassis "host" slot (the device itself) — see slot-tree note | (no installable models; structural) |
| 19 | ASA cover | `ASA-Cover` |
| 21 | PT-CELL-NM | `PT-CELL-NM-1CX`, `PT-CELL-NM-3G/4G` |
| 22 | PT-IOT-NM (small) | `PT-IOT-NM-1CGE`, `PT-IOT-NM-1W` |
| 23 | PT-IOT-NM (full) | `PT-IOT-NM-1CGE`, `PT-IOT-NM-1FGE`, `PT-IOT-NM-1W-AC`, `PT-IOT-NM-5G` |
| 26 | PT-IOT-CUSTOM-IO | `PT-IOT-CUSTOM-IO` |
| 27 | PT-IOT-POWER-ADAPTER | `PT-IOT-POWER-ADAPTER` |
| 28 | PT-UNV-PWR-ADAPTER | `PT-UNV-PWR-ADAPTER` |
| 29 | Industrial / rugged power | `PWR-RGD-AC-DC`, `PWR_IE50W_AC_L`, `ROUTER-ADAPTER` |
| 30 | SFP / GLC fiber transceivers | `GLC-T`, `GLC-LH-SMD`, `GLC-LX-SM-RGD`, `GLC-SX-MM-RGD`, `GLC-GE-100FX`, `GLC-FE-100FX-RGD` |
| 31 | Access-point power adapter (model present in catalog but no probed device exposes a type-31 slot — see M3 note) | `ACCESS_POINT_POWER_ADAPTER` |
| 32 | BUILTIN (non-removable chassis-fixed modules) | `ISR4321-BUILTIN`, `ISR4331-BUILTIN`, `C3650-BUILTIN`, `C9320-BUILTIN`, `IR1101-BUILTIN`, `IE3400-SFP-BUILTIN`, etc. |
| 34 | Meraki power | `MERAKI-POWER-ADAPTER` |
| 36 | ISA DC adapter A | `ISA-DC-POWER-ADAPTER-A` |
| 37 | ISA DC adapter B | `ISA-DC-POWER-ADAPTER-B` |

Type 17, 20, 24, 25, 33, 35 had zero members in the catalog at probe
time. If a future use-case needs a missing type, extend the probe with
the same enumeration loop.

## M2 — Per-device slot tree (`Device.getRootModule()`)

**Status:** done for 14 device kinds (the Phase 4.7 catalog + ASA + MLS).

`Device.getRootModule()` returns the **root Module** — a structural
container whose slots hold sub-Modules (the chassis, expansion bays,
WIC sub-slots, …). Slot indices, types, and occupancy can be walked
with the `class_module.html` API:

```js
var root = dev.getRootModule();
root.getSlotCount();                // top-level slots on the chassis
root.getSlotTypeAt(i);              // ModuleType int of slot i
root.getModuleAt(i);                // child Module or null (empty slot)
root.getPortCount();                // ports owned directly by this Module
root.getPortAt(j);                  // → Port (same Port class used in M3)
root.addModuleAt(model_str, i);     // install — see M3
root.removeModuleAt(i);             // uninstall
root.getSlotPath();                 // structural path string ("", "0", "0/0", "0/1")
```

### Observed shapes (probe 1)

| Device | root slot types | chassis (slot 0 child) sub-slots | default ports |
|---|---|---|---|
| `ROUTER 2811` | `[18, 1]` | `[2, 2, 2, 2]` (4 WIC slots) | `FastEthernet0/0`, `0/1` |
| `ROUTER 2911` | `[18]` | `[2, 2, 2, 2]` (4 WIC/HWIC slots) | `GigabitEthernet0/0..0/2` |
| `ROUTER 1841` | `[18]` | `[2, 2]` (2 WIC slots) | `FastEthernet0/0`, `0/1` |
| `ROUTER ISR4321` | `[18]` | `[32, 2, 2]` (1 BUILTIN + 2 NIM) | `GigabitEthernet0/0/0`, `0/0/1` |
| `SWITCH 2960-24TT` | `[18]` | `[]` (no expansion) | 24× FastEthernet + 2× GigabitEthernet uplinks |
| `MLS 3560-24PS` | `[18]` | `[]` (no expansion) | 24× FE + 2× GE uplinks |
| `PC PC-PT` | `[7, 18]` | (slot 0 is wireless NIC, default-filled; slot 1 is host chassis with peripheral sub-slots `[16, 16]`) | `FastEthernet0`, `Bluetooth` |
| `LAPTOP Laptop-PT` | `[9, 18]` | (slot 0 wireless NIC default-filled; slot 1 chassis with `[16, 16]`) | `FastEthernet0`, `Bluetooth` |
| `SERVER Server-PT` | `[7, 7]` | (slot 0 default-filled NIC; slot 1 empty) | `FastEthernet0` |
| `IP_PHONE 7960` | `[18]` | `[11]` (power-adapter slot, empty by default!) | `Vlan1`, `Switch`, `PC` |
| `AP AccessPoint-PT` | `[6, 18]` | (both slots default-filled; AP has no power-adapter slot at this level) | `Port 0`, `Port 1` |
| `DSL_MODEM DSL-Modem-PT` | `[18, 8]` | (slot 0 default Ethernet, slot 1 modem) | `Port 0`, `Port 1` |
| `CABLE_MODEM Cable-Modem-PT` | `[18, 8]` | identical layout to DSL | `Port 0`, `Port 1` |
| `ASA 5506-X` | `[18, 18]` | (only `ASA-Cover` installable — no real expansion) | 8× Gi + Management |

The recurring root pattern: **slot type 18 is the chassis self-slot,
already filled with a sub-Module the moment `addDevice` returns.** The
*expansion* slots (WICs / wireless NIC / power adapter / etc.) live
inside that chassis child, not at the root. M3 makes this concrete.

### `Device.getSupportedModule()` quirk

`getSupportedModule()` returns a `vector<string>` (mapped by Qt-Script
to a JS array of strings) of *acceptable module models for this
device*. Each entry is **`model:image_path<description>`** concatenated
into one string — e.g. `"WIC-1T:../art/PhysicalView/gModuleNM-WIC-1T.png
The WIC-1T provides a single port serial connection ..."`.

Parse by splitting on the first `:` and taking the head:

```python
parsed = [s.split(":", 1)[0] for s in dev.getSupportedModule()]
```

Probed lists (model names only):

- **2811**: GLC-LH-SMD, HWIC-1GE-SFP, HWIC-2T, HWIC-4ESW, HWIC-8A,
  HWIC-AP-AG-B, NM-1E, NM-1E2W, NM-1FE-FX, NM-1FE-TX, NM-1FE2W,
  NM-2E2W, NM-2FE2W, NM-2W, NM-4A/S, NM-4E, NM-8A/S, NM-8AM, NM-Cover,
  NM-ESW-161, WIC-1AM, WIC-1ENET, WIC-1T, WIC-2AM, WIC-2T, WIC-Cover
  *(superset — accepts both legacy NM and modern WIC/HWIC; the "Swiss-
  army knife")*
- **2911**: GLC-LH-SMD, HWIC-1GE-SFP, HWIC-2T, HWIC-4ESW, HWIC-8A,
  WIC-Cover *(HWIC-only chassis)*
- **1841**: GLC-LH-SMD, HWIC-1GE-SFP, HWIC-2T, HWIC-4ESW, HWIC-8A,
  HWIC-AP-AG-B, WIC-1AM, WIC-1ENET, WIC-1T, WIC-2AM, WIC-2T, WIC-Cover
- **ISR4321**: GLC-GE-100FX, GLC-LH-SMD, NIM-2T, NIM-Cover, NIM-ES2-4
  *(NIM-only — modern ISR)*
- **2960-24TT, 3560-24PS**: `[]` *(no installable modules at JS layer)*
- **PC-PT**: Linksys-WMP300N, PT-HEADPHONE, PT-HOST-NM-1CE/CFE/CGE,
  PT-HOST-NM-1FFE(-SM)/1FGE(-SM), PT-HOST-NM-1W/-1W-A/-1W-AC,
  PT-HOST-NM-3G/4G, PT-HOST-NM-5G, PT-HOST-NM-COVER, PT-MICROPHONE
- **Laptop-PT**: Linksys-WPC300N + the PT-LAPTOP-NM-* mirror set,
  PT-HEADPHONE, PT-MICROPHONE
- **Server-PT**: same shape as PC's NM family (no audio peripherals)
- **IP_PHONE 7960**: `[IP_PHONE_POWER_ADAPTER]` — exactly one entry
- **AccessPoint-PT**: 8× `PT-REPEATER-NM-*` family
- **DSL-Modem-PT / Cable-Modem-PT**: 3× `PT-MODEM-NM-*`
- **ASA 5506-X**: `[ASA-Cover]` only

## M3 — Install + remove (`Module.addModuleAt` / `removeModuleAt`)

**Status:** done. Round-tripped install + remove on routers (2811,
2911, ISR4321), PC, Laptop, IP phone.

### The critical structural rule

`addModuleAt(model, slot_idx)` lives on `Module`, **not Device**. It
must be called on whichever Module owns the target slot. For WIC/HWIC
slots that's the *chassis child*, not the root:

```js
// WIC-1T into 2811 slot 0:
var dev = net().getDevice(uuid);
var chassis = dev.getRootModule().getModuleAt(0);   // ← NOT getRootModule() directly
chassis.addModuleAt("WIC-1T", 0);                   // → true
// Port "Serial0/0/0" appears immediately on dev.getPort()/.getPortAt().
```

For the wireless NIC slot on PC/Laptop, the slot is at the *root*
(slot 0, type 7 or 9) and ships **already occupied by a default cover
or generic module**. Remove first, then install:

```js
var root = pc.getRootModule();
root.removeModuleAt(0);                       // drop the default placeholder
root.addModuleAt("Linksys-WMP300N", 0);       // → true. "Wireless0" port appears.
```

### Verified installs

| Device | model | container | slot | new port(s) |
|---|---|---|---|---|
| 2811 | `WIC-1T` | `root.getModuleAt(0)` | 0 | `Serial0/0/0` |
| 2811 | `WIC-2T` | `root.getModuleAt(0)` | 0 | `Serial0/0/0`, `Serial0/0/1` |
| 2911 | `HWIC-2T` | `root.getModuleAt(0)` | 0 | `Serial0/0/0`, `Serial0/0/1` |
| ISR4321 | `NIM-2T` | `root.getModuleAt(0)` | 1 (slot 0 is built-in) | `Serial0/1/0`, `Serial0/1/1` |
| PC-PT | `Linksys-WMP300N` | root | 0 (after `removeModuleAt(0)`) | `Wireless0` |
| Laptop-PT | `Linksys-WPC300N` | root | 0 (after `removeModuleAt(0)`) | `Wireless0` |
| 7960 | `IP_PHONE_POWER_ADAPTER` | `root.getModuleAt(0)` | 0 | *(no new port — slot 11 module just powers the chassis)* |

### Port naming after install

PT names new ports by the slot path. `WIC-1T` in 2811 chassis slot 0
yields `Serial0/0/0` (chassis 0, expansion 0, port 0). `NIM-2T` in
ISR4321 slot 1 yields `Serial0/1/0..1`. `Linksys-WMP300N` always
yields `Wireless0` (host wireless NIC is single-port).

### `removeModuleAt` is the inverse

```js
chassis.removeModuleAt(0);   // Serial0/0/0 disappears from getPortAt()
```

Probe trial confirmed: port list collapsed back to pre-install state.

### `Module.getSlotPath()` — debugging aid

`""` for the root, `"0"` for the chassis child, `"0/0"` for a module
installed in chassis slot 0, `"0/1"` for slot 1, etc. Mirrors PT's
internal CLI naming exactly. Useful when reporting errors back to the
caller.

### Device-level `addModule` / `removeModule` (skipped)

`Device.addModule(string, ModuleType, string)` and
`Device.removeModule(string)` exist (Doxygen signature), but the
working path is via the right `Module` instance with `addModuleAt`.
The Device-level wrappers presumably accept a slot-path string but
weren't probed — `Module.addModuleAt` is sufficient and unambiguous.

## M4 — Power control

### Device-level: `Device.setPower(bool)` / `getPower()`

**Status:** done. Round-tripped on 2811, PC, Laptop, Server, 7960.

```js
dev.getPower();        // → true (default after addDevice)
dev.setPower(false);   // → undefined; getPower() then returns false
dev.setPower(true);    // → undefined; getPower() returns true again
```

All five probed devices started `true`. Setting `false` and reading
back showed `false`; `true` restored `true`. No side effects observed
on the JS surface (the device persists, modules stay installed). The
canvas presumably renders an unpowered chassis but the bridge layer
just sees the boolean.

### Per-port: `HostPort.setPower(bool)` / `getPower()` / `isPowerOn()`

**Status:** done. Probed on `7960` (3 ports) and `PC-PT` (2 ports).

```js
var p = dev.getPort("FastEthernet0");
p.getPower();      // initial state
p.isPowerOn();     // equivalent boolean
p.setPower(false); // turn the port off (admin-down-ish at the physical layer)
```

Observed defaults:

| device | port | `getPower()` | meaning |
|---|---|:--:|---|
| 7960 | `Vlan1` | `false` | virtual port, always off |
| 7960 | `Switch` | `true` | upstream Ethernet to switch |
| 7960 | `PC` | `true` | downstream daisy-chain |
| PC-PT | `FastEthernet0` | `true` | host NIC |
| PC-PT | `Bluetooth` | `false` | radio off by default |

The phone's `Vlan1` port reads `false` even though the phone itself is
powered — that's a property of the virtual port type, not a power
issue.

### What the catalog suggests for "power adapter" support

Five distinct ModuleType ints look like power-supply slots in the
catalog (11, 27, 28, 31, 34, 36, 37). Of these, only **11** (phone)
exposed itself as a real slot on a device we probed; the AP's
`ACCESS_POINT_POWER_ADAPTER` (type 31) is in the catalog but
`AccessPoint-PT`'s root slot types are `[6, 18]` — there's no type-31
slot to install it into. Two possibilities, untested:

1. PT 9 dropped AP power-adapter support, leaving the catalog model
   present but orphaned. AP power is then controlled by
   `Device.setPower(bool)` alone.
2. A different AP model exposes the slot — e.g. `AccessPoint-PT-A`,
   `AccessPoint-PT-AC`. Probe these models in Phase 5.1 Step 2 if a
   build needs an AP power adapter, otherwise treat it as a structural
   limit and `setPower(true)` is enough.

For phones, the actionable rule is:

> `7960`'s `root.getModuleAt(0)` has one empty slot of type 11. Install
> `IP_PHONE_POWER_ADAPTER` there before the phone can register with
> CME. After install, `getPortCount()` is unchanged (no new port) but
> the phone is now "powered" in PT's voice-stack sense.

This is the Phase 5.1 acceptance criterion 5 for IP phone registration.

## M5 — Cleanup quirks

### `LogicalWorkspace.deleteDevice` does NOT exist

The phase 4 `op_delete_device` handler in `api.js` (line 510-517) is
defensive — it tries `lw.deleteDevice(name)` first, then falls back to
`lw.removeDevice(uuid)`. In PT 9.0.0, only the second path works:

```js
var lw = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace();
// methods matching /delete|remove|destroy/:
//   ["deleteLink", "removeCanvasItem", "removeCluster",
//    "removeDevice", "removeRemoteNetwork", "removeTextPopup"]
```

So **`removeDevice` is the right primitive**, and it accepts either a
uuid or (per the existing `op_delete_device` fallback) a name. The
existing handler already does the right thing — no code change needed.

### `Module.removeModuleAt` doesn't free the slot for ModuleType==18

The root self-slot (type 18, the chassis) cannot be removed — calling
`removeModuleAt(0)` on a device whose slot 0 is the chassis would
disassemble the device itself. PT probably no-ops or rejects this.
Phase 5.1 Step 2's `op_add_module` must therefore validate the target
slot type before removal: only remove placeholder modules in slots
matching the module-type we're about to install.

## Open questions for Phase 5.1 Step 2

1. **AP power-adapter slot** — does any AP variant model expose a
   type-31 slot, or is `setPower(bool)` the only path? Probe
   `AccessPoint-PT-A`, `AccessPoint-PT-AC`, `AccessPoint-PT-N` before
   exposing a phone-style power op for APs.
2. **Existing-occupant policy.** For `op_add_module(R1, slot=0,
   model="WIC-1T")`, what happens if slot 0 already holds a WIC-2T?
   Phase 5.1 Step 2 decision: refuse with `PT_REJECTED` (caller
   removes first), or auto-remove. Recommended: refuse, with the
   occupant's model surfaced in `error_data` so the caller can decide.
3. **Slot path vs. nested index.** `op_add_module` API surface
   options:
     a. `(device, chassis_slot, model)` — caller passes the *root* slot
        and we recurse to `root.getModuleAt(chassis_slot)`. Maps cleanly
        to "I want WIC-1T in chassis slot 0 of R1."
     b. `(device, slot_path, model)` — caller passes `"0/0"` (the
        `getSlotPath()` string). More flexible but more error-prone.
     c. `(device, slot_type_int, model)` — server-side picks the
        first empty slot of the right type. Ergonomic but ambiguous
        when multiple WIC slots are empty.
   Recommended: (a) is the primary surface; (c) as a convenience
   wrapper for callers who don't care which WIC bay.
4. **Built-in (type 32) module visibility.** ISR4321/4331 ship with
   `ISR4321-BUILTIN`/`ISR4331-BUILTIN` already installed at chassis
   slot 0. The probe walked this OK; just document that built-in
   modules are read-only — `removeModuleAt` shouldn't be exposed for
   them in Step 2's wrapper.

## Acceptance — Phase 5.1 Step 1 closes here

- [x] Probe lands a structured JS-surface report (`probes/phase51_probe_result.json`, 2279 lines).
- [x] Iteration 2 lands install round-trips (`probes/phase51_probe2_result.json`).
- [x] Doxygen-confirmed APIs (`hardwareFactory()`, `modules()`, `getRootModule`,
      `addModuleAt`, `setPower`) are runtime-verified.
- [x] Module catalog enumerated (199 entries, by ModuleType int).
- [x] Per-device slot trees mapped for the 14 device kinds Phase 4.7 wired.
- [x] Install verified on routers, PC, Laptop, IP phone — new ports observed
      with the expected `Serial0/<chassis>/<slot>/<port>` and `Wireless0`
      naming.
- [x] `removeModuleAt` round-trip confirms install reversibility.
- [x] Power on/off round-tripped at device and host-port levels.

Phase 5.1 Step 2 (the `add_module` + `power_device` bridge ops) starts
from this map. No `api.js` or `pkt_mcp/server.py` changes were made in
Step 1.
