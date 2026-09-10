# OceanFIR — FROZEN CONTRACT v2.0

**Do not change anything in this file without telling the whole team.**
Every lane builds against this. If it changes, someone's work breaks.

The rule that makes 6 people work in parallel: **nobody waits for the Python
pipeline.** Everything downstream is written against `mock/data.json`, which
already exists and already validates against this schema. When the real
pipeline is ready it drops in and nothing else changes.

---

## 1. The data document (`data.json` v2.0)

```jsonc
{
  "meta": {
    "version": "2.0",
    "source": "pipeline" | "mock",        // mock data is ALWAYS labelled
    "generated_utc": "2026-09-08T18:40:00Z",
    "detector": "classical" | "unet-resnet34",  // SAME spelling as
                                 //   detection.method below. Two spellings for
                                 //   one thing is how fields drift apart.
    "runtime_s": 2.4
  },

  "scene": {
    "id": "S1A_IW_GRDH_1SDV_20230620T000234",
    "time": "2023-06-20 00:02 UTC",
    "time_iso": "2023-06-20T00:02:34Z",
    "bbox": [lonMin, latMin, lonMax, latMax],   // ALWAYS this order
    "image": "sar_sea.png",                      // relative to /static/{scene_id}/
    "mask":  "data_unet.png",   // FILENAME VARIES -- never hardcode "mask.png".
                                //   Each result names its own overlay so a
                                //   classical result cannot be drawn with the
                                //   U-Net's mask. Read this field.
    "satellite": "Sentinel-1A",
    "mode": "IW GRDH",
    "polarisation": "VV+VH"       // IW GRDH 1SDV is dual-pol and the U-Net
                                  //   reads VH, so plain "VV" misdescribes
                                  //   what we actually process
  },

  "detection": {
    "method": "classical" | "unet-resnet34",
    "confidence": 0.663,         // 0..1 mean oil probability over the region.
                                 //   null on the classical path -- an
                                 //   unsupervised threshold has no confidence.
    "lookalike_prob": null,      // ALWAYS null. The dataset annotates only oil
                                 //   pixels, so there is no look-alike class to
                                 //   take a probability from. The look-alike
                                 //   number is a scene-level false-alarm rate in
                                 //   results/RESULTS.md. Render "not available",
                                 //   never 0%.
    "slick": {
      "polygon": [[lon, lat], ...],        // closed ring, lon/lat, 20-60 points
      "area_km2": 70.8,
      "length_km": 15.3,
      "head": [lon, lat],                  // northernmost / upstream point
      "centroid": [lon, lat],
      "coverage_pct": 0.17,
      "age_hours_est": [4, 9]              // [min, max], null if not estimated
    }
  },

  "drift": {                     // null until Lane E lands — UI must handle null
    "method": "back-advection",
    "origin": [lon, lat],
    "origin_time_iso": "2023-06-19T18:30:00Z",
    "uncertainty_km": 3.2,
    "path": [[lon, lat, "ISO8601"], ...],  // slick head backwards in time
    "ensemble": [[[lon, lat], ...], ...]   // optional, N back-tracks, may be []
  },

  "forecast": {                  // null when not run. Forward advection: where
                                 //   the slick is GOING. drift above is where it
                                 //   came FROM. Both are asked for by the PS.
    "method": "forward-advection",
    "endpoint": [lon, lat],      // slick head at the end of the horizon
    "endpoint_time_iso": "2023-06-20T12:02:34Z",
    "uncertainty_km": 5.2,       // 90th pct spread of the ensemble endpoints
    "path": [[lon, lat, "ISO8601"], ...],   // head forwards in time
    "ensemble": [[[lon, lat], ...], ...],
    "forcing": {                 // provenance of the current used, so nobody
                                 //   has to guess where -0.25 m/s came from
      "u_ms": -0.25, "v_ms": -0.12,
      "wind_ms": [0.0, 0.0],
      "effective_u_ms": -0.25, "effective_v_ms": -0.12,
      "n_ensemble": 25,
      "source": "free text -- where these numbers came from"
    }
  },

  "vessels": [
    {
      "mmsi": 367481920,
      "name": "JACK CENAC",
      "type": "Tanker",
      "len_m": 183,

      "score": 0.67,             // 0..1 combined
      "proximity": 0.61,         // 0..1 each component, all four always present
      "parity": 0.72,
      "temporality": 0.75,
      "silence": 0.40,

      "ais_gap_min": 54,         // 0 if no gap
      "dist_km": 8.6,            // closest approach to slick (or to drift origin)
      "dark": true,              // radar contact with no AIS
      "verdict": "accused" | "suspect" | "cleared",
      "reason": null,            // string ONLY when verdict == "cleared"

      "track": [[lon, lat], ..., null, ...]   // null = AIS reporting gap
    }
  ],

  "dark_contacts": [             // radar ship detections with no AIS match
    { "id": "dc_01", "lon": -89.42, "lat": 28.71, "len_px": 34, "matched_mmsi": null }
  ],

  "summary": {
    "verdict": "accused" | "no_attribution",
    "accused_mmsi": 367481920,   // null when no_attribution
    "threshold": 0.45,
    "n_scored": 557,
    "n_suspect": 3,
    "n_cleared": 553,
    "note": "human-readable one-liner for the UI banner"
  }
}
```

### Hard rules

1. `bbox` is **always** `[lonMin, latMin, lonMax, latMax]`. Never lat-first.
2. `null` inside a `track` array is an **AIS gap**, not missing data. The UI
   draws the runs either side solid and bridges the gap with a **dashed cyan
   line**. That dashed line *is* the "silence as evidence" idea — it is the
   single most important pixel in the whole product. Do not skip it.
