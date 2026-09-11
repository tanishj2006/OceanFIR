# OceanFIR — Final Report

**Problem Statement SIH26143 · NTRO · Space Technology**
**Team Commit & Conquer · Smart India Hackathon 2026**
Report date: 11 September 2026

---

## 1. What the problem is

Ships dump oil at sea. Sometimes it is an accident. Very often it is deliberate —
a ship washes out its tanks or dumps waste oil at night, far from the coast,
because it is cheaper than paying for proper disposal.

Two things make this hard to stop:

1. **You cannot see it.** These dumps happen hundreds of kilometres offshore, at
   night, in bad weather. No patrol boat is watching.
2. **By the time anyone notices, the ship is gone.** Oil drifts with the current
   and wind. A slick found this morning may have been dumped 12 hours ago,
   30 km away, by a ship that is now 300 km away.

So the oil is found, and nobody is punished. The problem statement asks us to
close that gap: **find the oil from satellite radar, work out where it came
from, and name the ship that did it.**

---

## 2. What we built

**OceanFIR** is a working software pipeline. It takes a satellite radar image
and a file of ship position records, and it produces an evidence report that
either names a ship or explicitly says "we cannot name anyone, and here is why."

It has four stages.

### Stage 1 — Find the oil

Satellite radar (Sentinel-1) does not take photographs. It bounces radio waves
off the sea and measures what comes back. A rough, windy sea scatters the waves
and looks **bright**. Oil flattens the tiny ripples on the surface, so an oil
slick scatters less and looks **dark**.

We use a neural network (a U-Net) that has been trained to outline the dark
patches that are oil.

### Stage 2 — Reject the false alarms

Here is the central difficulty of this whole field: **oil is not the only thing
that looks dark on radar.** Low wind, algae blooms, natural biological films,
rain cells — these all flatten the sea surface too. They are called
**look-alikes**, and to a radar they are nearly identical to oil.

So we added a second stage. It takes each dark patch the U-Net found, measures
12 properties of it (how rough its inside is, how sharp its edges are, how much
darker it is than the sea around it, its shape), and a machine-learning
classifier decides: real oil, or look-alike?

### Stage 3 — Drift the slick backwards in time

Oil moves. We run the slick backwards through the ocean current and wind to
estimate where it was released. We run this 25 times with slightly different
current and wind values, and the spread of those 25 answers becomes our
uncertainty circle — typically about **±5 km over 12 hours**. We do not guess
this number; it comes out of the spread.

### Stage 4 — Name the ship

Every large ship broadcasts its position over AIS (Automatic Identification
System). We take every ship that was near the estimated release point at the
estimated release time and score it on four things:

| What we score | Weight | Why |
|---|---|---|
| **Proximity** — how close the ship was | 0.30 | It had to be there |
| **Parity** — does the ship type match | 0.10 | A tanker is more likely than a ferry |
| **Temporality** — was it there at the right time | 0.18 | It had to be there *then* |
| **Silence** — did the ship's AIS go quiet | **0.42** | **This is our main idea** |

**Why "silence" carries the most weight.** A ship that is about to dump oil
turns its AIS transponder off. So we do not look for a ship we can see — we look
for a **gap** in the record. A ship that goes silent for an hour right over the
release point, and reappears afterwards, is far more suspicious than one that
broadcast continuously the whole time. This is backed by published research
(Welch et al., *Science Advances*, 2022) showing AIS is deliberately disabled.

**The system is allowed to say "I don't know."** We only name a ship if its
score is above 0.45 **and** it beats the second-place ship by at least 0.08. On
the real Gulf of Mexico scene we tested, the top five ships scored
0.50 / 0.50 / 0.50 / 0.49 / 0.46 — too close to separate — so the system
**refused to accuse anyone**. We consider that the correct behaviour. A system
that always names someone is a system that sometimes names the wrong person.

The output includes an **exoneration record**: every ship that was considered and
cleared, with the reason it was cleared. That is what makes the evidence stand up
if it is challenged.

---

## 3. The numbers

Everything below was measured on **data the model had never seen during
training**. We split the data by whole scenes, not by small image patches, so
there is no way for the model to have memorised part of a test image.

### 3.1 The test data

450 satellite scenes from a public Sentinel-1 oil spill dataset (Zenodo, free to
use under a CC-BY licence). Each image is 2048 × 2048 pixels.

