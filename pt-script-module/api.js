// pkt-mcp Phase 3 — JS API layer.
//
// Each Phase 3 op is a function on this file's DISPATCH table. The
// dispatcher in main.js parses {id, op, args}, looks up DISPATCH[op], and
// calls it. Handlers are either:
//
//   - Sync: return the result object on success; throw an Error whose
//     .error_type matches one of the typed prefixes from
//     docs/phase3-protocol.md ("BAD_ARGS" | "PT_NOT_FOUND" | "PT_REJECTED"
//     | "PT_TIMEOUT" | "INTERNAL") on failure.
//
//   - Async: return DEFER, then call done(result, errorOrNull) when the
//     paced sequence completes. Used by ops that have to space out
//     enterCommand() calls (the M5 race rule — chained CLI input inside one
//     eval drops commands silently). The dispatcher's busy flag suspends
//     mailbox polling between read of cmd.json and the eventual done() call,
//     so the mailbox stays single-slot end-to-end (see phase3-protocol.md).
//
// Use err(type, message, data?) to construct typed errors; the helper
// stamps .error_type / .error_data on a real Error so message/stack still
// surface in dprint.

// String sentinel (not {}) so hot-reloaded handlers' DEFER, declared in a
// Function-constructor closure, still === main.js's global DEFER. Object
// identity would diverge on every reload_api call. See main.js's
// `op === "reload_api"` branch for the closure trick.
var DEFER = "__pkt_mcp_DEFER__";

// Device-type enum (per phase2-api-map.md M1 — extend cautiously, only ints
// with a runtime-confirmed model belong here).
var DEVICE_TYPES = {
    ROUTER: 0,
    SWITCH: 1,
    HUB: 4,
    PC: 8,
    SERVER: 9,
    WIRELESS_ROUTER: 11
};

var DEVICE_TYPE_BY_INT = {};
(function () {
    for (var k in DEVICE_TYPES) {
        if (DEVICE_TYPES.hasOwnProperty(k)) DEVICE_TYPE_BY_INT[DEVICE_TYPES[k]] = k;
    }
})();

// Cable-type enum (per phase2-api-map.md M3 CONNECT_TYPES table — sourced
// from PT's Doxygen, not probed, so this is authoritative).
var CABLE_TYPES = {
    ETHERNET_STRAIGHT: 8100,
    ETHERNET_CROSS:    8101,
    ETHERNET_ROLL:     8102,
    FIBER:             8103,
    PHONE:             8104,
    CABLE:             8105,
    SERIAL:            8106,
    AUTO:              8107,
    CONSOLE:           8108,
    WIRELESS:          8109,
    COAXIAL:           8110,
    OCTAL:             8111,
    CELLULAR:          8112,
    USB:               8113,
    CUSTOM_IO:         8114
};

// System entities to filter from list_devices. Fresh workspaces have a
// "Power Distribution Device0" (M2 finding); after fileOpen the suffix
// increments ("Device1", etc.) so a prefix match is more robust than a
// fixed name. Phase 4 may want to switch to a type-int filter if more
// system entity kinds turn up.
function isSystemDevice(name) {
    return name.indexOf("Power Distribution Device") === 0;
}

// Pacing for paced async ops. Fixed setTimeout gaps are not enough — the
// IOS simulator takes 1-3 s to even reach its boot dialog, and individual
// CLI mode transitions can take a few hundred ms. We poll for state
// instead and only proceed when the expected transition has actually
// landed (the M5 race rule, properly handled this time).
var POLL_MS_INNER = 100;
var BOOT_DIALOG_DEADLINE_MS = 60000;   // PT IOS boot is slow on first start;
                                       // bumped from 30s for back-to-back router
                                       // adds (phase 4.5 medium-test feedback #1)
var ROUTER_BOOT_PHASE_MS    = 30000;   // post-dialog "Press RETURN" + user-mode
                                       // transitions; was sharing the 8s
                                       // IOS_MODE_DEADLINE_MS until phase 4.5,
                                       // tight under multi-router boot load
var IOS_MODE_DEADLINE_MS    = 8000;    // intra-config IOS mode transitions
                                       // (configure_interface) — these are fast
                                       // even under load; keep snappy
