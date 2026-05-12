# CLAUDE.md

Networking + Packet Tracer knowledge for sessions in this repo. The repo's
*infrastructure* (architecture, MCP wiring, Bridge protocol) lives in
`docs/`; this file is the *operating manual* for actually building good
topologies through it.

## How this project works

`pkt-mcp` is an MCP server that drives Cisco Packet Tracer 9.0 from Claude.
The plumbing chain is **Claude → MCP (`pkt_mcp/server.py`) → typed Bridge
client (`tools/pkt_bridge.py`) → file mailbox (`/tmp/pkt-mcp/`) → Script
Module inside PT (`pt-script-module/{main,api}.js`) → PT canvas**. The MCP
tools are defined in `pkt_mcp/server.py`; their docstrings are the
authoritative API reference. For depth on any layer, see `docs/`:
`architecture.md`, `phase1-investigation.md` (Java path, dead end),
`phase2-api-map.md` (PT JS API surface), `phase3-protocol.md` (typed
op/args wire), `phase4-mcp.md` (this MCP layer).

Out-of-band: `tools/pkt_services.py` + vendored `tools/unpacket/` (MIT,
Punkcake21/Unpacket) handle Server-PT service toggles by decrypting,
patching, and re-encrypting saved .pkt files — needed because the
service classes in PT aren't reachable from the JS bridge. See `set_pkt_services` tool docstring for usage.

## Defaults to apply automatically

When the spec doesn't say otherwise:

- **Addressing:** RFC1918 only (`10.0.0.0/8`, `172.16.0.0/12`,
  `192.168.0.0/16`). Pick `192.168.X.0/24` for small lab demos by default.
- **Hostnames:** `hostname <name>` matching the device name on the canvas
  (R1 → `hostname R1`).
- **Privileged exec auth:** `enable secret <strong>` (never
  `enable password`, which stores plaintext).
- **Other passwords:** `service password-encryption` after setting line
  passwords / usernames.
- **Remote management:** SSH only. `ip domain-name <lab>.local`,
  `crypto key generate rsa modulus 2048`, `username admin secret <pw>`,
  `line vty 0 4` → `transport input ssh` + `login local`.
  Never leave `transport input telnet` or `transport input all`.
- **Console hygiene:** `line console 0` → `logging synchronous`,
  `exec-timeout 10 0`, `login local`.
- **DNS hang prevention:** `no ip domain-lookup` on every IOS device
  (kills the multi-second "translating ..." pause on a typo).
- **Banner:** `banner motd # Authorized access only — disconnect if not
  authorized. #`. Don't include the literal word `cisco` anywhere in
  passwords or banners.
- **Interface descriptions:** Every configured interface gets
  `description <to-far-end>` (e.g. `description to SW1 Fa0/1`). Makes
  `show ip interface brief` and `summarize_topology` self-explanatory.
- **Hosts:** Static IP + gateway by default. Only use DHCP when the spec
  asks for it or when there's a DHCP server on the topology.

## Build order rules

Build and **verify** in this order. Don't move to step N+1 until step N
verifies clean.

1. **Devices.** `add_device` everything the spec lists.
2. **Links.** `connect` ports per the topology diagram. Use `auto_portfast`
   default (it kicks in for switch↔host links automatically).
3. **L2/L3 addressing.** `configure_interface` on routers/switches with
   SVIs, `configure_host` on hosts. Bring interfaces up
   (`no_shutdown=True`).
4. **L2 / single-subnet ping verify.** Use `ping` (success = `lost=0`)
   between every pair on the same broadcast domain. Don't proceed if any
   adjacent ping fails.
5. **Routing (static / OSPF / EIGRP / BGP).** Configure only after L2 is
   green. Verify cross-subnet `ping` after each routing change.
6. **ACLs.** Last. Always start permissive, tighten incrementally, ping
   after every tightening.

The reason for the order: a routing or ACL bug looks identical to a
cabling/IP bug if you haven't proven L2 first. Configuring routing on top
of an unverified L2 wastes an hour debugging the wrong layer.

## Things never to do