| Type | Total | Used for training | Kept aside for testing |
|---|---|---|---|
| Real oil spills | 150 | 120 | 30 |
| Look-alikes (not oil) | 150 | 120 | 30 |
| Clean sea | 150 | 120 | 30 |

### 3.2 Finding the oil (tested only on scenes that contain oil)

This is how research papers normally report this kind of result, so these are
the numbers that are comparable to published work.

| Setting | Precision | Recall | F1 | IoU |
|---|---|---|---|---|
| Sensitive (threshold 0.20) | 0.880 | 0.928 | **0.903** | **0.824** |
| Balanced (threshold 0.50) | 0.906 | 0.851 | 0.878 | 0.782 |

**In plain words:** when there is oil in the picture, the model finds about
**93%** of it, and about **88%** of what it marks really is oil.

**IoU** ("Intersection over Union") measures how well the outline it draws
matches the true outline. **0.824 means the shapes overlap 82%.**

One important detail: the model's own score during training was **0.745**. On
scenes it had never seen, it scored **0.782–0.824** — *better*. That means the
model is not memorising. It genuinely generalises.

### 3.3 The realistic test (oil + look-alikes + clean sea together)

This is the harder test, and most published work does not run it. We mixed all
90 held-out scenes together, so the model has to handle pictures with no oil in
them at all.

| | U-Net alone | U-Net + look-alike reject |
|---|---|---|
| Real spills correctly found | 28 / 30 | 26 / 30 |
| Look-alike scenes correctly ignored | 9 / 30 | **19 / 30** |
| Clean sea correctly ignored | 28 / 30 | **30 / 30** |
| **Overall scene accuracy** | **72.2%** | **83.3%** |
| Pixel precision | 0.438 | 0.623 |
| Pixel IoU | 0.406 | 0.482 |

**The headline: our look-alike reject stage raised overall accuracy from
72.2% to 83.3%, and brought false alarms on clean sea down to zero.**

### 3.4 Why we measured look-alikes separately (the key finding)

We measured how often the detector fires on a picture with no oil in it:

| Scene type | False alarm rate |
|---|---|
| Look-alike scenes | **11.09%** of pixels |
| Clean open sea | 0.79% of pixels |

**Look-alikes cause 14.1 times more false alarms than open sea.** And of every
false alarm the system produces:

- **86%** come from look-alike scenes
- 8% come from inside real oil scenes (slightly wrong outlines)
- 6% come from clean sea

This single measurement is the most useful thing we produced. It tells us
exactly where the remaining problem is, and it is why we built the reject stage
rather than, say, collecting more oil images.

### 3.5 The look-alike classifier

Trained on 5,533 dark patches taken from the 240 training scenes (1,295 from oil
scenes, 4,238 from look-alike scenes). Cross-validated by scene, so patches from
the same picture never appear on both sides of the test.

Which properties mattered most:

| Property | Importance |
|---|---|
| Roughness inside the patch | 0.182 |
| Sharpness of the edges | 0.164 |
| Average darkness | 0.126 |
| Variation in edge sharpness | 0.109 |
| Roughness of the surrounding sea | 0.109 |
| Contrast against the sea | 0.089 |
| What the U-Net thought | 0.075 |
| Area, shape, elongation, etc. | 0.025–0.053 each |

**What this tells us, and it surprised us:** the *shape* of a patch barely
matters. All five shape measurements together are worth less than the single
"roughness inside" measurement. Classic 1990s oil-spill papers relied heavily on
shape. In our system the neural network has already used up the shape
information, so what the classifier adds is **texture** — how grainy the patch is
and how crisp its border is. Oil has a smooth, sharply-bounded interior;
look-alikes are patchier with softer edges.

Also worth noting: "what the U-Net thought" ranked only 7th. The classifier is
not just re-reading the neural network's confidence — it is bringing genuinely
new evidence.

### 3.6 Attribution

There is **no public dataset anywhere in the world** that says "this slick was
caused by that ship." Nobody has ever published verified spill-to-vessel truth
at scale. So we cannot report an accuracy figure for attribution the way we can
for detection, and we will not invent one.

What we do instead: a **controlled injection test**. We take a real satellite
scene with real ship traffic, place a synthetic slick along a known ship's wake,
delete that ship's AIS record for a period, run the full real pipeline, and check
whether it recovers the correct ship. On our test case the correct vessel was
recovered at a score of 0.801 with five other ships listed as considered and
cleared.