var SAVE_DEADLINE_MS = 10000;          // fileSaveAsNoPrompt writes async

// ─── error helper ────────────────────────────────────────────────────────

function err(type, message, data) {
    var e = new Error(String(message || ""));
    e.error_type = type;
    if (data !== undefined) e.error_data = data;
    return e;
}

// ─── PT object accessors ─────────────────────────────────────────────────

function lw() {
    return ipc.appWindow().getActiveWorkspace().getLogicalWorkspace();
}

function net() {
    return ipc.appWindow().getActiveFile().getMainNetwork();
}

function listRawDevices() {
    var n = net();
    var arr = [];
    var count = (typeof n.getDeviceCount === "function") ? n.getDeviceCount() : 0;
    if (typeof n.getDeviceAt === "function") {
        for (var i = 0; i < count; i++) {
            var d = n.getDeviceAt(i);
            if (d) arr.push(d);
        }
    }
    return arr;
}

function findDeviceByName(name) {
    var devs = listRawDevices();
    for (var i = 0; i < devs.length; i++) {
        if (devs[i].getName() === name) return devs[i];
    }
    return null;
}

function findPort(device, portName) {
    if (typeof device.getPort === "function") {
        var p = device.getPort(portName);
        if (p) return p;
    }
    if (typeof device.getPortCount === "function" && typeof device.getPortAt === "function") {
        for (var i = 0; i < device.getPortCount(); i++) {
            var pp = device.getPortAt(i);
            if (pp && pp.getName() === portName) return pp;
        }
    }
    return null;
}

// ─── arg validation ──────────────────────────────────────────────────────

function requireArg(args, key, type) {
    var v = (args || {})[key];
    if (v === undefined || v === null) {
        throw err("BAD_ARGS", "missing arg: " + key);
    }
    if (type === "string" && typeof v !== "string") {
        throw err("BAD_ARGS", key + " must be string, got " + typeof v);
    }
    if (type === "number" && typeof v !== "number") {
        throw err("BAD_ARGS", key + " must be number, got " + typeof v);
    }
    if (type === "boolean" && typeof v !== "boolean") {
        throw err("BAD_ARGS", key + " must be boolean, got " + typeof v);
    }
    return v;
}

function requireDevice(name) {
    var d = findDeviceByName(name);
    if (!d) throw err("PT_NOT_FOUND", "device not found: " + name);
    return d;
}

function requirePort(device, portName) {
    var p = findPort(device, portName);
    if (!p) {
        throw err("PT_NOT_FOUND",
            "port not found: " + device.getName() + "/" + portName);
    }
    return p;
}

// ─── port-state introspection ────────────────────────────────────────────

function portStateOf(port) {
    return {
        ip:          (typeof port.getIpAddress === "function") ? port.getIpAddress() : null,
        mask:        (typeof port.getSubnetMask === "function") ? port.getSubnetMask() : null,
        up:          (typeof port.isPortUp === "function") ? !!port.isPortUp() : null,
        protocol_up: (typeof port.isProtocolUp === "function") ? !!port.isProtocolUp() : null,
        link:        (typeof port.getLink === "function") ? (port.getLink() != null) : null
    };
}

// ─── async polling helper ────────────────────────────────────────────────

// Poll a predicate every interval_ms until it returns truthy, then call
// onReady(); if deadline_ms expires first, call onTimeout(). Predicates
// that throw count as falsy (a setter may not be ready right after
// addDevice, etc.).
function pollUntil(predicate, opts, onReady, onTimeout) {
    var iv = (opts && opts.interval_ms) || POLL_MS_INNER;
    var deadlineAt = Date.now() + ((opts && opts.deadline_ms) || IOS_MODE_DEADLINE_MS);
    function tick() {
        var ok = false;
        try { ok = !!predicate(); } catch (e) { /* keep polling */ }
        if (ok) { onReady(); return; }
        if (Date.now() > deadlineAt) { onTimeout(); return; }
        setTimeout(tick, iv);
    }
    tick();
}

// ─── ops ─────────────────────────────────────────────────────────────────

