#!/usr/bin/env python3
"""
OceanFIR - working detection + attribution pipeline.

Reads a real Sentinel-1 scene and a real MarineCadastre AIS day file,
detects the slick, scores every vessel in the acquisition window, and
writes data.json for the UI plus mask.png for slides.

    python oceanfir.py --sar sar_scene.png --ais AIS_2023_06_20.csv \
        --bbox -90.821 28.133 -88.555 29.829 \
        --time 2023-06-20T00:02:34 --window 3

Detection is classical dark-spot segmentation: real, unsupervised, and a
legitimate baseline. Swap in the U-Net later by replacing detect_slick().
"""
import argparse, json, math, sys, warnings
warnings.filterwarnings("ignore")
import subprocess
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from PIL import Image
from scipy import ndimage
from skimage import measure, morphology

# Distance scales. The Mississippi Delta scene is ~200 km wide; a 6 km
# proximity scale scored every one of 557 vessels exactly zero, which
# collapsed the whole ranking onto temporality. See CONTRACT.md.
PROX_SCALE_M = 25_000.0
# Shape of the proximity falloff. "linear" is 1 - d/PROX_SCALE_M, which treats
# 0.5 km and 3 km as nearly the same thing — useless for separating vessels in
# one shipping lane. "exp" is exp(-d/PROX_TAU_M), which decides at the scale a
# discharge actually happens on. Swept by inject.py --prox.
PROX_SHAPE   = "exp"
PROX_TAU_M   = 2_500.0
MIN_MARGIN   = 0.08     # top score must clear the runner-up by this much
# 40 km was too loose: almost every vessel has SOME AIS gap somewhere in a
# 200 km scene, so "silence" scored near 1 for everyone and stopped
# discriminating. inject.py measured it — at 40 km the system falsely accused
# a vessel in 3 of 10 empty-water trials; at 20 km and below, 0 of 10, and the
# guilty vessel's median rank improved from 3.5 to 2.0. See
# out/gap_scale_experiment.json.
GAP_SCALE_M  = 10_000.0

AIS_COLS = ["MMSI", "BaseDateTime", "LAT", "LON", "SOG", "VesselName", "VesselType", "Length"]

VESSEL_TYPE = {70:"Cargo",71:"Cargo",72:"Cargo",73:"Cargo",74:"Cargo",75:"Cargo",76:"Cargo",
               77:"Cargo",78:"Cargo",79:"Cargo",80:"Tanker",81:"Tanker",82:"Tanker",83:"Tanker",
               84:"Tanker",85:"Tanker",86:"Tanker",87:"Tanker",88:"Tanker",89:"Tanker",
               30:"Fishing",31:"Tug",32:"Tug",52:"Tug",60:"Passenger",61:"Passenger",
               62:"Passenger",63:"Passenger",64:"Passenger",69:"Passenger",90:"Other"}


# ----------------------------------------------------------------- geometry
def make_proj(bbox):
    lon0, lat0, lon1, lat1 = bbox
    latc = (lat0 + lat1) / 2
    mlon = 111320.0 * math.cos(math.radians(latc))
    mlat = 110540.0
    def to_m(lon, lat):
        return (np.asarray(lon) - lon0) * mlon, (np.asarray(lat) - lat0) * mlat
    def to_deg(x, y):
        return lon0 + np.asarray(x) / mlon, lat0 + np.asarray(y) / mlat
    return to_m, to_deg


def pts_to_seg_dist(px, py, ax, ay, bx, by):
    """min distance from points (px,py) to segments a->b, all numpy arrays."""
    vx, vy = bx - ax, by - ay
    wx, wy = px[:, None] - ax[None, :], py[:, None] - ay[None, :]
    L2 = vx**2 + vy**2
    L2 = np.where(L2 == 0, 1e-9, L2)
    t = np.clip((wx * vx[None, :] + wy * vy[None, :]) / L2[None, :], 0, 1)
    cx = ax[None, :] + t * vx[None, :]
    cy = ay[None, :] + t * vy[None, :]
    return np.hypot(px[:, None] - cx, py[:, None] - cy).min(axis=1)


# ----------------------------------------------------------------- detection
def load_scene(sar_path, max_side=900):
    """Read the SAR scene once, downscaled. Every detector sees the same array,
    so a mask from the U-Net and a mask from the classical path are directly
    comparable and land in the same geometry code below."""
    img = Image.open(sar_path).convert("L")
    W0, H0 = img.size
    scale = min(1.0, max_side / max(W0, H0))
    im = np.asarray(img.resize((int(W0 * scale), int(H0 * scale))), float) / 255.0
    return im, (W0, H0)


