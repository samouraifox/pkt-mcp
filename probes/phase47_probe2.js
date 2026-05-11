// Phase 4.7 probe 2 — Server-PT services + AP wireless + gap-int device types.
//
// Probe 1 found: Server-PT has getProcess() but it throws on no args; no
// getHttpService/getDnsService etc. at device level. Strings sweep proves
// CServerHttp/CServerDns/CServerDhcp/CServerMail/ServerSyslog ARE Q_INVOKABLE
// Qt classes. So services live on child objects reached through some
// accessor. This probe brute-forces likely access patterns.

(function () {
    var report = {
        server_process_probe: {},
        server_accessor_probe: {},
        ap_methods_full: [],
        ap_descendant_probe: {},
        gap_int_probe: {},
        errors: []
    };

    function methodsOf(obj) {
        var out = [];
        if (!obj) return out;
        try {
            for (var k in obj) {
                try { if (typeof obj[k] === "function") out.push(k); } catch (e) {}
            }
            var p = Object.getPrototypeOf(obj);
            while (p && p !== Object.prototype) {
                var names = Object.getOwnPropertyNames(p);
                for (var i = 0; i < names.length; i++) {
                    if (out.indexOf(names[i]) < 0) {
                        try { if (typeof obj[names[i]] === "function") out.push(names[i]); } catch (e) {}
                    }
                }
                p = Object.getPrototypeOf(p);
            }
        } catch (e) { return ["<methodsOf err: " + e + ">"]; }
        out.sort();
        return out;
    }
    function safe(label, fn) {
        try { return fn(); } catch (e) { report.errors.push(label + ": " + e); return null; }
    }

    var lw = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace();
    var net = ipc.appWindow().getActiveFile().getMainNetwork();

    // ── 1. Server-PT process / service accessor brute force ───────────
    safe("server_probe", function () {
        var sUuid = lw.addDevice(9, "Server-PT", 200, 100);
        var s = net.getDevice(sUuid);

        // Try getProcess with various arg patterns.
        var args = [
            "http", "Http", "HTTP",
            "dns", "Dns", "DNS",
            "dhcp", "Dhcp", "DHCP",
            "ftp", "Ftp", "FTP",
            "smtp", "Smtp", "SMTP", "mail", "Mail",
            "pop3", "POP3",
            "syslog", "Syslog", "SYSLOG",
            "ntp", "Ntp", "NTP",
            "radius", "Radius", "RADIUS", "aaa", "AAA",
            "tftp", "TFTP",
            "iot", "IoT", "IOT",
            0, 1, 2, 3
        ];
        for (var i = 0; i < args.length; i++) {
            var a = args[i];
            try {
                var p = s.getProcess(a);
                if (p) {
                    report.server_process_probe[String(a)] = {
                        present: true,
                        class_name: (typeof p.getClassName === "function") ? p.getClassName() : "?",
                        methods: methodsOf(p).slice(0, 60)
                    };
                }
            } catch (e) {
                // Most will throw; ignore unless interesting.
            }
        }

        // Probe other likely method names exhaustively. Brute-force any method
        // starting with "get" that might return a service object.
        var allMethods = methodsOf(s);
        var getMethods = [];
        for (var j = 0; j < allMethods.length; j++) {
            if (allMethods[j].indexOf("get") === 0) getMethods.push(allMethods[j]);
        }
        for (var k = 0; k < getMethods.length; k++) {
            var name = getMethods[k];
            // Skip obviously non-service ones (positional accessors / scalars).
            if (/At$|Count$|Coordinate$|Pos$|Time|Name|Model|Type|Flag|Uuid|Power|Index/.test(name)) continue;
            try {
                var rv = s[name]();
                if (rv && typeof rv === "object") {
                    var cls = (typeof rv.getClassName === "function") ? rv.getClassName() : "?";
                    // Only capture if it has a class name suggesting a service.
                    if (cls && (cls.indexOf("Server") >= 0 || cls.indexOf("Service") >= 0 || cls.indexOf("Process") >= 0 || cls.indexOf("Mail") >= 0 || cls.indexOf("Http") >= 0 || cls.indexOf("Dns") >= 0 || cls.indexOf("Dhcp") >= 0)) {
                        report.server_accessor_probe[name] = {
                            class_name: cls,
                            methods: methodsOf(rv).slice(0, 60)
                        };
                    } else if (typeof rv === "object" && rv !== null) {
                        // Note non-service objects too (might be a manager).
                        report.server_accessor_probe[name + "_other"] = {
                            class_name: cls,
                            methods: methodsOf(rv).slice(0, 30)
                        };
                    }
                }
            } catch (e) {
                // ignore — most no-arg getters fail
            }
        }

        try { lw.deleteDevice(s.getName()); } catch (e) {}
    });

    // ── 2. AP wireless surface ────────────────────────────────────────
    safe("ap_probe", function () {
        var aUuid = lw.addDevice(7, "AccessPoint-PT", 300, 100);
        var ap = net.getDevice(aUuid);
        report.ap_methods_full = methodsOf(ap);

        // AP ports / radio config probe.
        try {
            var pc = ap.getPortCount();
            for (var p = 0; p < pc; p++) {
                var port = ap.getPortAt(p);
                if (!port) continue;
                var portName = (typeof port.getName === "function") ? port.getName() : ("port" + p);
                report.ap_descendant_probe[portName] = {
                    methods: methodsOf(port).slice(0, 60)
                };
            }
        } catch (e) { report.errors.push("ap port probe: " + e); }

        try { lw.deleteDevice(ap.getName()); } catch (e) {}
    });

    // ── 3. Gap-int device type probe ──────────────────────────────────
    // Probe 1 found types 0-31 mostly. Gaps at 6, 15, 17, 23, 26, 28, 29, 30.
    // Also unmatched models: Sniffer, MCU-PT, PLC-PT, SBC-PT, e-PT,
    // Embedded-Server-PT, WLC-PT, LAP-PT, MCUComponent-PT, IPPhone-PT.
    var gap_ints = [6, 15, 17, 23, 26, 28, 29, 30];
    var unmatched_models = [
        "Sniffer", "Sniffer-PT", "MCU-PT", "MCUComponent-PT",
        "PLC-PT", "SBC-PT", "e-PT", "Embedded-Server-PT",
        "WLC-PT", "LAP-PT", "IPPhone-PT",
        "AccessPoint-PT-A", "AccessPoint-PT-AC", "AccessPoint-PT-N",
        "TV-PT", "PDA-PT", "Pda-PT"
    ];

    // For each gap int, try each model — first hit wins.
    for (var gi = 0; gi < gap_ints.length; gi++) {
        var ti = gap_ints[gi];
        for (var mi = 0; mi < unmatched_models.length; mi++) {
            var model = unmatched_models[mi];
            var uuid = null;
            try { uuid = lw.addDevice(ti, model, 0, 400 + gi * 30); } catch (e) { continue; }
            if (!uuid) continue;
            try {
                var dev = net.getDevice(uuid);
                report.gap_int_probe[String(ti)] = {
                    matched_model: model,
                    dev_type: (dev && dev.getType) ? dev.getType() : null,
                    dev_model: (dev && dev.getModel) ? dev.getModel() : null
                };
                try { lw.deleteDevice(dev.getName()); } catch (e) {}
            } catch (e) { report.errors.push("gap probe " + ti + "/" + model + ": " + e); }
            break;
        }
    }

    // Also try unmatched models against ALL int 0-32 in case the type int
    // is one of the known ones (model variant of an existing type — like
    // AccessPoint-PT-A might be int=7 too).
    var still_unmatched = [];
    for (var mu = 0; mu < unmatched_models.length; mu++) {
        var um = unmatched_models[mu];
        var found = false;
        for (var p in report.gap_int_probe) {
            if (report.gap_int_probe[p].matched_model === um) { found = true; break; }
        }
        if (!found) still_unmatched.push(um);
    }

    var modelToInt = {};
    for (var mui = 0; mui < still_unmatched.length; mui++) {
        var model2 = still_unmatched[mui];
        for (var tj = 0; tj <= 32; tj++) {
            var u2 = null;
            try { u2 = lw.addDevice(tj, model2, 0, 600); } catch (e) { continue; }
            if (!u2) continue;
            try {
                var dev2 = net.getDevice(u2);
                modelToInt[model2] = {
                    type_int: tj,
                    dev_type: dev2.getType(),
                    dev_model: dev2.getModel()
                };
                try { lw.deleteDevice(dev2.getName()); } catch (e) {}
            } catch (e) { report.errors.push("retry probe " + model2 + "/" + tj + ": " + e); }
            break;
        }
    }
    report.unmatched_model_retry = modelToInt;

    return report;
})();