function op_add_device(args, done) {
    var typeStr = requireArg(args, "type",  "string");
    var name    = requireArg(args, "name",  "string");
    var model   = requireArg(args, "model", "string");
    var x       = requireArg(args, "x",     "number");
    var y       = requireArg(args, "y",     "number");

    var typeInt = DEVICE_TYPES[typeStr];
    if (typeInt === undefined) {
        throw err("BAD_ARGS", "unknown device type: " + typeStr,
            { allowed: Object.keys(DEVICE_TYPES) });
    }

    var existing = findDeviceByName(name);
    if (existing) {
        // Fail loud on name collision rather than letting PT auto-rename
        // (R1 → R1-1, etc.) — quiet rename would desync the MCP layer's
        // name cache. Callers who want auto-rename can delete-then-add.
        var existingUuid = null;
        if (typeof existing.getUuid === "function") {
            try { existingUuid = String(existing.getUuid()); } catch (e) {}
        } else if (typeof existing.getObjectUuid === "function") {
            try { existingUuid = String(existing.getObjectUuid()); } catch (e) {}
        } else if (typeof existing.getId === "function") {
            try { existingUuid = String(existing.getId()); } catch (e) {}
        }
        throw err("PT_REJECTED", "device name already exists: " + name,
            { existing_uuid: existingUuid });
    }

    var uuid = lw().addDevice(typeInt, model, x, y);
    if (!uuid) {
        // M1 quirk: bad model returns "" instead of throwing.
        throw err("PT_REJECTED",
            "addDevice rejected model: " + model + " (returned empty uuid)",
            { type: typeStr, model: model });
    }

    var dev = net().getDevice(uuid);
    if (!dev) {
        throw err("INTERNAL",
            "addDevice returned uuid but getDevice() yielded null: " + uuid);
    }
    dev.setName(name);

    // Non-IOS devices (PC/Server/Hub) are ready as soon as addDevice returns.
    if (typeStr !== "ROUTER" && typeStr !== "SWITCH" && typeStr !== "WIRELESS_ROUTER") {
        return { uuid: String(uuid), name: name };
    }

    // Shared CLI introspection helpers (used by both the SWITCH boot-wait
    // and the ROUTER dialog-skip + boot-wait below).
    function tlFor(dev) {
        try { return (typeof dev.getCommandLine === "function") ? dev.getCommandLine() : null; }
        catch (e) { return null; }
    }
    function modeOf(tl) { try { return (tl && tl.getMode) ? tl.getMode() : ""; } catch (e) { return ""; } }
    function promptOf(tl) { try { return (tl && tl.getPrompt) ? tl.getPrompt() : ""; } catch (e) { return ""; } }

    // SWITCH and WIRELESS_ROUTER: no boot dialog, but the CLI takes a few
    // seconds to reach user/enable mode after addDevice. Phase 4.5 medium-
    // test feedback #5: connect()'s auto_portfast immediately CLI'd a fresh
    // switch and the IOS commands silently failed because the prompt was
    // still at boot output. add_device's contract is "returned device is
    // CLI-ready" — wait for it.
    if (typeStr !== "ROUTER") {
        pollUntil(
            function () {
                var t = tlFor(dev);
                if (!t) return false;
                var m = modeOf(t);
                return (m === "user" || m === "enable");
            },
            { interval_ms: POLL_MS_INNER, deadline_ms: ROUTER_BOOT_PHASE_MS },
            function () { done({ uuid: String(uuid), name: name }, null); },
            function () {
                // Defensive: try a single Enter (some switch builds park
                // briefly at "Press RETURN") and re-poll once.
                try {
                    var t = tlFor(dev);
                    if (t && typeof t.enterCommand === "function") t.enterCommand("");
                } catch (e) {}
                pollUntil(
                    function () {
                        var m = modeOf(tlFor(dev));
                        return (m === "user" || m === "enable");
                    },
                    { interval_ms: POLL_MS_INNER, deadline_ms: ROUTER_BOOT_PHASE_MS },
                    function () { done({ uuid: String(uuid), name: name }, null); },
                    function () {
                        var tlF = tlFor(dev);
                        done(null, err("PT_TIMEOUT",
                            typeStr.toLowerCase() + " did not reach user mode within boot deadline",
                            { last_mode: modeOf(tlF), last_prompt: promptOf(tlF) }));
                    }
                );
            }
        );
        return DEFER;
    }

    // Routers boot into the System Configuration Dialog (M5). PT IOS takes
    // 1-3 s to even reach the dialog prompt, so a fixed setTimeout doesn't
    // work — we have to poll for the dialog to actually appear before
    // sending "no", then poll for the resulting transition into user mode.
    // Phase 1: dialog prompt is up, OR we're somehow already past it.
    pollUntil(
        function () {
            var tl = tlFor(dev);
            if (!tl) return false;
            if (/yes\/no/i.test(promptOf(tl))) return true;
            var m = modeOf(tl);
            return (m === "user" || m === "enable");
        },
        { interval_ms: POLL_MS_INNER, deadline_ms: BOOT_DIALOG_DEADLINE_MS },
        function () {
            var tl = tlFor(dev);
            if (tl && /yes\/no/i.test(promptOf(tl))) {
                try { tl.enterCommand("no"); }
                catch (e) {
                    done(null, err("INTERNAL", "router dialog skip enterCommand threw: " + e));
                    return;
                }
            }
            // Phase 2: post-"no", IOS prints "Press RETURN to get started!"
            // and parks in mode=logout until we send an empty Enter. Wait
            // for either user mode (already past) or that logout state, then
            // send RETURN if needed and wait for user mode.
            pollUntil(
                function () {
                    var t = tlFor(dev);
                    if (!t) return false;
                    var m = modeOf(t);
                    if (m === "user" || m === "enable" || m === "logout") return true;
                    var out = (t.getOutput ? t.getOutput() : "");
                    return /Press RETURN to get started/.test(out);
                },
                { interval_ms: POLL_MS_INNER, deadline_ms: ROUTER_BOOT_PHASE_MS },
                function () {
                    var t = tlFor(dev);
                    var m = modeOf(t);
                    if (m !== "user" && m !== "enable") {
                        // Press RETURN.
                        try { t.enterCommand(""); } catch (e) {}
                    }
                    pollUntil(
                        function () {
                            var mm = modeOf(tlFor(dev));
                            return (mm === "user" || mm === "enable");
                        },
                        { interval_ms: POLL_MS_INNER, deadline_ms: ROUTER_BOOT_PHASE_MS },
                        function () { done({ uuid: String(uuid), name: name }, null); },
                        function () {
                            var t4 = tlFor(dev);
                            done(null, err("PT_TIMEOUT",
                                "router did not reach user mode after dialog + RETURN",
                                { last_mode: modeOf(t4), last_prompt: promptOf(t4),
                                  output_tail: (t4 && t4.getOutput) ? t4.getOutput().slice(-200) : "" }));
                        }
                    );
                },
                function () {
                    var t2 = tlFor(dev);
                    done(null, err("PT_TIMEOUT",
                        "router did not reach 'Press RETURN' state after sending 'no'",
                        { last_mode: modeOf(t2), last_prompt: promptOf(t2),
                          output_tail: (t2 && t2.getOutput) ? t2.getOutput().slice(-200) : "" }));
                }
            );
        },
        function () {
            // Phase 1 timeout — dialog never seen within BOOT_DIALOG_DEADLINE_MS.
            // Defensive recovery (phase 4.5 medium-test feedback #1): the
            // dialog might have rendered just after the last poll, or PT was
            // saturated by parallel router adds. Send "no" + RETURN
            // unconditionally and give it ROUTER_BOOT_PHASE_MS to land in
            // user/enable. Worst case is one or two harmless extra Enters
            // sent to a router that's not at the dialog.
            try {
                var tlR = tlFor(dev);
                if (tlR && typeof tlR.enterCommand === "function") tlR.enterCommand("no");
            } catch (e) {}
            setTimeout(function () {
                try {
                    var tlR2 = tlFor(dev);
                    if (tlR2 && typeof tlR2.enterCommand === "function") tlR2.enterCommand("");
                } catch (e) {}
                pollUntil(
                    function () {
                        var mm = modeOf(tlFor(dev));
                        return (mm === "user" || mm === "enable");
                    },
                    { interval_ms: POLL_MS_INNER, deadline_ms: ROUTER_BOOT_PHASE_MS },
                    function () { done({ uuid: String(uuid), name: name }, null); },
                    function () {
                        var tlF = tlFor(dev);
                        done(null, err("PT_TIMEOUT",
                            "router did not reach user mode (boot took >" +
                            BOOT_DIALOG_DEADLINE_MS + "ms initial + defensive recovery)",
                            { last_mode: modeOf(tlF), last_prompt: promptOf(tlF),
                              output_tail: (tlF && tlF.getOutput) ? tlF.getOutput().slice(-200) : "" }));
                    }
                );
            }, 1500);
        }
    );
    return DEFER;
}

