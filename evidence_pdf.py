"""OceanFIR evidence brief PDF builder.

Public API:
    build_pdf(doc: dict, out_path: str) -> None

The builder deliberately has no project dependencies beyond ReportLab.  Scene
assets are resolved from the output filename (the API writes
out/OceanFIR_<scene>.pdf) and from the repository layout, while the actual
asset filenames always come from doc["scene"].
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#16365C")
LIGHT = colors.HexColor("#EEF3F7")
MID = colors.HexColor("#D6E0E8")
DARK = colors.HexColor("#263746")
MUTED = colors.HexColor("#617282")
WHITE = colors.white

PAGE_W, PAGE_H = A4
LEFT = 16 * mm
RIGHT = 16 * mm
TOP = 17 * mm
BOTTOM = 15 * mm
FOOTER_H = 9 * mm
CONTENT_H = PAGE_H - TOP - BOTTOM - FOOTER_H
CONTENT_W = PAGE_W - LEFT - RIGHT

WEIGHTS = {
    "proximity": 0.30,
    "parity": 0.10,
    "temporality": 0.18,
    "silence": 0.42,
}


def _text(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _num(value: Any, digits: int = 2, fallback: str = "—") -> str:
    if value is None:
        return fallback
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _pct(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def _score(value: Any) -> str:
    return _num(value, 3)


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(str(text).replace("&", "&amp;"), style)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def _scene_key(out_path: str) -> str | None:
    name = Path(out_path).name
    m = re.match(r"OceanFIR_(.+)\.pdf$", name, re.I)
    return m.group(1) if m else None


def _asset_path(doc: dict, field: str, out_path: str) -> Path | None:
    """Resolve a scene asset without hardcoding its filename.

    The API's output path contains the endpoint scene id, which is the reliable
    directory key even when scene["id"] is an upstream SAR product id.
    """
    filename = doc.get("scene", {}).get(field)
    if not filename:
        return None
    filename = os.path.basename(str(filename))
    key = _scene_key(out_path)
    root = _repo_root()
    candidates = []
    if key:
        candidates.extend([root / "mock" / filename, root / "scenes" / key / filename])
    candidates.extend([root / filename, Path(out_path).resolve().parent / filename])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=19, leading=22, textColor=NAVY, spaceAfter=3 * mm,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.5, leading=11, textColor=MUTED, spaceAfter=5 * mm,
        ),
        "section": ParagraphStyle(
            "section", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=14, textColor=NAVY, spaceBefore=2 * mm,
            spaceAfter=3 * mm,
        ),
        "label": ParagraphStyle(
            "label", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=7.5, leading=9, textColor=MUTED,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.5, leading=11, textColor=DARK,
        ),
        "body_small": ParagraphStyle(
            "body_small", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.3, leading=9.3, textColor=DARK,
        ),
        "mono": ParagraphStyle(
            "mono", parent=base["Normal"], fontName="Courier",
            fontSize=8, leading=10, textColor=DARK,
        ),
        "mono_right": ParagraphStyle(
            "mono_right", parent=base["Normal"], fontName="Courier",
            fontSize=8, leading=10, textColor=DARK, alignment=TA_RIGHT,
        ),
        "mono_center": ParagraphStyle(
            "mono_center", parent=base["Normal"], fontName="Courier",
            fontSize=8, leading=10, textColor=DARK, alignment=TA_CENTER,
        ),
        "finding": ParagraphStyle(
            "finding", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=10, leading=13, textColor=NAVY, spaceAfter=3 * mm,
        ),
        "finding_body": ParagraphStyle(
            "finding_body", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.7, leading=12, textColor=DARK, spaceAfter=3 * mm,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontName="Courier",
            fontSize=6.5, leading=7.5, textColor=MUTED,
        ),
    }


def _label_value(label: str, value: Any, styles: dict[str, ParagraphStyle]) -> list:
    return [
        _paragraph(label.upper(), styles["label"]),
        _paragraph(_text(value), styles["mono"]),
    ]


def _metadata_table(items: list[tuple[str, Any]], styles: dict[str, ParagraphStyle], cols: int = 2) -> Table:
    rows = []
    cells = []
    for label, value in items:
        cells.append(_label_value(label, value, styles))
        if len(cells) == cols:
            rows.append(cells)
            cells = []
    if cells:
        while len(cells) < cols:
            cells.append("")
        rows.append(cells)
    table = Table(rows, colWidths=[CONTENT_W / cols] * cols, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.4, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, MID),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
    ]))
    return table


def _asset_image(path: Path | None, max_w: float, max_h: float) -> Image | None:
    if not path:
        return None
    try:
        img = Image(str(path))
        iw, ih = img.imageWidth, img.imageHeight
        if not iw or not ih:
            return None
        scale = min(max_w / iw, max_h / ih)
        img.drawWidth = iw * scale
        img.drawHeight = ih * scale
        return img
    except Exception:
        return None


def _asset_panel(path: Path | None, label: str, styles: dict[str, ParagraphStyle]) -> list:
    if path:
        img = _asset_image(path, (CONTENT_W - 4 * mm) / 2, 65 * mm)
        if img:
            return [
                _paragraph(label, styles["label"]),
                img,
                _paragraph(path.name, styles["mono"]),
            ]
    return [
        _paragraph(label, styles["label"]),
        _paragraph("Asset not found", styles["body"]),
        _paragraph(path.name if path else "—", styles["mono"]),
    ]


def _table(data: list[list[Any]], widths: list[float], styles: dict[str, ParagraphStyle], numeric_cols: Iterable[int] = ()) -> Table:
    numeric = set(numeric_cols)
    converted = []
    for r, row in enumerate(data):
        out = []
        for c, value in enumerate(row):
            if r == 0:
                out.append(_paragraph(str(value), styles["label"]))
            elif c in numeric:
                out.append(_paragraph(str(value), styles["mono_right"]))
            else:
                out.append(_paragraph(str(value), styles["body_small"]))
        converted.append(out)
    t = Table(converted, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.35, MID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.1 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.1 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.7 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.7 * mm),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
    ]))
    return t


def _footer(canvas, doc_obj, scene_id: str) -> None:
    canvas.saveState()
    y = 8 * mm
    canvas.setStrokeColor(MID)
    canvas.setLineWidth(0.45)
    canvas.line(LEFT, y + 3.2 * mm, PAGE_W - RIGHT, y + 3.2 * mm)
    canvas.setFont("Courier", 6.5)
    canvas.setFillColor(MUTED)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    canvas.drawString(LEFT, y, f"OceanFIR  |  {scene_id}  |  generated {generated}")
    canvas.drawRightString(PAGE_W - RIGHT, y, f"page {doc_obj.page}")
    canvas.restoreState()


def _legacy_to_v2(doc: dict) -> dict:
    """Small compatibility adapter for direct callers holding pre-v2 pipeline output."""
    if doc.get("meta", {}).get("version") == "2.0" and doc.get("detection") is not None:
        return doc
    sc = doc.get("scene", {})
    slick = doc.get("slick", {})
    vessels = doc.get("vessels", [])
    accused = next((v for v in vessels if v.get("verdict") == "accused"), None)
    return {
        "meta": {**doc.get("meta", {}), "version": "2.0", "detector": doc.get("detector", "classical")},
        "scene": {**sc, "time_iso": sc.get("time_iso")},
        "detection": {
            "method": doc.get("detector", "classical"),
            "confidence": slick.get("confidence"),
            "lookalike_prob": slick.get("lookalike_prob"),
            "slick": slick,
        },
        "drift": doc.get("drift"),
        "vessels": vessels,
        "dark_contacts": doc.get("dark_contacts", []),
        "summary": {
            "verdict": "accused" if accused else "no_attribution",
            "accused_mmsi": accused.get("mmsi") if accused else None,
            "threshold": 0.45,
            "n_scored": len(vessels),
            "n_suspect": sum(v.get("verdict") == "suspect" for v in vessels),
            "n_cleared": sum(v.get("verdict") == "cleared" for v in vessels),
            "note": "No vessel meets the attribution threshold." if not accused else f"{accused.get('name')} accused",
        },
    }


def _build_scene_page(story: list, doc: dict, out_path: str, styles: dict[str, ParagraphStyle]) -> None:
    scene = doc.get("scene", {})
    detection = doc.get("detection", {})
    slick = detection.get("slick", {})
    bbox = scene.get("bbox", [])
    bbox_text = "[" + ", ".join(_num(x, 3) for x in bbox) + "]" if bbox else "—"

    story.append(_paragraph("SCENE", styles["title"]))
    story.append(_paragraph("Satellite scene and detected slick evidence", styles["subtitle"]))

    meta = [
        ("Satellite", scene.get("satellite")),
        ("Mode", scene.get("mode")),
        ("Polarisation", scene.get("polarisation")),
        ("Acquisition time UTC", scene.get("time_iso") or scene.get("time")),
        ("Bounding box [lonMin, latMin, lonMax, latMax]", bbox_text),
        ("Detector method", detection.get("method") or doc.get("meta", {}).get("detector")),
        ("Detection confidence", _pct(detection.get("confidence")) if detection.get("confidence") is not None else "not available"),
    ]
    if detection.get("lookalike_prob") is not None:
        meta.append(("Look-alike probability", _pct(detection.get("lookalike_prob"))))
    story.append(_metadata_table(meta, styles, cols=2))
    story.append(Spacer(1, 4 * mm))

    img_path = _asset_path(doc, "image", out_path)
    mask_path = _asset_path(doc, "mask", out_path)
    panels = [[_asset_panel(img_path, "SCENE IMAGE", styles), _asset_panel(mask_path, "DETECTION OVERLAY", styles)]]
    panel_table = Table(panels, colWidths=[CONTENT_W / 2] * 2, hAlign="LEFT")
    panel_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.4, MID),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, MID),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    story.append(panel_table)
    story.append(Spacer(1, 4 * mm))

    story.append(_paragraph("SLICK GEOMETRY", styles["section"]))
    centroid = slick.get("centroid")
    centroid_text = "[" + ", ".join(_num(x, 5) for x in centroid) + "]" if centroid else "—"
    geometry = [
        ("Slick area", f"{_num(slick.get('area_km2'), 1)} km²"),
        ("Slick length", f"{_num(slick.get('length_km'), 1)} km"),
        ("Centroid [lon, lat]", centroid_text),
        ("Coverage", _pct(slick.get("coverage_pct"))),
    ]
    if slick.get("age_hours_est") is not None:
        age = slick.get("age_hours_est")
        geometry.append(("Estimated age", f"{_text(age[0])}–{_text(age[1])} h" if isinstance(age, (list, tuple)) and len(age) >= 2 else _text(age)))
    story.append(_metadata_table(geometry, styles, cols=2))


def _build_attribution_page(story: list, doc: dict, styles: dict[str, ParagraphStyle]) -> None:
    summary = doc.get("summary", {})
    vessels = doc.get("vessels", []) or []
    threshold = summary.get("threshold", 0.45)
    verdict = summary.get("verdict", "no_attribution")
    accused_mmsi = summary.get("accused_mmsi")
    accused = next((v for v in vessels if v.get("mmsi") == accused_mmsi or v.get("verdict") == "accused"), None)

    story.append(_paragraph("ATTRIBUTION", styles["title"]))
    story.append(_paragraph("AIS evidence, score decomposition, and attribution decision", styles["subtitle"]))

    if verdict == "no_attribution" or not accused:
        story.append(_paragraph("NO VESSEL MET THE THRESHOLD", styles["finding"]))
        story.append(_paragraph(
            "The system declined to attribute the detected slick. This is a deliberate finding: "
            "the available evidence did not support naming a vessel with sufficient confidence.",
            styles["finding_body"],
        ))
        ranked = sorted(vessels, key=lambda v: float(v.get("score", 0) or 0), reverse=True)[:3]
        data = [["Vessel", "MMSI", "Score", "Gap (min)", "Distance (km)", "Clearing reason"]]
        for v in ranked:
            data.append([
                _text(v.get("name")), _text(v.get("mmsi")), _score(v.get("score")),
                _num(v.get("ais_gap_min"), 0), _num(v.get("dist_km"), 2), _text(v.get("reason"), "No clearing reason recorded"),
            ])
        widths = [34 * mm, 26 * mm, 19 * mm, 22 * mm, 25 * mm, CONTENT_W - 126 * mm]
        story.append(_paragraph("TOP THREE SCORES", styles["section"]))
        if data[1:]:
            story.append(_table(data, widths, styles, numeric_cols={1, 2, 3, 4}))
        else:
            story.append(_paragraph("No scored vessels were recorded.", styles["body"]))
        story.append(Spacer(1, 5 * mm))
        story.append(_metadata_table([
            ("Decision", "SYSTEM DECLINED TO ATTRIBUTE"),
            ("Threshold", _score(threshold)),
            ("Vessels scored", _text(summary.get("n_scored", len(vessels)))),
            ("System note", _text(summary.get("note"))),
        ], styles, cols=2))
        return

    story.append(_paragraph(f"ACCUSED VESSEL — {accused.get('name', 'UNKNOWN')}", styles["finding"]))
    story.append(_metadata_table([
        ("MMSI", accused.get("mmsi")),
        ("Verdict", accused.get("verdict")),
        ("AIS gap", f"{_num(accused.get('ais_gap_min'), 0)} min"),
        ("Closest approach", f"{_num(accused.get('dist_km'), 2)} km"),
    ], styles, cols=2))
    story.append(Spacer(1, 4 * mm))

    story.append(_paragraph("SCORE BREAKDOWN", styles["section"]))
    rows = [["Component", "Raw value", "Weight", "Weighted contribution"]]
    total = 0.0
    for key in ("proximity", "parity", "temporality", "silence"):
        raw = accused.get(key)
        weight = WEIGHTS[key]
        contrib = (float(raw) * weight) if raw is not None else 0.0
        total += contrib
        rows.append([key.capitalize(), _score(raw), _score(weight), _score(contrib)])
    rows.append(["TOTAL", "", "", _score(accused.get("score", total))])
    t = _table(rows, [52 * mm, 30 * mm, 30 * mm, CONTENT_W - 112 * mm], styles, numeric_cols={1, 2, 3})
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 1), (-1, 1), WHITE),
        ("BACKGROUND", (0, 2), (-1, 2), WHITE),
        ("BACKGROUND", (0, 3), (-1, 3), WHITE),
        ("BACKGROUND", (0, 4), (-1, 4), colors.HexColor("#E7EEF5")),
        ("FONTNAME", (0, 4), (-1, 4), "Courier-Bold"),
        ("LINEABOVE", (0, 5), (-1, 5), 0.8, NAVY),
        ("FONTNAME", (0, 5), (-1, 5), "Courier-Bold"),
        ("TEXTCOLOR", (0, 5), (-1, 5), NAVY),
    ]))
    story.append(t)
    story.append(Spacer(1, 4 * mm))
    story.append(_metadata_table([
        ("Total score", _score(accused.get("score", total))),
        ("Attribution threshold", _score(threshold)),
        ("AIS gap", f"{_num(accused.get('ais_gap_min'), 0)} min"),
        ("Closest approach", f"{_num(accused.get('dist_km'), 2)} km"),
    ], styles, cols=2))

    drift = doc.get("drift")
    if drift:
        story.append(Spacer(1, 4 * mm))
        story.append(_paragraph("DRIFT CONTEXT", styles["section"]))
        origin = drift.get("origin")
        origin_text = "[" + ", ".join(_num(x, 5) for x in origin) + "]" if origin else "—"
        story.append(_metadata_table([
            ("Hindcast method", drift.get("method")),
            ("Hindcast origin", origin_text),
            ("Origin time UTC", drift.get("origin_time_iso")),
            ("Uncertainty radius", f"{_num(drift.get('uncertainty_km'), 2)} km"),
        ], styles, cols=2))


def _build_exoneration_pages(story: list, doc: dict, styles: dict[str, ParagraphStyle]) -> None:
    vessels = [v for v in (doc.get("vessels", []) or []) if v.get("verdict") == "cleared"]
    count = len(vessels)
    story.append(PageBreak())
    story.append(_paragraph(f"EXONERATION RECORD — {count} CLEARED", styles["title"]))
    story.append(_paragraph("Every vessel with verdict = cleared; no rows are omitted", styles["subtitle"]))

    if not vessels:
        story.append(_paragraph("No vessels were cleared in this result.", styles["body"]))
        return

    data = [["Vessel", "MMSI", "Distance (km)", "Gap (min)", "Score", "Reason"]]
    for v in vessels:
        data.append([
            _text(v.get("name")), _text(v.get("mmsi")), _num(v.get("dist_km"), 2),
            _num(v.get("ais_gap_min"), 0), _score(v.get("score")), _text(v.get("reason")),
        ])
    widths = [37 * mm, 29 * mm, 25 * mm, 21 * mm, 19 * mm, CONTENT_W - 131 * mm]
    story.append(_table(data, widths, styles, numeric_cols={1, 2, 3, 4}))


def build_pdf(doc: dict, out_path: str) -> None:
    """Build an OceanFIR evidence PDF at *out_path*.

    Args:
        doc: OceanFIR data.json v2.0 document.
        out_path: Destination PDF path.
    """
    if not isinstance(doc, dict):
        raise TypeError("doc must be a dict")
    doc = _legacy_to_v2(doc)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    styles = _styles()
    scene_id = _scene_key(out_path) or doc.get("scene", {}).get("id", "unknown")

    frame = Frame(LEFT, BOTTOM + FOOTER_H, CONTENT_W, CONTENT_H, leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0, id="normal")
    template = PageTemplate(id="evidence", frames=[frame],
                            onPage=lambda c, d: _footer(c, d, str(scene_id)))
    pdf = BaseDocTemplate(str(out), pagesize=A4, leftMargin=LEFT, rightMargin=RIGHT,
                          topMargin=TOP, bottomMargin=BOTTOM + FOOTER_H,
                          pageTemplates=[template], title=f"OceanFIR Evidence — {scene_id}")

    story: list = []
    _build_scene_page(story, doc, out_path, styles)
    story.append(PageBreak())
    _build_attribution_page(story, doc, styles)
    _build_exoneration_pages(story, doc, styles)
    pdf.build(story)
