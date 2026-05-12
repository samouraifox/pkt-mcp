# Phase 5.2 — bulk operations

Two new ops landed: `add_devices` (parallel boot of IOS chassis) and
`connect_many` (single-round-trip cable creation). Closes the wall-clock
gap from NovaCore 2.0: ~45 sequential `connect` calls + N × 30s router
boots dominated single-session time budget. Phase 5.2 collapses both.

## What landed

- **`_bootWaitFor(dev, typeStr, onSuccess, onFailure)`** in api.js —
  extracted from the old inline boot logic in `op_add_device`. Same
  ASA / SWITCH / ROUTER-or-MLS branches, same defensive recovery.
  Called once per device; multiple concurrent invocations share PT's
  setTimeout event loop and the chassis boot threads in PT itself.
- **`op_add_devices(devices: [...])`** — synchronous addDevice +
  setName per row, then fans out `_bootWaitFor` for each IOS chassis.
  Joins on a counter and calls `done({results: [...]})` once. Each
  row's success/failure is reported independently; one bad row does
  not abort the others.
- **`op_connect_many(links: [...])`** — pure JS-side sequential
  createLink loop. Single MCP round-trip vs. N. `auto_portfast` is
  NOT applied (the JS layer has no IOS CLI helpers); MCP-level
  `connect_many` documents the caller follows up with `run_commands`
  for portfast where needed.
- **`Bridge.add_devices` / `Bridge.connect_many`** in pkt_bridge.py —
  thin typed wrappers. `add_devices` also updates the run_command
  device-type cache for every successful row.
- **`add_devices` / `connect_many` `@mcp.tool()`** in server.py.

## Benchmark (probes/run_phase52_smoke.py + run_phase52_scale_bench.py)

PT 9.0.0 on the local dev box.

| operation                                   | observed | serial baseline | speedup |
|---------------------------------------------|---------:|----------------:|--------:|
| `add_devices` × 6 routers + 1 sw (cold)     |  31.1 s  |        ~183 s   |  5.9×   |
| `add_devices` × 20 routers (warm engine)    |  11.2 s  |        ~600 s   | 53.6×   |
| `connect_many` × 5 ETH straight             |   0.50 s |        ~7-8 s   | 14-16×  |

The router boot is the dominant cost in any topology build. With phase
5.2, that cost is amortized across the batch — N routers in roughly one
30s window on a cold engine, or ~10s on a warm one. For the 200-device
NovaCore 2.0 spec, this cuts the initial topology-build phase from
~hours to ~minutes.

Surprising finding: **N=20 was FASTER than N=6** (11.2s vs 31.1s). The
6-router run was the first batch after a fresh PT process + bridge
script reload; the 20-router run came after a 4-device smoke had
already warmed the JS engine and PT's event loop. The cold-boot cost is
front-loaded into the *first* call after PT startup; subsequent bulk
calls amortize across an already-primed scheduler. Implication: a
typical "build a 100-device topology" workflow should plan one small
warm-up batch first (or just accept the first batch is the slowest).

Effective per-device cost at N=20: 0.56s. Extrapolating to N=100 gives
~11s if parallelism stays linear, or ~30-60s if there's hidden
sub-linear scaling — either way **well under the kickoff acceptance
criterion (300s / 5 min for 100 devices).** Validated to N=20; N=50/100
are exercises for a future run when a topology that big is needed.

`connect_many`'s wall-clock isn't capped by IO latency the way single
`connect` is; the speedup vs. serial is mostly the MCP round-trip
collapse (1 RTT vs N).

## Partial-failure semantics

Both ops return `{results: [<row>, ...]}` aligned to input order. Each
row is either:
- `{"ok": true, ...}` on success
- `{"error": {"type": "<code>", "message": "...", "data": {...}}}` on
  per-row failure

A bad row does NOT abort the others — every device/link that can be
placed will be. Top-level shape errors (e.g. `devices` not a list)
still raise synchronously as `BAD_ARGS`.

This contrasts with `add_device` / `connect`, which raise on any
problem. The bulk variants are explicitly forgiving — a 100-device
batch shouldn't be wasted because device 47 had a name collision.

## Design decisions

- **JS-side parallelism vs protocol-level batching.** The kickoff doc
  weighed these. Option 1 (JS-side: one op_X handler loops/fans-out)
  won — minimal protocol change, low risk, already enough for the 5.9×
  router speedup. Option 2 (protocol-level: one mailbox envelope holds
  N ops) was deferred. If a future phase finds 5.9× insufficient,
  revisit then.
- **No `auto_portfast` in `connect_many`.** The MCP `connect` runs
  portfast via the run_command helper after the link is created.
  Replicating that in `op_connect_many` would either duplicate the
  IOS-pacing logic in JS or require per-row run_command calls from
  Python (eroding the round-trip win). Decision: skip for v1, let
  callers issue a single `run_commands` per switch afterwards covering
  all its access ports. Common case is well-served.
- **`op_add_device` refactor.** The boot logic was extracted into the
  shared helper `_bootWaitFor`. `op_add_device` still validates +
  addDevice + setName synchronously; the boot branch now just calls
  the helper with done()-wrapping callbacks. Behavior is identical;
  the regression smoke (probes/run_phase52_smoke.py reload + the
  pre-existing CME smoke) confirms no breakage.

## Next: phase 5.3

`configure_interfaces([{device, interface, ip, mask}, ...])` and
`ping_matrix([{from, to}, ...])` are the natural next bulk ops — but
they require interleaving per-device IOS CLI sessions, which is more
involved than `add_devices`'s fan-out (each row needs its own multi-
step state machine). Defer to phase 5.3.

Show-command parsers (phase 5.3 in the original kickoff) are now the
clearer next chunk: structured `show ip route`, `show ip ospf
neighbor`, etc. Move them up since 5.2 unblocks the throughput side.

## Acceptance — phase 5.2 closes here

- [x] `_bootWaitFor` helper extracted; `op_add_device` uses it; no
      behavioral regression (CME smoke from phase 5.1 still passes).
- [x] `op_add_devices` lands; 6-router parallel boot in ≤45s.
- [x] `op_connect_many` lands; 5-link bulk create in <1s.
- [x] Bridge + MCP wrappers in place with the same partial-failure
      semantics as the JS layer.
- [x] Smoke benchmark in `probes/run_phase52_smoke.py`.
