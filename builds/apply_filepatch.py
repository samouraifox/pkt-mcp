"""File-patch for corporate-network.pkt.

Applies:
1. Service toggles on DMZ servers + CO_Server
2. DNS records on SRV_DNS (cisco.com zone)
3. HTTP file content on SRV_HTTP
4. Wireless SSIDs on 12 APs (matching dept SSIDs)
5. Wireless client profiles on 24 hosts (12 IoT + 12 LT) — auto-associate
   to dept AP on file load (phase 5.4 tool)
6. Colored zones + NOTE labels (CENTRAL pink, BRANCH olive, Mobile orange,
   ISP green ellipse, DMZ cyan + IoT type + VLAN summary labels)

Reads corporate-network.pkt, writes back in place.
"""

import sys
sys.path.insert(0, '/home/samouraifox/Work/Projects/pkt-mcp/tools')

from pkt_services import (
    set_pkt_services,
    set_pkt_dns_records,
    set_pkt_http_files,
    set_pkt_ap_wireless,
    set_pkt_dhcp_pools,
    set_pkt_wireless_client,
)
from pkt_zones import set_pkt_zones

PKT = "/home/samouraifox/Work/Projects/pkt-mcp/builds/corporate-network.pkt"

# 1. Services on DMZ servers + CO_Server
SERVICES = {
    "SRV_HTTP":   {"HTTP": True, "HTTPS": True},
    "SRV_DNS":    {"DNS": True},
    "SRV_NTP":    {"NTP": True},
    "SRV_EMAIL":  {"SMTP": True, "POP3": True},
    "SRV_SYSLOG": {"SYSLOG": True},
    "SRV_IOTAAA": {"AAA": True, "IoT": True},
    "CO_Server":  {"DHCP": True, "DNS": True, "HTTP": True},
}
print("[1/6] Applying services...")
result = set_pkt_services(PKT, SERVICES)
print(f"      {result}")

# 2. DNS records
print("[2/6] Applying DNS records...")
DNS_RECORDS = {
    "SRV_DNS": {
        "cisco.com":     "90.64.110.1",
        "www.cisco.com": "90.64.110.1",
        "mail.cisco.com": "90.64.110.4",
        "ntp.cisco.com":  "90.64.110.3",
        "aaa.cisco.com":  "90.64.110.6",
        "syslog.cisco.com": "90.64.110.5",
    }
}
try:
    result = set_pkt_dns_records(PKT, DNS_RECORDS)
    print(f"      {result}")
except Exception as e:
    print(f"      DNS records failed: {e}")

# 3. HTTP content
print("[3/6] Applying HTTP files...")
HTTP_FILES = {
    "SRV_HTTP": {
        "index.html": (
            "<html><head><title>Cisco Corporate Network</title></head>"
            "<body><h1>Welcome to Cisco Corporate Network</h1>"
            "<p>Central HQ &amp; Branch Office - IPSec VPN tunnel active</p>"
            "<p>Departments: TPK, TP, SiTi, MIT, KS, FMU (Central) | SP, LV, RLZ, MK, PM, FM (Branch)</p>"
            "</body></html>"
        )
    }
}
try:
    result = set_pkt_http_files(PKT, HTTP_FILES)
    print(f"      {result}")
except Exception as e:
    print(f"      HTTP files failed: {e}")

# 4. Wireless SSIDs
print("[4/6] Applying wireless SSIDs...")
WIRELESS = {
    "AP_TPK":  {"ssid": "TPK",  "auth": "wpa2-psk", "passphrase": "CISCO123"},
    "AP_TP":   {"ssid": "TP",   "auth": "wpa2-psk", "passphrase": "CISCO124"},
    "AP_SITI": {"ssid": "SITI", "auth": "wpa2-psk", "passphrase": "CISCO125"},
    "AP_MIT":  {"ssid": "MIT",  "auth": "wpa2-psk", "passphrase": "CISCO126"},
    "AP_KS":   {"ssid": "KS",   "auth": "wpa2-psk", "passphrase": "CISCO127"},
    "AP_FMU":  {"ssid": "FMU",  "auth": "wpa2-psk", "passphrase": "CISCO128"},
    "AP_SP":   {"ssid": "SP",   "auth": "wpa2-psk", "passphrase": "CISCO129"},
    "AP_LV":   {"ssid": "LV",   "auth": "wpa2-psk", "passphrase": "CISCO130"},
    "AP_RLZ":  {"ssid": "RLZ",  "auth": "wpa2-psk", "passphrase": "CISCO131"},
    "AP_MK":   {"ssid": "MK",   "auth": "wpa2-psk", "passphrase": "CISCO132"},
    "AP_PM":   {"ssid": "PM",   "auth": "wpa2-psk", "passphrase": "CISCO133"},
    "AP_FM":   {"ssid": "FM",   "auth": "wpa2-psk", "passphrase": "CISCO134"},
}
try:
    result = set_pkt_ap_wireless(PKT, WIRELESS)
    print(f"      {result}")
