// Phase 4.11 — zones probe 2: signature + schema discovery.
//
// Phase 1 found: logicalWorkspace exposes addCluster, addNote, drawCircle,
// drawLine, plus getters (getCanvasRectIds, getRectItemData, etc.). Now
// we need the exact call signatures and the data-schema fields (color,
// fill, border, label) so we can implement the MCP tool.
//
// Strategy: place test artifacts at x=5000+ (far off-canvas from NovaCore
// build), capture their data, then DELETE every test item via
// removeCanvasItem / removeCluster. Robust cleanup even on errors.

(function () {
    var report = {
        signatures: {},
        schemas: {},
        cleanup_log: [],
        errors: []
    };

    var lw = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace();
    var created_items = [];       // {id, kind} for cleanup
    var created_clusters = [];    // cluster ids

    function safe(label, fn) {
        try { return fn(); }
        catch (e) { report.errors.push(label + ": " + String(e)); return null; }
    }

    function ids(fn) {
        try {
            var v = fn();
            if (!v) return [];
            if (Array.isArray(v)) return v;
            // Qt sometimes returns variant arrays; coerce.
            var out = [];
            try { for (var i = 0; i < v.length; i++) out.push(v[i]); } catch (e) {}
            return out;
        } catch (e) { return ["<err: " + e + ">"]; }
    }

    function diff(before, after) {
        var s = {};
        for (var i = 0; i < before.length; i++) s[String(before[i])] = true;
        var added = [];
        for (var j = 0; j < after.length; j++) {
            if (!s[String(after[j])]) added.push(after[j]);
        }
        return added;
    }

    // ── A. Probe addCluster signature ─────────────────────────────────────
    // Try a sequence of argument shapes until one works.
    safe("addCluster_signatures", function () {
        var trials = [
            {name: "addCluster()", args: function () { return lw.addCluster(); }},
            {name: "addCluster(x,y)", args: function () { return lw.addCluster(5000, 5000); }},
            {name: "addCluster(x,y,w,h)", args: function () { return lw.addCluster(5000, 5000, 200, 150); }},
            {name: "addCluster(parentId,x,y)", args: function () { return lw.addCluster("1-1", 5000, 5000); }},
            {name: "addCluster(parentId,x,y,w,h)", args: function () { return lw.addCluster("1-1", 5000, 5000, 200, 150); }},
            {name: "addCluster(parentId,name,x,y)", args: function () { return lw.addCluster("1-1", "ProbeZ", 5000, 5000); }},
            {name: "addCluster(name,x,y)", args: function () { return lw.addCluster("ProbeZ", 5000, 5000); }},
            {name: "addCluster(name,x,y,w,h)", args: function () { return lw.addCluster("ProbeZ", 5000, 5000, 200, 150); }}
        ];
        var sig_results = [];
        for (var i = 0; i < trials.length; i++) {
            var r = null, err = null;
            try { r = trials[i].args(); }
            catch (e) { err = String(e); }
            sig_results.push({trial: trials[i].name, returned: (r === null || r === undefined) ? String(r) : r, error: err});
            // If a real id came back, remember it for cleanup
            if (r && typeof r === "string" && r !== "" && r !== "undefined") {
                created_clusters.push(r);
            } else if (r && typeof r === "number") {
                created_clusters.push(String(r));
            }
        }
        report.signatures["addCluster"] = sig_results;
    });

    // After signatures probed, capture the root cluster's child list
    // and walk the first new cluster's API surface in depth.
    safe("inspect_first_cluster", function () {
        if (created_clusters.length === 0) return;
        var c = lw.getCluster(created_clusters[0]);
        if (!c) { report.errors.push("getCluster(" + created_clusters[0] + ") returned null"); return; }
        var methods = [];
        for (var k in c) {
            try { if (typeof c[k] === "function") methods.push(k); } catch (e) {}
        }
        try {
            var p = Object.getPrototypeOf(c);
            while (p && p !== Object.prototype) {
                var names = Object.getOwnPropertyNames(p);
                for (var i = 0; i < names.length; i++) {
                    if (methods.indexOf(names[i]) < 0) {
                        try { if (typeof c[names[i]] === "function") methods.push(names[i]); } catch (e) {}
                    }
                }
                p = Object.getPrototypeOf(p);
            }
        } catch (e) {}
        methods.sort();
        report.schemas["cluster_methods"] = methods;

        // Try common getters / setters on cluster
        var probes = ["getName", "getId", "getXCoordinate", "getYCoordinate",
                      "getCenterXCoordinate", "getCenterYCoordinate",
                      "getWidth", "getHeight", "getColor", "getBackgroundColor",
                      "getFillColor", "getBorderColor", "getLabel",
                      "isVisible", "getOpacity", "getIconPath",
                      "getChildClusterCount"];
        var info = {};
        for (var pi = 0; pi < probes.length; pi++) {
            var m = probes[pi];
            try {
                if (typeof c[m] === "function") {
                    var v = c[m]();
                    info[m] = (v === null || v === undefined) ? String(v)
                            : (typeof v === "object" ? "<obj>" : v);
                }
            } catch (e) { info[m] = "threw: " + e; }
        }
        report.schemas["cluster_first_values"] = info;
    });

    // ── B. Probe addNote signature ────────────────────────────────────────
    safe("addNote_signatures", function () {
        var before = ids(function () { return lw.getCanvasNoteIds(); });
        var trials = [
            {name: "addNote(x,y,'text')", args: function () { return lw.addNote(5000, 5100, "ZoneLabelA"); }},
            {name: "addNote('text',x,y)", args: function () { return lw.addNote("ZoneLabelB", 5000, 5150); }},
            {name: "addNote(x,y)", args: function () { return lw.addNote(5000, 5200); }},
            {name: "addNote('text')", args: function () { return lw.addNote("ZoneLabelC"); }}
        ];
        var results = [];
        for (var i = 0; i < trials.length; i++) {
            var r = null, err = null;
            try { r = trials[i].args(); }
            catch (e) { err = String(e); }
            results.push({trial: trials[i].name, returned: (r === null || r === undefined) ? String(r) : r, error: err});
        }
        report.signatures["addNote"] = results;
        var after = ids(function () { return lw.getCanvasNoteIds(); });
        var new_ids = diff(before, after);
        report.signatures["addNote_new_ids"] = new_ids;
        for (var ni = 0; ni < new_ids.length; ni++) {
            created_items.push({id: new_ids[ni], kind: "note"});
        }
        // Capture text of each new note
        var note_texts = {};
        for (var ni2 = 0; ni2 < new_ids.length; ni2++) {
            try { note_texts[String(new_ids[ni2])] = lw.getCanvasNoteText(new_ids[ni2]); }
            catch (e) { note_texts[String(new_ids[ni2])] = "threw: " + e; }
        }
        report.schemas["note_texts"] = note_texts;
    });

    // ── C. Probe drawCircle signature ────────────────────────────────────
    safe("drawCircle_signatures", function () {
        var before = ids(function () { return lw.getCanvasEllipseIds(); });
        var trials = [
            {name: "drawCircle(x,y,r)", args: function () { return lw.drawCircle(5000, 5300, 100); }},
            {name: "drawCircle(x,y,w,h)", args: function () { return lw.drawCircle(5200, 5300, 150, 80); }},
            {name: "drawCircle(x,y,rx,ry)", args: function () { return lw.drawCircle(5400, 5300, 100, 60); }},
            {name: "drawCircle(x,y,w,h,color)", args: function () { return lw.drawCircle(5600, 5300, 100, 60, "#FFC0CB"); }},
            {name: "drawCircle(x1,y1,x2,y2)", args: function () { return lw.drawCircle(5800, 5300, 5900, 5350); }}
        ];
        var results = [];
        for (var i = 0; i < trials.length; i++) {
            var r = null, err = null;
            try { r = trials[i].args(); }
            catch (e) { err = String(e); }
            results.push({trial: trials[i].name, returned: (r === null || r === undefined) ? String(r) : r, error: err});
        }
        report.signatures["drawCircle"] = results;
        var after = ids(function () { return lw.getCanvasEllipseIds(); });
        var new_ids = diff(before, after);
        report.signatures["drawCircle_new_ids"] = new_ids;
        for (var ni = 0; ni < new_ids.length; ni++) {
            created_items.push({id: new_ids[ni], kind: "ellipse"});
        }
        // Inspect schema on the first new ellipse
        if (new_ids.length > 0) {
            try {
                var data = lw.getEllipseItemData(new_ids[0]);
                report.schemas["ellipse_data_keys"] = (data && typeof data === "object") ? Object.keys(data) : String(data);
                report.schemas["ellipse_data_sample"] = data;
            } catch (e) { report.errors.push("getEllipseItemData: " + e); }
        }
    });

    // ── D. Probe drawLine signature (for completeness) ────────────────────
    safe("drawLine_signatures", function () {
        var before = ids(function () { return lw.getCanvasLineIds(); });
        var trials = [
            {name: "drawLine(x1,y1,x2,y2)", args: function () { return lw.drawLine(5000, 5500, 5200, 5500); }},
            {name: "drawLine(x1,y1,x2,y2,color)", args: function () { return lw.drawLine(5000, 5550, 5200, 5550, "#000000"); }}
        ];
        var results = [];
        for (var i = 0; i < trials.length; i++) {
            var r = null, err = null;
            try { r = trials[i].args(); }
            catch (e) { err = String(e); }
            results.push({trial: trials[i].name, returned: (r === null || r === undefined) ? String(r) : r, error: err});
        }
        report.signatures["drawLine"] = results;
        var after = ids(function () { return lw.getCanvasLineIds(); });
        var new_ids = diff(before, after);
        for (var ni = 0; ni < new_ids.length; ni++) {
            created_items.push({id: new_ids[ni], kind: "line"});
        }
        if (new_ids.length > 0) {
            try {
                var data = lw.getLineItemData(new_ids[0]);
                report.schemas["line_data_keys"] = (data && typeof data === "object") ? Object.keys(data) : String(data);
                report.schemas["line_data_sample"] = data;
            } catch (e) {}
        }
    });

    // ── E. Are there hidden rect creators? Check current rect items ──────
    safe("rect_ids_currently", function () {
        report.schemas["existing_rect_ids"] = ids(function () { return lw.getCanvasRectIds(); });
        var rid = report.schemas["existing_rect_ids"];
        if (rid && rid.length > 0 && rid[0] !== undefined) {
            try {
                var data = lw.getRectItemData(rid[0]);
                report.schemas["rect_data_keys"] = (data && typeof data === "object") ? Object.keys(data) : String(data);
                report.schemas["rect_data_sample"] = data;
            } catch (e) { report.errors.push("getRectItemData on existing: " + e); }
        }
    });

    // ── F. Cleanup (best-effort, robust to errors) ────────────────────────
    safe("cleanup", function () {
        for (var i = 0; i < created_items.length; i++) {
            try {
                lw.removeCanvasItem(created_items[i].id);
                report.cleanup_log.push("removed " + created_items[i].kind + " " + created_items[i].id);
            } catch (e) {
                report.cleanup_log.push("failed " + created_items[i].kind + " " + created_items[i].id + ": " + e);
            }
        }
        for (var j = 0; j < created_clusters.length; j++) {
            try {
                lw.removeCluster(created_clusters[j]);
                report.cleanup_log.push("removed cluster " + created_clusters[j]);
            } catch (e) {
                report.cleanup_log.push("failed cluster " + created_clusters[j] + ": " + e);
            }
        }
    });

    return report;
})();
