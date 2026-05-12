// Phase 4.11 — zone / cluster / drawing / annotation probe.
//
// Goal: discover whether PT 9 exposes any JS-bridge methods for placing
// visual zone primitives (outlined rectangles, filled rectangles, filled
// ellipses) like the ones in the user's reference images. PT's GUI has:
//   - "Add a Cluster" tool (logical workspace clustering, dashed box)
//   - "Place Note" tool (free-text label)
//   - shape-drawing primitives in the toolbar
//
// We need to know if any of those have Q_INVOKABLE bindings.
//
// READ-ONLY: enumerates method surfaces only. No addDevice / no shape
// creation that touches the live canvas.
//
// Returns a structured JSON report.

(function () {
    var report = {
        timestamp: new Date().toISOString(),
        nodes: {},          // path → method names
        cluster_probes: {}, // results of trying common cluster method names
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

    function captureNode(path, obj) {
        if (!obj) {
            report.nodes[path] = "<null>";
            return;
        }
        report.nodes[path] = methodsOf(obj);
    }

    function safe(label, fn) {
        try { return fn(); }
        catch (e) { report.errors.push(label + ": " + e); return null; }
    }

    // ── Phase 1: top-level traversal ──────────────────────────────────────

    safe("ipc", function () { captureNode("ipc", ipc); });
    safe("appWindow", function () { captureNode("appWindow", ipc.appWindow()); });
    safe("activeWorkspace", function () {
        captureNode("activeWorkspace", ipc.appWindow().getActiveWorkspace());
    });
    safe("logicalWorkspace", function () {
        var lw = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace();
        captureNode("logicalWorkspace", lw);
    });
    safe("activeFile", function () {
        captureNode("activeFile", ipc.appWindow().getActiveFile());
    });
    safe("mainNetwork", function () {
        captureNode("mainNetwork", ipc.appWindow().getActiveFile().getMainNetwork());
    });

    // Some PT versions expose a PhysicalWorkspace and EnvironmentManager;
    // probe those too.
    safe("physicalWorkspace", function () {
        var ws = ipc.appWindow().getActiveWorkspace();
        if (typeof ws.getPhysicalWorkspace === "function") {
            captureNode("physicalWorkspace", ws.getPhysicalWorkspace());
        }
    });

    // ── Phase 2: probe for cluster/annotation method names on lw + net ───
    //
    // Many shape/cluster APIs in PT are exposed on the LogicalWorkspace.
    // We test a wide list of candidate names — any that exist tell us the
    // surface area. We DO NOT invoke them (just check `typeof`).

    var candidate_methods = [
        // Cluster APIs (logical workspace clustering)
        "addCluster", "createCluster", "newCluster", "insertCluster",
        "addLogicalCluster", "createLogicalCluster",
        "getCluster", "getClusters", "getClusterCount", "getClusterAt",
        "deleteCluster", "removeCluster",
        "getRoot", "getRootCluster", "getMainCluster",
        // Note / annotation APIs
        "addNote", "createNote", "newNote", "getNote", "getNotes",
        "getNoteCount", "deleteNote", "removeNote",
        "addAnnotation", "getAnnotation", "getAnnotations",
        // Shape / drawing APIs
        "addShape", "addRectangle", "addEllipse", "addCircle", "addLine",
        "addPolygon", "addText", "addLabel", "addDrawing",
        "getShape", "getShapes", "getDrawings",
        "createShape", "createRectangle", "createEllipse",
        // PT-specific (guesses from class names CCluster / CNote / etc.)
        "getCCluster", "addCCluster", "addCNote", "addCShape",
        "getClusterManager", "getDrawingManager", "getAnnotationManager",
        "getNoteManager",
        // Canvas / view methods
        "getCanvas", "getView", "redraw", "refresh",
        // Generic factories
        "create", "add", "insert"
    ];

    var lw_obj, net_obj;
    safe("get_lw_for_probe", function () {
        lw_obj = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace();
    });
    safe("get_net_for_probe", function () {
        net_obj = ipc.appWindow().getActiveFile().getMainNetwork();
    });

    var probe_targets = [
        {label: "logicalWorkspace", obj: lw_obj},
        {label: "mainNetwork",      obj: net_obj}
    ];

    for (var ti = 0; ti < probe_targets.length; ti++) {
        var target = probe_targets[ti];
        if (!target.obj) continue;
        var found = {};
        for (var ci = 0; ci < candidate_methods.length; ci++) {
            var name = candidate_methods[ci];
            try {
                if (typeof target.obj[name] === "function") {
                    found[name] = "function";
                }
            } catch (e) {
                found[name] = "threw: " + e;
            }
        }
        report.cluster_probes[target.label] = found;
    }

    // ── Phase 3: try getRoot()/getMainCluster() if present ────────────────
    // The PT cluster system is hierarchical; the root cluster typically
    // exists from creation. Walking from the root reveals child APIs.

    safe("walk_root_cluster", function () {
        if (!lw_obj) return;
        var root = null;
        if (typeof lw_obj.getRoot === "function") {
            root = lw_obj.getRoot();
        } else if (typeof lw_obj.getRootCluster === "function") {
            root = lw_obj.getRootCluster();
        } else if (typeof lw_obj.getMainCluster === "function") {
            root = lw_obj.getMainCluster();
        }
        if (root) {
            report.nodes["root_cluster"] = methodsOf(root);
            // Try common accessors
            var info = {};
            ["getName", "getId", "getUuid", "getX", "getY", "getWidth",
             "getHeight", "getColor", "getBackgroundColor", "getLabel",
             "getChildCount", "getChildren"].forEach(function (m) {
                try {
                    if (typeof root[m] === "function") {
                        var v = root[m]();
                        info[m] = (v === null || v === undefined) ? String(v)
                                : (typeof v === "object" ? "<object>" : v);
                    }
                } catch (e) {
                    info[m] = "threw: " + e;
                }
            });
            report.nodes["root_cluster_values"] = info;
        } else {
            report.nodes["root_cluster"] = "<no root accessor>";
        }
    });

    // ── Phase 4: look for cluster collections on mainNetwork ─────────────
    // Some PT internals keep clusters indexed on the network. Mirror the
    // device probe pattern (getDeviceCount / getDeviceAt).

    safe("net_cluster_iter", function () {
        if (!net_obj) return;
        var info = {};
        ["getClusterCount", "getClusterAt", "getCluster",
         "getNoteCount", "getNoteAt", "getNote",
         "getAnnotationCount", "getAnnotationAt"].forEach(function (m) {
            info[m] = (typeof net_obj[m] === "function") ? "function" : "absent";
        });
        report.nodes["mainNetwork_cluster_accessors"] = info;
    });

    return report;
})();
