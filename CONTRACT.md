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
    "detector": "classical" | "unet-resnet34",
    "runtime_s": 2.4
  },

  "scene": {
    "id": "S1A_IW_GRDH_1SDV_20230620T000234",
    "time": "2023-06-20 00:02 UTC",
    "time_iso": "2023-06-20T00:02:34Z",
    "bbox": [lonMin, latMin, lonMax, latMax],   // ALWAYS this order
    "image": "sar_sea.png",                      // relative to /static/{scene_id}/
    "mask":  "mask.png",
    "satellite": "Sentinel-1A",
    "mode": "IW GRDH",
    "polarisation": "VV"
  },

  "detection": {
    "method": "classical" | "unet-resnet34",
    "confidence": 0.87,          // 0..1  model confidence this is oil
    "lookalike_prob": 0.12,      // 0..1  probability it is a look-alike
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
4. `drift` may be `null`. `dark_contacts` may be `[]`. `age_hours_est` may be
   `null`. The UI must render correctly in all three cases — build for that
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
