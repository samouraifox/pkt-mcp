"""pkt_services — programmatic Server-PT service toggling for PT 9.

Background: PT 9 hides Server-PT service config (HTTP/DNS/DHCP/SMTP/NTP/Syslog/
RADIUS/FTP/TFTP/POP3) behind a GUI Services tab. The C++ classes (CServerHttp,
CServerDns, etc.) are Q_INVOKABLE but unreachable from the device's JS surface
(verified by two rounds of probing in phase 4.7+4.8). The only programmatic
path is the .pkt file itself: decrypt → patch XML enable flag → re-encrypt.

PT 9 uses the same Twofish-EAX + obfuscation pipeline as prior versions; the
crypto is broken & vendored from Punkcake21/Unpacket (MIT, see tools/unpacket/).

This module exposes one function:

    set_pkt_services(pkt_path, services)

where `services` is a {device_name: {service_name: enabled_bool, ...}, ...}
dict. The .pkt is decrypted, every requested flag flipped in place, and
re-encrypted to the same path. Reopen the file in PT to see the change.

Limitations:
- Top-level on/off only. Doesn't add DNS records, HTTP files, DHCP pools,
  POP3 mailboxes — those need richer XML manipulation, future work.
- DHCP is per-port, not a single flag — also future work.
- Operates on the saved file, not the live PT in-memory state. To see the
  change in a running PT session: save → patch → reopen the file.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Mapping

# Importable when run from pkt-mcp root: `from tools.unpacket.pt_crypto import …`.
# When the bridge module path-shim adds tools/ to sys.path, this still works
# because Python resolves `unpacket` relative to that path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unpacket.pt_crypto import decrypt_pkt, encrypt_pkt_xml  # noqa: E402


# ── service schema ─────────────────────────────────────────────────────────
#
# Each entry maps a friendly service name to (block_tag, flag_tag) — the XML
# block that wraps the service, and the child tag carrying the enable bit.
# Probed by diff'ing live serializeToXml output before/after GUI clicks in
# phase 4.8 (May 2026). Default values are PT 9.0.0.0810 fresh-server defaults.

_SCHEMA: dict[str, tuple[str, str]] = {
    "HTTP":    ("HTTP_SERVER",   "ENABLED"),         # default ON
    "HTTPS":   ("HTTPS_SERVER",  "HTTPSENABLED"),    # default ON
    "DNS":     ("DNS_SERVER",    "ENABLED"),         # default OFF
    "TFTP":    ("TFTP_SERVER",   "ENABLED"),         # default ON
    "NTP":     ("NTP_SERVER",    "ENABLED"),         # default ON
    "FTP":     ("FTP_SERVER",    "ENABLED"),         # default ON
    "SYSLOG":  ("SYSLOG_SERVER", "ENABLED"),         # default ON
    "AAA":     ("ACS_SERVER",    "ENABLED"),         # default OFF (RADIUS / TACACS+)
    "RADIUS":  ("ACS_SERVER",    "ENABLED"),         # alias for AAA
    "SMTP":    ("EMAIL_SERVER",  "SMTP_ENABLED"),    # default ON
    "POP3":    ("EMAIL_SERVER",  "POP3_ENABLED"),    # default ON
    "NETFLOW": ("NF_COLLECTOR",  "ENABLED"),         # default OFF
}

SERVICE_NAMES = tuple(_SCHEMA.keys())


# ── XML patching ───────────────────────────────────────────────────────────
#
# Strategy: regex-patch within each device's <DEVICE>…</DEVICE> slice. PT
# wraps each device in a NAME element; we use that to scope the search.
# Doing this with regex is acceptable because the format is deterministic
# (PT writes it with consistent indent + whitespace) and a full XML parse
# of 1.5 MB documents would be slow.


_DEVICE_RE = re.compile(r"<DEVICE>(.*?)</DEVICE>", re.DOTALL)
_NAME_RE = re.compile(r"<NAME[^>]*>([^<]+)</NAME>")


def _patch_device_block(block: str, service: str, enabled: bool) -> tuple[str, bool]:
    """Return (new_block, did_change). did_change=False if the service block
    isn't present (caller can warn)."""
    block_tag, flag_tag = _SCHEMA[service]
    target = "1" if enabled else "0"
    # Match <BLOCK_TAG>...<FLAG_TAG>[01]</FLAG_TAG>...</BLOCK_TAG> within block.
    pat = re.compile(
        rf"(<{block_tag}>\s*(?:.*?<{flag_tag}>))[01](</{flag_tag}>)",
        re.DOTALL,
    )
    if not pat.search(block):
        return block, False
    new_block = pat.sub(rf"\g<1>{target}\g<2>", block, count=1)
    return new_block, new_block != block