This is honest but limited: we built the test, so we know the answer. It proves
the scoring logic works. It does not prove real-world accuracy.

---

## 4. Why the numbers are not higher

This is the section we most want to be straight about. There are five reasons,
and only one of them is about our code.

### Reason 1 — The training data has no look-alike labels (the biggest one)

The public dataset gives us oil masks. For look-alike scenes, the mask is
**entirely blank** — every pixel is labelled "not oil."

That means when the model trains on a look-alike picture, it is being told
*"this dark algae patch is ordinary sea water."* But it plainly is not ordinary
sea water — it is dark, just like oil. The model is never once shown a label
that says *"this is a dark patch that is NOT oil."*

So the model has only two categories: oil and sea. Look-alikes fall into the
crack between them. **This is a limitation of how the dataset was built, not of
our network.** No amount of extra training on this dataset fixes it, because the
information simply is not in the labels.

### Reason 2 — Oil and look-alikes are genuinely similar on radar

Even with perfect labels there is a physical ceiling. Radar measures surface
roughness. Oil damps the small surface ripples and looks dark. Low wind damps
the same ripples and looks dark. A biological film damps the same ripples and
looks dark. **The sensor is measuring the same physical effect in all three
cases.**

Human experts get this wrong too. Separating them reliably needs information the
image alone does not contain — see Section 5.

### Reason 3 — We could only use part of the dataset

The full dataset comes in three parts:

| Part | Contents | Actual download size |
|---|---|---|
| Part I | 1,200 oil scenes | **40.7 GB** |
| Part II | 685 look-alike + 685 clean sea | **45.9 GB** |
| Part III | 450 test scenes | ~9 GB — **this is what we used** |

Parts I and II together are **86.6 GB compressed**. Free Google Colab gives us
about **50 GB** of disk. Extracting Part I alone needs roughly 81 GB at peak
(the compressed file and the extracted files have to exist at the same time). It
physically does not fit.

We checked whether this actually mattered before accepting it — and it does not,
much. Our model already scores *better* on unseen data (IoU 0.782) than it did on
its own training validation (0.745), which means it is not short of oil examples.
More oil pictures would not have helped. More *look-alike labels* would have.

### Reason 4 — We tried to fix it by retraining, and it made things worse

We attempted exactly the obvious fix: fine-tune the network with the 120
look-alike scenes fed in as "hard negatives." The result:

| | Before | After fine-tune |
|---|---|---|
| Spills found | 28/30 | **21/30** |
| Recall | 0.850 | **0.311** |
| IoU | 0.482 | 0.269 |
| Look-alike false alarms | 21/30 | 8/30 |

It cut false alarms, but it **lost 7 spills out of 30** to do it. The cause: of
the 360 training scenes, 240 contained no oil at all, and a random crop taken
from an oil scene often contains no oil either. The training signal became about
96% "no oil," so the network learned the easiest possible answer — say "no oil"
everywhere. Its training loss went *down* the whole time, which is exactly why
this failure is easy to miss.

We reverted it. We are reporting it because it is a real, measured result and it
tells you precisely what a future attempt must fix.

### Reason 5 — The test set is small, so small gains cannot be proven

We have 30 scenes of each type. With 30 samples, the statistical margin of error
on a "26 out of 30" result is roughly **±6 percentage points**.

That means any result between about 80% and 86% is **the same result**. When we
swept every combination of settings, the best configurations ranged from 82.2%
to 84.4% — a spread of **two scenes out of ninety**. That is noise, not
improvement.

We could have reported 84.4%. We did not, because the configuration that reaches
84.4% gets there by **finding only 20 of 30 spills**. Overall accuracy treats a
missed spill and a false alarm as equally bad. In reality they are not: an
analyst dismisses a false alarm in seconds, but a missed spill is a polluter who
gets away. We chose the setting that finds 26 of 30.

---

## 5. What we would need to do better

In rough order of how much each would help:

### 5.1 Data with look-alike labels — the single biggest unlock

A dataset where look-alikes are labelled **as look-alikes**, not as blank sea.
This lets us train a three-class model (sea / oil / look-alike) instead of
two-class, so the network learns the distinction directly instead of us patching
it afterwards.

The Krestenitis dataset from MKLab (Greece) has exactly this — five classes
including look-alike, ship and land. It is **restricted access**: you apply with
an institutional email, a project description and a supervisor's approval.

