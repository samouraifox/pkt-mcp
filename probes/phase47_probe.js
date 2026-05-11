// Phase 4.7 investigation probe — single JS payload run via bridge.raw().
//
// Goals (all read-only or self-cleaning):
//   1. Enumerate methods on key PT objects (ipc, lw, net, a placed router,
//      a placed server) to find license/service accessors.
//   2. Brute-force DEVICE_TYPES enum ints for AP/IoT/Sniffer/Laptop/Printer/
//      Smartphone/Tablet/CellTower/Webcam/Thermostat — place, capture
//      type/model, delete.
//   3. Probe getLicenseManager() on a router for Q_INVOKABLE methods.
//   4. Probe Server-PT for child service objects (getMail / getHttp / getDns).
//
// Returns a structured JSON document. The bridge's raw op returns whatever
// the eval produces, so we wrap the whole thing in a function that builds
// and returns a result dict.

(function () {
    var report = {
        timestamp: new Date().toISOString(),
        ipc_methods: [],
        lw_methods: [],
        net_methods: [],
        license_manager_methods: [],
        license_object_methods: [],
        router_methods: [],
        server_methods: [],
        ap_methods: [],
        device_type_probe: {},
        errors: []
    };

    function methodsOf(obj) {
        var out = [];
        if (!obj) return out;
        try {
            for (var k in obj) {
                try {
                    if (typeof obj[k] === "function") out.push(k);
                } catch (e) {}
            }
            // Also try to walk prototype chain.
            try {
                var p = Object.getPrototypeOf(obj);
                while (p && p !== Object.prototype) {
                    var names = Object.getOwnPropertyNames(p);
                    for (var i = 0; i < names.length; i++) {
                        if (out.indexOf(names[i]) < 0) {
                            try {
                                if (typeof obj[names[i]] === "function") out.push(names[i]);
                            } catch (e) {}
                        }
                    }
                    p = Object.getPrototypeOf(p);
                }
            } catch (e) {}
        } catch (e) {
            return ["<methodsOf err: " + e + ">"];
        }
        out.sort();
        return out;
    }

    function safe(label, fn) {
        try { return fn(); }
        catch (e) { report.errors.push(label + ": " + e); return null; }
    }

    // ── 1. Top-level accessors ─────────────────────────────────────────
    safe("ipc_methods", function () {
        report.ipc_methods = methodsOf(ipc);
    });
    safe("lw_methods", function () {
        var w = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace();
        report.lw_methods = methodsOf(w);
    });
    safe("net_methods", function () {
        var n = ipc.appWindow().getActiveFile().getMainNetwork();
        report.net_methods = methodsOf(n);
    });

    // ── 2. Device-type enum brute force ────────────────────────────────
    // Try addDevice(N, model, 0, 0) for N in 0..32 with a probe model per
    // common type, then delete. Catch each independently.
    var lw = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace();
    var net = ipc.appWindow().getActiveFile().getMainNetwork();

    // Try one model per type-int. We use a generic-ish model first, then
    // fall back to type-specific ones if needed. The strategy: place at
    // x=0,y=0 (off-screen-ish), capture the resulting device's getType()
    // and getModel(), then delete.
    var probe_models = [
        "2911", "2960-24TT", "Hub-PT", "PC-PT", "Server-PT",
        "Linksys-WRT300N", "7960", "3560-24PS", "5506-X",
        "AccessPoint-PT", "Laptop-PT", "Printer-PT",
        "TabletPC-PT", "SMARTPHONE-PT", "Cell-Tower",
        "WiredEndDevice-PT", "WirelessEndDevice-PT",
        "Sniffer", "WLC-PT", "LAP-PT", "Home-VoIP-PT",
        "Analog-Phone-PT", "Embedded-Server-PT", "MCU-PT", "PLC-PT",
        "SBC-PT", "e-PT", "Bridge-PT", "Repeater-PT",
        "DSL-Modem-PT", "Cable-Modem-PT", "Cloud-PT"
    ];

    var typeProbeBlock = {};

    // Strategy: for each candidate model name, try addDevice with each int
    // in [0..32]. Most pairs will fail (returns empty uuid). The first
    // successful pair tells us the right int for that model. Then read
    // dev.getType() and dev.getModel() to confirm and capture both ends.
    for (var mi = 0; mi < probe_models.length; mi++) {
        var model = probe_models[mi];
        // For each model, try a focused int range. Skip already-known
        // (we still want to confirm and harvest method surfaces though).
        for (var ti = 0; ti < 33; ti++) {
            var uuid = null;
            try { uuid = lw.addDevice(ti, model, 0 + mi * 5, 0); } catch (e) { continue; }
            if (!uuid) continue;
            // Success. Capture, delete, move on.
            try {
                var dev = net.getDevice(uuid);
                var devType = (dev && dev.getType) ? dev.getType() : null;
                var devModel = (dev && dev.getModel) ? dev.getModel() : null;
                var name = dev && dev.getName ? dev.getName() : null;
                typeProbeBlock[model] = {
                    type_int: ti,
                    dev_type_reported: devType,
                    dev_model_reported: devModel,
                    name: name
                };
                // Delete to keep canvas clean.
                try { lw.deleteDevice(name); } catch (e) {}
            } catch (e) {
                report.errors.push("probe " + model + "/" + ti + ": " + e);
            }
            break;
        }
    }
    report.device_type_probe = typeProbeBlock;

    // ── 3. Place a 2911 router and probe ───────────────────────────────
    safe("router_probe", function () {
        var routerUuid = lw.addDevice(0, "2911", 100, 100);
        if (!routerUuid) { report.errors.push("router probe: addDevice empty uuid"); return; }
        // Don't wait for boot — method surface is available immediately
        // since this is the JS-visible object, not the IOS terminal.
        var r = net.getDevice(routerUuid);
        report.router_methods = methodsOf(r);

        // Probe license manager.
        var lm = null;
        try {
            if (typeof r.getLicenseManager === "function") {
                lm = r.getLicenseManager();
            }
        } catch (e) { report.errors.push("getLicenseManager call: " + e); }
        if (lm) {
            report.license_manager_methods = methodsOf(lm);
            // Try to enumerate a license object too.
            try {
                if (typeof lm.getLicense === "function") {
                    var lic = lm.getLicense("ipbasek9");
                    if (lic) report.license_object_methods = methodsOf(lic);
                    else report.errors.push("getLicense('ipbasek9') returned null");
                }
            } catch (e) { report.errors.push("license object probe: " + e); }
        } else {
            report.errors.push("router has no getLicenseManager accessor");
        }

        // Cleanup.
        try { lw.deleteDevice(r.getName()); } catch (e) {}
    });

    // ── 4. Place a Server-PT and probe service accessors ───────────────
    safe("server_probe", function () {
        var serverUuid = lw.addDevice(9, "Server-PT", 200, 100);
        if (!serverUuid) { report.errors.push("server probe: addDevice empty uuid"); return; }
        var s = net.getDevice(serverUuid);
        report.server_methods = methodsOf(s);

        // Try a few likely accessor names.
        var likely = [
            "getMail", "getMailService", "getMailIpc", "getHttp",
            "getHttpService", "getDns", "getDnsService", "getDhcp",
            "getDhcpService", "getNtp", "getNtpService", "getSyslog",
            "getSyslogService", "getRadius", "getRadiusService",
            "getProcess", "getProcessManager", "getApplicationManager",
            "getServer", "getServerByName", "getServiceByName"
        ];
        var found = {};
        for (var li = 0; li < likely.length; li++) {
            var fnName = likely[li];
            if (typeof s[fnName] === "function") {
                found[fnName] = "exists";
                try {
                    var v = s[fnName]();
                    if (v) {
                        found[fnName] = {
                            present: true,
                            child_methods: methodsOf(v).slice(0, 40)
                        };
                    } else {
                        found[fnName] = "returns_null";
                    }
                } catch (e) {
                    found[fnName] = "threw: " + e;
                }
            }
        }
        report.server_child_accessors = found;

        try { lw.deleteDevice(s.getName()); } catch (e) {}
    });

    // ── 5. If AP type was found in step 2, probe its method surface ───
    safe("ap_probe", function () {
        var apEntry = typeProbeBlock["AccessPoint-PT"];
        if (!apEntry) return;
        var apUuid = lw.addDevice(apEntry.type_int, "AccessPoint-PT", 300, 100);
        if (!apUuid) return;
        var ap = net.getDevice(apUuid);
        report.ap_methods = methodsOf(ap);
        try { lw.deleteDevice(ap.getName()); } catch (e) {}
    });

    return report;
})();
