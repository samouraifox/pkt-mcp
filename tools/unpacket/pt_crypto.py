"""PT .pkt file encrypt/decrypt — vendored from Punkcake21/Unpacket (MIT).

Self-contained: decrypt_pkt(bytes) -> xml_bytes  and  encrypt_pkt_xml(xml_bytes) -> pkt_bytes.

The pipeline (each direction inverts the other):
    decrypt:  stage1_deobf → Twofish-EAX decrypt → stage2_deobf → Qt uncompress
    encrypt:  Qt compress → stage2_obf → Twofish-EAX encrypt → stage1_obf

Hardcoded key/IV are the constants Cisco uses in every PT 6/7/8/9 binary —
extracted by reverse-engineering, verified working on PT 9.0.0.0810 (May 2026).
"""

from __future__ import annotations

import struct
import zlib

from .eax import EAX
from .twofish import Twofish

# Constants extracted from PT binary (same across PT 6-9).
_KEY = bytes([137]) * 16
_IV  = bytes([16]) * 16


# ── obfuscation layers ─────────────────────────────────────────────────────


def _deobf_stage1(data: bytes) -> bytes:
    L = len(data)
    return bytes(data[L - 1 - i] ^ (L - i * L & 0xFF) for i in range(L))


def _obf_stage1(data: bytes) -> bytes:
    L = len(data)
    out = bytearray(L)
    for i in range(L):
        out[L - 1 - i] = data[i] ^ ((L - i * L) & 0xFF)
    return bytes(out)


def _obf_stage2(data: bytes) -> bytes:
    """XOR mask — symmetric, used in both directions."""
    L = len(data)
    return bytes(b ^ (L - i & 0xFF) for i, b in enumerate(data))


# ── Qt compression (zlib with 4-byte big-endian size prefix) ───────────────


def _qt_compress(xml: bytes) -> bytes:
    return struct.pack(">I", len(xml)) + zlib.compress(xml)


def _qt_uncompress(blob: bytes) -> bytes:
    size = struct.unpack(">I", blob[:4])[0]
    return zlib.decompress(blob[4:])[:size]


# ── high-level pipelines ───────────────────────────────────────────────────


def decrypt_pkt(pkt: bytes) -> bytes:
    """Take encrypted .pkt bytes, return the inner XML bytes."""
    stage1 = _deobf_stage1(pkt)
    tf = Twofish(_KEY)
    eax = EAX(tf.encrypt)
    decrypted = eax.decrypt(nonce=_IV, ciphertext=stage1[:-16], tag=stage1[-16:])
    return _qt_uncompress(_obf_stage2(decrypted))


def encrypt_pkt_xml(xml: bytes) -> bytes:
    """Take XML bytes, return encrypted .pkt bytes (PT-loadable)."""
    compressed = _qt_compress(xml)
    stage2 = _obf_stage2(compressed)
    tf = Twofish(_KEY)
    eax = EAX(tf.encrypt)
    ciphertext, tag = eax.encrypt(nonce=_IV, plaintext=stage2)
    return _obf_stage1(ciphertext + tag)