3. `reason` is non-null **only** for `verdict == "cleared"`. It is a computed
   sentence, never hardcoded.
4. `drift` may be `null`. `dark_contacts` may be `[]`. `age_hours_est`,
   `confidence` and `lookalike_prob` may be `null`. The UI must render
   correctly in all of these cases — build for that
   from hour one, not as a patch later.
5. Every score field is `0..1`. Never a percentage, never 0..100.
6. `summary.verdict == "no_attribution"` is a **legitimate, correct output**,
   not an error. A system that declines to accuse when the evidence is weak is
   a feature. The UI needs a designed state for it.

---

## 2. The REST API

Base: `http://localhost:8000`

| Method | Path | Returns |
|---|---|---|
| `GET`  | `/api/health` | `{"status":"ok","version":"2.0"}` |
| `GET`  | `/api/scenes` | `[{"id","name","time_iso","thumb","has_result"}]` |
| `POST` | `/api/analyze` | body `{"scene_id":"...","window_h":3}` → full data.json v2 |
| `GET`  | `/api/result/{scene_id}` | full data.json v2, `404` if never analysed |
| `GET`  | `/api/vessels/{scene_id}?verdict=cleared` | filtered `vessels` array |
| `GET`  | `/api/evidence/{scene_id}` | `application/pdf` evidence brief |
| `GET`  | `/static/{scene_id}/{file}` | `sar_sea.png`, `mask.png` |

- CORS is open to `*` in dev. Frontend calls the API directly, no proxy.
- Errors: `{"error": "human readable string"}` with a real HTTP status code.
- `POST /api/analyze` is **synchronous** and takes ~40 s on the real AIS file.
  The UI must show a progress state. There is no job queue — do not build one.

---

## 3. File ownership — one owner per file, no exceptions

Merge conflicts are the number one way a 1.5-day build dies. Nobody edits a
file they do not own. If you need a change in someone else's file, message them.

| File / folder | Owner |
|---|---|
| `oceanfir.py`, `unet.py`, `inject.py` | Lane A |
| `web/src/components/Map*`, `web/src/components/Evidence*` | Lane B |
| `web/src/components/Vessel*`, `web/src/components/Score*` | Lane C |
| `api.py`, `evidence_pdf.py` | Lane D |
| `drift.py`, `deploy/` | Lane E |
| `deck/`, `demo/`, `README.md` | Lane F |
| `CONTRACT.md`, `mock/data.json` | **Lane A only.** Read-only for everyone else. |

`web/src/App.jsx` and `web/src/api.js` are shared — Lane B owns them, Lane C
requests changes. Do not both edit them.


---

## 4. Changelog

**10 Sept — `forecast` added, and `drift` gains `forcing`. Additive, nothing breaks.**
The PS asks for drift "backward and forward"; only the hindcast existed. A new
top-level `forecast` block carries the forward advection — same integration and
the same 25-member ensemble as `back_advect`, sign flipped, so the two cannot
drift apart as the model is tuned. It is `null` when not run, like `drift`, and
the UI must handle that. Both blocks now carry `forcing`, recording the current
and wind actually used plus a free-text `source`, because the PS names
oceanographic and meteorological data as inputs and a bare `-0.25` in a shell
history is not provenance. The values live in `scenes/<id>/scene.json` per scene,
not in `drift.py`.

**Age (`detection.slick.age_hours_est`) stays `null` on the real path, deliberately.**
Age from a single SAR pass needs a spreading model with an assumed discharge
volume. We do not know the volume, so any figure would be invented. Two passes
over the same slick give it properly. The PS says "if feasible" — this is us
saying it is not, rather than printing a number we cannot defend.

**9 Sept — the pipeline now emits v2.0 directly. No schema change.**
`oceanfir.py` used to write a flat v1 document that `api.py` lifted into v2 on
the way out, so the file on disk never matched the schema everyone validates
against. It now writes the contract shape itself. The adapter in `api.py`
short-circuits on `meta.version == "2.0"` and stays where it is, harmless.
Two values were tightened at the same time: `meta.detector` now uses the same
spelling as `detection.method` (`unet-resnet34`, not `unet`), and
`scene.polarisation` is `VV+VH`. `scene.image` is now a bare filename — it used
to be whatever path the pipeline was invoked with, which 404s in the UI.
`summary.n_scored / n_suspect / n_cleared` count the WHOLE scored population;
`vessels[]` is truncated by `--top`, so they are `>=` its length, never equal.

**9 Sept — two wrong values fixed in `mock/data.json`.**
`detection.lookalike_prob` was `0.12`. It is now `null`, as this file has always
said it must be. The slick ring was 19 points against a stated 20-60 and has
been densified to 21 — same shape. And the accused vessel cleared the runner-up
by 0.076, under the 0.08 `MIN_MARGIN` the real scorer enforces, so the fixture
showed an accusation the pipeline would itself have refused; the runner-up now
scores 0.715. Nothing built against the mock needs rework.

**9 Sept — scoring tuned from measurement, no schema break.**
Field shapes are unchanged; only values moved. `proximity` is now an
exponential falloff with a 2.5 km scale instead of linear over 25 km, and the
AIS gap scale went 40 km to 10 km. Both were measured with `inject.py`, not
guessed — see `results/RESULTS.md`. Practical effect: **scores are lower across
the board.** The top vessel on the real scene scores 0.58, not 0.9. Do not
hardcode UI colour thresholds that assume high scores.

**9 Sept — three clarifications, marked inline above.**
`scene.mask` is a filename that varies per result. `detection.confidence` is
real on the U-Net path and null on the classical one. `detection.lookalike_prob`
is always null, and why.

`mock/data.json` is unchanged by any of this. Nothing built against it needs
rework.