def _patch_xml(xml: str, services_by_device: Mapping[str, Mapping[str, bool]]
               ) -> tuple[str, dict[str, dict[str, str]]]:
    """Return (patched_xml, report). report[device][service] = "applied" |
    "no_change" | "block_missing" | "device_missing"."""
    report: dict[str, dict[str, str]] = {d: {} for d in services_by_device}

    def replace_device(match: re.Match) -> str:
        block = match.group(1)
        name_m = _NAME_RE.search(block)
        if not name_m:
            return match.group(0)
        device_name = name_m.group(1)
        if device_name not in services_by_device:
            return match.group(0)
        for service, enabled in services_by_device[device_name].items():
            svc_norm = service.upper()
            if svc_norm not in _SCHEMA:
                report[device_name][service] = f"unknown_service"
                continue
            new_block, changed = _patch_device_block(block, svc_norm, enabled)
            if not changed:
                # Could be either "already at requested value" or "block missing".
                # Distinguish by checking presence of block_tag.
                block_tag = _SCHEMA[svc_norm][0]
                if f"<{block_tag}>" not in block:
                    report[device_name][service] = "block_missing"
                else:
                    report[device_name][service] = "no_change"
            else:
                report[device_name][service] = "applied"
                block = new_block
        return f"<DEVICE>{block}</DEVICE>"

    patched = _DEVICE_RE.sub(replace_device, xml)
    # Note which devices weren't found at all.
    for d in services_by_device:
        if not report[d]:
            for svc in services_by_device[d]:
                report[d][svc] = "device_missing"
    return patched, report


# ── public API ─────────────────────────────────────────────────────────────


def set_pkt_services(
    pkt_path: str,
    services: Mapping[str, Mapping[str, bool]],
    *,
    output_path: str | None = None,
) -> dict:
    """Toggle Server-PT services in a saved .pkt file.

    Args:
        pkt_path: Path to the existing .pkt file (will be decrypted).
        services: {device_name: {service_name: enabled_bool, ...}, ...}.
                  Service names are HTTP/HTTPS/DNS/TFTP/NTP/FTP/SYSLOG/
                  AAA/RADIUS/SMTP/POP3/NETFLOW (case-insensitive).
        output_path: Where to write the re-encrypted .pkt. Defaults to
                     overwriting pkt_path.

    Returns:
        {
          "input":  <pkt_path>,
          "output": <output_path>,
          "report": {device: {service: status, ...}, ...},
          "size":   <bytes in output>,
        }
        Status values: "applied" (flipped), "no_change" (already at target),
        "block_missing" (device exists but doesn't have that service block),
        "device_missing" (no device with that name in the .pkt),
        "unknown_service" (service name not in SCHEMA).
    """
    if output_path is None:
        output_path = pkt_path

    with open(pkt_path, "rb") as f:
        encrypted = f.read()

    xml = decrypt_pkt(encrypted).decode("utf-8")
    patched, report = _patch_xml(xml, services)
    out_bytes = encrypt_pkt_xml(patched.encode("utf-8"))

    with open(output_path, "wb") as f:
        f.write(out_bytes)

    return {
        "input":  pkt_path,
        "output": output_path,
        "report": report,
        "size":   len(out_bytes),
    }


# ── CLI for ad-hoc use ─────────────────────────────────────────────────────


def _main(argv: list[str]) -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Toggle Server-PT services in a .pkt file."
    )
    parser.add_argument("pkt", help="Path to .pkt file")
    parser.add_argument(
        "spec",
        help='JSON spec, e.g. \'{"SRV-HTTP": {"HTTP": true, "DNS": true}}\'',
    )
    parser.add_argument("-o", "--output", help="Output path (default: in place)")
    args = parser.parse_args(argv[1:])

    services = json.loads(args.spec)
    result = set_pkt_services(args.pkt, services, output_path=args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    _main(sys.argv)