except Exception as e:
    print(f"      Wireless failed: {e}")

# 5. Wireless clients — auto-associate 12 IoT + 12 Laptops to their dept AP
print("[5/6] Applying wireless client profiles (12 IoT + 12 LT)...")

# Per-dept SSID/PSK is the same as the AP side. Static IPs are chosen high in
# each /27 (central) or /28 (branch) to stay clear of likely DHCP pools and
# wired hosts. Gateway is .1 of each subnet (the SVI on MLSx_C / MLSx_P).
_DEPT_CENTRAL = [
    # (dept,    ssid,    psk,         net_base,         gw,             iot_ip,           lt_ip)
    ("TPK",  "TPK",  "CISCO123", "192.168.170.0",   "192.168.170.1",   "192.168.170.20",   "192.168.170.21"),
    ("TP",   "TP",   "CISCO124", "192.168.170.32",  "192.168.170.33",  "192.168.170.52",   "192.168.170.53"),
    ("SITI", "SITI", "CISCO125", "192.168.170.64",  "192.168.170.65",  "192.168.170.84",   "192.168.170.85"),
    ("MIT",  "MIT",  "CISCO126", "192.168.170.96",  "192.168.170.97",  "192.168.170.116",  "192.168.170.117"),
    ("KS",   "KS",   "CISCO127", "192.168.170.128", "192.168.170.129", "192.168.170.148",  "192.168.170.149"),
    ("FMU",  "FMU",  "CISCO128", "192.168.170.160", "192.168.170.161", "192.168.170.180",  "192.168.170.181"),
]
_DEPT_BRANCH = [
    ("SP",   "SP",   "CISCO129", "192.168.171.0",   "192.168.171.1",   "192.168.171.10",   "192.168.171.11"),
    ("LV",   "LV",   "CISCO130", "192.168.171.16",  "192.168.171.17",  "192.168.171.26",   "192.168.171.27"),
    ("RLZ",  "RLZ",  "CISCO131", "192.168.171.32",  "192.168.171.33",  "192.168.171.42",   "192.168.171.43"),
    ("MK",   "MK",   "CISCO132", "192.168.171.48",  "192.168.171.49",  "192.168.171.58",   "192.168.171.59"),
    ("PM",   "PM",   "CISCO133", "192.168.171.64",  "192.168.171.65",  "192.168.171.74",   "192.168.171.75"),
    ("FM",   "FM",   "CISCO134", "192.168.171.80",  "192.168.171.81",  "192.168.171.90",   "192.168.171.91"),
]
DNS_GW = "192.168.170.1"  # any L3 gateway works; pick MLS1_C
WIRELESS_CLIENTS = {}
for dept, ssid, psk, _net, gw, iot_ip, lt_ip in _DEPT_CENTRAL:
    mask = "255.255.255.224"  # /27
    WIRELESS_CLIENTS[f"IoT_{dept}"] = {
        "ssid": ssid, "auth": "wpa2-psk", "passphrase": psk,
        "ip": iot_ip, "mask": mask, "gateway": gw, "dns": "90.64.110.2",
    }
    WIRELESS_CLIENTS[f"LT_{dept}"] = {
        "ssid": ssid, "auth": "wpa2-psk", "passphrase": psk,
        "ip": lt_ip, "mask": mask, "gateway": gw, "dns": "90.64.110.2",
    }
for dept, ssid, psk, _net, gw, iot_ip, lt_ip in _DEPT_BRANCH:
    mask = "255.255.255.240"  # /28
    WIRELESS_CLIENTS[f"IoT_{dept}"] = {
        "ssid": ssid, "auth": "wpa2-psk", "passphrase": psk,
        "ip": iot_ip, "mask": mask, "gateway": gw, "dns": "90.64.110.2",
    }
    WIRELESS_CLIENTS[f"LT_{dept}"] = {
        "ssid": ssid, "auth": "wpa2-psk", "passphrase": psk,
        "ip": lt_ip, "mask": mask, "gateway": gw, "dns": "90.64.110.2",
    }
try:
    result = set_pkt_wireless_client(PKT, WIRELESS_CLIENTS)
    print(f"      {result}")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"      Wireless client patch failed: {e}")

