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
  MIT — Punkcake21/Unpacket). Four MCP tools cover the file-patch path:
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
  Workflow for any of these: `save_pkt → set_pkt_* → File→Open in PT`.
  Open service contents NOT yet patchable: DHCP server pools on Server-PT,
  POP3/SMTP mailbox accounts, RADIUS users + NAS clients, TFTP file
  content. Probe schemas via diff and extend `tools/pkt_services.py`
  when needed.

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
