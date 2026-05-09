# pkt-mcp

MCP server that builds Cisco Packet Tracer networks from PDF requirements.

**Status:** WIP, Day 1 spike in progress.

## Architecture

```
Claude Code (Read PDF, reason about topology)
  → stdio → pkt-mcp-server (Python, FastMCP)
  → localhost HTTP/JSON → pt-bridge (Java)
  → PTMP/TCP:39000 → Packet Tracer 9.0.0
  → output.pkt
```

## Requirements

- Linux (tested on Arch), Java 17+, Python 3.11+, [uv](https://docs.astral.sh/uv/)
- Cisco Packet Tracer 9.0.0 (build 9.0.0.0810) running with IPC enabled on `localhost:39000`
- `PT_HOME` env var set to the Packet Tracer install directory (the dir that contains `help/default/ipc/pt-cep-java-framework-*.jar`)

> The Cisco PT framework JARs are not redistributed — they ship with Packet Tracer and are referenced via `$PT_HOME` at build time.
