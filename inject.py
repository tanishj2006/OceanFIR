#!/usr/bin/env python3
"""
inject.py — controlled validation of the ATTRIBUTION stage.

There is no public dataset with ground-truth spill-to-vessel labels. Detection
can be scored against labelled masks; attribution cannot be scored against
anything, because nobody publishes "this slick came from this MMSI". So the
accuracy of every attribution system in this problem space, ours included, is
normally just asserted.

This builds the measurement instead. Real Sentinel-1 scene, real MarineCadastre
AIS. Pick a real vessel, lay a synthetic slick along its wake, blank its AIS
across the discharge window, and run the real scorer. Then ask: did it name that
ship?

Two halves, and the second one matters more:

  POSITIVE trials  — a vessel is guilty. Measures recall: how often we find it.
  NEGATIVE trials  — nobody is guilty; the slick sits in empty water far from
                     every track. Measures the thing that actually matters for
                     an accusation system: how often we blame someone anyway.

A system that always accuses scores 100% on positives and is worthless. Report
both numbers together, always.

This validates attribution ONLY. The slick polygon is injected directly rather
than painted into the SAR image, so detection is not being tested here and no
claim about detection accuracy follows from these results — that is measured
separately as IoU against labelled masks.

    python inject.py --trials 20
    python inject.py --trials 20 --gap-min 45 --json out/injection.json
"""
import argparse, json, math, os, random, sys, warnings
warnings.filterwarnings("ignore")
from datetime import timedelta

import numpy as np
import pandas as pd

import oceanfir
from oceanfir import load_ais, score_vessels, make_proj, MIN_MARGIN

SLICK_LEN_KM = 14.0      # length of the injected ribbon
OFFSET_M     = 2200.0    # perpendicular offset from the wake
HALF_W_M     = 1400.0    # half-width of the ribbon


# ------------------------------------------------------------------ geometry
def m_per_deg(lat):
    return 111320.0 * math.cos(math.radians(lat)), 110540.0


def ribbon(spine, latc, offset_m=OFFSET_M, half_w_m=HALF_W_M):
    """Turn a run of [lon,lat] points into a closed slick polygon offset to one
    side of it, the way a discharge trail sits beside the track that made it."""
    mx, my = m_per_deg(latc)
    dx = (spine[-1][0] - spine[0][0]) * mx
    dy = (spine[-1][1] - spine[0][1]) * my
    n = math.hypot(dx, dy)
    if n < 1.0:
        return None, 0.0
    plon, plat = (-dy / n) / mx, (dx / n) / my      # perpendicular, in degrees

    top, bot = [], []
    for p in spine:
        cl, ca = p[0] + plon * offset_m, p[1] + plat * offset_m
        top.append([round(cl + plon * half_w_m, 5), round(ca + plat * half_w_m, 5)])
        bot.append([round(cl - plon * half_w_m, 5), round(ca - plat * half_w_m, 5)])
    poly = top + bot[::-1]
    poly.append(poly[0])
    return poly, n / 1000.0


def slick_doc(poly, length_km, latc):
    cen = [round(sum(p[0] for p in poly) / len(poly), 5),
           round(sum(p[1] for p in poly) / len(poly), 5)]
    head = max(poly, key=lambda p: p[1])
    return {"polygon": poly, "length_km": round(length_km, 1),
            "area_km2": round(length_km * (2 * HALF_W_M / 1000.0) * 0.78, 1),
            "head": [round(head[0], 5), round(head[1], 5)],
            "centroid": cen, "coverage_pct": 0.3}


