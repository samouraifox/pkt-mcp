// Phase 5.1 Step 1 probe — iteration 2.
//
// Probe 1 confirmed: ipc.hardwareFactory().modules() exposes the global
// module catalog (199 entries); device.getRootModule() / .getSupportedModule()
// / .setPower(bool) / .getPower() / .addModule() / .removeModule() all live;
// HostPort exposes setPower/getPower/isPowerOn. But: (1) lw.deleteDevice
// doesn't exist on QtScript LogicalWorkspace — use lw.removeDevice(uuid)
// instead; (2) WIC/HWIC slots live inside the chassis CHILD module, not the
// root, so addModuleAt has to be called on root.getModuleAt(0); (3) PC has a
// default placeholder occupying the wireless slot — remove it before install.
//
// This iteration:
//   1. Installs WIC-1T into a 2811 chassis WIC slot (nested), confirms the
//      resulting Serial port appears.
//   2. Installs WIC-2T into another 2811 slot to test 2-port modules.
//   3. Installs Linksys-WMP300N into a PC after removing the default cover.
//   4. Installs PT-HOST-NM-1W-AC into a Laptop (different ModuleType=9).
//   5. Installs IP_PHONE_POWER_ADAPTER into a 7960 phone (nested in child).
//   6. Confirms removeModuleAt() reverts the install (port disappears).
//   7. Inspects the chassis child's slot tree before/after each install.
//
// Cleans up by uuid via lw.removeDevice(uuid).

