# OceanFIR — measured results

Every number here came out of a script in this repo. Nothing is estimated and
nothing is rounded in our favour. If a figure is not in this file, it should not
be said out loud.

Regenerate: `python inject.py`, and `notebooks/train_unet.ipynb` for the detector.

---

## 1. Attribution — the part that is actually novel

Measured by `inject.py`. There is no public dataset with ground-truth
spill-to-vessel labels, so attribution accuracy cannot be scored the normal way.
The harness manufactures the measurement: take the real Gulf scene and real AIS,
lay a synthetic slick along a real vessel's wake, blank that vessel's AIS for 60
minutes, run the real scorer, and ask whether it names that ship. Negative trials
put the slick in empty water with nobody's AIS touched.

**20 positive + 10 negative trials, seed 7, shipping rule (threshold 0.45, margin 0.08):**

| | |
|---|---|
| correct vessel accused | 4 / 20 |
| guilty vessel in top 3 | 13 / 20 |
| **wrong vessel accused** | **0 / 20** |
| **false accusation, empty water** | **0 / 10** |
| median rank of guilty vessel | 2.0 |

Say it as **"4 of 4 accusations were correct"**, never "100% precision" — it is
four accusations, and a judge who does that arithmetic should hear it from us first.

The system declines in 80% of cases. That is the honest cost of the margin rule,
and it is the right trade for an evidence system: naming an innocent vessel is a
categorically worse failure than declining to name anyone.

### Why the decision rule is what it is

Same 30 trials re-scored at other rules:

| threshold | margin | recall | wrong | precision |
|---|---|---|---|---|
| 0.45 | 0.00 | 40% | 35% | 53% |
| 0.45 | 0.02 | 35% | 20% | 64% |
| 0.45 | 0.04 | 20% | 20% | 50% |
| **0.45** | **0.08** | **20%** | **0%** | **100%** |
| 0.50 | 0.02 | 35% | 10% | 78% |

We can have 35% recall at the cost of blaming the wrong ship one time in five.
We chose not to.

### Two scoring bugs this harness found

**Gap scale 40 km → 10 km.** Nearly every vessel has *some* AIS gap somewhere in
a 200 km scene, so "silence" scored ~1 for everyone and carried no information
despite holding the heaviest weight (0.42).

| gap scale | recall | wrong | false accusation | median rank |
|---|---|---|---|---|
| 40 km | 15% | 5% | **30%** | 3.5 |
| 20 km | 15% | 10% | 0% | 3.5 |
| 10 km | 15% | 15% | 0% | 2.0 |

**Proximity linear over 25 km → exponential, 2.5 km scale.** A linear falloff
cannot tell 0.5 km from 3 km, so every vessel in one shipping lane scored ~0.9.

| shape | recall | wrong | median rank |
|---|---|---|---|
| linear 25 km | 15% | 15% | 2.0 |
| exp 8 km | 15% | 10% | 2.0 |
| exp 4 km | 15% | 5% | 1.5 |
| **exp 2.5 km** | **20%** | **0%** | 2.0 |

### Why the drift lane is load-bearing

Slick offset from the wake that produced it, same vessels throughout:

| offset | recall | wrong accusations | median rank |
|---|---|---|---|
| 0.2 km | 25% | 5% | 2.5 |
| 0.8 km | 25% | 5% | 2.0 |
| 2.2 km | 15% | 15% | 2.0 |
| 4.5 km | 15% | 20% | 3.0 |
| 8.0 km | 10% | **25%** | 4.0 |

As a slick drifts from its source, recall halves and wrong accusations rise five
times. **Attributing to the slick where we observe it increasingly blames the
wrong ship.** That is the measured case for the reverse-drift hindcast.

---

## 2. Detection — table stakes, and where it falls down

U-Net, resnet34 encoder, 2 classes (sea / oil), trained on the VH channel of
Zenodo's Sentinel-1 oil spill dataset Part III (CC-BY-4.0): 450 labelled scenes,
360 train / 90 held out, 15 epochs on a T4.