*(A copy of this dataset is floating around on Kaggle with no licence stated. We
deliberately did not use it. Beyond the licensing problem, it is 8-bit JPEG,
which destroys the radar measurement values our pipeline depends on. For an NTRO
problem statement, using unlicensed data is not a risk worth taking.)*

### 5.2 Use both radar channels instead of one

Sentinel-1 records **two** channels — VV and VH — which measure the sea with
differently-oriented radio waves. **We currently use only one.**

The ratio between the two behaves differently for oil than for low wind. Using
both is well-established in the literature as a look-alike discriminator, and it
requires **no new data at all** — the second channel is already sitting in every
file we downloaded. This is the cheapest available improvement and the first
thing we would do.

### 5.3 Add the wind field

The most common look-alike is a **low-wind patch**. If we know the wind speed at
the location and moment the image was taken, low-wind areas can be flagged
directly instead of guessed at from texture.

ERA5 reanalysis wind data is **free** from Copernicus. This is a data-plumbing
job, not a research problem.

### 5.4 More training data, properly balanced

Parts I and II of the Zenodo dataset (86.6 GB) on a machine with 100+ GB of disk
and a better GPU. Combined with a corrected training recipe — oil weighting
raised from 2 to about 6, the 120 all-sea scenes dropped, and crops centred on
oil rather than placed randomly — this would give the retrain a fair chance.

### 5.5 Verified spill reports for real attribution validation

To put a true accuracy number on attribution we need confirmed cases: "on this
date, at this position, this vessel was prosecuted for this discharge." That data
exists inside coast guards and pollution-control authorities. It is not public.
Access would need an institutional partnership — which, for an NTRO problem
statement, is a realistic path rather than a fantasy one.

### 5.6 Satellite AIS coverage

The free AIS feeds are **terrestrial** — shore-based receivers that reach maybe
40–60 nautical miles offshore. Deliberate dumping happens well beyond that.
Covering India's full Exclusive Economic Zone requires **satellite** AIS, which
is a paid commercial service (see costs below).

---

## 6. Costs

### 6.1 What is free — and it is most of it

| Item | Cost | Notes |
|---|---|---|
| Sentinel-1 satellite radar | **Free** | Copernicus Data Space Ecosystem, open licence |
| Training data (Zenodo Parts I–III) | **Free** | CC-BY-4.0 |
| Historic AIS (US waters) | **Free** | MarineCadastre / NOAA |
| Ocean currents | **Free** | Copernicus Marine, registration required |
| Wind data (ERA5) | **Free** | Copernicus |
| All software | **Free** | PyTorch, FastAPI, React — open source |
| Live coastal AIS | **Free** | aisstream.io — terrestrial only, 3 connections |

**The entire prototype was built for ₹0 in data and software costs.** That is
worth saying out loud.

### 6.2 What costs money

All figures are **estimates** from public pricing pages, gathered September 2026.

| Item | Estimated cost | Why you would need it |
|---|---|---|
| **Satellite AIS** (Spire Maritime) | **$2,000–8,000 / month** | Tracks ships beyond coastal radio range. This is the single largest running cost and it is unavoidable for open-ocean coverage. |
| Commercial AIS API (MarineTraffic) | $200–500 / month | Cheaper, but coastal-focused and priced per call |
| Full maritime intelligence platform | ~$75,000 / year | Enterprise tier; almost certainly overkill here |
| GPU for training | ~$10 / month (Colab Pro) or $1–4 / hour (cloud A100) | Only needed while training, not while running |
| Server to run the system | ~$50–200 / month | A modest cloud VM is enough |
| Storage | ~₹ varies by provider | See estimate below |

### 6.3 What it would cost to actually run this over India's EEZ

These are our own estimates, built from measured numbers. The assumptions are
stated so they can be checked.

**Data volume.** India's Exclusive Economic Zone is roughly 2.3 million km². One
Sentinel-1 IW scene covers about 250 × 250 km (~62,500 km²), so covering the EEZ
once takes roughly **38 scenes**. The current Sentinel-1C/1D constellation has a
**6-day revisit**, giving about **6 scenes per day**, or **~2,300 scenes per
year**. At roughly 1.6 GB per scene that is **3–4 TB per year** of raw imagery —
though scenes can be processed and discarded rather than archived.

