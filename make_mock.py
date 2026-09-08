#!/usr/bin/env python3
"""
Builds mock/data.json — a schema-valid v2.0 document with REAL vessel names and
REAL AIS tracks from the Gulf scene, but a SYNTHETIC slick placed on one
vessel's track so that attribution actually discriminates.

Purpose: unblock the frontend, PDF and deck lanes on hour zero so nobody waits
for the pipeline. meta.source is set to "mock" so this can never be mistaken
for a real result. Run once, commit the output, do not regenerate casually.

    python3 make_mock.py            # reads ./data.json, writes ./mock/data.json
"""
import json, math, os
from datetime import datetime, timedelta

SRC = "data.json"
OUT = os.path.join("mock", "data.json")
PROX_SCALE_KM = 25.0        # see CONTRACT §1 — this is the scale the real
                            # pipeline must also use. 6 km scored every vessel 0.


def m_per_deg(lat):
    return 111320.0 * math.cos(math.radians(lat)), 110540.0


def seg_dist_km(p, a, b, latc):
    """Distance from point p to segment a-b, all [lon,lat], in km."""
    mx, my = m_per_deg(latc)
    px, py = p[0] * mx, p[1] * my
    ax, ay = a[0] * mx, a[1] * my
    bx, by = b[0] * mx, b[1] * my
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy or 1e-9
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
    cx, cy = ax + t * vx, ay + t * vy
    return math.hypot(px - cx, py - cy) / 1000.0


def track_to_poly_dist(track, poly, latc):
    """Min distance in km from any track point to any polygon edge."""
    pts = [p for p in track if p is not None]
    if len(pts) < 1:
        return 999.0
    best = 999.0
    for p in pts:
        for i in range(len(poly) - 1):
            d = seg_dist_km(p, poly[i], poly[i + 1], latc)
            if d < best:
                best = d
    return best


