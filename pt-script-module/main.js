// pkt-mcp — Phase 2 M1 probe iteration 2.
// First sweep confirmed HUB=4 / PC=8 / SERVER=9 with their guessed models, but
// SWITCH=1 ("2960") and WIRELESS_ROUTER=11 ("WRT300N") returned empty (model
// rejected). Strings on $PT_HOME/bin/PacketTracer point to "2960-24TT" and
// "Linksys-WRT300N" — re-probe with those (plus generic "Switch-PT" as a
// backup) to confirm the JS API accepts them.
//
// Re-run procedure: File → New, then Stop / Start the module.

function main() {
    dprint("[pkt-mcp] phase2 M1 iter2 start");

    var win = ipc.appWindow();
    var lw = win.getActiveWorkspace().getLogicalWorkspace();

    var probes = [
        [1,  "2960-24TT"],         // expect SWITCH (Catalyst default)
        [1,  "Switch-PT"],         // expect SWITCH (generic fallback)
        [11, "Linksys-WRT300N"]    // expect WIRELESS_ROUTER
    ];

    for (var i = 0; i < probes.length; i++) {
        var devType = probes[i][0];
        var model = probes[i][1];
        var x = 100 + i * 200;
        var y = 100;
        try {
            var name = lw.addDevice(devType, model, x, y);
            dprint("[pkt-mcp] N=" + devType + " model=" + model + " -> " + name);
        } catch (e) {
            dprint("[pkt-mcp] N=" + devType + " model=" + model + " ERR: " + e);
        }
    }

    dprint("[pkt-mcp] phase2 M1 iter2 done");
}

function cleanUp() {
    dprint("[pkt-mcp] cleanUp");
}