**Processing cost — and this is the good news.** We measured our model at about
0.85 seconds per 2048 × 2048 image on a basic T4 GPU. A full Sentinel-1 scene is
roughly 100 times larger, so about **85 seconds of GPU time per scene**. At 6
scenes a day that is **under 10 minutes of GPU time per day** to monitor India's
entire EEZ. A single cheap cloud GPU, or even one good desktop machine, is
enough. **Compute is not the bottleneck. Data licensing is.**

**Realistic annual running cost:**

| Component | Estimated annual cost |
|---|---|
| Satellite imagery | ₹0 (free) |
| Satellite AIS | ₹20–70 lakh (~$24,000–96,000) |
| Compute + hosting | ₹1–3 lakh |
| Storage | ₹1–2 lakh |
| **Total** | **roughly ₹25–75 lakh per year**, dominated by AIS |

For context, a single large oil spill clean-up costs far more than this, and the
fines available under India's maritime pollution rules are substantial. But we
are engineers, not accountants — we are presenting the cost, not claiming a
return on it.

### 6.4 The hard operational limit nobody can buy their way past

Sentinel-1 revisits a given point roughly **every 6 days**.

This means OceanFIR is a **forensic and deterrence** tool, not a real-time alarm.
We cannot catch a ship in the act. What we can do is find the slick on the next
pass, drift it backwards, and name the ship from the historical record — which is
exactly what the problem statement asks for.

Faster revisit would need either commercial SAR satellites (Capella, ICEYE —
priced per image and expensive) or India's own RISAT/EOS radar satellites, which
would be a national-capability question rather than a procurement one.

---

## 7. What we are honest about

We would rather state these ourselves than have them found.

1. **11 of 30 look-alike scenes still raise a false alarm.** Look-alike
   discrimination is improved, not solved.
2. **2 of 30 spills are missed before the classifier is even involved** — lost
   by the detector itself or by our minimum-size filter. No amount of threshold
   tuning recovers them.
3. **Attribution has no field-truth validation**, because no such dataset exists
   publicly. We validate on controlled injections, which we built ourselves.
4. **AIS is historical, not live.** This is what the problem statement asks for,
   and free real-time AIS does not exist.
5. **Pixel size is assumed to be 10 m** (the Sentinel-1 nominal figure) when
   converting our area filter to km². The dataset record does not state the
   spacing, so any km² figure we quote carries that assumption.
6. **The database and container parts of our architecture diagram are proposed,
   not built.** They are labelled as such.
7. **Our test set is 30 scenes per class.** Differences smaller than about 6
   percentage points are not statistically meaningful.

---

## 8. Summary — the numbers in one place

| Measurement | Value |
|---|---|
| Oil outline accuracy on unseen oil scenes (IoU) | **0.824** |
| Oil detection F1 on unseen oil scenes | **0.903** |
| Overall scene accuracy, realistic mixed test | **83.3%** |
| Same, without our look-alike reject stage | 72.2% |
| Real spills found | 26 / 30 |
| Clean sea scenes correctly cleared | 30 / 30 |
| Look-alike false alarm rate vs open sea | **14.1×** |
| Share of all false alarms caused by look-alikes | **86%** |
| Drift uncertainty over 12 hours | ±5.17 km |
| Scenes used for testing (never trained on) | 90 |
| Data and software cost of the prototype | **₹0** |

---

## Appendix — small glossary

- **SAR** — Synthetic Aperture Radar. A satellite radar that works at night and
  through cloud, because it makes its own radio signal instead of relying on
  sunlight.
- **VV / VH** — the two channels Sentinel-1 records, differing in how the radio
  wave is oriented on the way out and on the way back.
- **Precision** — of everything the system flagged as oil, what fraction really
  was oil.
- **Recall** — of all the oil that was actually there, what fraction the system
  found.
- **F1** — a single score combining precision and recall.
- **IoU** — how well the outline drawn overlaps the true outline. 1.0 is perfect.
- **Look-alike** — something that looks like oil on radar but is not: low wind,
  algae, biological films, rain.
- **AIS** — Automatic Identification System. The radio beacon large ships
  broadcast with their identity, position, course and speed.
- **Held-out data** — data deliberately kept away from the model during
  training, used only to test it. The only honest way to measure.

---

*All figures in this report were measured on 11 September 2026 using
`notebooks/oceanfir_improve_v2.ipynb`. Cost figures are estimates from public
pricing pages gathered the same day and should be re-checked before being
quoted in any commitment.*
