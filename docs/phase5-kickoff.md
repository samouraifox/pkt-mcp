# Phase 5 — kickoff for a fresh session

This doc is the **single entry point** for a fresh Claude Code session that
is going to *build the MCP*, not build a topology. The previous session
ran a full stress-test build (NovaCore 2.0, a ~35-device single-conversation
collapse of a 200-device portfolio spec) and that build surfaced a coherent
backlog of MCP-level gaps. Phase 5 works through that backlog.

If you are that fresh session: read this whole file first; everything else
in `docs/` (architecture, phase 1–4) is background. Pick up at the section
labelled **"Phase 5.1 — Cable + module integration"** for the first chunk
of concrete work.

## Where the project stands

End of phase 4.11 (commit `c832d62`). Tool surface is the 12 originals
plus 5 file-patchers (`set_pkt_services`, `set_pkt_dns_records`,
`set_pkt_http_files`, `set_pkt_ap_wireless`, `set_pkt_dhcp_pools`) plus
`set_pkt_zones` (canvas grouping). Bridge protocol stable. Hot-reload
of `api.js` works (`reload_api`); `main.js` edits still need the GUI
Stop/Start cycle.

The repo is unblocked at the *protocol* layer — adding a new op is a
mechanical exercise. What's gated is **what PT lets you reach from
JavaScript** and **what the JS surface exposes vs. requires a file
patch**. Phase 5 mostly extends along those axes.

## Stress-test signal — NovaCore 2.0

Full results: `/home/samouraifox/Work/Projects/portfolio-network/novacore-2/results.md`
(35 devices, 8 PASS / 3 PARTIAL / 1 SKIPPED on Section 17 acceptance).

What the stress test proved:
- The MCP can drive a multi-site enterprise build end-to-end.
- Single-conversation budget tops out around 30-40 devices because every
  `add_device` / `connect` / `configure_interface` is a separate
  round-trip with serial waits. This is the **bulk-ops** gap.
- File-patchers reliably close the "JS surface missing" gaps for
  services and wireless config.
- Several real Cisco features (serial WAN, multi-cable topology,
  wireless host association, working IP phone with CME) couldn't be
  attempted because the *physical assembly* of devices (modules + power
  adapters) isn't reachable from the MCP. This is the **module
  integration** gap.

## Gap inventory (from NovaCore 2.0)

Organized by tier (impact × frequency-hit). Phase 5.1–5.3 below pick from
Tier 1–2. Tier 3+ is backlog the fresh session should be aware of.

### Tier 1 — physical-layer blockers (Phase 5.1)

- **Cable types beyond Ethernet are wired in `CABLE_TYPES` but unproven.**
  `pt-script-module/api.js:70` lists `ETHERNET_STRAIGHT`, `ETHERNET_CROSS`,
  `ETHERNET_ROLL`, `FIBER`, `PHONE`, `CABLE` (DOCSIS), `SERIAL`, `AUTO`,
  `CONSOLE`, `WIRELESS`, `COAXIAL`, `OCTAL`, `CELLULAR`, `USB`, `CUSTOM_IO`.
  NovaCore 2.0 only ever used the first four. `SERIAL`, `COAXIAL`,
  `PHONE`, `FIBER` are required for any realistic WAN/ISP/backbone build.
- **Module configuration is entirely absent.** `add_device(type, name,
  model, x, y)` accepts no slot config — PT picks the default chassis.
  A 2811 boots with no WIC-1T → no serial port → `SERIAL` cable has
  nothing to attach to. A PC boots with no `Linksys-WMP300N` → no
  wireless NIC → `WIRELESS` cable has nothing to attach to. An IP-phone
  boots **without a power adapter** → won't register.
- **Power-on for unpowered devices.** PT phones, DSL/cable modems, some
  endpoints ship with their power module *off* by default. The GUI step
  is dragging the power cord onto the chassis "Physical" tab. No bridge
  op exists.

### Tier 2 — workflow scale-out (Phase 5.2)

- **No bulk ops.** `add_devices([...])`, `connect_many([...])`,
  `configure_interfaces([...])`, `ping_matrix([{src,dst}, ...])`. For
  the NovaCore 2.0 single-shot, ~45 sequential connect calls dominated
  the wall clock. A batch primitive that parallelizes the per-op waits
  (or at least overlaps the boot dialog for routers) would be
  transformational.
- **No port-budget pre-check.** `device_capacity(name)` exposing free
  ports per type. I hit port exhaustion on R-HQ-2 mid-build and had to
  relocate BGP onto MLS-HQ-2.
