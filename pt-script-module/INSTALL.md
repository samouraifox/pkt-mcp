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

## 3. Script Files tab

1. Click **Add** → name it `main.js`.
2. Open `pt-script-module/main.js` from this repo, copy the whole file, and
   paste it into the editor in PT.
3. Click **Save** in the Scripting Interface (this creates a `.pts` somewhere
   under `~/pt/extensions/` or wherever PT prompts you — that path is a build
   artifact, not source).

## 4. Security tab — request the privilege we need

The Script Module needs permission to mutate the network before
`logical.addDevice(...)` will work. In the Security tab, request:

- `PrivChangeNetwork` (Change Network)

If PT lists more granular options, also tick anything obviously related to
"add device" / "modify topology". Save again.

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
