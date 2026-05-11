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


# ── DNS records, HTTP files, AP wireless (phase 4.9) ──────────────────────
#
# All three follow the same per-device pattern as set_pkt_services: locate
# the <DEVICE>…</DEVICE> block by name, then patch a sub-element. Schemas
# captured by diff'ing serializeToXml around GUI clicks in phase 4.9.


# DNS uses a list of <RESOURCE-RECORD> entries inside NAMESERVER-DATABASE.
# Empty form is <NAMESERVER-DATABASE/> (self-closing); populated form has
# children. We always emit the populated form when records exist, the
# self-closing form when records is empty.
_DNS_DB_RE = re.compile(
    r"<NAMESERVER-DATABASE\s*/>|<NAMESERVER-DATABASE>.*?</NAMESERVER-DATABASE>",
    re.DOTALL,
)


def _render_dns_db(records: Mapping[str, str]) -> str:
    if not records:
        return "<NAMESERVER-DATABASE/>"
    items = []
    for name, ip in records.items():
        items.append(
            "<RESOURCE-RECORD>"
            "<TYPE>A-REC</TYPE>"
            f"<NAME>{name}</NAME>"
            "<TTL>86400</TTL>"
            f"<IPADDRESS>{ip}</IPADDRESS>"
            "</RESOURCE-RECORD>"
        )
    return "<NAMESERVER-DATABASE>" + "".join(items) + "</NAMESERVER-DATABASE>"


def _patch_dns_records(block: str, records: Mapping[str, str]) -> tuple[str, str]:
    """Replace NAMESERVER-DATABASE with the given A-record set (full
    replacement: not additive). Returns (new_block, status)."""
    if "<DNS_SERVER>" not in block:
        return block, "block_missing"
    new_db = _render_dns_db(records)
    new_block, n = _DNS_DB_RE.subn(new_db, block, count=1)
    if n == 0:
        return block, "block_missing"
    if new_block == block:
        return block, "no_change"
    return new_block, "applied"


# HTTP files: each file is a <FILE class="CFile"> entry inside <FILES>.
# To replace content we locate the <FILE> with matching <NAME>, then swap
# the inner <TEXT>. PT escapes '<' as '&lt;' and '&' as '&amp;', leaves '>'
# literal — we mirror that.

def _pt_html_escape(s: str) -> str:
    # Order matters: do '&' first so we don't double-escape.
    return s.replace("&", "&amp;").replace("<", "&lt;")


def _patch_http_files(block: str, files: Mapping[str, str]) -> dict[str, str]:
    """Modify TEXT of each existing <FILE> by NAME. PT auto-creates a small
    set of files (index.html, helloworld.html, copyrights.html, image.html);
    we only modify existing entries. Returns per-file status dict."""
    status: dict[str, str] = {}
    new_block = block
    if "<FILE class=\"CFile\">" not in new_block:
        for f in files:
            status[f] = "block_missing"
        return new_block, status

    for filename, content in files.items():
        escaped = _pt_html_escape(content)
        # Match the FILE block whose NAME tag is exactly filename, then
        # replace the inner TEXT. Use a non-greedy any-char run between
        # <NAME> and <TEXT> so we stay within the same FILE block.
        pat = re.compile(
            r"(<FILE class=\"CFile\">[\s\S]*?<NAME>"
            + re.escape(filename)
            + r"</NAME>[\s\S]*?<TEXT>)[\s\S]*?(</TEXT>)",
            re.DOTALL,
        )
        candidate, n = pat.subn(rf"\g<1>{escaped}\g<2>", new_block, count=1)
        if n == 0:
            status[filename] = "file_missing"
        elif candidate == new_block:
            status[filename] = "no_change"
        else:
            new_block = candidate
            status[filename] = "applied"
    return new_block, status


# AP wireless: <WIRELESS_SERVER><WIRELESS_COMMON> carries SSID, ENCRYPT_TYPE,
# AUTHEN_TYPE, and (for non-open auth) a WEP_PROCESS sub-block. Encoding
# (probed in phase 4.9):
#   open      → ENCRYPT_TYPE=0, AUTHEN_TYPE=0, no WEP_PROCESS
#   wpa2-psk  → ENCRYPT_TYPE=4, AUTHEN_TYPE=4, WEP_PROCESS with KEY=passphrase
# Other modes (WEP, WPA-PSK, WPA2-Enterprise) exist but aren't yet wired —
# capture them on demand and add to _WIRELESS_AUTH_CODES.

_WIRELESS_AUTH_CODES: dict[str, tuple[int, int, int]] = {
    # auth_name: (ENCRYPT_TYPE, AUTHEN_TYPE, WEP_PROCESS_ENCRYPTION)
    "open":     (0, 0, 0),
    "wpa2-psk": (4, 4, 4),
}