- **Console auto-logout recovery should be transparent.** `run_commands`
  should detect a user-mode prompt at line 1 and prepend `enable`
  automatically (with empty password if needed). Workaround pattern
  `["", "enable", ...]` was rediscovered three times during the build.

### Tier 2 — verification ergonomics (Phase 5.3)

- **No structured show-command parsers.** Today every verification is a
  text grep against the opaque CLI blob. Targets:
    * `show_ip_route(device)` → `[{prefix, mask, via, source, metric,
      iface}]`
    * `show_ip_ospf_neighbor(device)` → `[{neighbor_id, state, iface}]`
    * `show_vlan_brief(device)` → `[{vlan, name, ports}]`
    * `show_mac_address_table(device)` → `[{vlan, mac, type, port}]`
    * `show_ip_interface_brief(device)` → already easy from
      `get_port_state` but a typed sweep helper is missing
- **OSPF `/30` defaults to broadcast.** DR/BDR election causes 2WAY/DROTHER
  pairs on point-to-point links. Should be auto-set to
  `ip ospf network point-to-point` when the prefix is `/30` or `/31`, or
  expose a `configure_interface(ospf_network=...)` kwarg.
- **`detectIosError` false positives.** Phase 4.7 fixed `% NOTE:` /
  `% Warning:`. Remaining tripper: `% Generating <N> bit RSA keys...`
  (the progress line that precedes a successful keygen). Add to the
  whitelist in `api.js detectIosError`.

### Tier 3 — protocol-coverage gaps (backlog)

- **VRRP missing on PT 9's 3560 IOS image.** Falls back to HSRP. Probe
  other MLS models (3650-24PS) to confirm. If genuinely absent, document
  in CLAUDE.md alongside the existing PT-9 limitation list.
- **DMVPN.** `tunnel mode gre multipoint` + `ip nhrp` family untested.
- **MPLS L3VPN.** `mpls ip`, `vrf definition`, `mpls label protocol`
  untested.
- **Etherchannel/LACP.** `channel-group N mode active`, `interface
  Port-channel N`. Untested.
