"""pkt_zones — programmatic canvas-zone drawing for PT 9 .pkt files.

Adds visual zones (outlined rectangles, filled rectangles, filled ellipses)
plus text labels to a saved .pkt file. The JS bridge exposes addCluster /
drawCircle / drawLine but crashes PT 9.0.0 on bad arguments (verified May
2026 during phase 4.11 probing). The file-patch path bypasses the bridge
entirely.

Three zone kinds, mirroring the visual references the user shared:
  - rect_outline   — outlined rectangle, no fill (Image 1 style)
  - rect_filled    — filled rectangle with outline (Image 2 style)
  - ellipse_filled — filled ellipse with outline (Image 3 style)
  - note           — bare text label (no shape)

A zone with a `label` field additionally produces a NOTE near the shape's
top-left corner.

Public API: `set_pkt_zones(pkt_path, zones, *, output_path, clear_existing)`.

Limitations:
- POLYGONS and freeform LINES not yet wired (uses RECTANGLES + ELLIPSES + NOTES).
- All shapes live in the root cluster ("1-1"). Sub-cluster nesting not yet wired.
- MEM_ADDR is hard-coded to 0 — PT 9 round-trips this fine on reopen
  (it re-assigns its own pointers on load).
"""

from __future__ import annotations

import os
import re
import sys
import uuid as _uuid_mod
from typing import Sequence, Mapping

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unpacket.pt_crypto import decrypt_pkt, encrypt_pkt_xml  # noqa: E402


# ── zone-kind constants ────────────────────────────────────────────────────

ZONE_KINDS = ("rect_outline", "rect_filled", "ellipse_filled", "note")

# Default RGB used when fill_color/outline_color are not supplied. Matches
# PT 9's own default on GUI-drawn shapes.
_DEFAULT_FILL_RGB = (0, 0, 255)   # blue
_DEFAULT_OUTLINE = "#000000"      # black

# Depth (Z) and cluster id PT uses for new shapes by default. Captured from
# diffing a GUI-drawn sample against an empty .pkt in phase 4.11.
_DEFAULT_Z = 0.21
_ROOT_CLUSTER_ID = "1-1"


# ── color helpers ──────────────────────────────────────────────────────────


