# Unpacket — vendored

The cryptographic decoder for Cisco Packet Tracer .pkt files.
Vendored from https://github.com/Punkcake21/Unpacket — MIT license.

See LICENSE-UNPACKET for the original license.

Files:
  twofish.py  — Twofish block cipher
  cmac.py     — CMAC (OMAC) authentication
  ctr.py      — CTR mode counter engine
  eax.py      — EAX authenticated encryption (AEAD)
  pt_crypto.py — PT-specific obfuscation + crypto wrapper

Used by tools/pkt_services.py to flip Server-PT service enable flags
in saved .pkt files (those services are GUI-only via PT's JS bridge;
file-level XML edit is the only programmatic path).
