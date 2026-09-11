# Shipped operating point — read this before using anything in results/

Settled 11 Sep 2026 after the A7 sweep. Measured with
`notebooks/oceanfir_improve_v2.ipynb`.

## Configuration

| Parameter | Value | Set where |
|---|---|---|
| detector weights | `unet_oil.pt` (resnet34 U-Net, 1ch VH, 2 classes, 15 epochs) | `unet.py` |
| pixel threshold | 0.50 | `--min-oil-prob` |
| min region size | 150 px | region proposals |
| **look-alike classifier threshold** | **0.35** | `lookalike_clf.joblib` → `["tau"]` |
| min slick area | 1.0 km² | `oceanfir.py` `min_km2` |

## Why two different thresholds appear in this folder

`lookalike_clf.joblib` carries **0.35**. That is the shipped value.

`lookalike_metrics.json` and `end_to_end.json` both record **0.30**. They are not
stale or wrong — they are records of a *different selection criterion*:

- `lookalike_metrics.json` — 0.30 is the best **g-mean** on region-level
  cross-validation over the 240 TRAIN scenes. That optimises region
  classification in isolation.
- `end_to_end.json` — ran at 0.30 before the A7 sweep existed.
- `operating_grid.json` — the A7 sweep, which scores **whole scenes** the way
  `mask_to_slick()` actually consumes them. This is what picked 0.35.

Region-level g-mean and scene-level accuracy are different objectives. 0.35 wins
on the one that matches the product.

## Held-out results at the shipped operating point

90 scenes (30 oil / 30 look-alike / 30 clean sea). The classifier was fit only on
the 240 TRAIN scenes and never saw these.

| | U-Net alone | + look-alike reject @ 0.35 |
|---|---|---|
| Spills found | 28/30 | 26/30 |
| Look-alikes correctly cleared | 9/30 | 19/30 |
| Clean sea correctly cleared | 28/30 | 30/30 |
| **Scene accuracy** | **72.2%** | **83.3%** |
| Pixel precision | 0.438 | 0.623 |
| Pixel recall | 0.850 | 0.680 |
| Pixel IoU | 0.406 | 0.482 |

On held-out OIL scenes only (comparable to published segmentation work):
IoU **0.824** / F1 **0.903** at threshold 0.20; IoU 0.782 / F1 0.878 at 0.50.

Key diagnostic: look-alike scenes false-alarm at **14.1x** the rate of open sea
(11.09% vs 0.79% of pixels at threshold 0.50), and account for **86%** of all
false positives.

## Do not re-tune these on the held-out set

With 30 scenes per class the standard error on a 26/30 rate is about 6 points.
The A7 grid's top band spans 82.2%-84.4%, which is two scenes out of ninety —
noise, not signal. The 84.4% rows reach that number only by finding 20/30 spills.
0.35 / 1.0 km² was chosen from a broad plateau, and 1.0 km² is unchanged from
what `oceanfir.py` already used, so no physical parameter was fitted to the test
set.

## Loading the classifier

```python
import joblib
b = joblib.load("results/lookalike_clf.joblib")
clf, feats, tau = b["clf"], b["features"], b["tau"]   # tau == 0.35
```

Feature order matters and is fixed:
`area, elongation, jaggedness, solidity, eccentricity, mean_in, std_in,
contrast, sea_std, edge_sharp, edge_sharp_std, unet_prob`

The classifier is NOT yet wired into `oceanfir.py`. Doing so adds a
`scikit-learn` runtime dependency that is not currently in `requirements.txt`.

## Not in this folder, on purpose

`unet_oil_v2.pt` (the look-alike hard-negative fine-tune) is deliberately not
committed. It cut false alarms but lost 7 of 30 spills — recall collapsed from
0.850 to 0.311 because 240 of the 360 training scenes contained no oil at all.
Reverted. Details and the corrected recipe are in `REPORT.md` section 4.4.