| | |
|---|---|
| oil IoU | **0.60 median across epochs, 0.745 best checkpoint** |
| oil precision | 0.779 |
| oil recall | 0.945 |
| oil F1 | 0.854 |

Quote the median alongside the best. Per-epoch IoU bounced between 0.47 and 0.75
with no trend, and taking the maximum of 15 noisy evaluations on 90 crops
overstates true performance.

### The limitation, stated plainly

Predicted oil pixels per held-out scene (of ~3.7M scanned):

| scene type | n | p10 | median | p90 |
|---|---|---|---|---|
| clean sea | 21 | 86 | 845 | 82,432 |
| oil | 32 | 37,067 | 186,584 | 573,039 |
| **look-alike** | 37 | 79 | **197,734** | 1,161,075 |

Look-alike scenes trigger *more* predicted oil than oil scenes do. Sweeping the
scene-level threshold does not separate them:

| threshold (px) | oil detected | clean-sea false alarm | look-alike false alarm |
|---|---|---|---|
| 10,000 | 100% | 33% | 81% |
| 40,000 | 84% | 14% | 73% |
| 150,000 | 56% | 10% | 54% |

At 150,000 it is 56% detection against 54% false alarm — a coin flip.

**The detector separates oil from open water reliably and does not separate oil
from look-alikes at all.** That is the main limitation of the system and we say
it before we are asked.

### Why there is no look-alike class

The design called for three classes. All 450 masks were checked: only the oil
scenes carry labelled pixels — look-alike scenes are annotated identically to
clean sea. A third class with no positive examples trains to nothing and reports
a confident 0.000. The 150 look-alike scenes were used as hard negatives instead,
and the look-alike claim moved to the scene-level rate above.

`detection.lookalike_prob` in the contract is therefore `null` from the U-Net path.

---

## 3. The two detectors on the real scene

Mississippi Delta, Sentinel-1A, 2023-06-20 00:02 UTC, bbox
`-90.821 28.133 -88.555 29.2`, 8.6 M AIS rows scanned, 266 vessels in window,
239 scored.

| | classical | U-Net |
|---|---|---|
| slick area | 49.4 km² | 123.8 km² |
| slick length | 13.5 km | 16.9 km |
| detection confidence | n/a | 0.663 |
| top vessel | FEDERAL PILOT II 0.381 | GULF DAWN 0.577 |
| top vessel AIS gap | 0 min | 36 min |
| verdict | no attribution | no attribution |

Both decline. The U-Net run came closest: GULF DAWN scored 0.577 at 0.2 km with a
36-minute blackout, and the runner-up was 0.51 — a margin of 0.07 against the
0.08 rule. **The system came within 0.01 of naming a ship and declined anyway.**

Worth stating: the two detectors find different slicks and therefore produce
different candidate sets. Detector choice materially changes who gets accused,
which is an argument for reporting detection confidence alongside any accusation.

---

## 4. Limits to state before anyone asks

- Attribution is validated on controlled injections, not field-confirmed spills.
  No public dataset has ground-truth spill-to-vessel labels.
- 20 positive and 10 negative trials, one scene, one seed. Directional, not
  publication-grade.
- The Gulf scene is a traffic scene, not a confirmed spill. Detection capability
  is measured separately on labelled data.
- The detector cannot reject look-alikes (§2).
- Trained on the *test* release of the Zenodo series; the 40 GB training release
  did not fit the build window. Held out 20% of 450 scenes.
- Trained on VH only. VV carried no usable contrast in this dataset
  (+0.02 dB inside the slick versus its local ring, against +4 to +6 dB for VH).
  Using both polarisations is the obvious next improvement.
- AIS is historical, not live. That is what the problem statement asks for; free
  real-time AIS does not exist.
- PostgreSQL / TimescaleDB / MinIO / Docker on the deck are proposed
  architecture, not built.
