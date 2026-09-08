# OceanFIR

SIH 2026 · PS **26143** · NTRO · Disaster Management · Team **Commit & Conquer**

Detect oil slicks in Sentinel-1 SAR imagery and attribute them to a vessel
using historic AIS — scoring the ship's **silence**, not just its visible track.

---

## Read these two files before writing any code

1. **`CONTRACT.md`** — the frozen `data.json` v2.0 schema, the REST endpoints,
   and which lane owns which file. It does not change without a message to all six.
2. The sprint board (link in the group) — your lane, your definition of done,
   and the prompt to paste into your AI tool.

## The one rule that makes six people work in parallel

**Nobody waits for the pipeline.** `mock/data.json` is a complete, schema-valid
document with real vessel names, real AIS tracks and a working attribution
(one accused at 0.801, five suspects, AIS gaps, drift path, dark contacts).
Build against it from minute one. When the real pipeline is ready it drops in
behind the same API and nothing you wrote changes.

If your lane is blocked on someone else's lane, you are doing it wrong — say so
in the group rather than waiting.

---

## Setup

```bash
git clone <repo-url>
cd OceanFIR
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

**Frontend only (lanes B and C)?** You do not need Python at all. Just run the
API someone else has running, or point at the committed `mock/data.json`.

## Run

```bash
# API — serves the contract, including the mock. Start here.
source venv/bin/activate
uvicorn api:app --reload --port 8000
open http://localhost:8000/docs
curl localhost:8000/api/result/mock

# Full pipeline on real data (needs ./fetch_data.sh first, ~40 s to run)
python oceanfir.py --sar sar_sea.png --ais data/AIS_2023_06_20.csv \
  --bbox -90.821 28.133 -88.555 29.2 \
  --time 2023-06-20T00:02:34 --window 3 --top 20

# Rebuild the mock (only if CONTRACT.md changed)
python make_mock.py
```

## The data files are not in git

`data/AIS_2023_06_20.csv` is 927 MB. GitHub rejects anything over 100 MB and it
would make every clone unusable. Get it with:

```bash
./fetch_data.sh
```

Same for model weights (`*.pt`) — share those in the Drive folder, not here.

---

## Layout

```
CONTRACT.md          frozen schema + endpoints + file ownership   [Lane A owns]
oceanfir.py          detection + AIS attribution pipeline         [Lane A]
unet.py              learned detector, drops into detect_slick()  [Lane A]
inject.py            synthetic-slick harness, measures recovery   [Lane A]
api.py               FastAPI, port 8000, v1->v2 adapter           [Lane D]
evidence_pdf.py      build_pdf(doc, path) -> the evidence brief   [Lane D]
drift.py             back-advection to the discharge origin       [Lane E]
web/                 React app (Vite)                             [Lanes B + C]
mock/data.json       the fixture everything is built against      [Lane A owns]
scenes/<id>/         real scene: sar, mask, data.json
notebooks/           Colab exports
data/                AIS + big inputs (gitignored)
legacy/index.html    the original single-file UI, kept for reference
```

## Branches

One branch per lane. You only ever merge at a checkpoint, and Tanish does the merge.

```
main        checkpoint merges only
lane-a      pipeline & ML
lane-b      react — map & scene
lane-c      react — attribution panel
lane-d      api & evidence pdf
lane-e      drift & deploy
```

```bash
git checkout -b lane-b
git add -A && git commit -m "map: draw AIS gaps as dashed cyan"
git push -u origin lane-b
```

**Do not push to `main`. Do not `git push --force`, ever.** File ownership in
CONTRACT.md means your branch should almost never touch a file another lane
touches — if git reports a conflict, that means two people edited one file, so
stop and message the group instead of resolving it yourself.

Lane F (deck, demo, recordings) does not use git. Binary PPTX and MP4 files
belong in the shared Drive folder.

---

## State as of the sprint start

Working: pipeline runs end to end on real data (8.6 M AIS rows → 239 vessels
scored, ~40 s), detection returns 49.4 km² / 13.5 km, API serves v2.0, mock is
complete.

The system currently returns **`no_attribution`** on the Gulf scene. That is
correct, not broken: the top five vessels score 0.50/0.50/0.50/0.49/0.46 with no
AIS gaps, and the margin rule refuses to name a ship it cannot separate from the
next one. `inject.py` is what will prove the positive case.

Open: `inject.py`, U-Net, `evidence_pdf.py`, `drift.py`, the React UI.

## Honest limits — say these before a judge asks

- Detection is classical, so it finds dark anomalies; it does not yet separate
  oil from look-alikes (low wind, biogenic film).
- The Gulf scene is a traffic scene, not a confirmed spill.
- Attribution is validated on controlled injections, not field truth — no public
  dataset has ground-truth spill-to-vessel labels.
- AIS is historical, not live. That is what the PS asks for; free real-time AIS
  does not exist.
- PostgreSQL / TimescaleDB / MinIO / Docker on the deck are **proposed**
  architecture, not built. Label them that way on the slide.
