// pkt-mcp Phase 3 — file-mailbox listener with structured op/args dispatch.
//
// Polls /tmp/pkt-mcp/cmd.json every 500 ms. Reads {id, op, args}. Looks up
// op in DISPATCH (defined in api.js, loaded alongside this script by the
// .pts module bundle). Calls the handler, atomically writes result.json
// with {id, result, error, logs}.
//
// Handlers may be sync (return result, or throw an Error with .error_type
// on failure) or async (return DEFER, then call done(result, errorOrNull)
// later). The mailbox is single-slot — `busy` suspends polling between
// read of cmd.json and the eventual write of result.json, so async ops
// (configure_interface, ROUTER add_device) don't race a follow-up command.
//
// Mailbox protocol:
//   Python writes  /tmp/pkt-mcp/cmd.json.tmp,    renames to cmd.json
//   SE     reads   /tmp/pkt-mcp/cmd.json,        deletes after read
//   SE     writes  /tmp/pkt-mcp/result.json.tmp, renames to result.json
//   Python reads   /tmp/pkt-mcp/result.json,     deletes after read
//
// Command shape: {"id": <str>, "op": <op_name>, "args": {...}}
// Result  shape: {"id": <same>,
//                 "result": <op-specific|null>,
//                 "error":  null | {error_type, error_message, error_data?},
//                 "logs":   [<dprint strings during eval>]}
//
// op:"raw" is a Phase 2 escape hatch retained for ad-hoc probing —
// args.code is eval()'d. Production callers (the typed bridge client, the
// Phase 4 MCP server) must not use it.

var MAILBOX     = "/tmp/pkt-mcp";
var CMD_PATH    = MAILBOX + "/cmd.json";
var RESULT_PATH = MAILBOX + "/result.json";
var POLL_MS     = 500;

var sfm        = null;
var pollTimer  = null;
var realDprint = dprint;
var busy       = false;

function writeAtomic(path, content) {
    var tmp = path + ".tmp";
    sfm.writePlainTextToFile(tmp, content);
    sfm.moveSrcFileToDestFile(tmp, path, true);
}

function buildErrorEnvelope(errorObj) {
    if (!errorObj) return null;
    var env = {
        error_type:    errorObj.error_type || "INTERNAL",
        error_message: String(errorObj.message || errorObj)
    };
    if (errorObj.error_data !== undefined && errorObj.error_data !== null) {
        env.error_data = errorObj.error_data;
    }
    return env;
}

function buildResult(id, result, errorObj, logs) {
    var envelope = {
        id:     (id == null) ? null : id,
        result: (result === undefined) ? null : result,
        error:  buildErrorEnvelope(errorObj),
        logs:   logs
    };
    try {
        return JSON.stringify(envelope);
    } catch (e) {
        // Cyclic / non-jsonable result — downgrade and flag.
        return JSON.stringify({
            id: envelope.id,
            result: null,
            error: {
                error_type:    "INTERNAL",
                error_message: "result not JSON-serializable: " + e,
                error_data:    { stringified: String(result) }
            },
            logs: logs
        });
    }
}

function finishCommand(id, result, errorObj, logs) {
    dprint = realDprint;
    writeAtomic(RESULT_PATH, buildResult(id, result, errorObj, logs));
    busy = false;
}

function handleCommand(raw) {
    busy = true;
    var logs = [];
    dprint = function (msg) { logs.push(String(msg)); realDprint(msg); };

    var cmd, id = null, op = null, args = null;
    try {
        cmd = JSON.parse(raw);
        id = cmd.id;
        op = cmd.op;
        args = cmd.args || {};
    } catch (e) {
        finishCommand(null, null,
            { error_type: "BAD_ARGS", message: "cmd parse failed: " + e },
            logs);
        return;
    }

    // Phase 2 raw-eval escape hatch (debug only).
    if (op === "raw") {
        var code = (args && args.code) || "";
        var rawResult = null, rawError = null;
        try { rawResult = eval(code); }
        catch (e) { rawError = { error_type: "INTERNAL", message: String(e) }; }
        finishCommand(id, rawResult, rawError, logs);
        return;
    }

    var handler = DISPATCH[op];
    if (!handler) {
        finishCommand(id, null,
            { error_type: "UNKNOWN_OP",
              message: "no such op: " + String(op),
              error_data: { available: Object.keys(DISPATCH) } },
            logs);
        return;
    }

    var ret;
    try {
        ret = handler(args, function done(result, errorObj) {
            finishCommand(id, result, errorObj, logs);
        });
    } catch (e) {
        // Sync error path. If the thrown object has .error_type it's a
        // typed error from api.js; otherwise wrap as INTERNAL.
        var typed = (e && e.error_type)
            ? e
            : { error_type: "INTERNAL", message: String(e) };
        finishCommand(id, null, typed, logs);
        return;
    }

    if (ret === DEFER) {
        // Async path — handler will call done() to finish.
        return;
    }

    finishCommand(id, ret, null, logs);
}

function poll() {
    try {
        if (busy) return;
        if (!sfm.fileExists(CMD_PATH)) return;
        var raw = sfm.getFileContents(CMD_PATH);
        sfm.removeFile(CMD_PATH);
        handleCommand(raw);
    } catch (e) {
        realDprint("[pkt-mcp] poll ERR: " + e);
        busy = false;
    }
}

function main() {
    realDprint("[pkt-mcp] phase-3 listener start, mailbox=" + MAILBOX);
    sfm = ipc.systemFileManager();
    if (!sfm.directoryExists(MAILBOX)) sfm.makeDirectory(MAILBOX);
    try { sfm.removeFile(CMD_PATH); } catch (e) {}
    try { sfm.removeFile(RESULT_PATH); } catch (e) {}
    pollTimer = setInterval(poll, POLL_MS);
    realDprint("[pkt-mcp] listener ready, ops=" + Object.keys(DISPATCH).join(","));
}

function cleanUp() {
    if (pollTimer) {
        try { clearInterval(pollTimer); } catch (e) {}
        pollTimer = null;
    }
    realDprint("[pkt-mcp] listener stopped");
}