function op_delete_device(args) {
    var name = requireArg(args, "name", "string");
    var dev = requireDevice(name);
    var w = lw();

    if (typeof w.deleteDevice === "function") {
        w.deleteDevice(name);
    } else if (typeof w.removeDevice === "function") {
        var uuid = (typeof dev.getUuid === "function") ? dev.getUuid() : null;
        w.removeDevice(uuid || name);
    } else {
        throw err("INTERNAL", "no delete primitive on LogicalWorkspace");
    }

    if (findDeviceByName(name)) {
        throw err("PT_REJECTED", "device still present after delete: " + name);
    }
    return { ok: true };
}

function op_connect(args) {
    var devA   = requireArg(args, "dev_a",      "string");
    var portA  = requireArg(args, "port_a",     "string");
    var devB   = requireArg(args, "dev_b",      "string");
    var portB  = requireArg(args, "port_b",     "string");
    var cable  = requireArg(args, "cable_type", "string");

    var cableInt = CABLE_TYPES[cable];
    if (cableInt === undefined) {
        throw err("BAD_ARGS", "unknown cable_type: " + cable,
            { allowed: Object.keys(CABLE_TYPES) });
    }

    requireDevice(devA);
    requireDevice(devB);

    var ok = lw().createLink(devA, portA, devB, portB, cableInt);
    if (!ok) {
        throw err("PT_REJECTED",
            "createLink failed: " + devA + "/" + portA + " <-> " +
            devB + "/" + portB + " (" + cable + ")",
            { dev_a: devA, port_a: portA, dev_b: devB, port_b: portB, cable_type: cable });
    }
    return { ok: true };
}