_SSID_RE = re.compile(r"<SSID>[^<]*</SSID>")
_ENC_RE = re.compile(r"<ENCRYPT_TYPE>\d+</ENCRYPT_TYPE>")
_AUTH_RE = re.compile(r"<AUTHEN_TYPE>\d+</AUTHEN_TYPE>")
_WEP_RE = re.compile(r"<WEP_PROCESS>[\s\S]*?</WEP_PROCESS>")
_WIRELESS_COMMON_RE = re.compile(
    r"<WIRELESS_COMMON>([\s\S]*?)</WIRELESS_COMMON>"
)


def _patch_ap_wireless(block: str, config: Mapping[str, str | int]) -> tuple[str, str]:
    """Update SSID / auth-mode / passphrase inside <WIRELESS_COMMON>. Config
    keys: ssid (str), auth ('open' | 'wpa2-psk'), passphrase (str, required
    if auth='wpa2-psk'). Missing keys leave the corresponding XML element
    untouched."""
    if "<WIRELESS_SERVER>" not in block:
        return block, "block_missing"

    m = _WIRELESS_COMMON_RE.search(block)
    if not m:
        return block, "block_missing"

    common_inner = m.group(1)
    new_inner = common_inner

    ssid = config.get("ssid")
    if ssid is not None:
        new_inner = _SSID_RE.sub(f"<SSID>{ssid}</SSID>", new_inner, count=1)

    auth = config.get("auth")
    if auth is not None:
        auth_norm = str(auth).lower()
        if auth_norm not in _WIRELESS_AUTH_CODES:
            return block, f"unknown_auth:{auth}"
        enc_v, auth_v, wep_enc_v = _WIRELESS_AUTH_CODES[auth_norm]
        new_inner = _ENC_RE.sub(f"<ENCRYPT_TYPE>{enc_v}</ENCRYPT_TYPE>", new_inner, count=1)
        new_inner = _AUTH_RE.sub(f"<AUTHEN_TYPE>{auth_v}</AUTHEN_TYPE>", new_inner, count=1)

        if auth_norm == "open":
            new_inner = _WEP_RE.sub("", new_inner, count=1)
        else:
            passphrase = config.get("passphrase", "")
            wep_block = (
                "<WEP_PROCESS>"
                f"<KEY>{passphrase}</KEY>"
                "<USERID></USERID>"
                "<PASSWORD></PASSWORD>"
                f"<ENCRYPTION>{wep_enc_v}</ENCRYPTION>"
                "</WEP_PROCESS>"
            )
            if _WEP_RE.search(new_inner):
                new_inner = _WEP_RE.sub(wep_block, new_inner, count=1)
            else:
                # Insert before STANDARD_CHANNEL5G if present, else before
                # the close of WIRELESS_COMMON.
                if "<STANDARD_CHANNEL5G>" in new_inner:
                    new_inner = new_inner.replace(
                        "<STANDARD_CHANNEL5G>", wep_block + "<STANDARD_CHANNEL5G>", 1
                    )
                else:
                    new_inner = new_inner.rstrip() + wep_block

    new_block = block[:m.start(1)] + new_inner + block[m.end(1):]
    if new_block == block:
        return block, "no_change"
    return new_block, "applied"


# ── shared decrypt/encrypt skeleton ───────────────────────────────────────


def _load_xml(pkt_path: str) -> str:
    with open(pkt_path, "rb") as f:
        return decrypt_pkt(f.read()).decode("utf-8")


def _save_pkt(xml: str, output_path: str) -> int:
    out_bytes = encrypt_pkt_xml(xml.encode("utf-8"))
    with open(output_path, "wb") as f:
        f.write(out_bytes)
    return len(out_bytes)


def _patch_each_device(
    xml: str,
    targets: Mapping[str, object],
    patcher,
) -> tuple[str, dict[str, object]]:
    """For each device in `targets`, locate its <DEVICE>…</DEVICE> block by
    <NAME> match and pass it through `patcher(block, targets[device_name])`.
    The patcher must return (new_block, status) where status is anything
    JSON-serializable (string or per-sub-key dict).

    Returns (patched_xml, report) where report[device_name] = status, plus
    "device_missing" for any name never seen in the XML."""
    report: dict[str, object] = {}
    seen: set[str] = set()

    def replace_device(match: re.Match) -> str:
        block = match.group(1)
        name_m = _NAME_RE.search(block)
        if not name_m:
            return match.group(0)
        device_name = name_m.group(1)
        if device_name not in targets:
            return match.group(0)
        seen.add(device_name)
        new_block, status = patcher(block, targets[device_name])
        report[device_name] = status
        return f"<DEVICE>{new_block}</DEVICE>"

    patched = _DEVICE_RE.sub(replace_device, xml)
    for name in targets:
        if name not in seen:
            report[name] = "device_missing"
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
    xml = _load_xml(pkt_path)
    patched, report = _patch_xml(xml, services)
    size = _save_pkt(patched, output_path)
    return {"input": pkt_path, "output": output_path, "report": report, "size": size}


