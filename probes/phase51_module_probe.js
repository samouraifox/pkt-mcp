// Phase 5.1 Step 1 probe — module + power API surface.
//
// Goal: confirm Doxygen-mapped Module/HardwareFactory APIs are live on the
// QtScript surface, enumerate the global module catalog, and capture per-
// device-kind supported-module lists + slot layouts. Read-only / self-
// cleaning: every placed device is deleted before the probe returns.
//
// Source for the API map: PT_HOME/help/default/IpcAPI/{class_device,
// class_module,class_module_factory,class_module_descriptor,class_hardware
// _factory,class_host_port,class_i_p_c}*.html.

(function () {
    var report = {
        timestamp: new Date().toISOString(),
        hardware_factory: {},
        module_factory: {},
        module_catalog: [],          // every ModuleDescriptor the factory exposes
        device_probes: {},           // keyed by probe label (e.g. "ROUTER:2811")
        install_trials: [],          // each: { label, slot, model, ok, port_added }
        power_trials: [],            // each: { label, before, after_off, after_on }
        host_port_power: {},         // 7960 + PC port power read/write
        errors: []
    };

    function methodsOf(obj) {
        var out = [];
        if (!obj) return out;
        try {
            for (var k in obj) {
                try { if (typeof obj[k] === "function") out.push(k); } catch (e) {}
            }
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
        } catch (e) { return ["<methodsOf err: " + e + ">"]; }
        out.sort();
        return out;
    }

    function safe(label, fn) {
        try { return fn(); }
        catch (e) { report.errors.push(label + ": " + e); return null; }
    }

    function lwOf() { return ipc.appWindow().getActiveWorkspace().getLogicalWorkspace(); }
    function netOf() { return ipc.appWindow().getActiveFile().getMainNetwork(); }

    // ── 1. HardwareFactory + ModuleFactory ────────────────────────────
    var moduleFactory = null;
    safe("hardware_factory", function () {
        var hf = ipc.hardwareFactory();
        report.hardware_factory.exists = !!hf;
        report.hardware_factory.methods = methodsOf(hf);
        if (hf && typeof hf.modules === "function") {
            moduleFactory = hf.modules();
        }
    });

    safe("module_factory", function () {
        if (!moduleFactory) {
            report.errors.push("moduleFactory not reachable via hardwareFactory().modules()");
            return;
        }
        report.module_factory.methods = methodsOf(moduleFactory);
        var count = -1;
        try { count = moduleFactory.getAvailableModuleCount(); } catch (e) {
            report.errors.push("getAvailableModuleCount: " + e);
        }
        report.module_factory.available_count = count;
    });

    // ── 2. Global module catalog ──────────────────────────────────────
    safe("module_catalog", function () {
        if (!moduleFactory) return;
        var count = 0;
        try { count = moduleFactory.getAvailableModuleCount(); } catch (e) { return; }
        // Cap to avoid runaway logs; PT 9.0.0 module set should fit easily.
        var cap = Math.min(count, 500);
        for (var i = 0; i < cap; i++) {
            try {
                var md = moduleFactory.getAvailableModuleAt(i);
                if (!md) continue;
                var entry = {
                    idx: i,
                    type: (typeof md.getType === "function") ? md.getType() : null,
                    model: (typeof md.getModel === "function") ? md.getModel() : null,
                    slot_count: (typeof md.getSlotCount === "function") ? md.getSlotCount() : null
                };
                // Slot type list — what this module accepts in each of its
                // own slots (modules can nest, e.g. an expansion bay holds WICs).
                if (entry.slot_count && entry.slot_count > 0) {
                    var slots = [];
                    for (var s = 0; s < entry.slot_count; s++) {
                        try { slots.push(md.getSlotTypeAt(s)); } catch (e) { slots.push("err"); }
                    }
                    entry.slot_types = slots;
                }
                report.module_catalog.push(entry);
            } catch (e) {
                report.errors.push("catalog[" + i + "]: " + e);
            }
        }
    });

    // ── 3. Per-device probes ──────────────────────────────────────────
    function describeModule(mod, depth) {
        if (!mod || depth > 4) return null;
        var info = {
            module_name: null,
            slot_path: null,
            module_type: null,
            slot_count: 0,
            port_count: 0,
            children: []
        };
        try { info.module_name = mod.getModuleNameAsString(); } catch (e) {}
        try { info.slot_path = mod.getSlotPath(); } catch (e) {}
        try { info.module_type = mod.getModuleType(); } catch (e) {}
        try { info.slot_count = mod.getSlotCount(); } catch (e) {}
        try { info.port_count = mod.getPortCount(); } catch (e) {}
        try {
            var mc = mod.getModuleCount();
            for (var i = 0; i < mc; i++) {
                try {
                    var child = mod.getModuleAt(i);
                    if (child) {
                        var c = describeModule(child, depth + 1);
                        if (c) { c.child_idx = i; info.children.push(c); }
                    }
                } catch (e) { info.children.push({ child_idx: i, err: "" + e }); }
            }
        } catch (e) {}
        // Also record slot-type list at this level
        if (info.slot_count > 0) {
            var st = [];
            for (var s = 0; s < info.slot_count; s++) {
                try { st.push(mod.getSlotTypeAt(s)); } catch (e) { st.push("err"); }
            }
            info.slot_types = st;
        }
        return info;
    }

    function probeDevice(label, typeInt, model, x, opts) {
        opts = opts || {};
        var w = lwOf(), n = netOf();
        var uuid = null;
        try { uuid = w.addDevice(typeInt, model, x, 50); }
        catch (e) { report.errors.push(label + " addDevice threw: " + e); return null; }
        if (!uuid) { report.errors.push(label + " addDevice empty uuid"); return null; }

        var dev = null;
        try { dev = n.getDevice(uuid); } catch (e) {}
        if (!dev) { report.errors.push(label + " getDevice null after addDevice"); return null; }

        var entry = {
            type_int: typeInt,
            model: model,
            uuid: String(uuid),
            name: null,
            power: null,
            supported_modules: null,
            root_module: null,
            port_count_before: null,
            port_names_before: [],
            device_methods_filtered: []
        };

        try { entry.name = dev.getName(); } catch (e) {}
        try { entry.power = (typeof dev.getPower === "function") ? dev.getPower() : "(missing)"; } catch (e) {}
        try {
            var sm = (typeof dev.getSupportedModule === "function") ? dev.getSupportedModule() : null;
            // QtScript returns vector<string> as a JS array. Coerce defensively.
            if (sm && typeof sm.length === "number") {
                var arr = [];
                for (var i = 0; i < sm.length; i++) arr.push(String(sm[i]));
                entry.supported_modules = arr;
            } else {
                entry.supported_modules = sm;
            }
        } catch (e) { report.errors.push(label + " getSupportedModule: " + e); }

        try {
            var rm = (typeof dev.getRootModule === "function") ? dev.getRootModule() : null;
            if (rm) entry.root_module = describeModule(rm, 0);
        } catch (e) { report.errors.push(label + " getRootModule: " + e); }

        try {
            if (typeof dev.getPortCount === "function") entry.port_count_before = dev.getPortCount();
            if (typeof dev.getPortAt === "function" && entry.port_count_before) {
                var names = [];
                for (var p = 0; p < entry.port_count_before; p++) {
                    try { var prt = dev.getPortAt(p); if (prt) names.push(prt.getName()); } catch (e) {}
                }
                entry.port_names_before = names;
            }
        } catch (e) {}

        // Filter Device method surface for module/power-related names so the
        // first probe-run report stays tractable.
        try {
            var meth = methodsOf(dev);
            entry.device_methods_filtered = meth.filter(function (k) {
                return /module|slot|chassis|power|adapter|root|booted|reload|restart|setOn|setOff/i.test(k);
            });
        } catch (e) {}

        report.device_probes[label] = entry;

        // ── 3b. Optional install trial ────────────────────────────────
        if (opts.install) {
            try {
                var rm2 = dev.getRootModule();
                // Find a slot of the right type — opts.install.slot_type is
                // an int (ModuleType). If undefined, just try slot index 0
                // / 1 / 2 in order.
                var trial = {
                    label: label,
                    model: opts.install.model,
                    requested_slot: opts.install.slot,
                    requested_type: opts.install.slot_type,
                    chose_slot: null,
                    ok: false,
                    error: null,
                    port_count_after: null,
                    new_port_names: []
                };

                var slotIdx = opts.install.slot;
                if (slotIdx === undefined && rm2 && opts.install.slot_type !== undefined) {
                    var sc = rm2.getSlotCount();
                    for (var ss = 0; ss < sc; ss++) {
                        if (rm2.getSlotTypeAt(ss) === opts.install.slot_type) {
                            // Skip occupied slot (getModuleAt non-null).
                            var occ = null;
                            try { occ = rm2.getModuleAt(ss); } catch (e) {}
                            if (!occ) { slotIdx = ss; break; }
                        }
                    }
                }
                trial.chose_slot = slotIdx;

                if (rm2 && typeof rm2.addModuleAt === "function" && slotIdx !== undefined) {
                    var ok = false;
                    try { ok = !!rm2.addModuleAt(opts.install.model, slotIdx); }
                    catch (e) { trial.error = "addModuleAt threw: " + e; }
                    trial.ok = ok;
                }

                // Re-read port count and names.
                try {
                    trial.port_count_after = dev.getPortCount();
                    var existingSet = {};
                    for (var ii = 0; ii < entry.port_names_before.length; ii++) {
                        existingSet[entry.port_names_before[ii]] = true;
                    }
                    var newNames = [];
                    for (var pp = 0; pp < trial.port_count_after; pp++) {
                        var prt2 = dev.getPortAt(pp);
                        if (prt2) {
                            var nm = prt2.getName();
                            if (!existingSet[nm]) newNames.push(nm);
                        }
                    }
                    trial.new_port_names = newNames;
                } catch (e) { trial.error = (trial.error || "") + " | port re-read: " + e; }

                report.install_trials.push(trial);
            } catch (e) {
                report.errors.push(label + " install trial: " + e);
            }
        }

        // ── 3c. Optional power trial ──────────────────────────────────
        if (opts.power) {
            try {
                var p_before = dev.getPower();
                dev.setPower(false);
                var p_off = dev.getPower();
                dev.setPower(true);
                var p_on = dev.getPower();
                report.power_trials.push({
                    label: label,
                    before: p_before,
                    after_off: p_off,
                    after_on: p_on
                });
            } catch (e) {
                report.errors.push(label + " power trial: " + e);
            }
        }

        // ── 3d. Cleanup ───────────────────────────────────────────────
        try { lwOf().deleteDevice(entry.name); } catch (e) {
            report.errors.push(label + " cleanup deleteDevice: " + e);
        }

        return entry;
    }

    // Routers (2811 = crypto/voice image; 2911 = ipbase for comparison).
    probeDevice("ROUTER:2811", 0, "2811", 100, {
        install: { model: "WIC-1T", slot_type: undefined, slot: undefined },
        power: true
    });
    probeDevice("ROUTER:2911", 0, "2911", 150);
    probeDevice("ROUTER:1841", 0, "1841", 200);
    probeDevice("ROUTER:ISR4321", 0, "ISR4321", 250);

    // Switches.
    probeDevice("SWITCH:2960-24TT", 1, "2960-24TT", 300);
    probeDevice("MLS:3560-24PS",   16, "3560-24PS", 350);

    // End hosts.
    probeDevice("PC:PC-PT", 8, "PC-PT", 400, {
        install: { model: "Linksys-WMP300N", slot_type: undefined, slot: undefined },
        power: true
    });
    probeDevice("LAPTOP:Laptop-PT", 18, "Laptop-PT", 450, { power: true });
    probeDevice("SERVER:Server-PT", 9, "Server-PT", 500, { power: true });

    // Voice / wireless / WAN edge.
    probeDevice("IP_PHONE:7960", 12, "7960", 550, { power: true });
    probeDevice("AP:AccessPoint-PT", 7, "AccessPoint-PT", 600);
    probeDevice("DSL_MODEM:DSL-Modem-PT", 13, "DSL-Modem-PT", 650);
    probeDevice("CABLE_MODEM:Cable-Modem-PT", 14, "Cable-Modem-PT", 700);
    probeDevice("ASA:5506-X", 27, "5506-X", 750);

    // ── 4. HostPort power probe (on a phone and a PC) ─────────────────
    safe("host_port_power", function () {
        var w = lwOf(), n = netOf();
        var phUuid = w.addDevice(12, "7960", 800, 200);
        if (!phUuid) { report.errors.push("host_port_power: phone addDevice empty"); return; }
        var ph = n.getDevice(phUuid);
        var info = { phone: {}, pc: {} };
        try {
            // 7960 ports: "Switch" (upstream), "PC" (daisy-chain), "Vlan1" maybe
            for (var i = 0; i < ph.getPortCount(); i++) {
                var pp = ph.getPortAt(i);
                if (!pp) continue;
                var nm = pp.getName();
                var rec = {
                    has_getPower: (typeof pp.getPower === "function"),
                    has_isPowerOn: (typeof pp.isPowerOn === "function"),
                    has_setPower: (typeof pp.setPower === "function"),
                    getPower: null,
                    isPowerOn: null
                };
                try { rec.getPower = pp.getPower(); } catch (e) {}
                try { rec.isPowerOn = pp.isPowerOn(); } catch (e) {}
                info.phone[nm] = rec;
            }
        } catch (e) { report.errors.push("host_port_power phone walk: " + e); }
        try { w.deleteDevice(ph.getName()); } catch (e) {}

        var pcUuid = w.addDevice(8, "PC-PT", 850, 200);
        if (pcUuid) {
            var pc = n.getDevice(pcUuid);
            try {
                for (var j = 0; j < pc.getPortCount(); j++) {
                    var pp2 = pc.getPortAt(j);
                    if (!pp2) continue;
                    var nm2 = pp2.getName();
                    info.pc[nm2] = {
                        has_getPower: (typeof pp2.getPower === "function"),
                        has_isPowerOn: (typeof pp2.isPowerOn === "function"),
                        has_setPower: (typeof pp2.setPower === "function"),
                        getPower: (typeof pp2.getPower === "function") ? pp2.getPower() : null,
                        isPowerOn: (typeof pp2.isPowerOn === "function") ? pp2.isPowerOn() : null
                    };
                }
            } catch (e) { report.errors.push("host_port_power pc walk: " + e); }
            try { w.deleteDevice(pc.getName()); } catch (e) {}
        }
        report.host_port_power = info;
    });

    return report;
})();