function op_configure_interface(args, done) {
    var name   = requireArg(args, "device",    "string");
    var iface  = requireArg(args, "interface", "string");
    var ip     = requireArg(args, "ip",        "string");
    var mask   = requireArg(args, "mask",      "string");
    var noShut = (args && args.no_shutdown !== undefined) ? !!args.no_shutdown : true;

    var dev  = requireDevice(name);
    var port = requirePort(dev, iface);
    var tl   = (typeof dev.getCommandLine === "function") ? dev.getCommandLine() : null;
    if (!tl) throw err("PT_NOT_FOUND", "no command line on device: " + name);

    // Each step's predicate is what must become true before we send the
    // next command. Mode-changing steps wait for the mode transition;
    // state-changing steps (ip address, no shutdown) wait for the port to
    // reflect the change. This is the M5 race rule properly handled —
    // fixed sleeps drop commands when IOS lags.
    var steps = [
        { cmd: "enable",
          ready: function () { return tl.getMode() === "enable"; } },
        { cmd: "configure terminal",
          ready: function () { return tl.getMode() === "global"; } },
        { cmd: "interface " + iface,
          ready: function () { return /^int/.test(tl.getMode() || ""); } },
        { cmd: "ip address " + ip + " " + mask,
          ready: function () { return port.getIpAddress() === ip; } }
    ];
    if (noShut) {
        steps.push({ cmd: "no shutdown",
                     ready: function () { return port.isPortUp() === true; } });
    }
    steps.push({ cmd: "end",
                 ready: function () { return tl.getMode() === "enable"; } });

    var i = 0;
    function nextStep() {
        if (i >= steps.length) {
            // Final convergence: wait for the port to read fully up/up.
            // protocol_up lags no-shutdown by ~1s (line protocol nego);
            // poll instead of insta-check so callers see a coherent
            // green state when configure_interface returns.
            pollUntil(
                function () {
                    var st = portStateOf(port);
                    return (st.ip === ip) && (st.mask === mask) &&
                           (!noShut || (st.up === true && st.protocol_up === true));
                },
                { interval_ms: POLL_MS_INNER, deadline_ms: IOS_MODE_DEADLINE_MS },
                function () {
                    done({ ok: true, port_state: portStateOf(port) }, null);
                },
                function () {
                    var st = portStateOf(port);
                    done(null, err("PT_TIMEOUT",
                        "configure_interface did not converge: requested " +
                        JSON.stringify({ ip: ip, mask: mask, no_shutdown: noShut }) +
                        ", observed " + JSON.stringify(st),
                        { observed: st,
                          requested: { ip: ip, mask: mask, no_shutdown: noShut } }));
                }
            );
            return;
        }
        var step = steps[i++];
        try {
            tl.enterCommand(step.cmd);
        } catch (e) {
            done(null, err("INTERNAL", "enterCommand threw on '" + step.cmd + "': " + e));
            return;
        }
        pollUntil(
            step.ready,
            { interval_ms: POLL_MS_INNER, deadline_ms: IOS_MODE_DEADLINE_MS },
            nextStep,
            function () {
                done(null, err("PT_TIMEOUT",
                    "step did not converge: '" + step.cmd + "'",
                    { failed_step: step.cmd,
                      mode: (tl.getMode ? tl.getMode() : null),
                      prompt: (tl.getPrompt ? tl.getPrompt() : null),
                      observed: portStateOf(port) }));
            }
        );
    }
    nextStep();
    return DEFER;
}