def set_pkt_dns_records(
    pkt_path: str,
    records_by_device: Mapping[str, Mapping[str, str]],
    *,
    output_path: str | None = None,
) -> dict:
    """Replace the DNS A-record set on one or more Server-PTs.

    Args:
        pkt_path: Path to existing .pkt file.
        records_by_device: {device_name: {hostname: ip_address, ...}, ...}.
                          Passing an empty inner dict clears all records for
                          that server. NOT additive — the existing record
                          set is replaced wholesale.
        output_path: Defaults to overwriting pkt_path.

    Returns the same envelope as set_pkt_services. Status per device:
        "applied" / "no_change" / "block_missing" / "device_missing".

    Note: DNS service must also be ENABLED for queries to resolve. Use
    set_pkt_services({"<srv>": {"DNS": True}}) to flip the service flag.
    """
    if output_path is None:
        output_path = pkt_path
    xml = _load_xml(pkt_path)

    def patcher(block: str, records: Mapping[str, str]) -> tuple[str, str]:
        return _patch_dns_records(block, records)

    patched, report = _patch_each_device(xml, records_by_device, patcher)
    size = _save_pkt(patched, output_path)
    return {"input": pkt_path, "output": output_path, "report": report, "size": size}


def set_pkt_http_files(
    pkt_path: str,
    files_by_device: Mapping[str, Mapping[str, str]],
    *,
    output_path: str | None = None,
) -> dict:
    """Replace HTTP file content on one or more Server-PTs.

    Args:
        pkt_path: Path to existing .pkt file.
        files_by_device: {device_name: {filename: html_content, ...}, ...}.
                        filename must match an existing file on the server
                        (PT auto-creates index.html, helloworld.html,
                        copyrights.html, image.html). Content is raw HTML;
                        '<' and '&' are escaped automatically per PT's
                        wire format.
        output_path: Defaults to overwriting pkt_path.

    Returns the same envelope as set_pkt_services. Per-device status is
    itself a dict {filename: status}. file-level status:
        "applied" / "no_change" / "file_missing" / "block_missing".

    Limitation: only modifies existing files. Creating new files would
    require updating <FILE_NUMBER>, <FILE_COUNTER>, and inserting a new
    <FILE> block — not yet implemented.
    """
    if output_path is None:
        output_path = pkt_path
    xml = _load_xml(pkt_path)

    def patcher(block: str, files: Mapping[str, str]) -> tuple[str, dict]:
        return _patch_http_files(block, files)

    patched, report = _patch_each_device(xml, files_by_device, patcher)
    size = _save_pkt(patched, output_path)
    return {"input": pkt_path, "output": output_path, "report": report, "size": size}


def set_pkt_ap_wireless(
    pkt_path: str,
    config_by_device: Mapping[str, Mapping[str, str | int]],
    *,
    output_path: str | None = None,
) -> dict:
    """Set SSID, auth mode, and passphrase on one or more Access Points.

    Args:
        pkt_path: Path to existing .pkt file.
        config_by_device: {device_name: {key: val, ...}, ...} where keys are:
            "ssid":       str — broadcast SSID
            "auth":       "open" | "wpa2-psk"  (case-insensitive)
            "passphrase": str — required iff auth="wpa2-psk", 8-63 chars
            Omitted keys leave the corresponding XML element untouched.
        output_path: Defaults to overwriting pkt_path.

    Returns the same envelope as set_pkt_services. Status per device:
        "applied" / "no_change" / "block_missing" / "device_missing" /
        "unknown_auth:<val>".

    Limitation: only 'open' and 'wpa2-psk' modes wired. WEP, WPA-PSK, and
    WPA2-Enterprise have code points but need probe captures to confirm
    the WEP_PROCESS layout — see _WIRELESS_AUTH_CODES in this module.
    """
    if output_path is None:
        output_path = pkt_path
    xml = _load_xml(pkt_path)

    def patcher(block: str, cfg: Mapping[str, str | int]) -> tuple[str, str]:
        return _patch_ap_wireless(block, cfg)

    patched, report = _patch_each_device(xml, config_by_device, patcher)
    size = _save_pkt(patched, output_path)
    return {"input": pkt_path, "output": output_path, "report": report, "size": size}


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