(function () {
    var report = {
        timestamp: new Date().toISOString(),
        delete_method: null,
        install_trials: [],   // { label, slot_path, model, slot_idx, ok, before, after, removed_ok }
        errors: []
    };

    function lwOf() { return ipc.appWindow().getActiveWorkspace().getLogicalWorkspace(); }
    function netOf() { return ipc.appWindow().getActiveFile().getMainNetwork(); }

    function moduleMethods(obj) {
        var keys = [];
        if (!obj) return keys;
        for (var k in obj) {
            try { if (typeof obj[k] === "function") keys.push(k); } catch (e) {}
        }
        keys.sort();
        return keys;
    }

    // Surface every method on lw so we can pin down the correct delete name.
    safe("lw_delete_methods", function () {
        var w = lwOf();
        var keys = moduleMethods(w).filter(function (k) {
            return /delete|remove|destroy|drop|del\b|removeDevice/i.test(k);
        });
        report.delete_method = keys;
    });
    function safe(label, fn) {
        try { return fn(); }
        catch (e) { report.errors.push(label + ": " + e); return null; }
    }

    function portNamesOf(dev) {
        var arr = [];
        try {
            for (var i = 0; i < dev.getPortCount(); i++) {
                var p = dev.getPortAt(i);
                if (p) arr.push(p.getName());
            }
        } catch (e) {}
        return arr;
    }

    function slotMapOf(mod) {
        // Return [{slot_idx, type, occupied_by_name}] for one module level.
        var out = [];
        if (!mod) return out;
        try {
            var sc = mod.getSlotCount();
            for (var i = 0; i < sc; i++) {
                var entry = {
                    slot: i,
                    slot_type: null,
                    child: null
                };
                try { entry.slot_type = mod.getSlotTypeAt(i); } catch (e) {}
                try {
                    var c = mod.getModuleAt(i);
                    if (c) {
                        entry.child = {
                            slot_path: (typeof c.getSlotPath === "function") ? c.getSlotPath() : null,
                            module_type: (typeof c.getModuleType === "function") ? c.getModuleType() : null,
                            port_count: (typeof c.getPortCount === "function") ? c.getPortCount() : null
                        };
                    }
                } catch (e) {}
                out.push(entry);
            }
        } catch (e) {}
        return out;
    }

    function tryInstall(label, typeInt, model, opts) {
        // opts: { module_model, slot_type, container: "root"|"child0", remove_default_at: <int> }
        var trial = {
            label: label,
            device_model: model,
            module_model: opts.module_model,
            container: opts.container,
            removed_default_at: null,
            before: { ports: [], container_slots: [] },
            chose_slot: null,
            ok: false,
            after: { ports: [], container_slots: [] },
            new_ports: [],
            uuid_deleted_via: null,
            errors: []
        };

        var w = lwOf(), n = netOf();
        var uuid = null;
        try { uuid = w.addDevice(typeInt, model, 50, 50); }
        catch (e) { trial.errors.push("addDevice: " + e); report.install_trials.push(trial); return; }
        if (!uuid) { trial.errors.push("addDevice empty uuid"); report.install_trials.push(trial); return; }
        var dev = n.getDevice(uuid);

        try {
            var rm = dev.getRootModule();
            var container = (opts.container === "child0") ? rm.getModuleAt(0) : rm;
            if (!container) { trial.errors.push("container null"); }
            else {
                trial.before.ports = portNamesOf(dev);
                trial.before.container_slots = slotMapOf(container);

                // Optional: remove a default placeholder at a specific slot
                // first (PC wireless slot ships with a cover module).
                if (opts.remove_default_at !== undefined) {
                    try {
                        container.removeModuleAt(opts.remove_default_at);
                        trial.removed_default_at = opts.remove_default_at;
                    } catch (e) { trial.errors.push("removeModuleAt default: " + e); }
                }

                // Pick the slot. If opts.slot is set, use it. Else find the
                // first slot whose type matches opts.slot_type and is empty.
                var chosen = opts.slot;
                if (chosen === undefined) {
                    var sc = container.getSlotCount();
                    for (var s = 0; s < sc; s++) {
                        if (container.getSlotTypeAt(s) === opts.slot_type) {
                            var occ = null;
                            try { occ = container.getModuleAt(s); } catch (e) {}
                            if (!occ) { chosen = s; break; }
                        }
                    }
                }
                trial.chose_slot = chosen;

                if (chosen !== undefined) {
                    var ok = false;
                    try { ok = !!container.addModuleAt(opts.module_model, chosen); }
                    catch (e) { trial.errors.push("addModuleAt: " + e); }
                    trial.ok = ok;
                }

                trial.after.ports = portNamesOf(dev);
                trial.after.container_slots = slotMapOf(container);

                // Diff to find newly-added ports.
                var beforeSet = {};
                for (var i = 0; i < trial.before.ports.length; i++) beforeSet[trial.before.ports[i]] = true;
                for (var j = 0; j < trial.after.ports.length; j++) {
                    if (!beforeSet[trial.after.ports[j]]) trial.new_ports.push(trial.after.ports[j]);
                }

                // Optional removeModuleAt round-trip to confirm the port goes away.
                if (opts.test_remove && trial.ok && chosen !== undefined) {
                    try {
                        container.removeModuleAt(chosen);
                        trial.after_remove_ports = portNamesOf(dev);
                    } catch (e) { trial.errors.push("test_remove removeModuleAt: " + e); }
                }
            }
        } catch (e) { trial.errors.push("trial body: " + e); }

        // Clean up — try removeDevice(uuid); fall back to removeDevice(name).
        try {
            if (typeof w.removeDevice === "function") {
                w.removeDevice(uuid);
                trial.uuid_deleted_via = "removeDevice(uuid)";
            }
        } catch (e) {
            try {
                if (typeof w.removeDevice === "function") {
                    w.removeDevice(dev.getName());
                    trial.uuid_deleted_via = "removeDevice(name)";
                }
            } catch (e2) {
                trial.errors.push("cleanup: " + e + " | " + e2);
            }
        }

        report.install_trials.push(trial);
    }

    // 1. 2811 + WIC-1T  → expected Serial0/0/0 port (or similar)
    tryInstall("2811_WIC-1T", 0, "2811", {
        container: "child0", slot_type: 2, module_model: "WIC-1T", test_remove: true
    });

    // 2. 2811 + WIC-2T  → expected 2x Serial ports
    tryInstall("2811_WIC-2T", 0, "2811", {
        container: "child0", slot_type: 2, module_model: "WIC-2T"
    });

    // 3. 2911 + HWIC-2T (NIM-style? actually still type 2 on 2911)
    tryInstall("2911_HWIC-2T", 0, "2911", {
        container: "child0", slot_type: 2, module_model: "HWIC-2T"
    });

    // 4. ISR4321 + NIM-2T (slot_type 2 inside chassis child)
    tryInstall("ISR4321_NIM-2T", 0, "ISR4321", {
        container: "child0", slot_type: 2, module_model: "NIM-2T"
    });

    // 5. PC + Linksys-WMP300N  — slot 0 on ROOT is type 7, occupied by a
    //    default cover. Remove it then install.
    tryInstall("PC_WMP300N", 8, "PC-PT", {
        container: "root", slot: 0, remove_default_at: 0, module_model: "Linksys-WMP300N"
    });

    // 6. Laptop + Linksys-WPC300N (root slot 0, ModuleType 9). Default child present.
    tryInstall("Laptop_WPC300N", 18, "Laptop-PT", {
        container: "root", slot: 0, remove_default_at: 0, module_model: "Linksys-WPC300N"
    });

    // 7. 7960 IP phone + IP_PHONE_POWER_ADAPTER.
    //    7960 has root [18], child[0].slots = [11]. So container=child0, slot=0.
    tryInstall("Phone_PowerAdapter", 12, "7960", {
        container: "child0", slot: 0, module_model: "IP_PHONE_POWER_ADAPTER"
    });

    // 8. AccessPoint-PT + ACCESS_POINT_POWER_ADAPTER.
    //    AP has root [6, 18]. Power slot is type 31, not present at root.
    //    Try ModuleType 31 first; fallback explore.
    tryInstall("AP_PowerAdapter", 7, "AccessPoint-PT", {
        container: "root", slot_type: 31, module_model: "ACCESS_POINT_POWER_ADAPTER"
    });

    return report;
})();
