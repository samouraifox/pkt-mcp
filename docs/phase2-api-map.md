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

## M2..M6

_Stubbed; populate after each milestone lands._
