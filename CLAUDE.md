# CLAUDE.md

Networking + Packet Tracer knowledge for sessions in this repo. The repo's
*infrastructure* (architecture, MCP wiring, Bridge protocol) lives in
`docs/`; this file is the *operating manual* for actually building good
topologies through it.

## How this project works

`pkt-mcp` is an MCP server that drives Cisco Packet Tracer 9.0 from Claude.
The plumbing chain is **Claude → MCP (`pkt_mcp/server.py`) → typed Bridge
client (`tools/pkt_bridge.py`) → file mailbox (`/tmp/pkt-mcp/`) → Script
Module inside PT (`pt-script-module/{main,api}.js`) → PT canvas**. The 12
MCP tools are defined in `pkt_mcp/server.py`; their docstrings are the
authoritative API reference. For depth on any layer, see `docs/`:
`architecture.md`, `phase1-investigation.md` (Java path, dead end),
`phase2-api-map.md` (PT JS API surface), `phase3-protocol.md` (typed
op/args wire), `phase4-mcp.md` (this MCP layer).

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
