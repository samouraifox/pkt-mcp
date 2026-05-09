// pkt-mcp — Phase 1B spike Script Module body.
// Purpose: prove a PT Script Module can call the IPC API to add/rename a router,
// without going through the externally-authenticated PTMP/ExApp path.
//
// Source-of-truth file. The encrypted .pts that PT generates after Save is a
// build artifact; do not commit it.
//
// Drop this into the Script Files tab of a new PT Script Module. See
// pt-script-module/INSTALL.md for step-by-step PT GUI instructions.

function main() {
    dprint("[pkt-mcp] start");
    dprint("[pkt-mcp] typeof ipc=" + typeof ipc +
           " typeof DeviceType=" + typeof DeviceType +
           " typeof appWindow=" + typeof appWindow);

    // Probe 1: can we read the network?
    try {
        var n = ipc.network();
        dprint("[pkt-mcp] ipc.network() ok, deviceCount=" + n.getDeviceCount());
    } catch (e) {
        dprint("[pkt-mcp] ipc.network() ERR: " + e);
    }

    // Probe 2: can we reach the active workspace?
    var win, ws, lw;
    try {
        win = ipc.appWindow();
        dprint("[pkt-mcp] ipc.appWindow() ok");
        ws = win.getActiveWorkspace();
        dprint("[pkt-mcp] getActiveWorkspace() ok");
        lw = ws.getLogicalWorkspace();
        dprint("[pkt-mcp] getLogicalWorkspace() ok");
    } catch (e) {
        dprint("[pkt-mcp] workspace chain ERR: " + e);
        return;
    }

    // Probe 3: add a Cisco 2911 router and rename it to R1.
    try {
        // PT's IPC engine wants the int value of the C++ DeviceType enum, not a name
        // string. Confirmed from the framework JAR: ROUTER=0, SWITCH=1, CLOUD=2,
        // BRIDGE=3, HUB=4, REPEATER=5, AP=7, PC=8, SERVER=9, ...
        var devType = 0;
        var name = lw.addDevice(devType, "2911", 200, 200);
        dprint("[pkt-mcp] addDevice returned: " + name);

        var net = win.getActiveFile().getMainNetwork();
        var dev = net.getDevice(name);
        dev.setName("R1");
        dprint("[pkt-mcp] OK created=" + name + " renamed=R1");
    } catch (e) {
        dprint("[pkt-mcp] addDevice ERR: " + e);
    }
}

function cleanUp() {
    dprint("[pkt-mcp] cleanUp");
}