- `permit any any` as the final ACL line in production-style configs (it
  defeats the ACL). For a lab demo where the spec is "allow all", say so
  explicitly with a comment, otherwise use specific permits.
- `enable password cisco` (or any literal `cisco` password). The grader
  will dock you and the security review will dock you twice.
- Shared/common passwords across devices. Each device's `enable secret`
  and local users should be distinct.
- `line vty` open without an ACL **and** without SSH. If the spec asks for
  remote management, layer SSH + ACL on `vty 0 4`.
- Configuring an interface and forgetting `no shutdown`. `configure_interface`
  defaults `no_shutdown=True` for this reason — only override when the
  spec says "leave admin-down".
- Committing Cisco-shipped binaries (`.pta`, framework JARs, `.pkt`s
  bundled with PT). The repo's `.gitignore` covers `.pkt` already; keep
  it that way.
- Pushing while a phase isn't closed. Phase 4 is the first phase whose
  close-out includes a push; future phases should wait for explicit
  green-light too.

## PT-specific gotchas (from phase 1–4 evidence)

- **Router boot dialog (~30 s).** Fresh 2911 boots into the System
  Configuration Dialog and parks in `mode=logout` after `"no"` until you
  send RETURN. `add_device(type="ROUTER", …)` handles all of that
  transparently — don't re-litigate it via `run_command`.