function op_configure_host(args) {
    var name = requireArg(args, "device", "string");
    var dhcp = !!(args && args.dhcp);
    var ip   = (args && args.ip)      || null;
    var mask = (args && args.mask)    || null;
    var gw   = (args && args.gateway) || null;

    if (!dhcp && (!ip || !mask)) {
        throw err("BAD_ARGS", "dhcp=false requires ip and mask");
    }

    var dev  = requireDevice(name);
    var port = findPort(dev, "FastEthernet0");
    if (!port) {
        throw err("PT_NOT_FOUND",
            "no FastEthernet0 port on " + name + " (configure_host assumes the M6 host-port layout)");
    }

    if (dhcp) {
        port.setDhcpClientFlag(true);
    } else {
        port.setDhcpClientFlag(false);
        port.setIpSubnetMask(ip, mask);
        if (gw && typeof dev.setDefaultGateway === "function") {
            dev.setDefaultGateway(gw);
        }
    }
    return { ok: true };
}

function op_run_command(args) {
    var name     = requireArg(args, "device",   "string");
    var cmd      = requireArg(args, "command",  "string");
    var terminal = requireArg(args, "terminal", "string");
    if (cmd.indexOf("\n") >= 0) {
        throw err("BAD_ARGS", "command must be a single line (no embedded newline)");
    }
    if (terminal !== "ios" && terminal !== "desktop") {
        throw err("BAD_ARGS",
            "terminal must be \"ios\" or \"desktop\", got " + JSON.stringify(terminal),
            { allowed: ["ios", "desktop"] });
    }

    var dev = requireDevice(name);
    var tl = null;
    if (terminal === "desktop") {
        if (typeof dev.getCommandPrompt !== "function") {
            throw err("PT_NOT_FOUND",
                "device has no desktop Command Prompt: " + name +
                " (terminal:\"desktop\" requires a host like PC/Laptop)");
        }
        tl = dev.getCommandPrompt();
    } else {
        if (typeof dev.getCommandLine !== "function") {
            throw err("PT_NOT_FOUND",
                "device has no IOS console line: " + name +
                " (terminal:\"ios\" requires routers/switches/IOS gear)");
        }
        tl = dev.getCommandLine();
    }
    if (!tl) {
        throw err("PT_NOT_FOUND",
            "terminal accessor returned null on device: " + name +
            " (terminal=" + terminal + ")");
    }

    tl.enterCommand(cmd);
    return {
        output: (typeof tl.getOutput === "function") ? tl.getOutput() : "",
        prompt: (typeof tl.getPrompt === "function") ? tl.getPrompt() : "",
        mode:   (typeof tl.getMode   === "function") ? tl.getMode()   : ""
    };
}

