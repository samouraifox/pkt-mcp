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

var DEFER = {};

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

// System entities to filter from list_devices (per phase2 M2 finding —
// fresh workspace already contains a "Power Distribution Device0").
var SYSTEM_DEVICE_NAMES = { "Power Distribution Device0": true };

// Pacing for configure_interface's enterCommand sequence. M5 used one
// mailbox roundtrip per command (~50 ms each); 100 ms here is conservative.
var STEP_MS = 100;

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

    if (typeStr !== "ROUTER") {
        return { uuid: String(uuid), name: name };
    }

    // Routers boot into the System Configuration Dialog (M5). Skip with
    // enterCommand("no") on a small delay so the boot prompt has time to
    // appear. Async: wait → send "no" → wait → done.
    setTimeout(function () {
        try {
            var tl = (typeof dev.getCommandLine === "function") ? dev.getCommandLine() : null;
            if (tl && typeof tl.enterCommand === "function") {
                tl.enterCommand("no");
            }
        } catch (e) {
            done(null, err("INTERNAL", "router dialog skip failed: " + e));
            return;
        }
        setTimeout(function () {
            done({ uuid: String(uuid), name: name }, null);
        }, STEP_MS);
    }, STEP_MS);
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

    var steps = [
        "enable",
        "configure terminal",
        "interface " + iface,
        "ip address " + ip + " " + mask
    ];
    if (noShut) steps.push("no shutdown");
    steps.push("end");

    var i = 0;
    function next() {
        if (i >= steps.length) {
            var st = portStateOf(port);
            var ipOk   = (st.ip === ip);
            var maskOk = (st.mask === mask);
            var upOk   = (!noShut) || (st.up === true);
            if (!(ipOk && maskOk && upOk)) {
                done(null, err("PT_TIMEOUT",
                    "configure_interface did not converge: requested " +
                    JSON.stringify({ ip: ip, mask: mask, no_shutdown: noShut }) +
                    ", observed " + JSON.stringify(st),
                    { observed: st,
                      requested: { ip: ip, mask: mask, no_shutdown: noShut } }));
                return;
            }
            done({ ok: true, port_state: st }, null);
            return;
        }
        try {
            tl.enterCommand(steps[i++]);
        } catch (e) {
            done(null, err("INTERNAL", "enterCommand threw: " + e));
            return;
        }
        setTimeout(next, STEP_MS);
    }
    setTimeout(next, STEP_MS);
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

function op_list_devices() {
    var devs = listRawDevices();
    var out = [];
    for (var i = 0; i < devs.length; i++) {
        var d = devs[i];
        var nm = d.getName();
        if (SYSTEM_DEVICE_NAMES[nm]) continue;

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

function op_save(args) {
    // Step 6 will probe ipc.appWindow / ipc.systemFileManager / activeFile /
    // activeWorkspace for save|export|write methods (Doxygen incomplete —
    // see TerminalLine.getOutput in M6) before declaring this a blocker.
    throw err("INTERNAL", "save() not implemented yet — Step 6 probe pending",
        { status: "blocker" });
}

// ─── dispatch table ──────────────────────────────────────────────────────

var DISPATCH = {
    add_device:          op_add_device,
    delete_device:       op_delete_device,
    connect:             op_connect,
    configure_interface: op_configure_interface,
    configure_host:      op_configure_host,
    run_command:         op_run_command,
    list_devices:        op_list_devices,
    get_port_state:      op_get_port_state,
    save:                op_save
};
