// Phase 4.11 — zones probe 3: specific signatures based on C++ symbols.
//
// From the binary:
//   CLogicalWorkspace::drawCircle(int, int, double, int, int, int, int)
//   CLogicalWorkspace::drawLine(int, int, int, int, double, int, int, int, int)
//   CLogicalWorkspace::addNote(int, int, double, QString)
//
// Color hypothesis: PT typically packs colors as ARGB 32-bit ints. Try
// drawCircle(x, y, lineWidth, w, h, fillColorARGB, lineColorARGB).
//
// Cleanup: any test artifacts go in the (5000, 5000) zone and are
// removed via removeCanvasItem.

(function () {
    var report = { results: {}, created_items: [], cleanup_log: [], errors: [] };
    var lw = ipc.appWindow().getActiveWorkspace().getLogicalWorkspace();

    function before_rect()    { try { return lw.getCanvasRectIds()    || []; } catch (e) { return []; } }
    function before_ellipse() { try { return lw.getCanvasEllipseIds() || []; } catch (e) { return []; } }
    function before_line()    { try { return lw.getCanvasLineIds()    || []; } catch (e) { return []; } }
    function before_note()    { try { return lw.getCanvasNoteIds()    || []; } catch (e) { return []; } }

    function diff(a, b) {
        var s = {};
        for (var i = 0; i < a.length; i++) s[String(a[i])] = true;
        var out = [];
        for (var j = 0; j < b.length; j++) if (!s[String(b[j])]) out.push(b[j]);
        return out;
    }

    function record(name, fn, kind) {
        var bRect = before_rect(), bEll = before_ellipse(),
            bLine = before_line(), bNote = before_note();
        var ret = null, err = null;
        try { ret = fn(); }
        catch (e) { err = String(e); }
        var aRect = before_rect(), aEll = before_ellipse(),
            aLine = before_line(), aNote = before_note();
        var newR = diff(bRect, aRect), newE = diff(bEll, aEll),
            newL = diff(bLine, aLine), newN = diff(bNote, aNote);
        var info = {
            trial: name,
            returned: (ret === null || ret === undefined) ? String(ret) : ret,
            error: err,
            new_rect_ids: newR,
            new_ellipse_ids: newE,
            new_line_ids: newL,
            new_note_ids: newN
        };
        // capture schema for first new of each kind
        function captureData(getter, ids, key) {
            if (ids.length > 0) {
                try {
                    var d = getter(ids[0]);
                    info[key] = d;
                } catch (e) { info[key] = "threw: " + e; }
            }
        }
        captureData(function (id) { return lw.getRectItemData(id); }, newR, "rect_data");
        captureData(function (id) { return lw.getEllipseItemData(id); }, newE, "ellipse_data");
        captureData(function (id) { return lw.getLineItemData(id); }, newL, "line_data");
        // Notes: just text
        if (newN.length > 0) {
            try { info["note_text"] = lw.getCanvasNoteText(newN[0]); }
            catch (e) { info["note_text"] = "threw: " + e; }
        }
        // Remember everything new for cleanup
        for (var i = 0; i < newR.length; i++) report.created_items.push(newR[i]);
        for (var i = 0; i < newE.length; i++) report.created_items.push(newE[i]);
        for (var i = 0; i < newL.length; i++) report.created_items.push(newL[i]);
        for (var i = 0; i < newN.length; i++) report.created_items.push(newN[i]);
        report.results[name] = info;
    }

    // ── A. drawCircle — based on C++ signature (2 int, 1 double, 4 int) ──
    // Hypothesis: (x, y, lineWidthOrAngle_double, w, h, fillARGB, lineARGB)
    // ARGB packed: alpha << 24 | r << 16 | g << 8 | b
    var ARGB_PINK   = (0xFF << 24) | (0xFF << 16) | (0xC0 << 8) | 0xCB;  // pink #FFC0CB
    var ARGB_BLACK  = (0xFF << 24) | 0;
    var ARGB_RED    = (0xFF << 24) | (0xFF << 16);
    var ARGB_TRANSP = 0;  // alpha=0 → transparent

    record("drawCircle(x,y,2.0,w,h,fillARGB,lineARGB)", function () {
        return lw.drawCircle(5000, 5000, 2.0, 200, 100, ARGB_PINK, ARGB_BLACK);
    });
    // Alternative: 4 trailing ints could be r,g,b,a (single color)
    record("drawCircle(x,y,2.0,w,h_RGB+A_as_4_ints?)", function () {
        return lw.drawCircle(5300, 5000, 2.0, 0xFF, 0x00, 0x00, 0xFF);
    });

    // ── B. drawLine — (4 int, 1 double, 4 int) ───────────────────────────
    // Hypothesis: (x1, y1, x2, y2, width_double, r, g, b, a)
    record("drawLine(x1,y1,x2,y2,2.0,0,0,0,255)", function () {
        return lw.drawLine(5000, 5200, 5300, 5200, 2.0, 0, 0, 0, 255);
    });
    // Or: (x1, y1, x2, y2, width, lineARGB, ?, ?, ?)
    record("drawLine(x1,y1,x2,y2,2.0,ARGB_BLACK,0,0,0)", function () {
        return lw.drawLine(5000, 5250, 5300, 5250, 2.0, ARGB_BLACK, 0, 0, 0);
    });

    // ── C. addNote — (int, int, double, QString) ─────────────────────────
    // Hypothesis: (x, y, fontSize_double, "text")
    record("addNote(x,y,1.0,'text')", function () {
        return lw.addNote(5000, 5400, 1.0, "ZoneLabelTest");
    });
    record("addNote(x,y,12.0,'text')", function () {
        return lw.addNote(5100, 5400, 12.0, "ZoneLabelTest2");
    });

    // ── D. addCluster — try varied signatures ─────────────────────────────
    // C++ has addCluster(QPoint, CDeviceDescriptor*). Bridge may convert.
    // Try things that match common bridge patterns.
    record("addCluster(x,y)_as_two_ints", function () {
        return lw.addCluster(5000, 5500);
    });
    record("addCluster('name',x,y)", function () {
        return lw.addCluster("ZoneA", 5200, 5500);
    });
    record("addCluster(x,y,'name')", function () {
        return lw.addCluster(5400, 5500, "ZoneB");
    });
    record("addCluster(x,y,w,h,'name')", function () {
        return lw.addCluster(5600, 5500, 300, 200, "ZoneC");
    });
    // Maybe it takes an item id (promote shape to cluster)
    record("addCluster('1-1')_promote_root", function () {
        return lw.addCluster("1-1");
    });
    record("addCluster_no_args", function () {
        return lw.addCluster();
    });

    // After all addCluster trials, check whether root cluster grew
    try {
        var root = lw.getRootCluster();
        report.results["root_cluster_after"] = {
            getName: root.getName(),
            getId: root.getId(),
            getChildClusterCount: root.getChildClusterCount(),
        };
    } catch (e) { report.errors.push("root inspection: " + e); }

    // ── E. drawCircle with line-only (alpha=0 fill) to test if "outline-only" works
    record("drawCircle_outline_only(transparent_fill)", function () {
        return lw.drawCircle(5800, 5000, 2.0, 200, 100, ARGB_TRANSP, ARGB_BLACK);
    });

    // ── F. Cleanup ────────────────────────────────────────────────────────
    for (var i = 0; i < report.created_items.length; i++) {
        try {
            lw.removeCanvasItem(report.created_items[i]);
            report.cleanup_log.push("removed " + report.created_items[i]);
        } catch (e) {
            report.cleanup_log.push("failed " + report.created_items[i] + ": " + e);
        }
    }

    return report;
})();