def _parse_hex_color(s: str) -> tuple[int, int, int]:
    """Accept '#RRGGBB' or 'RRGGBB' and return (r, g, b) ints in 0..255."""
    h = s.strip().lstrip("#")
    if len(h) != 6:
        raise ValueError(f"hex color must be 6 hex digits, got {s!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _normalize_color(c, default_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    if c is None:
        return default_rgb
    if isinstance(c, str):
        return _parse_hex_color(c)
    if isinstance(c, (tuple, list)) and len(c) == 3:
        return int(c[0]), int(c[1]), int(c[2])
    raise ValueError(f"color must be '#RRGGBB' string or (r, g, b) tuple, got {c!r}")


def _hex_from_rgb(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


# ── XML rendering ──────────────────────────────────────────────────────────


def _new_uuid() -> str:
    return "{" + str(_uuid_mod.uuid4()) + "}"


def _render_rectangle(
    x1: int, y1: int, x2: int, y2: int,
    fill_rgb: tuple[int, int, int],
    outline_hex: str,
    filled: bool,
    outlined: bool,
    label_for_placement: str = "",
) -> str:
    """Emit a <RECTANGLE> block matching PT 9's schema exactly."""
    r, g, b = fill_rgb
    f = "1" if filled else "0"
    o = "true" if outlined else "false"
    # Center of the shape used as DevicePlacement_Shape{X,Y} hint
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    return (
        f'  <RECTANGLE uuid="{_new_uuid()}">\n'
        f'   <TopLeftX>{int(x1)}</TopLeftX>\n'
        f'   <TopLeftY>{int(y1)}</TopLeftY>\n'
        f'   <BottomRightX>{int(x2)}</BottomRightX>\n'
        f'   <BottomRightY>{int(y2)}</BottomRightY>\n'
        f'   <Color>\n'
        f'    <Red>{r}</Red>\n'
        f'    <Green>{g}</Green>\n'
        f'    <Blue>{b}</Blue>\n'
        f'   </Color>\n'
        f'   <Filled OUTLINECOLOR="{outline_hex}" OUTLINED="{o}">{f}</Filled>\n'
        f'   <RECTCLUSTERID>{_ROOT_CLUSTER_ID}</RECTCLUSTERID>\n'
        f'   <MEM_ADDR>0</MEM_ADDR>\n'
        f'   <DevicePlacement_ShapeName>{_xml_escape(label_for_placement)}</DevicePlacement_ShapeName>\n'
        f'   <DevicePlacement_ShapeX>{cx}</DevicePlacement_ShapeX>\n'
        f'   <DevicePlacement_ShapeY>{cy}</DevicePlacement_ShapeY>\n'
        f'   <DevicePlacement_ShapeZ>{_DEFAULT_Z}</DevicePlacement_ShapeZ>\n'
        f'  </RECTANGLE>\n'
    )


def _render_ellipse(
    x1: int, y1: int, x2: int, y2: int,
    fill_rgb: tuple[int, int, int],
    outline_hex: str,
    filled: bool,
    outlined: bool,
    label_for_placement: str = "",
) -> str:
    r, g, b = fill_rgb
    f = "1" if filled else "0"
    o = "true" if outlined else "false"
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    return (
        f'  <ELLIPSE uuid="{_new_uuid()}">\n'
        f'   <TopLeftX>{int(x1)}</TopLeftX>\n'
        f'   <TopLeftY>{int(y1)}</TopLeftY>\n'
        f'   <BottomRightX>{int(x2)}</BottomRightX>\n'
        f'   <BottomRightY>{int(y2)}</BottomRightY>\n'
        f'   <Color>\n'
        f'    <Red>{r}</Red>\n'
        f'    <Green>{g}</Green>\n'
        f'    <Blue>{b}</Blue>\n'
        f'   </Color>\n'
        f'   <Filled OUTLINECOLOR="{outline_hex}" OUTLINED="{o}">{f}</Filled>\n'
        f'   <ELLIPSECLUSTERID>{_ROOT_CLUSTER_ID}</ELLIPSECLUSTERID>\n'
        f'   <MEM_ADDR>0</MEM_ADDR>\n'
        f'   <DevicePlacement_ShapeName>{_xml_escape(label_for_placement)}</DevicePlacement_ShapeName>\n'
        f'   <DevicePlacement_ShapeX>{cx}</DevicePlacement_ShapeX>\n'
        f'   <DevicePlacement_ShapeY>{cy}</DevicePlacement_ShapeY>\n'
        f'   <DevicePlacement_ShapeZ>{_DEFAULT_Z}</DevicePlacement_ShapeZ>\n'
        f'  </ELLIPSE>\n'
    )


def _render_note(x: float, y: float, text: str) -> str:
    return (
        f'   <NOTE uuid="{_new_uuid()}">\n'
        f'    <X>{x}</X>\n'
        f'    <Y>{y}</Y>\n'
        f'    <Z>{_DEFAULT_Z}</Z>\n'
        f'    <TEXT translate="true">{_xml_escape(text)}</TEXT>\n'
        f'    <NOTECLUSTERID></NOTECLUSTERID>\n'
        f'    <MEM_ADDR>0</MEM_ADDR>\n'
        f'   </NOTE>\n'
    )


def _xml_escape(s: str) -> str:
    """Mirror PT 9's asymmetric escaping (Phase 4.9): only '<' and '&'."""
    if s is None:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;")


# ── XML insertion ──────────────────────────────────────────────────────────
#
# Three target blocks:
#   <RECTANGLES>...</RECTANGLES>  — workspace root (sibling of CLUSTERS)
#   <ELLIPSES>...</ELLIPSES>      — workspace root
#   <NOTES>...</NOTES>            — INSIDE <PHYSICALWORKSPACE>
#
# In an empty file these are self-closing (e.g. <RECTANGLES/>). Once
# populated they become open/close pairs. We handle both.


_RECTANGLES_EMPTY_RE = re.compile(r"<RECTANGLES\s*/>")
_RECTANGLES_OPEN_RE = re.compile(r"(<RECTANGLES>)(.*?)(</RECTANGLES>)", re.DOTALL)
_ELLIPSES_EMPTY_RE = re.compile(r"<ELLIPSES\s*/>")
_ELLIPSES_OPEN_RE = re.compile(r"(<ELLIPSES>)(.*?)(</ELLIPSES>)", re.DOTALL)

# NOTES is ambiguous (also appears inside DEVICE blocks). Scope to the
# workspace-level one by matching inside the PHYSICALWORKSPACE block.
_PHYSWS_RE = re.compile(r"(<PHYSICALWORKSPACE>)(.*?)(</PHYSICALWORKSPACE>)", re.DOTALL)
_NOTES_EMPTY_RE = re.compile(r"<NOTES\s*/>")
_NOTES_OPEN_RE = re.compile(r"(<NOTES>)(.*?)(</NOTES>)", re.DOTALL)


def _splice_block(xml: str, empty_re: re.Pattern, open_re: re.Pattern,
                  inner_block: str, open_tag: str, close_tag: str,
                  clear_existing: bool) -> str:
    """Replace <X/> with <X>inner</X>, or insert into existing <X>...</X>.
    If clear_existing, drop any existing children before inserting."""
    if empty_re.search(xml):
        return empty_re.sub(f"{open_tag}\n{inner_block} {close_tag}", xml, count=1)
    m = open_re.search(xml)
    if not m:
        # Block doesn't exist at all — append before USER_PROFILE as a
        # reasonable fallback. Should not happen on real PT 9 files.
        return xml
    if clear_existing:
        return open_re.sub(f"{open_tag}\n{inner_block} {close_tag}", xml, count=1)
    existing = m.group(2)
    return open_re.sub(
        f"{open_tag}{existing}{inner_block} {close_tag}", xml, count=1
    )


def _splice_notes(xml: str, notes_block: str, clear_existing: bool) -> str:
    """NOTES lives inside PHYSICALWORKSPACE; scope the patch accordingly."""
    pm = _PHYSWS_RE.search(xml)
    if not pm:
        return xml
    physws_inner = pm.group(2)
    new_inner = _splice_block(
        physws_inner, _NOTES_EMPTY_RE, _NOTES_OPEN_RE,
        notes_block, "<NOTES>", "</NOTES>", clear_existing,
    )
    return _PHYSWS_RE.sub(
        lambda m: f"{m.group(1)}{new_inner}{m.group(3)}",
        xml, count=1,
    )


# ── load / save (mirrors pkt_services) ─────────────────────────────────────


def _load_xml(pkt_path: str) -> str:
    with open(pkt_path, "rb") as f:
        return decrypt_pkt(f.read()).decode("utf-8")


def _save_pkt(xml: str, output_path: str) -> int:
    out_bytes = encrypt_pkt_xml(xml.encode("utf-8"))
    with open(output_path, "wb") as f:
        f.write(out_bytes)
    return len(out_bytes)


# ── per-zone validation + rendering ────────────────────────────────────────


def _validate_zone(idx: int, z: Mapping) -> str:
    kind = z.get("kind")
    if kind not in ZONE_KINDS:
        raise ValueError(
            f"zone[{idx}]: kind must be one of {ZONE_KINDS}, got {kind!r}"
        )
    if kind == "note":
        for k in ("x", "y", "text"):
            if k not in z:
                raise ValueError(f"zone[{idx}] (note): missing required field {k!r}")
    else:
        for k in ("x", "y", "w", "h"):
            if k not in z:
                raise ValueError(
                    f"zone[{idx}] ({kind}): missing required field {k!r} "
                    f"(need x, y, w, h)"
                )
        if int(z["w"]) <= 0 or int(z["h"]) <= 0:
            raise ValueError(f"zone[{idx}]: w and h must be > 0")
    return kind


def _build_zones_xml(zones: Sequence[Mapping]
                     ) -> tuple[str, str, str, dict]:
    """Return (rectangles_xml, ellipses_xml, notes_xml, report)."""
    rects: list[str] = []
    ells: list[str] = []
    notes: list[str] = []
    report = {"rectangles_added": 0, "ellipses_added": 0, "notes_added": 0}

    for i, z in enumerate(zones):
        kind = _validate_zone(i, z)

        if kind == "note":
            notes.append(_render_note(z["x"], z["y"], z["text"]))
            report["notes_added"] += 1
            continue

        x = int(z["x"]); y = int(z["y"])
        w = int(z["w"]); h = int(z["h"])
        x2 = x + w; y2 = y + h
        outline_hex = z.get("outline_color", _DEFAULT_OUTLINE)
        # Normalize outline_color: accept hex string or tuple
        if not isinstance(outline_hex, str):
            outline_hex = _hex_from_rgb(_normalize_color(outline_hex, (0, 0, 0)))
        outlined = bool(z.get("outlined", True))
        label = z.get("label", "")

        if kind == "rect_outline":
            # Outline-only: filled=False; Color block is irrelevant for fill
            # but PT still writes one, so use default blue.
            rects.append(_render_rectangle(
                x, y, x2, y2,
                fill_rgb=_DEFAULT_FILL_RGB,
                outline_hex=outline_hex,
                filled=False,
                outlined=outlined,
                label_for_placement=label,
            ))
            report["rectangles_added"] += 1
        elif kind == "rect_filled":
            fill_rgb = _normalize_color(z.get("fill_color"), _DEFAULT_FILL_RGB)
            rects.append(_render_rectangle(
                x, y, x2, y2,
                fill_rgb=fill_rgb,
                outline_hex=outline_hex,
                filled=True,
                outlined=outlined,
                label_for_placement=label,
            ))
            report["rectangles_added"] += 1
        elif kind == "ellipse_filled":
            fill_rgb = _normalize_color(z.get("fill_color"), _DEFAULT_FILL_RGB)
            ells.append(_render_ellipse(
                x, y, x2, y2,
                fill_rgb=fill_rgb,
                outline_hex=outline_hex,
                filled=True,
                outlined=outlined,
                label_for_placement=label,
            ))
            report["ellipses_added"] += 1

        # If shape has a label, also emit a NOTE near top-left
        if label:
            notes.append(_render_note(
                z.get("label_x", x + 4),
                z.get("label_y", y - 14),
                label,
            ))
            report["notes_added"] += 1

    return "".join(rects), "".join(ells), "".join(notes), report


# ── public API ─────────────────────────────────────────────────────────────


def set_pkt_zones(
    pkt_path: str,
    zones: Sequence[Mapping],
    *,
    output_path: str | None = None,
    clear_existing: bool = False,
) -> dict:
    """Add visual zones to a saved .pkt file.

    Args:
        pkt_path: Existing .pkt to mutate.
        zones: List of zone specs. Each spec is a dict with required key
            `kind` ∈ {"rect_outline", "rect_filled", "ellipse_filled", "note"}.

            For rect_outline / rect_filled / ellipse_filled:
                x, y (int, top-left of bounding box, PT canvas units)
                w, h (int, must be > 0)
                fill_color (str "#RRGGBB" or (r,g,b) tuple) — only for filled kinds
                outline_color (default "#000000")
                outlined (bool, default True)
                label (str, optional) — also emits a NOTE near top-left
                label_x, label_y (override label position; defaults near top-left)

            For note:
                x, y (canvas position)
                text (str)

        output_path: Defaults to overwriting pkt_path.
        clear_existing: If True, wipe pre-existing rectangles/ellipses/notes
            before inserting. If False (default), append.

    Returns:
        {"input": <pkt_path>, "output": <output_path>, "size": <bytes>,
         "report": {"rectangles_added": N, "ellipses_added": M, "notes_added": K}}
    """
    if output_path is None:
        output_path = pkt_path

    rect_xml, ell_xml, note_xml, report = _build_zones_xml(zones)

    xml = _load_xml(pkt_path)
    if rect_xml:
        xml = _splice_block(
            xml, _RECTANGLES_EMPTY_RE, _RECTANGLES_OPEN_RE,
            rect_xml, "<RECTANGLES>", "</RECTANGLES>", clear_existing,
        )
    elif clear_existing:
        xml = _RECTANGLES_OPEN_RE.sub("<RECTANGLES/>", xml, count=1)

    if ell_xml:
        xml = _splice_block(
            xml, _ELLIPSES_EMPTY_RE, _ELLIPSES_OPEN_RE,
            ell_xml, "<ELLIPSES>", "</ELLIPSES>", clear_existing,
        )
    elif clear_existing:
        xml = _ELLIPSES_OPEN_RE.sub("<ELLIPSES/>", xml, count=1)

    if note_xml:
        xml = _splice_notes(xml, note_xml, clear_existing)
    elif clear_existing:
        # Clear notes only inside PHYSICALWORKSPACE
        pm = _PHYSWS_RE.search(xml)
        if pm:
            inner = _NOTES_OPEN_RE.sub("<NOTES/>", pm.group(2), count=1)
            xml = _PHYSWS_RE.sub(
                lambda m: f"{m.group(1)}{inner}{m.group(3)}", xml, count=1,
            )

    size = _save_pkt(xml, output_path)
    return {"input": pkt_path, "output": output_path,
            "size": size, "report": report}
