// pkt-mcp — Phase 2 file-polling listener.
// Polls /tmp/pkt-mcp/cmd.json every 500ms; eval()s cmd.code; atomic-writes
// the response to /tmp/pkt-mcp/result.json. Once loaded the module stays
// running until Stop, so subsequent probes go through the file mailbox
// instead of the PT GUI paste/save/export/restart cycle.
//
// Mailbox protocol:
//   Python writes  /tmp/pkt-mcp/cmd.json.tmp,    renames to cmd.json
//   SE     reads   /tmp/pkt-mcp/cmd.json,        deletes after read
//   SE     writes  /tmp/pkt-mcp/result.json.tmp, renames to result.json
//   Python reads   /tmp/pkt-mcp/result.json,     deletes after read
// Command shape: {"id": <str>, "code": <js source>}
// Result  shape: {"id": <same>, "result": <jsonable>, "error": null|str,
//                 "logs": [<dprint strings during eval>]}

var MAILBOX     = "/tmp/pkt-mcp";
var CMD_PATH    = MAILBOX + "/cmd.json";
var RESULT_PATH = MAILBOX + "/result.json";
var POLL_MS     = 500;

var sfm        = null;
var pollTimer  = null;
var realDprint = dprint;

function writeAtomic(path, content) {
    var tmp = path + ".tmp";
    sfm.writePlainTextToFile(tmp, content);
    sfm.moveSrcFileToDestFile(tmp, path, true);
}

function buildResult(id, result, error, logs) {
    try {
        return JSON.stringify({
            id: (id == null) ? null : id,
            result: (result === undefined) ? null : result,
            error: error,
            logs: logs
        });
    } catch (e) {
        // Cyclic / non-jsonable result; downgrade to string and flag in error.
        return JSON.stringify({
            id: (id == null) ? null : id,
            result: String(result),
            error: (error || "") + " (stringify-failed:" + e + ")",
            logs: logs
        });
    }
}

function handleCommand(raw) {
    var cmd, id = null, code = null;
    try {
        cmd = JSON.parse(raw);
        id = cmd.id;
        code = cmd.code;
    } catch (e) {
        writeAtomic(RESULT_PATH, buildResult(null, null, "parse: " + e, []));
        return;
    }

    var logs = [];
    dprint = function (msg) { logs.push(String(msg)); realDprint(msg); };
    var result = null, error = null;
    try {
        result = eval(code);
    } catch (e) {
        error = String(e);
    } finally {
        dprint = realDprint;
    }
    writeAtomic(RESULT_PATH, buildResult(id, result, error, logs));
}

function poll() {
    try {
        if (!sfm.fileExists(CMD_PATH)) return;
        var raw = sfm.getFileContents(CMD_PATH);
        sfm.removeFile(CMD_PATH);
        handleCommand(raw);
    } catch (e) {
        realDprint("[pkt-mcp] poll ERR: " + e);
    }
}

function main() {
    realDprint("[pkt-mcp] listener start, mailbox=" + MAILBOX);
    sfm = ipc.systemFileManager();
    if (!sfm.directoryExists(MAILBOX)) sfm.makeDirectory(MAILBOX);
    try { sfm.removeFile(CMD_PATH); } catch (e) {}
    try { sfm.removeFile(RESULT_PATH); } catch (e) {}
    pollTimer = setInterval(poll, POLL_MS);
    realDprint("[pkt-mcp] listener ready, poll=" + POLL_MS + "ms");
}

function cleanUp() {
    if (pollTimer) {
        try { clearInterval(pollTimer); } catch (e) {}
        pollTimer = null;
    }
    realDprint("[pkt-mcp] listener stopped");
}
