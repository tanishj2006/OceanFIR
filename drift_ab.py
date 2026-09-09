#!/usr/bin/env python3
"""
drift_ab.py — does scoring against the hindcast ORIGIN beat scoring against the
slick where we SEE it?

inject.py showed that attribution degrades as a slick drifts from the ship that
made it: at 0.2 km offset, 5% wrong accusations; at 8 km, 25%. The obvious
inference is "so back-drift first and score against the origin". That is an
inference, not a result, and it may be wrong: drift.py reports ~5 km of
uncertainty on the origin while proximity decays over a 2.5 km scale, so the
correction could be fuzzier than the ruler it is being fed into.

This measures it instead of assuming.

Per trial:
  1. Lay a slick along a real vessel's wake      -> this is the true discharge site
  2. Translate it by a TRUE drift                -> this is what a satellite sees
  3. (A) score against the observed slick        -> what we ship today
  4. (B) back-advect, translate back, score      -> the proposal

The back-advection uses a NOMINAL current that differs from the true one by
about 18%. Using the same current for both would recover the origin perfectly
and prove nothing.

    python drift_ab.py --trials 20
"""
import argparse, math, warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import oceanfir
from oceanfir import load_ais, score_vessels, MIN_MARGIN
from inject import (m_per_deg, ribbon, slick_doc, spine_near, blank_ais,
                    evaluate, SLICK_LEN_KM)

# true current the slick actually rides, and the nominal one the hindcast
# assumes. The gap between them is the whole point.
TRUE_U, TRUE_V = -0.30, -0.15
NOM_U,  NOM_V  = -0.25, -0.12


def translate(poly, dlon, dlat):
    return [[p[0] + dlon, p[1] + dlat] for p in poly]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ais", default="data/AIS_2023_06_20.csv")
    p.add_argument("--bbox", nargs=4, type=float,
                   default=[-90.821, 28.133, -88.555, 29.2])
    p.add_argument("--time", default="2023-06-20T00:02:34")
    p.add_argument("--window", type=float, default=3.0)
    p.add_argument("--trials", type=int, default=20)
    p.add_argument("--gap-min", type=float, default=60.0)
    p.add_argument("--hours", default="3,6,12",
                   help="drift ages to test, comma separated")
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()

    try:
        from drift import back_advect
    except ImportError:
        raise SystemExit("drift.py not on this branch — merge lane-e first.")

    t0 = pd.Timestamp(a.time)
    t0_iso = t0.strftime("%Y-%m-%dT%H:%M:%SZ")
    latc = (a.bbox[1] + a.bbox[3]) / 2
    mx, my = m_per_deg(latc)

    print("loading AIS once …")
    df = load_ais(a.ais, a.bbox, t0, a.window)

    cands = []
    for mmsi, g in df.groupby("MMSI"):
        if len(g) < 6:
            continue
        km = float(np.hypot(np.diff(g.LON.values) * mx,
                            np.diff(g.LAT.values) * my).sum()) / 1000.0
        if km >= 8.0:
            cands.append((int(mmsi), km))
    cands.sort(key=lambda c: -c[1])
    import random
    rng = random.Random(a.seed)
    pool = [m for m, _ in cands[:max(a.trials * 3, 30)]]
    rng.shuffle(pool)

    print(f"\ntrue current ({TRUE_U}, {TRUE_V}) m/s · hindcast assumes "
          f"({NOM_U}, {NOM_V}) — an ~18% error, on purpose\n")
    print(f"  {'drift age':>9} {'drift km':>9} | {'A recall':>9} {'A wrong':>8} "
          f"| {'B recall':>9} {'B wrong':>8} | {'origin err':>10}")

    for hours in [float(x) for x in a.hours.split(",")]:
        dlon = TRUE_U * hours * 3600 / mx
        dlat = TRUE_V * hours * 3600 / my
        drift_km = math.hypot(TRUE_U, TRUE_V) * hours * 3600 / 1000.0

        A, B, errs, used = [], [], [], 0
        for mmsi in pool:
            if used >= a.trials:
                break
            g = df[df.MMSI == mmsi].sort_values("BaseDateTime")
            spine, t_mid = spine_near(g, t0, SLICK_LEN_KM, latc)
            if spine is None:
                continue
            poly_true, length_km = ribbon(spine, latc)
            if poly_true is None or length_km < 2.0:
                continue
            df2 = blank_ais(df, mmsi, t_mid, a.gap_min)
            if df2 is None:
                continue
            used += 1

            poly_obs = translate(poly_true, dlon, dlat)

            # (A) score where the slick is seen
            A.append(evaluate(score_vessels(df2, slick_doc(poly_obs, length_km, latc),
                                            a.bbox, t0), mmsi))

            # (B) hindcast the origin, shift the polygon back by that much
            head_obs = max(poly_obs, key=lambda q: q[1])
            dr = back_advect(head=head_obs, t0_iso=t0_iso, hours=hours,
                             u_ms=NOM_U, v_ms=NOM_V)
            sx = dr["origin"][0] - head_obs[0]
            sy = dr["origin"][1] - head_obs[1]
            poly_corr = translate(poly_obs, sx, sy)
            B.append(evaluate(score_vessels(df2, slick_doc(poly_corr, length_km, latc),
                                            a.bbox, t0), mmsi))

            # how far the corrected slick still sits from the true one
            errs.append(math.hypot((sx + dlon) * mx, (sy + dlat) * my) / 1000.0)

        f = lambda rows, k: sum(r[k] for r in rows) / max(len(rows), 1)
        print(f"  {hours:>7.0f} h {drift_km:>9.1f} | {f(A,'hit'):>8.0%} "
              f"{f(A,'wrong'):>8.0%} | {f(B,'hit'):>8.0%} {f(B,'wrong'):>8.0%} "
              f"| {np.mean(errs):>8.1f} km")

    print(f"\nA = score against the observed slick (what we ship today)")
    print(f"B = back-advect first, then score against the origin")
    print(f"'origin err' is how far B's corrected slick still sits from truth.")
    print(f"If that error exceeds the 2.5 km proximity scale, B cannot help.")


if __name__ == "__main__":
    main()