def main():
    src = json.load(open(SRC))
    bbox = src["scene"]["bbox"]
    latc = (bbox[1] + bbox[3]) / 2
    t0 = datetime(2023, 6, 20, 0, 2, 34)

    vessels = src["vessels"]

    # ---- pick the offender: the vessel that actually travels furthest in km.
    #      A moored vessel can report hundreds of times without moving, so
    #      counting AIS pings picks the wrong ship.
    _mx, _my = m_per_deg(latc)

    def track_km(v):
        pts = [p for p in v["track"] if p is not None]
        return sum(math.hypot((pts[i][0] - pts[i - 1][0]) * _mx,
                              (pts[i][1] - pts[i - 1][1]) * _my) / 1000.0
                   for i in range(1, len(pts)))
    offender = max(vessels, key=track_km)
    otrack = [p for p in offender["track"] if p is not None]

    # ---- synthetic slick: a 15 km ribbon along the offender's track,
    #      offset ~2 km perpendicular, as a discharge trail would sit.
    mx, my = m_per_deg(latc)
    TARGET_KM = 15.0
    i0 = max(0, len(otrack) // 5)
    spine, run = [otrack[i0]], 0.0
    for j in range(i0 + 1, len(otrack)):
        a, b = otrack[j - 1], otrack[j]
        run += math.hypot((b[0] - a[0]) * mx, (b[1] - a[1]) * my) / 1000.0
        spine.append(otrack[j])
        if run >= TARGET_KM:
            break
    if run < 2.0:
        spine, run = [otrack[0]], 0.0
        for j in range(1, len(otrack)):
            a, b = otrack[j - 1], otrack[j]
            run += math.hypot((b[0] - a[0]) * mx, (b[1] - a[1]) * my) / 1000.0
            spine.append(otrack[j])
            if run >= TARGET_KM:
                break
    dx = (spine[-1][0] - spine[0][0]) * mx
    dy = (spine[-1][1] - spine[0][1]) * my
    n = math.hypot(dx, dy) or 1.0
    # perpendicular unit vector, in degrees
    perp_lon, perp_lat = (-dy / n) / mx, (dx / n) / my
    OFFSET_M, HALF_W_M = 2200.0, 1400.0

    top, bot = [], []
    for p in spine:
        cl = p[0] + perp_lon * OFFSET_M
        ca = p[1] + perp_lat * OFFSET_M
        top.append([round(cl + perp_lon * HALF_W_M, 5), round(ca + perp_lat * HALF_W_M, 5)])
        bot.append([round(cl - perp_lon * HALF_W_M, 5), round(ca - perp_lat * HALF_W_M, 5)])
    poly = top + bot[::-1]
    poly.append(poly[0])

    length_km = n / 1000.0
    area_km2 = round(length_km * (2 * HALF_W_M / 1000.0) * 0.78, 1)
    cen = [round(sum(p[0] for p in poly) / len(poly), 5),
           round(sum(p[1] for p in poly) / len(poly), 5)]
    head = max(poly, key=lambda p: p[1])

    # ---- give the offender a realistic AIS blackout across the slick
    gap_at = len(otrack) // 2
    otrack_gapped = otrack[:gap_at] + [None] + otrack[gap_at:]

    out_vessels = []
    for v in vessels:
        is_off = v["mmsi"] == offender["mmsi"]
        track = otrack_gapped if is_off else v["track"]
        d = track_to_poly_dist(track, poly, latc)

        proximity = max(0.0, min(1.0, 1 - d / PROX_SCALE_KM))
        parity = round(min(1.0, max(0.0, v.get("parity", 0.3))), 3)
        temporality = round(v.get("temporality", 0.6), 3)
        gap = 63 if is_off else v.get("ais_gap_min", 0)
        silence = 0.0
        if gap >= 20:
            near = 0.9 if is_off else max(0.0, 1 - d / 40.0)
            silence = min(1.0, gap / 90.0) * near

        score = 0.30 * proximity + 0.10 * parity + 0.18 * temporality + 0.42 * silence

        out_vessels.append({
            "mmsi": v["mmsi"], "name": v["name"], "type": v["type"],
            "len_m": v["len_m"],
            "score": round(score, 3), "proximity": round(proximity, 3),
            "parity": parity, "temporality": temporality,
            "silence": round(silence, 3),
            "ais_gap_min": int(gap), "dist_km": round(d, 2),
            "dark": bool(gap >= 20 and d < 15),
            "verdict": None, "reason": None, "track": track,
        })

    out_vessels.sort(key=lambda v: -v["score"])
    THRESH = 0.45
    for i, v in enumerate(out_vessels):
        if i == 0 and v["score"] >= THRESH:
            v["verdict"] = "accused"
        elif v["score"] >= 0.30:
            v["verdict"] = "suspect"
        else:
            v["verdict"] = "cleared"
            if v["dist_km"] > 25:
                v["reason"] = f"closest approach {v['dist_km']:.0f} km from the slick"
            elif v["ais_gap_min"] == 0:
                v["reason"] = "reported continuously, no AIS gap in the window"
            elif v["len_m"] and v["len_m"] < 30:
                v["reason"] = f"length {v['len_m']} m inconsistent with a {length_km:.1f} km slick"
            else:
                v["reason"] = f"combined score {v['score']:.2f}, below the {THRESH} threshold"

    acc = out_vessels[0] if out_vessels[0]["verdict"] == "accused" else None

    # ---- back-drift: slick head walked upstream ~0.35 kn over 8 h
    path, drift_h = [], 8
    for h in range(drift_h + 1):
        path.append([round(head[0] - 0.011 * h, 5),
                     round(head[1] - 0.006 * h, 5),
                     (t0 - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")])

    doc = {
        "meta": {"version": "2.0", "source": "mock",
                 "generated_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "detector": "classical", "runtime_s": 2.4},
        "scene": {"id": "S1A_IW_GRDH_1SDV_20230620T000234",
                  "time": "2023-06-20 00:02 UTC",
                  "time_iso": "2023-06-20T00:02:34Z",
                  "bbox": bbox, "image": "sar_sea.png", "mask": "mask.png",
                  "satellite": "Sentinel-1A", "mode": "IW GRDH",
                  "polarisation": "VV"},
        "detection": {"method": "classical", "confidence": 0.87,
                      "lookalike_prob": 0.12,
                      "slick": {"polygon": poly, "area_km2": area_km2,
                                "length_km": round(length_km, 1), "head": head,
                                "centroid": cen, "coverage_pct": 0.31,
                                "age_hours_est": [4, 9]}},
        "drift": {"method": "back-advection", "origin": path[-1][:2],
                  "origin_time_iso": path[-1][2], "uncertainty_km": 3.2,
                  "path": path, "ensemble": []},
        "vessels": out_vessels,
        "dark_contacts": [
            {"id": "dc_01", "lon": round(cen[0] + 0.06, 5),
             "lat": round(cen[1] - 0.04, 5), "len_px": 34, "matched_mmsi": None},
            {"id": "dc_02", "lon": round(cen[0] - 0.11, 5),
             "lat": round(cen[1] + 0.02, 5), "len_px": 21, "matched_mmsi": None},
        ],
        "summary": {
            "verdict": "accused" if acc else "no_attribution",
            "accused_mmsi": acc["mmsi"] if acc else None,
            "threshold": THRESH,
            "n_scored": len(out_vessels),
            "n_suspect": sum(1 for v in out_vessels if v["verdict"] == "suspect"),
            "n_cleared": sum(1 for v in out_vessels if v["verdict"] == "cleared"),
            "note": (f"{acc['name']} accused: {acc['ais_gap_min']} min AIS blackout "
                     f"{acc['dist_km']:.1f} km from the slick"
                     if acc else "No vessel meets the attribution threshold."),
        },
    }

    os.makedirs("mock", exist_ok=True)
    json.dump(doc, open(OUT, "w"), indent=1)
    print(f"wrote {OUT}  ({os.path.getsize(OUT):,} bytes)")
    print(f"slick  {area_km2} km²  {length_km:.1f} km")
    print(f"verdict {doc['summary']['verdict']}  ·  {doc['summary']['note']}")
    for v in out_vessels[:6]:
        print(f"  {v['score']:.3f} {v['name'][:20]:<20} {v['verdict']:<8} "
              f"{v['dist_km']:>7.2f} km  gap {v['ais_gap_min']:>3}")


if __name__ == "__main__":
    main()
