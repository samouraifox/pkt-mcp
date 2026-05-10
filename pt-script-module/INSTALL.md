# Phase 1B spike: load the bridge Script Module into PT

You'll do this once by hand from PT's GUI. PT's Scripting Interface is the only
way to author a `.pts` file — there's no CLI to load `.js` directly.

## 1. Open the Scripting Interface

`Extensions → Scripting → New PT Script Module`

(If you've already created it before, use `Extensions → Scripting → Configure
PT Script Module → Edit`.)

## 2. General tab

- **Name**: `pkt-mcp Bridge`
- **ID**: `net.pkt-mcp.bridge`
- Leave both password fields blank.
- **Startup**: `On Demand` (we'll start it manually for the test).

## 3. Script Engine tab (this is where the JS goes)

PT 9's tabs are: Info / General / **Script Engine** / Custom Interfaces / Data
Store. Click **Script Engine**.

1. Click **Add** → name the file `main.js`.
2. Open `pt-script-module/main.js` from this repo, copy the whole file, and
   paste it into the editor in PT.
3. Click **Save** in the Scripting Interface (PT will pick a location under
   `~/pt/extensions/` for the encrypted `.pts` — that path is a build
   artifact, not source).

## 4. Privileges

PT 9 has no separate Security tab in this dialog. Privileges are prompted
at runtime: if a popup asks you to allow this Script Module to change the
network, accept it.

## 5. Run it

1. Click **Start** in the Scripting Interface.
2. Open `Extensions → Scripting → Debug Dialog`. Pick the `pkt-mcp Bridge`
   debug log.
3. Look for these lines:

   ```
   [pkt-mcp] start
   [pkt-mcp] typeof ipc=...
   [pkt-mcp] ipc.network() ok, deviceCount=...
   [pkt-mcp] ipc.appWindow() ok
   [pkt-mcp] getActiveWorkspace() ok
   [pkt-mcp] getLogicalWorkspace() ok
   [pkt-mcp] addDevice returned: Router0     ← (or some other auto-name)
   [pkt-mcp] OK created=Router0 renamed=R1
   ```

4. Switch to the PT canvas. **A Cisco 2911 router named R1 should be at
   roughly (200, 200) in the logical workspace.**

## 6. What to send back to me

Either way (working or broken), please paste the full Debug Dialog text from
the run. The probe lines (`typeof ipc=...`, etc.) tell us what API surface is
actually available, which I need before writing the real Script Module +
HTTP-poll bridge.

If `addDevice` failed but earlier probes succeeded, also note any prompt PT
showed about privileges or signing — that's likely the next thing to fix.

---

## Refreshing after edits to `main.js` or `api.js`

The body above is the *first-time install* (Phase 1B). The current bundle
has TWO files in the Script Engine — `main.js` (dispatcher / mailbox
listener) and `api.js` (typed op handlers, Phase 3+). When you edit either
file on disk, the encrypted `.pts` PT loaded does NOT auto-update — PT runs
its baked-in copy. To refresh:

1. **Extensions → Scripting → Configure PT Script Module → pkt-mcp Bridge**
2. Click **Stop**.
3. **Edit** → in the Script Engine tab, for **each changed file**, paste
   the latest source from this repo's `pt-script-module/`. Both files must
   exist in the bundle: `main.js` first, `api.js` second (load order
   doesn't matter at run time, but keep them named exactly that — `main.js`
   is what PT calls on `Start`).
4. Click **Save** — PT re-Exports the encrypted `.pts`.
5. Click **Start**.

**Verify the bundle is the version on disk:**

```
uv run python -c 'from tools.pkt_bridge import Bridge; print(Bridge(timeout=5).list_devices())'
```

A response (even `[]`) means the dispatcher is loaded. `TimeoutError` means
the listener didn't start — recheck Steps 1-5.

**Two symptoms that always mean "stale bundle, reload it":**

- A typed op returns `"... not implemented yet — Step N probe pending"`.
  That's a Phase 3-era stub; on-disk `api.js` has the real handler.
- An op fails with `UNKNOWN_OP` for an op that exists in `api.js`'s
  `DISPATCH` table.

This is the only manual GUI step in the project. Flag it loudly when
something looks wrong rather than chasing the symptom further.