# 6. Zones — colored rectangles matching image 2
print("[6/6] Applying colored zones + IoT labels...")
ZONES = [
    # CENTRAL (pink rectangle background, behind dept LANs + MLS pair)
    {"kind": "rect_filled", "x": 20, "y": 20, "w": 1100, "h": 1170,
     "fill_color": "#FFC0CB", "outline_color": "#A0526B", "label": "CENTRAL"},
    # BRANCH (olive rectangle background)
    {"kind": "rect_filled", "x": 1850, "y": 20, "w": 1100, "h": 1170,
     "fill_color": "#BDB76B", "outline_color": "#8B7E2A", "label": "BRANCH"},
    # Mobile network (orange rectangle, top center)
    {"kind": "rect_filled", "x": 1140, "y": 20, "w": 600, "h": 400,
     "fill_color": "#FFA060", "outline_color": "#C46A1F", "label": "Mobile network 172.18.250.0"},
    # ISP cloud (green ellipse, middle)
    {"kind": "ellipse_filled", "x": 1140, "y": 540, "w": 620, "h": 280,
     "fill_color": "#90EE90", "outline_color": "#006400", "label": "ISP provider — VPN tunnel IPSec"},
    # DMZ (cyan rectangle, bottom)
    {"kind": "rect_filled", "x": 1140, "y": 950, "w": 600, "h": 440,
     "fill_color": "#B0F0F8", "outline_color": "#1C8FA0", "label": "DMZ — VLAN 70 — 90.64.110.0/24"},

    # IoT type labels (since PT 9 only allows generic WirelessEndDevice-PT)
    {"kind": "note", "x": 130, "y": 250, "text": "Webcam IoT_TPK"},
    {"kind": "note", "x": 130, "y": 430, "text": "Thermostat IoT_TP"},
    {"kind": "note", "x": 130, "y": 610, "text": "Webcam IoT_SITI"},
    {"kind": "note", "x": 130, "y": 790, "text": "Thermostat IoT_MIT"},
    {"kind": "note", "x": 130, "y": 970, "text": "Webcam IoT_KS"},
    {"kind": "note", "x": 130, "y": 1150, "text": "Thermostat IoT_FMU"},
    {"kind": "note", "x": 2790, "y": 250, "text": "Thermostat IoT_SP"},
    {"kind": "note", "x": 2790, "y": 430, "text": "Webcam IoT_LV"},
    {"kind": "note", "x": 2790, "y": 610, "text": "Thermostat IoT_RLZ"},
    {"kind": "note", "x": 2790, "y": 790, "text": "Webcam IoT_MK"},
    {"kind": "note", "x": 2790, "y": 970, "text": "Thermostat IoT_PM"},
    {"kind": "note", "x": 2790, "y": 1150, "text": "Webcam IoT_FM"},

    # VLAN labels (per dept)
    {"kind": "note", "x": 50, "y": 50, "text": "VLAN 10 TPK\n192.168.170.0/27\nSSID: TPK / CISCO123"},
    {"kind": "note", "x": 50, "y": 230, "text": "VLAN 20 TP\n192.168.170.32/27\nSSID: TP / CISCO124"},
    {"kind": "note", "x": 50, "y": 410, "text": "VLAN 30 SiTi\n192.168.170.64/27\nSSID: SITI / CISCO125"},
    {"kind": "note", "x": 50, "y": 590, "text": "VLAN 40 MIT\n192.168.170.96/27\nSSID: MIT / CISCO126"},
    {"kind": "note", "x": 50, "y": 770, "text": "VLAN 50 KS\n192.168.170.128/27\nSSID: KS / CISCO127"},
    {"kind": "note", "x": 50, "y": 950, "text": "VLAN 60 FMU\n192.168.170.160/27\nSSID: FMU / CISCO128"},

    {"kind": "note", "x": 2860, "y": 50, "text": "VLAN 80 SP\n192.168.171.0/28\nSSID: SP / CISCO129"},
    {"kind": "note", "x": 2860, "y": 230, "text": "VLAN 90 LV\n192.168.171.16/28\nSSID: LV / CISCO130"},
    {"kind": "note", "x": 2860, "y": 410, "text": "VLAN 100 RLZ\n192.168.171.32/28\nSSID: RLZ / CISCO131"},
    {"kind": "note", "x": 2860, "y": 590, "text": "VLAN 110 MK\n192.168.171.48/28\nSSID: MK / CISCO132"},
    {"kind": "note", "x": 2860, "y": 770, "text": "VLAN 120 PM\n192.168.171.64/28\nSSID: PM / CISCO133"},
    {"kind": "note", "x": 2860, "y": 950, "text": "VLAN 130 FM\n192.168.171.80/28\nSSID: FM / CISCO134"},
]
try:
    result = set_pkt_zones(PKT, ZONES, clear_existing=True)
    print(f"      {result}")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"      Zones failed: {e}")

print("\nDone — corporate-network.pkt patched in place.")
print("Open it fresh in PT to see services/DNS/wireless/zones applied.")