def spine_near(g, t0, target_km, latc):
    """The run of a vessel's track, closest in time to acquisition, that spans
    about target_km. Returns (points, mid_timestamp) or (None, None)."""
    pts = list(zip(g.LON.values, g.LAT.values))
    ts = list(g.BaseDateTime.values)
    if len(pts) < 4:
        return None, None
    mx, my = m_per_deg(latc)
    i0 = int(np.argmin([abs((pd.Timestamp(t) - t0).total_seconds()) for t in ts]))
    i0 = min(i0, len(pts) - 2)

    # walk outward from the point nearest t0 until the run is long enough
    lo = hi = i0
    run = 0.0
    while run < target_km and (lo > 0 or hi < len(pts) - 1):
        if hi < len(pts) - 1:
            a, b = pts[hi], pts[hi + 1]
            run += math.hypot((b[0] - a[0]) * mx, (b[1] - a[1]) * my) / 1000.0
            hi += 1
        if run < target_km and lo > 0:
            a, b = pts[lo - 1], pts[lo]
            run += math.hypot((b[0] - a[0]) * mx, (b[1] - a[1]) * my) / 1000.0
            lo -= 1
    if run < 2.0 or hi - lo < 2:
        return None, None
    return [list(p) for p in pts[lo:hi + 1]], pd.Timestamp(ts[(lo + hi) // 2])


def blank_ais(df, mmsi, t_mid, gap_min, keep_min=3):
    """Delete a vessel's AIS rows around t_mid — the blackout a ship makes when
    it stops transmitting to discharge. Refuses if too few rows would remain,
    because a vessel with under 3 points is dropped by the scorer anyway."""
    half = timedelta(minutes=gap_min / 2)
    is_v = df.MMSI == mmsi
    drop = is_v & df.BaseDateTime.between(t_mid - half, t_mid + half)
    if (is_v.sum() - drop.sum()) < keep_min or drop.sum() == 0:
        return None
    return df.loc[~drop]


# ------------------------------------------------------------------- trials
def evaluate(vessels, target_mmsi):
    """Read the scorer's own verdicts. Never re-derive them here — the point is
    to test the shipping logic, not a copy of it."""
    top = vessels[0] if vessels else None
    accused = top["mmsi"] if top and top["verdict"] == "accused" else None
    rank = next((i + 1 for i, v in enumerate(vessels) if v["mmsi"] == target_mmsi), None)
    tv = next((v for v in vessels if v["mmsi"] == target_mmsi), None)
    margin = round(vessels[0]["score"] - vessels[1]["score"], 3) if len(vessels) > 1 else None
    return {"accused_mmsi": accused,
            "hit": accused is not None and accused == target_mmsi,
            "wrong": accused is not None and accused != target_mmsi,
            "declined": accused is None,
            "target_rank": rank,
            "target_score": tv["score"] if tv else None,
            "target_silence": tv["silence"] if tv else None,
            "target_proximity": tv["proximity"] if tv else None,
            "target_gap_min": tv["ais_gap_min"] if tv else None,
            "top_score": top["score"] if top else None,
            "margin": margin,
            # keep the ranked head so any (threshold, margin) pair can be scored
            # later without paying for another run
            "ranked": [[v["mmsi"], v["score"], v["ais_gap_min"]] for v in vessels[:6]],
            "rivals_with_gaps": sum(1 for v in vessels[:5]
                                    if v["mmsi"] != target_mmsi and v["ais_gap_min"] > 0),
            "n_scored": len(vessels)}


def sweep(rows, thresholds=(0.40, 0.45, 0.50), margins=(0.00, 0.02, 0.04, 0.06, 0.08, 0.12)):
    """Re-score every cached trial at different decision rules. The point is not
    to find a number that flatters us — it is to show what the number costs."""
    pos = [r for r in rows if r["kind"] == "positive"]
    neg = [r for r in rows if r["kind"] == "negative"]
    out = []
    for thr in thresholds:
        for mg in margins:
            def accused(r):
                rk = r["ranked"]
                if not rk or rk[0][1] < thr:
                    return None
                if len(rk) > 1 and (rk[0][1] - rk[1][1]) < mg:
                    return None
                return rk[0][0]
            hits = sum(1 for r in pos if accused(r) == r["target_mmsi"])
            wrong = sum(1 for r in pos
                        if accused(r) is not None and accused(r) != r["target_mmsi"])
            false_acc = sum(1 for r in neg if accused(r) is not None)
            named = hits + wrong
            out.append({
                "threshold": thr, "margin": mg,
                "recall": round(hits / len(pos), 3) if pos else None,
                "wrong": round(wrong / len(pos), 3) if pos else None,
                "precision": round(hits / named, 3) if named else None,
                "false_acc": round(false_acc / len(neg), 3) if neg else None})
    return out


def positive_trial(df, bbox, t0, mmsi, gap_min, latc, offset_m=OFFSET_M):
    g = df[df.MMSI == mmsi].sort_values("BaseDateTime")
    spine, t_mid = spine_near(g, t0, SLICK_LEN_KM, latc)
    if spine is None:
        return None
    poly, length_km = ribbon(spine, latc, offset_m=offset_m)
    if poly is None or length_km < 2.0:
        return None
    df2 = blank_ais(df, mmsi, t_mid, gap_min)
    if df2 is None:
        return None
    slick = slick_doc(poly, length_km, latc)
    r = evaluate(score_vessels(df2, slick, bbox, t0), mmsi)
    r.update(kind="positive", target_mmsi=int(mmsi), offset_m=offset_m,
             name=str(g.VesselName.dropna().iloc[0])[:22] if g.VesselName.notna().any()
                  else f"MMSI {int(mmsi)}",
             slick_km=round(length_km, 1), gap_min=gap_min)
    return r


def negative_trial(df, bbox, t0, latc, rng, min_clear_km=18.0, tries=400):
    """Slick in empty water, nobody's AIS touched. Correct answer: accuse nobody.

    The delta is busy, so a point 30 km clear of every AIS position may simply
    not exist. Relax the clearance rather than silently returning nothing — an
    unrun negative control is worse than a slightly closer one, and the achieved
    clearance is reported so the number can be read honestly."""
    lon0, lat0, lon1, lat1 = bbox
    to_m, _ = make_proj(bbox)
    vx, vy = to_m(df.LON.values, df.LAT.values)

    best = None
    for clear in (min_clear_km, min_clear_km * 0.66, min_clear_km * 0.4):
        for _ in range(tries):
            cl = rng.uniform(lon0 + 0.1, lon1 - 0.1)
            ca = rng.uniform(lat0 + 0.1, lat1 - 0.1)
            px, py = to_m([cl], [ca])
            d = float(np.hypot(vx - px[0], vy - py[0]).min()) / 1000.0
            if d >= clear:
                best = (cl, ca, d)
                break
        if best:
            break
    if not best:
        return None
    cl, ca, clear_km = best
    for _ in range(1):
        hdg = rng.uniform(0, math.pi)
        mx, my = m_per_deg(latc)
        half = SLICK_LEN_KM * 500.0
        spine = [[cl - math.cos(hdg) * half / mx, ca - math.sin(hdg) * half / my],
                 [cl, ca],
                 [cl + math.cos(hdg) * half / mx, ca + math.sin(hdg) * half / my]]
        poly, length_km = ribbon(spine, latc)
        if poly is None:
            continue
        slick = slick_doc(poly, length_km, latc)
        r = evaluate(score_vessels(df, slick, bbox, t0), target_mmsi=-1)
        r.update(kind="negative", target_mmsi=-1, name="(empty water)",
                 slick_km=round(length_km, 1), gap_min=0,
                 clearance_km=round(clear_km, 1))
        return r
    return None


# ---------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description="Controlled attribution validation.")
    p.add_argument("--ais", default="data/AIS_2023_06_20.csv")
    p.add_argument("--bbox", nargs=4, type=float,
                   default=[-90.821, 28.133, -88.555, 29.2])
    p.add_argument("--time", default="2023-06-20T00:02:34")
    p.add_argument("--window", type=float, default=3.0)
    p.add_argument("--trials", type=int, default=20, help="positive trials")
    p.add_argument("--negatives", type=int, default=10)
    p.add_argument("--gap-min", type=float, default=60.0, help="AIS blackout length")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--gap-scale-fixed", type=float, default=10_000.0,
                   help="GAP_SCALE_M held constant during the offset sweep")
    p.add_argument("--offsets", default=None,
                   help="comma-separated slick offsets in m from the wake, "
                        "e.g. 200,1000,2200,4000")
    p.add_argument("--gap-scales", default=None,
                   help="comma-separated GAP_SCALE_M values to compare, "
                        "e.g. 40000,15000,8000,4000")
    p.add_argument("--json", default="out/injection_report.json")
    a = p.parse_args()

    t0 = pd.Timestamp(a.time)
    latc = (a.bbox[1] + a.bbox[3]) / 2

    print("loading AIS once and reusing it across every trial …")
    df = load_ais(a.ais, a.bbox, t0, a.window)

    # candidates: vessels that actually move, so a wake exists to lay a slick on
    mx, my = m_per_deg(latc)
    cands = []
    for mmsi, g in df.groupby("MMSI"):
        if len(g) < 6:
            continue
        lon, lat = g.LON.values, g.LAT.values
        km = float(np.hypot(np.diff(lon) * mx, np.diff(lat) * my).sum()) / 1000.0
        if km >= 8.0:
            cands.append((int(mmsi), km))
    cands.sort(key=lambda c: -c[1])
    print(f"  {len(cands)} vessels with a usable wake; sampling {a.trials}\n")

    def run_all(gap_scale, offset_m=OFFSET_M, verbose=True):
        """One full pass. rng is re-seeded so every gap_scale sees the SAME
        vessels and the same empty-water locations — otherwise the comparison
        below measures luck, not the parameter."""
        oceanfir.GAP_SCALE_M = gap_scale
        rng = random.Random(a.seed)
        pool = [m for m, _ in cands[:max(a.trials * 3, 30)]]
        rng.shuffle(pool)
        rows, skipped = [], 0
        for mmsi in pool:
            if len(rows) >= a.trials:
                break
            r = positive_trial(df, a.bbox, t0, mmsi, a.gap_min, latc, offset_m)
            if r is None:
                skipped += 1
                continue
            rows.append(r)
            if verbose:
                mark = "HIT " if r["hit"] else ("WRONG" if r["wrong"] else "decl ")
                print(f"  {mark} {r['name']:<22} rank {str(r['target_rank']):>4}  "
                      f"score {r['target_score']}  margin {r['margin']}")
        if verbose:
            print()
        for _ in range(a.negatives):
            r = negative_trial(df, a.bbox, t0, latc, rng)
            if r is None:
                continue
            rows.append(r)
            if verbose:
                print(f"  {'FALSE' if r['accused_mmsi'] else 'ok   '} empty water, "
                      f"{r['clearance_km']:>5.1f} km clear   top {r['top_score']}  "
                      f"margin {r['margin']}")
        return rows, skipped

    offsets = [float(x) for x in a.offsets.split(",")] if a.offsets else []
    if offsets:
        print("offset experiment — how far the slick sits from the wake that made\n"
              "it. A fresh discharge sits on the track; a drifted one does not.\n"
              "If recall collapses as offset grows, then attributing to the slick\n"
              "WHERE WE SEE IT is the wrong thing to do, and the back-drift\n"
              "hindcast is load-bearing rather than decorative.\n")
        print(f"  {'offset':>9} {'recall':>7} {'wrong':>7} {'false-acc':>10} "
              f"{'median rank':>12}")
        res = []
        for om in offsets:
            rws, _ = run_all(a.gap_scale_fixed, offset_m=om, verbose=False)
            p_ = [r for r in rws if r["kind"] == "positive"]
            n_ = [r for r in rws if r["kind"] == "negative"]
            rec = sum(r["hit"] for r in p_) / max(len(p_), 1)
            wrg = sum(r["wrong"] for r in p_) / max(len(p_), 1)
            fa = sum(1 for r in n_ if r["accused_mmsi"]) / max(len(n_), 1)
            mr = float(np.median([r["target_rank"] for r in p_ if r["target_rank"]]))
            res.append({"offset_m": om, "recall": round(rec, 3), "wrong": round(wrg, 3),
                        "false_acc": round(fa, 3), "median_rank": mr})
            print(f"  {om/1000:>7.1f} km {rec:>7.0%} {wrg:>7.0%} {fa:>10.0%} {mr:>12.1f}")
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        json.dump({"offset_experiment": res, "gap_scale_m": a.gap_scale_fixed},
                  open(a.json, "w"), indent=1)
        print(f"\nwrote {a.json}")
        return

    scales = [float(x) for x in a.gap_scales.split(",")] if a.gap_scales else []
    if scales:
        print("gap-scale experiment — how tightly a blackout must sit beside the\n"
              "slick before 'silence' counts. Same vessels, same locations,\n"
              "one parameter changed.\n")
        print(f"  {'gap scale':>10} {'recall':>7} {'wrong':>7} {'false-acc':>10} "
              f"{'median rank':>12}")
        best = []
        for gs in scales:
            rws, _ = run_all(gs, verbose=False)
            p = [r for r in rws if r["kind"] == "positive"]
            n = [r for r in rws if r["kind"] == "negative"]
            rec = sum(r["hit"] for r in p) / max(len(p), 1)
            wrg = sum(r["wrong"] for r in p) / max(len(p), 1)
            fa = sum(1 for r in n if r["accused_mmsi"]) / max(len(n), 1)
            mr = float(np.median([r["target_rank"] for r in p if r["target_rank"]]))
            best.append({"gap_scale_m": gs, "recall": round(rec, 3),
                         "wrong": round(wrg, 3), "false_acc": round(fa, 3),
                         "median_rank": mr})
            print(f"  {gs/1000:>8.0f} km {rec:>7.0%} {wrg:>7.0%} {fa:>10.0%} "
                  f"{mr:>12.1f}")
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        json.dump({"gap_scale_experiment": best}, open(a.json, "w"), indent=1)
        print(f"\nwrote {a.json}")
        return

    rows, skipped = run_all(oceanfir.GAP_SCALE_M)
    pos = [r for r in rows if r["kind"] == "positive"]
    neg = [r for r in rows if r["kind"] == "negative"]
    hits = sum(r["hit"] for r in pos)
    wrong = sum(r["wrong"] for r in pos)
    decl = sum(r["declined"] for r in pos)
    top3 = sum(1 for r in pos if r["target_rank"] and r["target_rank"] <= 3)
    false_acc = sum(1 for r in neg if r["accused_mmsi"])

    n = max(len(pos), 1)
    summary = {
        "positives": len(pos), "negatives": len(neg), "skipped": skipped,
        "gap_min": a.gap_min, "min_margin": MIN_MARGIN, "seed": a.seed,
        "recall_at_1": round(hits / n, 3),
        "recall_at_3": round(top3 / n, 3),
        "wrong_accusation": round(wrong / n, 3),
        "declined_on_guilty": round(decl / n, 3),
        "false_accusation_rate": round(false_acc / len(neg), 3) if neg else None,
        "median_rank_of_guilty": float(np.median([r["target_rank"] for r in pos
                                                  if r["target_rank"]])) if pos else None,
    }

    print(f"""
{'='*62}
ATTRIBUTION VALIDATION — {len(pos)} positive, {len(neg)} negative trials
{'='*62}
  correct vessel accused        {hits}/{len(pos)}   ({summary['recall_at_1']:.0%})
  guilty vessel in top 3        {top3}/{len(pos)}   ({summary['recall_at_3']:.0%})
  WRONG vessel accused          {wrong}/{len(pos)}   ({summary['wrong_accusation']:.0%})
  declined though guilty        {decl}/{len(pos)}   ({summary['declined_on_guilty']:.0%})
  median rank of guilty vessel  {summary['median_rank_of_guilty']}

  false accusation, empty water {false_acc}/{len(neg)}""" +
          (f"   ({summary['false_accusation_rate']:.0%})" if neg else "") + f"""

  blackout {a.gap_min:.0f} min · margin rule {MIN_MARGIN} · seed {a.seed}
{'='*62}
Say both numbers together. Recall alone describes a system that
accuses everyone. Attribution only — detection is measured separately.
""")

    rivals = [r["rivals_with_gaps"] for r in pos]
    if rivals:
        print(f"diagnostic · rival vessels in the top 5 that ALSO had a natural "
              f"AIS gap: {np.mean(rivals):.1f} on average.\n"
              f"            Silence is only discriminating if the gap is rare "
              f"near the slick.\n")

    print("decision rule sweep — what each threshold actually costs")
    print(f"  {'thr':>5} {'margin':>7} {'recall':>7} {'wrong':>7} "
          f"{'precision':>10} {'false-acc':>10}")
    for s in sweep(rows):
        star = "  <- shipping" if (abs(s["threshold"] - 0.45) < 1e-9
                                   and abs(s["margin"] - MIN_MARGIN) < 1e-9) else ""
        fa = "n/a" if s["false_acc"] is None else f"{s['false_acc']:.0%}"
        pr = "n/a" if s["precision"] is None else f"{s['precision']:.0%}"
        print(f"  {s['threshold']:>5.2f} {s['margin']:>7.2f} {s['recall']:>7.0%} "
              f"{s['wrong']:>7.0%} {pr:>10} {fa:>10}{star}")
    print("\nPick the rule from this table, not from a hunch — and be able to say\n"
          "what the alternative would have cost.\n")

    os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
    json.dump({"summary": summary, "sweep": sweep(rows), "trials": rows},
              open(a.json, "w"), indent=1)
    print(f"wrote {a.json}")


if __name__ == "__main__":
    main()