def segment_classical(im):
    """Unsupervised dark-spot segmentation. Returns (candidate mask, land mask).

    A real baseline, not a placeholder: oil damps capillary waves, so a slick is
    genuinely darker than the sea around it in SAR. What it cannot do is tell oil
    from a look-alike — calm water and biogenic film are dark too. That is the
    job the U-Net exists to do."""
    sm = ndimage.gaussian_filter(im, 2.0)
    bg = ndimage.gaussian_filter(im, 40.0)       # slowly varying sea background
    anom = bg - sm                               # positive where darker than background
    thr = anom.mean() + 1.6 * anom.std()
    mask = anom > max(thr, 0.012)

    mask = morphology.remove_small_objects(mask, 220)
    mask = morphology.binary_closing(mask, morphology.disk(4))
    mask = morphology.remove_small_holes(mask, area_threshold=900)

    land = ndimage.gaussian_filter(im, 8.0) > np.percentile(im, 80)
    land = morphology.binary_dilation(land, morphology.disk(9))
    return mask & ~land, land


def mask_to_slick(mask, bbox, orig_size, min_km2=1.0, land=None,
                  mask_png="mask.png", prob=None):
    """Turn a binary mask into the slick record the rest of the system consumes.

    EVERY detector goes through this function. That is deliberate: it is the only
    way to guarantee a new detector cannot quietly return a different shape and
    break the contract downstream. A new detector supplies pixels; geometry,
    region selection and the output record are decided here, once.

    prob, when given, is the model's per-pixel confidence and is averaged over
    the winning region to fill detection.confidence."""
    H, W = mask.shape
    W0, H0 = orig_size
    lon0, lat0, lon1, lat1 = bbox
    m_per_px_x = abs(lon1 - lon0) * 111320.0 * math.cos(math.radians((lat0 + lat1) / 2)) / W
    m_per_px_y = abs(lat1 - lat0) * 110540.0 / H
    px_km2 = m_per_px_x * m_per_px_y / 1e6

    lab = measure.label(mask)
    best, best_score = None, 0.0
    for r in measure.regionprops(lab):
        area_km2 = r.area * px_km2
        if area_km2 < min_km2:
            continue
        if land is not None and land[tuple(np.array(r.coords).T)].mean() > 0.02:
            continue
        r0, c0, r1, c1 = r.bbox                  # touching the scene edge?
        if r0 <= 1 or c0 <= 1 or r1 >= H - 1 or c1 >= W - 1:
            continue                               # cut coastline, not a slick
        elong = r.axis_major_length / max(r.axis_minor_length, 1e-6)
        score = area_km2 * min(elong, 12)         # slicks are large AND elongated
        if score > best_score:
            best_score, best = score, r
    if best is None:
        raise SystemExit("No slick-like region found. Lower --min-km2 or check the image.")

    sel = lab == best.label
    cont = max(measure.find_contours(sel.astype(float), 0.5), key=len)
    cont = measure.approximate_polygon(cont, tolerance=2.0)
    if len(cont) > 60:
        cont = cont[:: max(1, len(cont) // 60)]

    poly = [[lon0 + col / W * (lon1 - lon0), lat1 - row / H * (lat1 - lat0)]
            for row, col in cont]                  # row = y from top, col = x

    area_km2 = best.area * px_km2
    length_km = best.axis_major_length * ((m_per_px_x + m_per_px_y) / 2) / 1000
    ys, xs = np.nonzero(sel)
    hi = int(np.argmin(ys))                        # northernmost pixel as slick head
    head = [lon0 + xs[hi] / W * (lon1 - lon0), lat1 - ys[hi] / H * (lat1 - lat0)]
    centroid = [lon0 + xs.mean() / W * (lon1 - lon0),
                lat1 - ys.mean() / H * (lat1 - lat0)]

    if mask_png:
        out = np.zeros((H, W, 4), np.uint8)
        out[sel] = (224, 90, 76, 150)
        Image.fromarray(out).resize((W0, H0), Image.NEAREST).save(mask_png)

    rec = {"polygon": [[round(a, 5), round(b, 5)] for a, b in poly],
           "area_km2": round(area_km2, 1),
           "length_km": round(length_km, 1),
           "head": [round(float(head[0]), 5), round(float(head[1]), 5)],
           "centroid": [round(float(centroid[0]), 5), round(float(centroid[1]), 5)],
           "coverage_pct": round(100 * sel.sum() / sel.size, 2)}
    if prob is not None:
        rec["confidence"] = round(float(prob[sel].mean()), 3)
    return rec


def detect_slick(sar_path, bbox, min_km2=1.0):
    """Classical detector. Same signature and same return it always had."""
    im, orig = load_scene(sar_path)
    mask, land = segment_classical(im)
    return mask_to_slick(mask, bbox, orig, min_km2, land=land)


# ----------------------------------------------------------------- AIS
def load_ais(path, bbox, t0, window_h):
    lon0, lat0, lon1, lat1 = bbox
    ta, tb = t0 - timedelta(hours=window_h), t0 + timedelta(hours=window_h)
    keep, total = [], 0
    for ch in pd.read_csv(path, usecols=lambda c: c.strip() in AIS_COLS,
                          chunksize=400_000, low_memory=False):
        ch.columns = [c.strip() for c in ch.columns]
        total += len(ch)
        ch["BaseDateTime"] = pd.to_datetime(ch["BaseDateTime"], errors="coerce")
        m = (ch.LON.between(lon0, lon1) & ch.LAT.between(lat0, lat1)
             & ch.BaseDateTime.between(ta, tb))
        if m.any():
            keep.append(ch.loc[m])
    if not keep:
        raise SystemExit("No AIS inside the box and window. Widen --window or check --bbox.")
    df = pd.concat(keep).sort_values(["MMSI", "BaseDateTime"]).reset_index(drop=True)
    print(f"  scanned {total:,} AIS rows, kept {len(df):,} from {df.MMSI.nunique()} vessels")
    return df


def score_vessels(df, slick, bbox, t0, gap_min=20.0, max_track=400):
    to_m, _ = make_proj(bbox)
    sx, sy = to_m([p[0] for p in slick["polygon"]], [p[1] for p in slick["polygon"]])
    ax, ay, bx, by = sx[:-1], sy[:-1], sx[1:], sy[1:]
    slick_len_m = slick["length_km"] * 1000

    out = []
    for mmsi, g in df.groupby("MMSI"):
        if len(g) < 3:
            continue
        g = g.sort_values("BaseDateTime")
        vx, vy = to_m(g.LON.values, g.LAT.values)
        t = g.BaseDateTime.values

        dist = pts_to_seg_dist(vx, vy, ax, ay, bx, by)
        dmin = float(dist.min())
        i_near = int(dist.argmin())

        # ---- silence: largest reporting gap
        dt_min = np.diff(t).astype("timedelta64[s]").astype(float) / 60.0
        gap = float(dt_min.max()) if len(dt_min) else 0.0
        gi = int(dt_min.argmax()) if len(dt_min) else -1
        gap_near = 0.0
        if gap >= gap_min and gi >= 0:
            mx, my = (vx[gi] + vx[gi + 1]) / 2, (vy[gi] + vy[gi + 1]) / 2
            gap_near = float(pts_to_seg_dist(np.array([mx]), np.array([my]),
                                             ax, ay, bx, by)[0])

        # ---- component scores, all 0..1
        proximity   = (float(math.exp(-dmin / PROX_TAU_M)) if PROX_SHAPE == "exp"
                       else float(np.clip(1 - dmin / PROX_SCALE_M, 0, 1)))
        track_len   = float(np.hypot(np.diff(vx), np.diff(vy)).sum())
        parity      = float(np.clip(1 - abs(track_len - slick_len_m) /
                                    max(slick_len_m, 1) / 2, 0, 1)) if track_len > 0 else 0.0
        dt_h        = abs((pd.Timestamp(t[i_near]) - t0).total_seconds()) / 3600
        temporality = float(np.clip(1 - dt_h / 6, 0, 1))
        silence     = float(np.clip(gap / 90, 0, 1) *
                            np.clip(1 - gap_near / GAP_SCALE_M, 0, 1)) if gap >= gap_min else 0.0

        score = 0.30 * proximity + 0.10 * parity + 0.18 * temporality + 0.42 * silence

        sog = float(g.SOG.replace(102.3, np.nan).mean()) if "SOG" in g else np.nan
        length = float(pd.to_numeric(g.Length, errors="coerce").max()) if "Length" in g else np.nan
        vtype = VESSEL_TYPE.get(int(pd.to_numeric(g.VesselType, errors="coerce").max() or 0), "Unknown") \
                if "VesselType" in g else "Unknown"
        name = str(g.VesselName.dropna().iloc[0]) if "VesselName" in g and g.VesselName.notna().any() \
               else f"MMSI {int(mmsi)}"

        track = list(zip(g.LON.values, g.LAT.values))
        step = max(1, len(track) // max_track)
        tr = [[round(float(a), 5), round(float(b), 5)] for a, b in track[::step]]
        if gap >= gap_min and gi >= 0:                      # insert an explicit null at the gap
            k = min(gi // step + 1, len(tr))
            tr = tr[:k] + [None] + tr[k:]

        # ---- exoneration reason, computed not invented
        reason = None
        if dmin > 25000:
            reason = f"closest approach {dmin/1000:.0f} km from the slick"
        elif not np.isnan(sog) and sog < 0.6:
            reason = "stationary throughout the acquisition window"
        elif not np.isnan(length) and length > 0 and length < 0.02 * slick_len_m:
            reason = f"length {length:.0f} m inconsistent with a {slick['length_km']:.1f} km slick"
        elif dt_h > 4:
            reason = f"closest approach {dt_h:.1f} h from the acquisition time"
        elif gap < gap_min:
            reason = "reported continuously, no AIS gap in the window"

        out.append(dict(mmsi=int(mmsi), name=name.strip()[:22] or f"MMSI {int(mmsi)}",
                        type=vtype, len_m=0 if np.isnan(length) else int(length),
                        score=round(score, 3), proximity=round(proximity, 3),
                        parity=round(parity, 3), temporality=round(temporality, 3),
                        silence=round(silence, 3), ais_gap_min=int(round(gap)) if gap >= gap_min else 0,
                        dist_km=round(dmin / 1000, 2), dark=bool(gap >= gap_min and gap_near < 15000),
                        _reason=reason, track=tr))

    out.sort(key=lambda v: -v["score"])

    # An accusation needs a WINNER, not just a leader. If the top two vessels
    # are within a hair of each other, the evidence does not separate them and
    # the correct output is to decline. A system that refuses to name a ship it
    # cannot distinguish is more defensible than one that always names someone.
    margin = (out[0]["score"] - out[1]["score"]) if len(out) > 1 else 1.0
    can_accuse = bool(out) and out[0]["score"] >= 0.45 and margin >= MIN_MARGIN
    if out and not can_accuse:
        out[0]["_reason"] = out[0]["_reason"] or (
            f"top score {out[0]['score']:.2f} but only {margin:.2f} clear of the "
            f"next vessel, below the {MIN_MARGIN} separation required to attribute")

    for i, v in enumerate(out):
        if i == 0 and can_accuse:
            v["verdict"] = "accused"; v["reason"] = None
        elif v["score"] >= 0.30 and v["_reason"] is None:
            v["verdict"] = "suspect"; v["reason"] = None
        else:
            v["verdict"] = "cleared"
            v["reason"] = v["_reason"] or f"combined score {v['score']:.2f}, below the attribution threshold"
        v.pop("_reason")
    return out


# ----------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sar", required=True)
    p.add_argument("--ais", required=True)
    p.add_argument("--bbox", nargs=4, type=float, required=True,
                   metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    p.add_argument("--time", required=True)
    p.add_argument("--window", type=float, default=3.0)
    p.add_argument("--min-km2", type=float, default=1.0)
    p.add_argument("--detector", choices=["classical", "unet"], default="classical",
                   help="classical = unsupervised dark-spot baseline, always available. "
                        "unet = learned 3-class model, needs unet_oil.pt from "
                        "notebooks/train_unet.ipynb")
    p.add_argument("--min-oil-prob", type=float, default=0.5,
                   help="unet only: probability above which a pixel counts as oil")
    p.add_argument("--score-at", choices=["observed", "origin"], default="observed",
                   help="score vessel proximity against the slick as observed, or "
                        "against the back-advected discharge origin. 'origin' is "
                        "measurably better WHEN THE SLICK AGE IS KNOWN (drift_ab.py: "
                        "at a 12 h drift it takes recall 0%%->30%% and wrong "
                        "accusations 15%%->10%%). We do not know the age on the real "
                        "scene, and correcting a fresh slick by 12 h would move it "
                        "14 km the wrong way, so the default stays 'observed'.")
    p.add_argument("--drift-hours", type=float, default=12.0,
                   help="how far back to hindcast the slick origin (0 disables)")
    p.add_argument("--u-ms", type=float, default=-0.25, help="surface current east, m/s")
    p.add_argument("--v-ms", type=float, default=-0.12, help="surface current north, m/s")
    p.add_argument("--top", type=int, default=14)
    p.add_argument("--out", default="data.json")
    p.add_argument("--mask", default=None,
                   help="where to write the overlay PNG. Defaults to the --out "
                        "name with a .png extension, so two detectors writing "
                        "into one folder cannot leave a data.json paired with "
                        "the other one's mask.")
    a = p.parse_args()

    t0 = pd.Timestamp(datetime.fromisoformat(a.time))

    print(f"1/3  detecting slick  [{a.detector}] …")
    mask_png = a.mask or (a.out.rsplit(".", 1)[0] + ".png")
    if a.detector == "unet":
        from unet import detect_slick_unet          # imported late: torch is optional
        slick = detect_slick_unet(a.sar, a.bbox, a.min_km2,
                                  min_oil_prob=a.min_oil_prob,
                                  mask_png=mask_png)
        print(f"     confidence {slick.get('confidence')}  "
              f"look-alike {slick.get('lookalike_prob')}")
    else:
        im, orig = load_scene(a.sar)
        m, land = segment_classical(im)
        slick = mask_to_slick(m, a.bbox, orig, a.min_km2, land=land,
                              mask_png=mask_png)
    print(f"     area {slick['area_km2']} km²  length {slick['length_km']} km  "
          f"head {slick['head']}  ({slick['coverage_pct']}% of scene)")

    # ---- reverse drift: where was this slick when it was discharged?
    # Optional by design. drift.py belongs to another lane, so a missing or
    # broken module leaves drift null and the pipeline still produces a result
    # -- the contract allows null and the UI handles it.
    drift = None
    if a.drift_hours > 0:
        try:
            from drift import back_advect
            drift = back_advect(head=slick["head"],
                                t0_iso=t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                hours=a.drift_hours, u_ms=a.u_ms, v_ms=a.v_ms)
            print(f"     drift origin {drift['origin']}  "
                  f"+/- {drift['uncertainty_km']} km  "
                  f"({len(drift['path'])} steps back to {drift['origin_time_iso']})")
        except ImportError:
            print("     drift.py not present yet — drift stays null")
        except Exception as e:
            print(f"     drift failed ({type(e).__name__}: {e}) — drift stays null")

    print("2/3  loading AIS …")
    df = load_ais(a.ais, a.bbox, t0, a.window)

    print("3/3  scoring vessels …")
    scoring_slick = slick
    if a.score_at == "origin" and drift:
        # shift the whole polygon by the head -> origin vector, so proximity is
        # measured to where the oil was discharged rather than where it drifted
        head = slick["head"]
        sx = drift["origin"][0] - head[0]
        sy = drift["origin"][1] - head[1]
        scoring_slick = dict(slick, polygon=[[p[0] + sx, p[1] + sy]
                                             for p in slick["polygon"]])
        print(f"     scoring against the hindcast origin, shifted "
              f"{math.hypot(sx * 111320 * math.cos(math.radians(head[1])), sy * 110540)/1000:.1f} km")
    vessels = score_vessels(df, scoring_slick, a.bbox, t0)
    print(f"     scored {len(vessels)} vessels")
    for v in vessels[:5]:
        print(f"     {v['score']:.2f}  {v['name']:<22} {v['verdict']:<8} "
              f"{v['dist_km']:>6.1f} km  gap {v['ais_gap_min']:>3} min")

    doc = {"scene": {"id": a.sar.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                     "time": t0.strftime("%Y-%m-%d %H:%M UTC"),
                     "bbox": a.bbox, "image": a.sar,
                     "mask": mask_png.rsplit("/", 1)[-1]},
           "detector": a.detector,
           "slick": slick,
           "drift": drift,
           "scored_at": a.score_at,
           "vessels": vessels[:a.top]}
    with open(a.out, "w") as f:
        json.dump(doc, f, indent=1)
    print(f"\nwrote {a.out} and {mask_png}  ·  open index.html to view")

    # ---- pipeline output validation
    val_res = subprocess.run([sys.executable, "validate.py", a.out])
    if val_res.returncode != 0:
        raise ValueError(f"Validation failed for pipeline output {a.out}!")
    print("Pipeline output successfully validated.")


if __name__ == "__main__":
    main()