function op_run_commands(args, done) {
    // Pipelined sibling of op_run_command. Sends a list of CLI lines through
    // a single mailbox round-trip with the same pollUntil pacing pattern
    // op_configure_interface uses (M5 race rule). Per-line results capture
    // each command's output slice + IOS state. On a "% ..." IOS error,
    // stops the sequence and returns what was completed — the caller is
    // responsible for the recovery decision (IOS modes are fragile;
    // continuing past a failure usually lands the next command in the
    // wrong context). Phase 4.5 medium-test feedback #4.
    var name     = requireArg(args, "device",   "string");
    var terminal = requireArg(args, "terminal", "string");
    if (!args || !(args.commands instanceof Array)) {
        throw err("BAD_ARGS", "commands must be an array of strings");
    }
    var commands = args.commands;
    for (var k = 0; k < commands.length; k++) {
        if (typeof commands[k] !== "string") {
            throw err("BAD_ARGS", "commands[" + k + "] must be a string, got " + typeof commands[k]);
        }
        if (commands[k].indexOf("\n") >= 0) {
            throw err("BAD_ARGS", "commands[" + k + "] contains embedded newline");
        }
    }
    if (terminal !== "ios" && terminal !== "desktop") {
        throw err("BAD_ARGS",
            "terminal must be \"ios\" or \"desktop\", got " + JSON.stringify(terminal),
            { allowed: ["ios", "desktop"] });
    }

    var dev = requireDevice(name);
    var tl = null;
    if (terminal === "desktop") {
        if (typeof dev.getCommandPrompt !== "function") {
            throw err("PT_NOT_FOUND",
                "device has no desktop Command Prompt: " + name +
                " (terminal:\"desktop\" requires a host like PC/Laptop)");
        }
        tl = dev.getCommandPrompt();
    } else {
        if (typeof dev.getCommandLine !== "function") {
            throw err("PT_NOT_FOUND",
                "device has no IOS console line: " + name +
                " (terminal:\"ios\" requires routers/switches/IOS gear)");
        }
        tl = dev.getCommandLine();
    }
    if (!tl) {
        throw err("PT_NOT_FOUND",
            "terminal accessor returned null on device: " + name +
            " (terminal=" + terminal + ")");
    }

    var results = [];
    var i = 0;

    function curPrompt() { try { return (typeof tl.getPrompt === "function") ? tl.getPrompt() : ""; } catch (e) { return ""; } }
    function curMode()   { try { return (typeof tl.getMode   === "function") ? tl.getMode()   : ""; } catch (e) { return ""; } }
    function curOutput() { try { return (typeof tl.getOutput === "function") ? tl.getOutput() : ""; } catch (e) { return ""; } }

    function finish(stoppedEarly) {
        done({
            results:        results,
            stopped_early:  !!stoppedEarly,
            final_prompt:   curPrompt(),
            final_mode:     curMode()
        }, null);
    }

    // Detect IOS error markers in a command's output slice. IOS prints
    // "% Invalid input detected at '^' marker.", "% Incomplete command.",
    // "% Ambiguous command:", "% Unknown ...", etc. — all start with "% ".
    function detectIosError(thisOut) {
        var lines = thisOut.split("\n");
        for (var j = 0; j < lines.length; j++) {
            var ln = lines[j];
            // Trim leading whitespace only — preserve the message body.
            var t = ln.replace(/^\s+/, "");
            if (t.length >= 2 && t.charAt(0) === "%" && t.charAt(1) === " ") {
                return t;
            }
        }
        return null;
    }

    function nextCommand() {
        if (i >= commands.length) { finish(false); return; }

        var cmd = commands[i];
        var preOut    = curOutput();
        var prePrompt = curPrompt();

        try {
            tl.enterCommand(cmd);
        } catch (e) {
            results.push({
                command:       cmd,
                output:        "",
                prompt:        prePrompt,
                mode:          curMode(),
                error_type:    "INTERNAL",
                error_message: "enterCommand threw: " + e
            });
            finish(true);
            return;
        }

        // Pacing predicate: prompt changed OR buffer grew. Either is a
        // signal that the command landed. On deadline expiry we proceed
        // anyway (a no-op like "interface ..." in already-config-mode
        // legitimately produces neither signal — that's not an error).
        pollUntil(
            function () {
                if (curPrompt() !== prePrompt) return true;
                if (curOutput().length > preOut.length) return true;
                return false;
            },
            { interval_ms: POLL_MS_INNER, deadline_ms: IOS_MODE_DEADLINE_MS },
            function () { afterCommand(cmd, preOut, prePrompt); },
            function () { afterCommand(cmd, preOut, prePrompt); }
        );
    }

    function afterCommand(cmd, preOut, prePrompt) {
        var nowOut = curOutput();
        var thisOut = (nowOut.length > preOut.length) ? nowOut.slice(preOut.length) : "";
        var entry = {
            command: cmd,
            output:  thisOut,
            prompt:  curPrompt(),
            mode:    curMode()
        };
        var iosErr = detectIosError(thisOut);
        if (iosErr) {
            entry.error_type    = "PT_REJECTED";
            entry.error_message = iosErr;
            results.push(entry);
            finish(true);
            return;
        }
        results.push(entry);
        i++;
        nextCommand();
    }

    nextCommand();
    return DEFER;
}

