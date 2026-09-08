#!/usr/bin/env python3
"""
unet.py — the learned detector. A drop-in for segment_classical().

The classical detector finds dark patches. It cannot tell oil from a look-alike,
because low wind, biogenic film and rain cells are dark in SAR too — that is the
"Radar Look Alikes" risk on the feasibility slide. This model is trained on
labelled SAR with a separate look-alike class, so it can say which kind of dark
patch it is looking at and report how confident it is.

Three classes, not two, and that is the point:
    0 sea   1 oil   2 look-alike

Geometry, region selection and the output record all still come from
mask_to_slick() in oceanfir.py. This file only supplies pixels. That is what
makes swapping detectors safe — the contract has exactly one implementation.

    from unet import detect_slick_unet
    slick = detect_slick_unet("sar_sea.png", bbox)

Weights come from notebooks/train_unet.ipynb. They are gitignored (~90 MB);
share them in the Drive folder.
"""
import os
import numpy as np

from oceanfir import load_scene, mask_to_slick

WEIGHTS = os.environ.get("OCEANFIR_UNET", "unet_oil.pt")
CLASSES = ["sea", "oil", "lookalike"]
_MODEL = None

_HELP = """
Cannot run the learned detector.

  {why}

Fix, in order of least effort:
  1. pip install torch segmentation-models-pytorch
  2. Train weights with notebooks/train_unet.ipynb on Colab (free T4, ~25 min)
     and put unet_oil.pt in the repo root, or point OCEANFIR_UNET at it.
  3. Until then run the classical detector, which needs neither:
     python oceanfir.py --detector classical ...

The classical path is a legitimate unsupervised baseline. Shipping it and
saying so is much better than shipping a model you cannot account for.
"""


def load_model(weights=None, device=None):
    """Load once, reuse. Raises a readable error rather than a stack trace."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        import torch
        import segmentation_models_pytorch as smp
    except ImportError as e:
        raise SystemExit(_HELP.format(why=f"missing dependency: {e}"))

    path = weights or WEIGHTS
    if not os.path.exists(path):
        raise SystemExit(_HELP.format(why=f"no weights at '{path}'"))

    if device is None:                      # Colab CUDA, Apple MPS, else CPU
        device = ("cuda" if torch.cuda.is_available()
                  else "mps" if torch.backends.mps.is_available() else "cpu")

    model = smp.Unet("resnet34", encoder_weights=None, in_channels=1,
                     classes=len(CLASSES))
    state = torch.load(path, map_location="cpu")
    model.load_state_dict(state.get("model", state))
    model.eval().to(device)
    model._ocf_device = device
    _MODEL = model
    return model


def predict_probs(im, model=None, tile=384, overlap=96, batch=8):
    """Per-pixel class probabilities for a whole scene, H x W x 3.

    The model was trained on 384 px crops, so the scene is tiled rather than
    resized — resizing a 900 px scene down to 384 would destroy exactly the
    thin, elongated structures a slick is made of. Tiles overlap and are summed
    with a weight map so tile seams do not appear as edges in the mask."""
    import torch
    model = model or load_model()
    dev = getattr(model, "_ocf_device", "cpu")
    H, W = im.shape
    step = tile - overlap

    ys = list(range(0, max(H - tile, 0) + 1, step)) or [0]
    xs = list(range(0, max(W - tile, 0) + 1, step)) or [0]
    if ys[-1] + tile < H:
        ys.append(H - tile)
    if xs[-1] + tile < W:
        xs.append(W - tile)

    pad_h, pad_w = max(0, tile - H), max(0, tile - W)
    if pad_h or pad_w:
        im = np.pad(im, ((0, pad_h), (0, pad_w)), mode="reflect")

    acc = np.zeros((len(CLASSES), im.shape[0], im.shape[1]), np.float32)
    wgt = np.zeros(im.shape, np.float32) + 1e-6
    # cosine window: tiles contribute least at their edges, so seams blend out
    w1 = np.hanning(tile)[:, None] * np.hanning(tile)[None, :] + 1e-3

    coords, crops = [], []
    with torch.no_grad():
        for y in ys:
            for x in xs:
                coords.append((y, x))
                crops.append(im[y:y + tile, x:x + tile])
                if len(crops) == batch or (y == ys[-1] and x == xs[-1]):
                    t = torch.from_numpy(np.stack(crops)[:, None].astype(np.float32)).to(dev)
                    p = torch.softmax(model(t), dim=1).cpu().numpy()
                    for (yy, xx), pr in zip(coords, p):
                        acc[:, yy:yy + tile, xx:xx + tile] += pr * w1
                        wgt[yy:yy + tile, xx:xx + tile] += w1
                    coords, crops = [], []

    probs = (acc / wgt)[:, :H, :W]
    return np.transpose(probs, (1, 2, 0))


def segment_unet(im, model=None, min_oil_prob=0.5):
    """Returns (oil mask, oil probability map, look-alike probability map)."""
    p = predict_probs(im, model)
    oil, look = p[..., 1], p[..., 2]
    # oil must both clear the threshold AND beat look-alike at that pixel —
    # a pixel the model thinks is 0.5 oil and 0.5 look-alike is not evidence
    mask = (oil >= min_oil_prob) & (oil > look)
    return mask, oil, look


def detect_slick_unet(sar_path, bbox, min_km2=1.0, weights=None,
                      min_oil_prob=0.5, mask_png="mask.png"):
    """Same signature and same return as detect_slick(), plus the two fields
    only a learned detector can honestly fill: confidence and lookalike_prob."""
    model = load_model(weights)
    im, orig = load_scene(sar_path)
    mask, oil, look = segment_unet(im, model, min_oil_prob)
    if not mask.any():
        raise SystemExit(
            f"U-Net found no oil above p={min_oil_prob}. Max oil probability in "
            f"the scene was {oil.max():.2f}. Lower --min-oil-prob, or accept that "
            f"this scene has no slick — which is a valid answer.")

    rec = mask_to_slick(mask, bbox, orig, min_km2, land=None,
                        mask_png=mask_png, prob=oil)
    sel_look = float(look[mask].mean())
    rec["lookalike_prob"] = round(sel_look, 3)
    rec["method"] = "unet-resnet34"
    return rec


if __name__ == "__main__":
    import argparse, json
    p = argparse.ArgumentParser(description="Run the learned detector on one scene.")
    p.add_argument("--sar", default="sar_sea.png")
    p.add_argument("--bbox", nargs=4, type=float,
                   default=[-90.821, 28.133, -88.555, 29.2])
    p.add_argument("--weights", default=None)
    p.add_argument("--min-oil-prob", type=float, default=0.5)
    a = p.parse_args()
    print(json.dumps(detect_slick_unet(a.sar, a.bbox, weights=a.weights,
                                       min_oil_prob=a.min_oil_prob), indent=1))