- **STP convergence (~30 s) on freshly-connected access ports.** The
  first ping batch after a switch↔host link drops entirely while the
  switchport is in listening + learning. `connect(..., auto_portfast=True)`
  (default) collapses this to ~0 s. The `ping` helper retries on total
  loss as a belt-and-suspenders. Switch↔switch links don't get portfast
  (it's unsafe there) — expect a wait, or pre-stage the ping retry.
- **Line protocol lags `isPortUp` by ~1 s.** Convergence checks must poll
  both `up` AND `protocol_up`. `configure_interface` already polls
  internally; ad-hoc verification should too.
- **Cable types.** `ROUTER↔SWITCH` = STRAIGHT. `SWITCH↔HOST` = STRAIGHT.
  `ROUTER↔PC` direct = STRAIGHT (PT does auto-MDIX) or AUTO. `SWITCH↔SWITCH`
  on legacy access switches = CROSS. `ROUTER↔ROUTER` direct = CROSS.
  When in doubt, AUTO.
- **Substring trap.** `"0% loss"` is a substring of `"100% loss"`. Use
  `"Lost = 0"` as the success predicate. Don't text-match `"0% loss"`.
- **Port naming asymmetry.** Hosts use no-slash (`FastEthernet0`). Routers
  and switches use slot/port (`GigabitEthernet0/0`, `FastEthernet0/1`).
  Easy to trip on after spending time in router-land.
- **System "Power Distribution Device".** Fresh workspaces ship with one;
  reloads spawn additional `Device1`, `Device2`. `list_devices` already
  filters by name prefix. If you ever bypass `list_devices` (don't), apply
  the same filter.
- **`add_device` on a duplicate name → `PT_REJECTED`.** Fails loud rather
  than letting PT auto-rename `R1 → R1-1`. Either `delete_device(name)`
  first, or pick a unique name. The error includes `existing_uuid`.

## Router model → feature matrix (phase 4.7, May 2026)

**The single most important table for portfolio building.** Each PT
router model carries a different IOS image variant; picking the right
model gives you the feature set you need with zero license activation.

| Model | IOS image | Crypto/IPsec | Classic CME (telephony-service / ephone-dn) | Notes |
|---|---|:-:|:-:|---|
| `2811` | advipservicesk9 | ✅ | ✅ | **Swiss-army knife — use for VPN gateway AND voice gateway** |
| `1841` | advipservicesk9 | ✅ | ✗ | Smaller, crypto-only |
| `ISR4321` | universalk9 | ✅ | ✗ | Modern ISR, no classic CME |
| `ISR4331` | universalk9 | ✅ | ✗ | Modern ISR, no classic CME |
| `2901` | universalk9 lite | ✗ | ✗ | Not for crypto/voice — pick something else |
| `2911` | ipbase | ✗ | ✗ | **Default many builds reach for, but no crypto/voice** |

Rules of thumb for portfolio design:
- VPN/IPsec router → `2811` (full classic crypto stack: isakmp/ipsec/map) or
  `ISR4321/4331` (modern universalk9, no `telephony-service`).
- CME / voice gateway → `2811` is the **only** confirmed-working choice.
- Pure L3 / WAN router with no crypto → `2911` is fine and well-supported.

The previous portfolio's "K9 license must be activated via GUI" verdict
was wrong: there's no license activation needed. The "license" comes
baked into the router model. Switching the right routers to `2811` closes
both 17.4 IPsec and 17.9 Voice without any code changes.

The previous "CME is REMOVED from PT 9" verdict was also wrong: CME
(classic, the `telephony-service` / `ephone-dn` flavour, not SIP CME) is
fully present — strings sweep shows `CCMEProcess`, `Cmeprocess::getLinenumber`,
`telephony-service`, `dial-peer voice`. SIP CME (`voice register global`) is
NOT in this binary but classic CME suffices for portfolio voice.

## PT 9.0.0 specifics (from portfolio-network build, May 2026)

Lessons from a full portfolio build that hit the limits of PT 9.0.0 vs
older releases. Bank these so the next portfolio re-run lands cleanly
without raw bridge workarounds.

### Device types wired in phase 4.7 (14 new + 16 total ints confirmed)

A brute-force probe enumerated PT 9's device-type enum. Confirmed (int,
model) pairs now wired in `DEVICE_TYPES` (`pt-script-module/api.js`):

| Int | Type | Common model | Probe layer |
|---|---|---|---|
| 0  | ROUTER | 2911 / 2811 / 1841 / 2901 / ISR4321 / ISR4331 | known |
| 1  | SWITCH | 2960-24TT | known |
| 2  | CLOUD | Cloud-PT, Cloud-PT-Empty | new (4.7) |
| 3  | BRIDGE | Bridge-PT | new (4.7) |
| 4  | HUB | Hub-PT | known |
| 5  | REPEATER | Repeater-PT | new (4.7) |
| 7  | ACCESS_POINT | AccessPoint-PT, AP-PT-A/-AC/-N | **new (4.7)** |
| 8  | PC | PC-PT | known |
| 9  | SERVER | Server-PT | known |
| 10 | PRINTER | Printer-PT | **new (4.7)** |
| 11 | WIRELESS_ROUTER | Linksys-WRT300N | known |
| 12 | IP_PHONE | 7960, IPPhone-PT | known |
| 13 | DSL_MODEM | DSL-Modem-PT | new (4.7) |
| 14 | CABLE_MODEM | Cable-Modem-PT | new (4.7) |
| 16 | MULTILAYER_SWITCH | 3560-24PS, 3650-24PS | 4.6 |
| 18 | LAPTOP | Laptop-PT | **new (4.7)** |
| 19 | TABLET | TabletPC-PT | new (4.7) |
| 20 | SMARTPHONE | SMARTPHONE-PT | **new (4.7)** |
| 21 | WIRELESS_END_DEVICE | WirelessEndDevice-PT | **new (4.7) — generic IoT** |
| 22 | WIRED_END_DEVICE | WiredEndDevice-PT | **new (4.7) — generic IoT** |
| 23 | TV | TV-PT | new (4.7) |
| 24 | HOME_VOIP | Home-VoIP-PT | new (4.7) |
| 25 | ANALOG_PHONE | Analog-Phone-PT | new (4.7) |
| 27 | ASA | 5506-X, 5505 | 4.6 |
| 31 | CELL_TOWER | Cell-Tower | **new (4.7)** |

Unmatched in probe 2 (may still exist via module-based placement, not
top-level addDevice): `Sniffer`, `MCU-PT`, `PLC-PT`, `SBC-PT`, `e-PT`,
`Embedded-Server-PT`, `WLC-PT`, `LAP-PT`, `MCUComponent-PT`. The first
six are typically dropped into a MCU/CPU module slot rather than placed
on the canvas directly. Out of scope for phase 4.7.

### Device wiring landed in phase 4.6
- **MULTILAYER_SWITCH (type=16).** Use for L3 switches like the 3560-24PS.
  Boots into the System Configuration Dialog like a router (~10s),
  supports `ip routing` and SVIs (`interface vlan N`), and has
  GigabitEthernet0/1..0/2 + FastEthernet0/1..0/24. The 3560 is the
  natural pick for inter-VLAN routing in a single-site lab.
- **IP_PHONE (type=12).** Model `7960`. Three ports: `Vlan1`, `Switch`
  (upstream — cable to a switch access port), `PC` (downstream daisy-
  chain). Phones in PT 9 cannot register (CME is gone — see below); they
  exist for layer-2/voice-VLAN demonstration only. `run_command` on a
  phone raises BAD_ARGS — they have a dormant `getCommandLine()` but no
  CLI a network operator would drive.
- **ASA (type=27).** Models `5506-X` and `5505`. 9 ports on the 5506-X:
  GigabitEthernet1/1..1/8 + Management1/1. ASA OS 9.6(1) image.
  - Boot is ROMMON → POST → user mode at `ciscoasa>` — **no** System
    Configuration Dialog. But boot is *slow* (90-150s cold). add_device
    waits up to 180s.
  - CLI lives behind `getConsoleLine()`, not `getCommandLine()` like
    routers/switches. `tlFor(dev)` in api.js handles the asymmetry.
  - **`configure_interface` is incomplete on ASA.** It emits the IOS
    skeleton (`enable / configure terminal / interface … / ip address …
    / no shutdown / end`) which gets the IP/up/up state right but ASA
    interfaces also need `nameif <name>` and `security-level <0-100>`
    before they pass traffic. Compose those via `run_commands`. Same
    for `access-list` / `access-group` policy.
  - **ASA `enable` prompts for a password.** The default is empty —
    after `enable`, the next entry is the password (just an empty line
    to accept the default). `run_commands` users must include this
    explicitly: `["enable", "", "show running-config"]`.

### Things PT 9.0.0 doesn't support
- **Server-PT services + DNS records + HTTP file content + AP wireless
  are NOT runtime-scriptable, BUT they ARE file-patchable** (phases
  4.8 + 4.9). The Q_INVOKABLE service classes (`CServerHttp`, `CServerDns`,
  `CServerDhcp`, `CServerMail`, `ServerSyslog`) exist in C++ but the
  Server-PT/Access-Point device's JS surface doesn't expose service or
  wireless config — `getProcess(<name>)` returns null, no `setSsid` /
  `setEnabled` setters. So you can't mutate any of this in a running PT
  session via the JS bridge. **BUT** the saved .pkt file carries every
  state value as XML, and PT 9 uses the same Twofish-EAX + obfuscation
  pipeline as prior versions (cracked & vendored under `tools/unpacket/`,
  MIT — Punkcake21/Unpacket). Six MCP tools cover the file-patch path:
    * `set_pkt_services(pkt, {dev: {svc: bool}})` — HTTP/HTTPS/DNS/TFTP/
      NTP/FTP/SYSLOG/AAA/SMTP/POP3/NETFLOW on/off (phase 4.8).
    * `set_pkt_dns_records(pkt, {dev: {hostname: ip}})` — replaces the
      A-record set (NAMESERVER-DATABASE / RESOURCE-RECORD, TYPE=A-REC,
      TTL=86400 hardcoded). DNS service must be enabled separately
      (phase 4.9).
    * `set_pkt_http_files(pkt, {dev: {filename: html}})` — modifies the
      `<TEXT>` of an existing `<FILE class="CFile">` matched by `<NAME>`.
      Default files PT auto-creates: `index.html`, `helloworld.html`,
      `copyrights.html`, `image.html`. New-file creation not yet
      implemented (would need FILE_NUMBER / FILE_COUNTER bookkeeping)
      (phase 4.9). PT's HTML escape is asymmetric: `<` → `&lt;` and
      `&` → `&amp;`, but `>` stays literal — mirror this in any custom
      patching.
    * `set_pkt_ap_wireless(pkt, {dev: {ssid, auth, passphrase}})` — sets
      SSID + auth mode + passphrase inside `<WIRELESS_COMMON>`. Auth
      modes wired today: `"open"` (ENCRYPT_TYPE=0, AUTHEN_TYPE=0) and
      `"wpa2-psk"` (4 / 4, plus `<WEP_PROCESS>` sub-block with the
      passphrase — named WEP_PROCESS for legacy reasons even for WPA2).
      WEP / WPA-PSK / WPA2-Enterprise have code points but aren't wired
      yet — capture them on demand and add to `_WIRELESS_AUTH_CODES`
      (phase 4.9).
    * `set_pkt_dhcp_pools(pkt, {dev: {pool_name: {start_ip, mask, …}}})`
      — adds or replaces DHCP pools on FastEthernet0 of a Server-PT and
      force-enables the DHCP service (`<ENABLED>1</ENABLED>` on the
      per-port `<DHCP_SERVER>`). Optional fields: `default_router`,
      `dns_server`, `tftp_address` (= **DHCP option 150 — the field that
      solves IP-phone auto-registration with CME**), `wlc_address`,
      `max_users` (default 50), `lease_time` (ms, default 86400000),
      `domain_name`. NETWORK and END_IP are auto-derived from `start_ip`
      + `mask` + `max_users` so callers don't have to compute them.
      Originally built to work around a believed PT 9 router-DHCP CLI
      limitation; that belief was disproven by the phase 5.1 CME smoke
      (router-side `option 150 ip X.X.X.X` is accepted AND served — a
      7960 with `IP_PHONE_POWER_ADAPTER` installed registers cleanly
      using only router-side `ip dhcp pool` + `option 150`). Tool is
      still useful for Server-PT-based DHCP fleets where the router
      doesn't run dhcpd, but router-side DHCP is no longer the blocker
      it was thought to be (phase 4.10 / corrected phase 5.1).
    * `set_pkt_zones(pkt, [{kind, x, y, w, h, fill_color, outline_color,
      label}, ...])` — adds visual zones (colored rectangles, ellipses,
      labels) to the canvas. Three shape kinds: `rect_outline` (Image 1
      style — black-bordered box around a sub-group), `rect_filled` (Image
      2 style — solid-color background for a whole site), `ellipse_filled`
      (Image 3 style — oval for VLAN clusters), plus `note` for bare text.
      Each rect/ellipse with a `label` field auto-emits a paired NOTE near
      its top-left. RECTANGLES and ELLIPSES live at the workspace root
      (siblings of `<CLUSTERS>`); NOTES live inside `<PHYSICALWORKSPACE>`.
      Shape XML schema: `<TopLeftX/Y>`+`<BottomRightX/Y>` for geometry,
      `<Color><Red/Green/Blue/>` for fill, `<Filled OUTLINECOLOR="#hex"
      OUTLINED="true">0|1</Filled>` for outline + fill flag, RECTCLUSTERID
      / ELLIPSECLUSTERID="1-1" pinning to root cluster. `MEM_ADDR=0` works
      — PT 9 re-assigns pointers on load. `clear_existing=True` wipes
      pre-existing shapes/notes before inserting. JS bridge route was
      explored but `addCluster`/`drawCircle`/`drawLine` crashed PT 9.0.0
      on bad args (phase 4.11) — file-patch is the safer path.
  Workflow for any of these: `save_pkt → set_pkt_* → File→Open in PT`.
  Service contents NOT yet patchable: POP3/SMTP mailbox accounts, RADIUS
  users + NAS clients, TFTP file content, HTTP new-file creation (needs
  FILE_NUMBER / FILE_COUNTER bookkeeping). Probe schemas via diff and
  extend `tools/pkt_services.py` when needed.

### Things PT 9.0.0 DOES support (corrections to prior verdicts)
- **CME is present, on the right router model.** Use `2811` (the
  advipservicesk9 image): `telephony-service`, `max-ephones`, `max-dn`,
  `ip source-address X port 2000`, `auto assign N to M`, `ephone-dn N`,
  `number XXXX` all accepted. The earlier "CME removed" verdict was a
  false negative from testing on a `2911` (IPbase image, no voice).
- **Full classic IPsec stack works on the right router model.**
  `crypto isakmp policy / encryption / hash / authentication pre-share /
  group`, `crypto isakmp key`, `crypto ipsec transform-set`,
  `crypto map ... ipsec-isakmp`, `set peer / set transform-set /
  match address` all accepted on `2811`, `1841`, `ISR4321`, `ISR4331`.
  Rejected on `2911`, `2901` (IPbase image, no crypto). No license
  activation is required — the feature set is selected by router model.
- **RSA keygen works in interactive form, not single-line.** PT 9
  rejects `crypto key generate rsa modulus 1024`. The accepted pattern:
  ```python
  bridge.run_commands(R, [
      "enable", "configure terminal",
      "hostname R1", "ip domain-name lab.local",
      "crypto key generate rsa",   # PT prompts "How many bits in the modulus [512]: "
      "2048",                      # answer to the prompt
      "end",
  ])
  ```
  The modulus prompt is the next CLI line after `crypto key generate
  rsa` — the multi-line `run_commands` pattern handles it transparently.

### IOS error markers — `% NOTE:` / `% Warning` are not errors
`op_run_commands` (api.js `detectIosError`) treats lines starting with
`% ` as errors EXCEPT for `% NOTE:` and `% Warning:`, which IOS prints
as informational hints. Real-world case: `crypto map VPNMAP 10
ipsec-isakmp` always prints `% NOTE: This new crypto map will remain
disabled until a peer and a valid access list have been configured.` —
that's the normal IOS workflow signal, not a failure. Earlier crypto
test runs falsely "failed" on this; fixed in phase 4.7.

### Cisco patterns that are real, not hacks
- **Fa-Fa trunk fallback when Gi uplinks are constrained.** A 24-port
  2960 has Fa0/1..0/24 access + Gi0/1..0/2 uplinks. When you've consumed
  both Gi uplinks and need a third trunk, `switchport mode trunk` on a
  Fa port is a real Cisco pattern — slower (100Mbps vs 1Gbps) but
  perfectly valid. Don't apologize for it in the topology doc.
- **Router-side static return route to a routed L3-switch transit
  subnet.** When a 3560 sources pings from an SVI on a transit /30 to
  the upstream router, the upstream router needs an explicit static
  route back to that transit subnet (otherwise return packets get
  black-holed by the router's connected-only view). The portfolio
  build's R-HQ ↔ L3-HQ link needed this. Always think about who has the
  return path.
- **Substitute-ASA-as-OSPF-relay (when an ASA isn't available).** If
  you're using a 2911 as a stand-in for ASA (older PT versions or by
  spec), and the spec says "ASA is static-only" but downstream
  adjacencies need to learn HQ subnets, the substitute ASA must speak
  OSPF to relay LSAs. This contradicts a strict reading of the spec
  but is the only way to satisfy reachability assertions like "show ip
  ospf neighbor on R-HQ shows R-BR and L3-HQ as FULL". With phase 4.6's
  real ASA wiring (type=27), this workaround is no longer needed —
  reach for the real ASA first.

### Hot-reload workflow recap
api.js edits land via `bridge.reload_api()` — no GUI step. Only main.js
edits need the manual Stop/Edit/Save/Start cycle in Extensions →
Scripting → Configure. See "Dev workflow" section above.

## Module integration (phase 5.1, May 2026)

Two MCP tools expose PT's hardware-assembly API, closing the "serial WAN
won't work because the router has no WIC" and "wireless host won't work
because the PC has no NIC" gaps that NovaCore 2.0 hit:

- `add_module(device, module_model, slot=None, container="chassis",
  replace_existing=False)` — install a module, returns the new port
  names PT exposes after install.
- `power_device(device, on)` — chassis-level setPower(bool) for HA
  failover / power-cycle demos.

Full JS-surface map: `docs/phase5.1-module-api.md`. Module catalog has
199 entries spread across the ModuleType int enum (table in M1).

### Container picking — which one to use

`container="chassis"` (the default) is `root.getModuleAt(0)`. This is
where WIC / HWIC / NIM slots live on **routers** and where the power
adapter slot lives on the **7960 IP phone**. Use this for serial
modules and phone power.

`container="root"` is the device's root Module directly. This is where
the wireless NIC slot lives on **PC / Laptop / Server** (always slot
0). Use this for wireless cards.

Mnemonic: routers and phones have a chassis tree (`root → chassis →
WIC/power`); hosts have a flat wireless slot (`root → NIC`). PT mirrors
the real Cisco physical layout.

### Confirmed (device, module, container, slot) triples

| Device | Module | Container | Slot | New ports | Notes |
|---|---|---|---|---|---|
| `2811` | `WIC-1T` | `chassis` | 0 | `Serial0/0/0` | Add per slot for more |
| `2811` | `WIC-2T` | `chassis` | 0 | `Serial0/0/0`, `Serial0/0/1` | |
| `2911` | `HWIC-2T` | `chassis` | 0 | `Serial0/0/0`, `Serial0/0/1` | 2911 is HWIC-only |
| `1841` | `WIC-1T` / `WIC-2T` | `chassis` | 0 or 1 | `Serial0/0/0` etc | 1841 has 2 WIC slots |
| `ISR4321` | `NIM-2T` | `chassis` | 1 | `Serial0/1/0`, `Serial0/1/1` | Slot 0 is BUILTIN |
| `PC-PT` | `Linksys-WMP300N` | `root` | 0 | `Wireless0` | **Needs `replace_existing=True`** — default cover ships in slot 0 |
| `Laptop-PT` | `Linksys-WPC300N` | `root` | 0 | `Wireless0` | Same — replace placeholder |
| `7960` | `IP_PHONE_POWER_ADAPTER` | `chassis` | 0 | *(none)* | No new port — module powers the voice stack so CME registration works |

### Workflow — adding serial WAN between two routers

```python
# Both ends.
add_device(type="ROUTER", name="R1", model="2811", x=100, y=100)
add_device(type="ROUTER", name="R2", model="2811", x=300, y=100)
add_module(device="R1", module_model="WIC-1T")     # → Serial0/0/0 on R1
add_module(device="R2", module_model="WIC-1T")     # → Serial0/0/0 on R2

# Cable. SERIAL is now a real option, not just an enum string.
connect(dev_a="R1", port_a="Serial0/0/0",
        dev_b="R2", port_b="Serial0/0/0",
        cable_type="SERIAL")

# IOS: the DCE side (PT picks one when cable_type=SERIAL) needs a clock
# rate. Find which end is DCE via `show controllers serial 0/0/0` and
# look for "DCE V.35" / "DTE V.35". Set the clock on DCE only:
run_commands("R1", [
    "enable", "configure terminal",
    "interface Serial0/0/0",
    "clock rate 64000",          # only on the DCE side
    "ip address 10.0.0.1 255.255.255.252",
    "no shutdown", "end",
])
run_commands("R2", [
    "enable", "configure terminal",
    "interface Serial0/0/0",
    "ip address 10.0.0.2 255.255.255.252",
    "no shutdown", "end",
])
```

### Workflow — wireless PC ↔ AP

```python
add_device(type="ACCESS_POINT", name="AP1", model="AccessPoint-PT", x=100, y=100)
add_device(type="PC",           name="PC1", model="PC-PT",          x=300, y=100)

# PC ships with a default PT-HOST-NM-COVER in root slot 0. Must displace
# it — the auto-pick path won't, since it only fills empty slots.
add_module(device="PC1", module_model="Linksys-WMP300N",
           container="root", slot=0, replace_existing=True)

# After install: PC1 has `Wireless0`. SSID config on the AP side is via
# set_pkt_ap_wireless (file-patcher), not at runtime. PC's wireless
# association is GUI-only in PT 9 — there's no programmatic equivalent.
```

### Workflow — IP phone registers with CME

```python
add_device(type="ROUTER",    name="R-CME",  model="2811",         x=100, y=100)
add_device(type="SWITCH",    name="SW1",    model="2960-24TT",    x=300, y=100)
add_device(type="IP_PHONE",  name="PHONE1", model="7960",          x=500, y=100)

# THE missing step from NovaCore 2.0: install the phone's power adapter.
# Without this, the phone places + cables but never registers with CME.
add_module(device="PHONE1", module_model="IP_PHONE_POWER_ADAPTER")

# Cable: phone Switch port → switch access port → CME router.
connect("PHONE1", "Switch", "SW1", "FastEthernet0/1", "ETHERNET_STRAIGHT")
connect("SW1",    "GigabitEthernet0/1", "R-CME", "GigabitEthernet0/0", "ETHERNET_STRAIGHT")

# Configure CME on R-CME, voice VLAN + DHCP option 150 on SW1 (the rest
# is regular IOS).
```

### Gotchas

- **Default placeholders.** PC, Laptop, Server, AP, DSL/Cable modem all
  ship with a default module already in their root slot 0 (`PT-HOST-NM-
  COVER` family). Installing a real NIC there needs `replace_existing=
  True`. Routers and the 7960 phone do NOT have placeholders in the
  slots you care about — the auto-pick path works directly.
- **AP power adapter is orphaned.** `ACCESS_POINT_POWER_ADAPTER` exists
  in the catalog (ModuleType 31) but the AP variants probed in phase 5.1
  expose no type-31 slot to install it into. Use `power_device(AP, on=
  False/True)` for AP power state instead — same effect.
- **Built-in modules are read-only.** ISR4321/4331 ship with
  `ISR4321-BUILTIN` in chassis slot 0. Don't try to displace it — it's
  the device's primary interface group. NIM-2T goes in slot 1.
- **Module install adds the port immediately.** No polling needed —
  `connect(..., port_a="Serial0/0/0", ...)` works on the very next call.
- **The `% NOTE:` IOS markers don't apply here.** `add_module` doesn't
  invoke IOS — it's a JS-side workspace mutation. Failures are
  `PT_REJECTED` with structured error_data (occupant / slot_type).

## Naming conventions

- Routers: `R1`, `R2`, `R3` (number from the topology diagram or
  left-to-right).
- Switches: `SW1`, `SW2`. Multilayer: `MLS1`, `MLS2`.
- Hosts: `PC1`, `PC2`. Laptops: `LT1`. Servers: `SRV1`, `SRV2`.
- Wireless gear: `AP1` (access point), `WLR1` (wireless router).
- IOS hostnames match the canvas device name exactly.
- Interface descriptions state the **far end**: `description to SW1
  GigabitEthernet0/1`, never `description uplink`.
- Subnet picks: `192.168.<area>.0/24` where `<area>` is a per-vlan or
  per-link integer; reserve `.1` for the gateway, `.10+` for hosts.

## Dev workflow — editing the in-PT bundle

The Script Module bundle has two source files: `pt-script-module/main.js`
(listener/dispatcher/mailbox) and `pt-script-module/api.js` (op handlers
and helpers). PT runs the encrypted `.pts` it last Exported, so on-disk
edits don't auto-take. Two paths:

- **Edit `api.js` (handlers, helpers, constants, DISPATCH entries):**
  call `reload_api()` (or `bridge.reload_api()`). The MCP tool ships the
  current file contents to a `reload_api` op in main.js, which rebuilds
  DISPATCH in place via a `new Function(code + "; return DISPATCH;")()`
  closure trick. New ops are live on the next call. **No GUI step.**
  Cheap; do it freely between iterations.
- **Edit `main.js` (listener structure, mailbox protocol, dispatcher
  glue):** manual GUI reload — Extensions → Scripting → Configure →
  Stop → Edit → paste both files → Save → Start. Rare; main.js is
  stable code.

If `reload_api()` returns `INTERNAL: reload_api eval threw: ...` the new
api.js has a syntax error or a runtime error during top-level
evaluation. Fix it on disk and retry — DISPATCH is left as it was on
parse failure (the merge runs only after the eval succeeds).