- **Sub-interface helper for router-on-a-stick.** `configure_interface`
  doesn't model sub-interfaces today. A `configure_subinterface(dev,
  parent, dot1q_vlan, ip, mask)` helper would close inter-VLAN routing.
- **CME source-address on a Loopback.** Document the
  `ip source-address <loopback-ip> port 2000` workaround in CLAUDE.md
  for the SVI-conflict case.
- **Wireless association from the client side.** `set_pkt_ap_wireless`
  sets the SSID on the AP; making a PC actually associate is GUI-only.
  Likely needs a probe of PT's wireless-client JS surface.

### Tier 4 — file-patcher extensions (backlog)

- POP3/SMTP mailbox accounts (`tools/pkt_services.py` neighbour)
- RADIUS users + NAS clients
- TFTP file content
- HTTP **new** file creation (needs `FILE_NUMBER`/`FILE_COUNTER`
  bookkeeping — `set_pkt_http_files` today only modifies existing
  `<FILE>` blocks)
- More wireless auth modes: WEP, WPA-PSK, WPA2-Enterprise. Capture
  the XML by hand-configuring in PT, diff, extend `_WIRELESS_AUTH_CODES`
  in `tools/pkt_services.py`.

---

## Phase 5.1 — Cable + module integration

**Goal.** Make every cable type in `CABLE_TYPES` actually usable, by
exposing PT's physical-assembly API (module install) and power-on
through the bridge. After 5.1 lands, a fresh session can build a
serial-WAN topology, a wireless-host topology, and a working IP-phone
topology from MCP calls alone — no GUI assembly step.

**Scope.**
- IN: serial WIC (WIC-1T, HWIC-2T), wireless NIC (Linksys-WMP300N for
  PC/Laptop), phone power adapter, DSL/cable modem power adapter, plus
  whatever PT exposes that's adjacent and cheap (probe will tell).
- OUT: redundant power supplies (HA demo nice-to-have), supervisor
  swaps on multilayer chassis, non-Cisco modules.

### Step 1 — Probe PT's module API surface

Pattern is identical to phase 2 (`docs/phase2-api-map.md`). Use a probe
script in `probes/` that enumerates the JS surface on a freshly added
device:

```js
// rough sketch — refine per phase-2 method
var dev = net().getDevice(uuid);
var keys = [];
for (var k in dev) keys.push(k);
log(keys.filter(function(k){return /module|card|wic|slot|power|adapter/i.test(k);}));
```

Look for: `addModule`, `getModuleList`, `getSlots`, `installModule`,
`getPhysicalModules`, `setPowerState`, `setOn`, `togglePower`,
`getPowerCord`, etc. Also probe `lw()` and `ipc.appWindow()` (the
top-level workspace handles often own the install operations even when
the device itself doesn't).

Module *model strings* are likely separate from device model strings —
PT internally has things like `PT-ROUTER-NM-1CGE` or `WIC-1T`. Enumerate
those by inspecting an existing device that was hand-assembled in the
GUI.

Phase 2-style output: write findings to a new
`docs/phase5.1-module-api.md` parallel to `docs/phase2-api-map.md`.

### Step 2 — Wire two ops through the bridge

Both ops follow the existing pattern in `pt-script-module/api.js`:
typed args, `requireArg`, structured return, `err("PT_REJECTED", ...)`
on PT-side failure.

**`op_add_module`** — `(device_name, slot, module_model) → {ok, slot,
module_model}`. After install, ports added by the module should be
queryable via `list_devices`/`get_port_state` immediately (or after a
short pollUntil if PT needs a tick to populate them).

**`op_power_device`** — `(device_name, on: bool) → {ok, on}`. For
phones / modems that boot off by default. Some devices may already be
on; the op should be idempotent.

Wire both through `tools/pkt_bridge.py` (typed client) and expose them
in `pkt_mcp/server.py` as `add_module` and `power_device`.

### Step 3 — Optional extension to `add_device`

Once `add_module` works, consider adding an optional `modules` kwarg
to `add_device`:

```python
add_device(
    type="ROUTER", name="R1", model="2811", x=100, y=100,
    modules={"slot0/0": "WIC-1T", "slot0/1": "WIC-2T"},
    power_on=True,
)
```

So a fresh session can describe a fully-assembled, powered-on device in
a single call. The implementation just sequences `addDevice` →
`addModule` per slot → `setPowerState`. Defer until 5.1 step 2 has
landed and you've seen 2-3 real builds use the new ops.

### Step 4 — Update CLAUDE.md

After the ops are wired, add to the "PT-specific gotchas" section:
- Which models *require* which modules for which cable types
  (2811 + WIC-1T → SERIAL; PC + WMP300N → WIRELESS; etc.)
- The full cable-type table — which `CABLE_TYPES` values are proven vs.
  speculative
- Power-on requirements per device type

### Acceptance — Phase 5.1 is done when…

1. A probe-only script in `probes/` lands a usable `docs/phase5.1-module-api.md`
   with a JS surface map identical in form to `phase2-api-map.md`.
2. `add_module(R1, "slot0/0", "WIC-1T")` adds the module and makes
   `Serial0/0/0` (or PT's actual port name) visible in
   `get_port_state`.
3. `connect(R1, "Serial0/0/0", R2, "Serial0/0/0", "SERIAL")` succeeds,
   clock-rate set on the DCE side via `run_commands`, OSPF/EIGRP comes
   up across the link.
4. A PC with `WMP300N` installed wirelessly associates with an AP whose
   SSID was set by `set_pkt_ap_wireless`, and `ping` from the PC to
   a wired host on the same VLAN returns `lost=0`.
5. A `7960` IP phone, `power_device(phone, on=True)`-ed, on a switch
   port voice-VLAN'd to a CME 2811, **registers** (i.e. shows a number
   on the phone display and `show ephone` on the router lists it as
   registered).

If any of 2–5 reveal a deeper PT-side limitation that the JS API can't
work around (e.g. "module ports show up but never link"), document it
the same way phase 4.7+ documented the file-patch fallbacks — i.e.,
treat the file-patch path as a legitimate alternative if PT's JS surface
is structurally missing the setter.

---

## Phase 5.2 — Bulk operations (sketch)

**Goal.** Make a 200-device single-session build feasible. NovaCore 2.0
spent the majority of its conversation budget on per-device serial
waits; batching collapses that to N-parallel-then-join.

**Candidate ops.** All accept a list and return a list-aligned result.
- `op_add_devices` — fan out `addDevice` over PT's `setTimeout` scheduler,
  collect uuids, run the boot-dialog handshake **in parallel** for all
  routers (single 30 s wait, not N × 30 s). Returns `[{ok, uuid, name},
  {error, ...}, ...]`.
- `op_connect_many` — sequential at the PT side (the JS bridge can only
  hold one op in flight) but a single round-trip from MCP → PT mailbox
  → JS, vs. N round-trips today.
- `op_configure_interfaces` — same pattern. The IOS interactions are
  inherently sequential per device but can interleave across devices.
- `op_ping_matrix` — `[{from, to}, ...] → [{ok, lost, latency_ms}, ...]`.
  Per-row sequential at PT (one CLI at a time per device) but rows for
  *different* source devices can interleave.

**Open design question.** The current bridge protocol is single-op-at-a-
time. Bulk ops can either:
- Be implemented entirely in JS (a single op_X handler that loops),
  trading off no Python-side concurrency but minimal protocol change.
- Be implemented as protocol-level batching (one mailbox envelope holds
  N ops, results returned in order), which is more invasive but more
  reusable.

Prefer option 1 for 5.2 — incremental, low-risk. Revisit option 2 if
5.2 turns out not to be enough.

**Acceptance.** A 100-device topology builds in under 5 minutes of wall
clock from MCP calls, including verification ping sweep.

---

## Phase 5.3 — Show-command parsers (sketch)

**Goal.** Turn verification from "text grep with `Lost = 0` substring
match" into typed assertions.

**Parser placement.** Two options:
- Python-side in `tools/pkt_bridge.py` (or a new
  `tools/pkt_show_parsers.py`). Pro: easier to test, easier to iterate,
  Python's `re` is more pleasant than QtScript.
- JS-side as new ops (`op_show_ip_route`, etc.). Pro: one round-trip
  per query; Con: parser bugs require `reload_api` cycles.

Prefer Python-side — show output is deterministic-enough and the
test corpus (capture once, regression-test forever) lives naturally in
`tests/`.

**Initial six parsers.**
1. `show ip route` — IPv4 routing table
2. `show ipv6 route` — IPv6 routing table
3. `show ip ospf neighbor` — OSPF adjacencies + states
4. `show ip eigrp neighbors` — EIGRP adjacencies
5. `show ip bgp summary` — BGP peer states
6. `show vlan brief` — VLAN-to-port map on switches

Each ships with a regression fixture in `tests/fixtures/show_*.txt`
captured from a real PT session, asserting the parser handles
multi-line continuations, trailing blanks, and the prompt suffix.

**Acceptance.** A test in `tests/` that takes a captured `show ip ospf
neighbor` output and produces `[{neighbor_id, state, dead_time, addr,
iface}]` with no manual fixup. Three real fixtures: full mesh,
single-neighbor, no-neighbors.

---

## Out of scope / deferred to Phase 5.4+

Tier 3–4 from the gap inventory above. Not blocked, just lower priority
than 5.1–5.3. Order to attack them later:
1. Sub-interface helper (`configure_subinterface`) — easy and unblocks
   inter-VLAN routing on routers.
2. Etherchannel primitive — moderate complexity, unblocks HA demos.
3. VRRP / DMVPN / MPLS investigation — depends on PT 9 actually
   supporting them; could be a fast "documented as unsupported"
   outcome.
4. POP3/SMTP/RADIUS/TFTP file-patchers — straightforward extension of
   `tools/pkt_services.py`, gated on demand.
5. HTTP new-file creation — only worth doing when a build needs >4
   files on a Server-PT.

---

## Fresh session, start here

1. Read this file top-to-bottom (you just did).
2. Skim `docs/phase4-mcp.md` for the tool-surface vocabulary and
   `docs/phase2-api-map.md` for the JS-probe pattern you'll mirror in
   Phase 5.1 Step 1.
3. Open `pt-script-module/api.js`. Find the `CABLE_TYPES` block
   (line ~70) and the existing `op_add_device` handler (line ~263).
   That's the shape of what you'll be extending.
4. Open `pkt_mcp/server.py`. The `@mcp.tool()` decorators around lines
   188 (`add_device`) and 285 (`connect`) are the templates for the
   new `add_module` / `power_device` tools.
5. Start at **Phase 5.1 Step 1** — write the probe, dump findings to
   `docs/phase5.1-module-api.md`. Don't write any new ops until the
   probe is in.
6. Open PT 9 with the Script Module bundle loaded (`reload_api`
   available). You'll need the live PT process to probe.

When 5.1 lands cleanly: commit with the existing `phase N.M: <title>`
format (see `git log`), push, then start Phase 5.2 in a fresh
conversation using the same pattern.