function op_list_devices() {
    var devs = listRawDevices();
    var out = [];
    for (var i = 0; i < devs.length; i++) {
        var d = devs[i];
        var nm = d.getName();
        if (isSystemDevice(nm)) continue;

        var typeInt = (typeof d.getType === "function") ? d.getType() : null;
        var typeName = null;
        if (typeInt != null) {
            typeName = DEVICE_TYPE_BY_INT[typeInt] || String(typeInt);
        }
        out.push({
            name:  nm,
            type:  typeName,
            model: (typeof d.getModel === "function") ? d.getModel() : null,
            x:     (typeof d.getX     === "function") ? d.getX()     : null,
            y:     (typeof d.getY     === "function") ? d.getY()     : null
        });
    }
    return out;
}

function op_get_port_state(args) {
    var name  = requireArg(args, "device",    "string");
    var iface = requireArg(args, "interface", "string");
    var dev   = requireDevice(name);
    var port  = requirePort(dev, iface);
    return portStateOf(port);
}

function op_save(args, done) {
    // Step 6 introspection found appWindow.fileSaveAsNoPrompt(path, bool) as
    // the headless save primitive. It writes a real .pkt asynchronously
    // (~ms-to-1s latency) and does NOT update getActiveFile().getSavedFilename(),
    // so successive saves to different paths don't trash PT's "current file"
    // state — exactly what we want for an MCP server.
    var path = requireArg(args, "path", "string");
    if (path.charAt(0) !== "/") {
        throw err("BAD_ARGS",
            "path must be absolute (start with '/'), got: " + path);
    }
    var win = ipc.appWindow();
    var sfm = ipc.systemFileManager();
    if (typeof win.fileSaveAsNoPrompt !== "function") {
        throw err("INTERNAL", "appWindow.fileSaveAsNoPrompt missing");
    }

    // Best-effort: wipe any stale file at path so file-existence after the
    // call is an unambiguous signal that the write completed.
    try { sfm.removeFile(path); } catch (e) {}

    try { win.fileSaveAsNoPrompt(path, true); }
    catch (e) {
        throw err("INTERNAL", "fileSaveAsNoPrompt threw: " + e);
    }

    // Poll for the file to land — async write.
    pollUntil(
        function () { return sfm.fileExists(path); },
        { interval_ms: POLL_MS_INNER, deadline_ms: SAVE_DEADLINE_MS },
        function () {
            var size = null;
            try { size = sfm.getFileSize(path); } catch (e) {}
            done({ ok: true, path: path, size: size }, null);
        },
        function () {
            done(null, err("PT_TIMEOUT",
                "save did not flush to disk within " + SAVE_DEADLINE_MS + "ms",
                { path: path }));
        }
    );
    return DEFER;
}

// ─── dispatch table ──────────────────────────────────────────────────────

var DISPATCH = {
    add_device:          op_add_device,
    delete_device:       op_delete_device,
    connect:             op_connect,
    configure_interface: op_configure_interface,
    configure_host:      op_configure_host,
    run_command:         op_run_command,
    run_commands:        op_run_commands,
    list_devices:        op_list_devices,
    get_port_state:      op_get_port_state,
    save:                op_save
};
