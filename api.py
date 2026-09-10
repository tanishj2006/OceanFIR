#!/usr/bin/env python3
"""
OceanFIR REST API — the thin layer between the Python pipeline and the React UI.

Serves CONTRACT.md v2.0 and nothing else. If you are about to add a field,
add it to CONTRACT.md first and tell the team.

    pip install fastapi uvicorn python-multipart
    uvicorn api:app --reload --port 8000
    open http://localhost:8000/docs

Scenes live in ./scenes/{scene_id}/ containing sar.png, mask.png, data.json.
The special scene id "mock" is served from ./mock/data.json so the frontend
works before the pipeline does.
"""
import json, os, subprocess, sys, time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).parent
SCENES = ROOT / "scenes"
SCENES.mkdir(exist_ok=True)

app = FastAPI(title="OceanFIR", version="2.0",
              description="Oil slick detection and AIS vessel attribution")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# --------------------------------------------------------------- v1 -> v2
def upgrade_v1(doc: dict) -> dict:
    """The pipeline still emits the old flat shape. Lift it into v2 so the
    frontend only ever sees one schema. Delete this once oceanfir.py emits v2."""
    if doc.get("meta", {}).get("version") == "2.0":
        return doc
    vessels = doc.get("vessels", [])
    acc = next((v for v in vessels if v.get("verdict") == "accused"), None)
    sc = doc.get("scene", {})
    return {
        "meta": {"version": "2.0", "source": "pipeline",
                 "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 # the pipeline writes `detector` at the top level; the contract
                 # says it lives in meta, so it is mapped here rather than
                 # leaking a second spelling to the frontend
                 "detector": doc.get("detector", "classical"),
                 "runtime_s": None},
        "scene": {**sc, "time_iso": sc.get("time_iso"),
                  "satellite": "Sentinel-1A", "mode": "IW GRDH",
                  "polarisation": "VV"},
        "detection": {"method": doc.get("detector", "classical"),
                      # both filled by the U-Net path; classical leaves them null
                      "confidence": doc.get("slick", {}).get("confidence"),
                      "lookalike_prob": doc.get("slick", {}).get("lookalike_prob"),
                      "slick": {**doc.get("slick", {}),
                                "centroid": doc.get("slick", {}).get("centroid"),
                                "age_hours_est": None}},
        "drift": doc.get("drift"),   # filled by drift.py via oceanfir.py
        "vessels": vessels,
        "dark_contacts": [],
        "summary": {"verdict": "accused" if acc else "no_attribution",
                    "accused_mmsi": acc["mmsi"] if acc else None,
                    "threshold": 0.45,
                    "n_scored": len(vessels),
                    "n_suspect": sum(1 for v in vessels if v.get("verdict") == "suspect"),
                    "n_cleared": sum(1 for v in vessels if v.get("verdict") == "cleared"),
                    "note": (f"{acc['name']} accused"
                             if acc else "No vessel meets the attribution threshold.")},
    }


def load(scene_id: str) -> dict:
    p = (ROOT / "mock" / "data.json") if scene_id == "mock" \
        else (SCENES / scene_id / "data.json")
    if not p.exists():
        raise HTTPException(404, f"scene '{scene_id}' has no result yet")
    return upgrade_v1(json.load(open(p)))


# --------------------------------------------------------------- endpoints
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0"}


@app.get("/api/scenes")
def scenes():
    out = [{"id": "mock", "name": "Mississippi Delta (mock)",
            "time_iso": "2023-06-20T00:02:34Z",
            "thumb": "/static/mock/sar_sea.png",
            "has_result": (ROOT / "mock" / "data.json").exists()}]
    for d in sorted(SCENES.iterdir()) if SCENES.exists() else []:
        if d.is_dir():
            out.append({"id": d.name, "name": d.name,
                        "time_iso": None,
                        "thumb": f"/static/{d.name}/sar_sea.png",
                        "has_result": (d / "data.json").exists()})
    return out


class AnalyzeReq(BaseModel):
    scene_id: str
    window_h: float = 3.0


@app.post("/api/analyze")
def analyze(req: AnalyzeReq):
    """Synchronous — takes ~40 s on the real AIS file. The UI shows a spinner.
    Do not build a job queue; there is no time and no need."""
    if req.scene_id == "mock":
        return load("mock")

    d = SCENES / req.scene_id
    cfg = d / "scene.json"
    if not cfg.exists():
        raise HTTPException(404, f"no scenes/{req.scene_id}/scene.json")
    c = json.load(open(cfg))

    t = time.time()
    cmd = [sys.executable, str(ROOT / "oceanfir.py"),
           "--sar", str(d / c["image"]), "--ais", str(ROOT / c["ais"]),
           "--bbox", *[str(x) for x in c["bbox"]],
           "--time", c["time"], "--window", str(req.window_h),
           "--out", str(d / "data.json")]
    # Extra pipeline flags from scene.json. Without these a live /api/analyze
    # runs the CLASSICAL detector with no drift and overwrites a U-Net result
    # that took real work to produce -- i.e. clicking "analyse" on stage would
    # silently downgrade the scene. Absent key = old behaviour.
    cmd += [str(x) for x in c.get("args", [])]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(d))
    if r.returncode != 0:
        raise HTTPException(500, f"pipeline failed: {r.stderr[-600:]}")

    doc = load(req.scene_id)
    doc["meta"]["runtime_s"] = round(time.time() - t, 1)
    return doc


@app.get("/api/result/{scene_id}")
def result(scene_id: str):
    return load(scene_id)


@app.get("/api/vessels/{scene_id}")
def vessels(scene_id: str, verdict: str | None = None):
    v = load(scene_id)["vessels"]
    return [x for x in v if x.get("verdict") == verdict] if verdict else v


@app.get("/api/evidence/{scene_id}")
def evidence(scene_id: str):
    """Lane D: implement build_pdf(doc, out_path) in evidence_pdf.py."""
    try:
        from evidence_pdf import build_pdf
    except ImportError:
        raise HTTPException(501, "evidence_pdf.py not implemented yet")
    out = ROOT / "out" / f"OceanFIR_{scene_id}.pdf"
    out.parent.mkdir(exist_ok=True)
    build_pdf(load(scene_id), str(out))
    return FileResponse(str(out), media_type="application/pdf",
                        filename=out.name)


@app.exception_handler(HTTPException)
def err(request, exc):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


# Mock assets live in ./mock; real scene assets live under ./scenes.
(ROOT / "mock").mkdir(exist_ok=True)
app.mount("/static/mock", StaticFiles(directory=str(ROOT / "mock")), name="mockstatic")
app.mount("/static", StaticFiles(directory=str(SCENES)), name="static")
