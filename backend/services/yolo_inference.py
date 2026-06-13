"""Singleton loader + tiled inference for the trained YOLO SKU detection model.

Inference uses the same SAHI-style 640×640 tiling that was used during training,
so products appear at the same relative scale the model learned from.  Detections
from overlapping tiles are merged back into full-image coordinates and deduplicated
with greedy IoU-based NMS.
"""
import json
import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("store_check")

_model = None
_class_map: dict[int, str] = {}   # idx → label

# Must match yolo_export.py so inference scale == training scale
TILE_SIZE   = 640
TILE_STRIDE = 512   # 128 px overlap


def model_status() -> dict:
    from backend.config import settings
    weights = Path(settings.yolo_weights_path)
    class_map = Path(settings.yolo_class_map_path)
    return {
        "loaded": _model is not None,
        "weights_exist": weights.exists(),
        "class_map_exists": class_map.exists(),
        "n_classes": len(_class_map) if _model else 0,
    }


def load_model():
    global _model, _class_map
    from backend.config import settings
    from ultralytics import YOLO

    # Prefer the active archived model; fall back to legacy fixed path
    from backend.routers.detection import get_active_weights_path
    weights = get_active_weights_path()
    if weights is None:
        raise FileNotFoundError("No trained weights found. Train a model first.")

    # Use class map from archive folder if available, else fall back to legacy
    archive_cm = weights.parent / "class_map.json"
    class_map_file = archive_cm if archive_cm.exists() else Path(settings.yolo_class_map_path)

    if not class_map_file.exists():
        raise FileNotFoundError(f"Class map not found: {class_map_file}")

    log.info("Loading trained SKU detector from %s", weights)
    _model = YOLO(str(weights))
    raw = json.loads(class_map_file.read_text())
    _class_map = {int(v): k for k, v in raw.items()}
    log.info("SKU detector loaded — %d classes", len(_class_map))


def reload_model():
    """Force reload after retraining."""
    global _model, _class_map
    _model = None
    _class_map = {}
    load_model()


# ── Tiling helpers ────────────────────────────────────────────────────────────

def _make_tiles(img_w: int, img_h: int) -> "list[tuple]":
    """Return list of (x1, y1, x2, y2) tile rects covering the image."""
    tiles = []
    y = 0
    while y < img_h:
        x = 0
        while x < img_w:
            x2 = min(x + TILE_SIZE, img_w)
            y2 = min(y + TILE_SIZE, img_h)
            if x2 - x < TILE_SIZE and x > 0:
                x = max(0, img_w - TILE_SIZE); x2 = img_w
            if y2 - y < TILE_SIZE and y > 0:
                y = max(0, img_h - TILE_SIZE); y2 = img_h
            tiles.append((x, y, x2, y2))
            if x2 == img_w:
                break
            x += TILE_STRIDE
        if y2 == img_h:
            break
        y += TILE_STRIDE
    return tiles


def _nms(dets: "list[dict]", iou_threshold: float = 0.5) -> "list[dict]":
    """Greedy NMS: suppress lower-confidence boxes that overlap a kept box."""
    if not dets:
        return []
    dets = sorted(dets, key=lambda d: d["confidence"], reverse=True)
    kept = []
    suppressed = [False] * len(dets)
    for i, d in enumerate(dets):
        if suppressed[i]:
            continue
        kept.append(d)
        for j in range(i + 1, len(dets)):
            if suppressed[j]:
                continue
            a, b = d, dets[j]
            ix1 = max(a["x1"], b["x1"]); iy1 = max(a["y1"], b["y1"])
            ix2 = min(a["x2"], b["x2"]); iy2 = min(a["y2"], b["y2"])
            if ix2 <= ix1 or iy2 <= iy1:
                continue
            inter = (ix2 - ix1) * (iy2 - iy1)
            area_a = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
            area_b = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
            union = area_a + area_b - inter
            if union > 0 and inter / union >= iou_threshold:
                suppressed[j] = True
    return kept


# ── Public API ────────────────────────────────────────────────────────────────

def detect_shelf(image_path: str, conf_threshold: float = 0.25, iou_threshold: float = 0.5) -> "list[dict]":
    """Run tiled YOLO detection on a full shelf image.

    The image is sliced into overlapping TILE_SIZE×TILE_SIZE patches — the same
    tiling used during training — so products appear at the same scale the model
    learned from.  Results are merged back into full-image coordinates and
    deduplicated with NMS.

    Returns a list of dicts: {x1, y1, x2, y2, label, confidence}.
    Raises FileNotFoundError if weights are missing.
    """
    global _model
    if _model is None:
        load_model()

    from backend.ml.models import get_device

    bgr = cv2.imread(str(image_path))
    if bgr is None:
        raise ValueError(f"Could not read image: {image_path}")
    img_h, img_w = bgr.shape[:2]

    # If the image already fits in a single tile, skip tiling overhead
    if img_w <= TILE_SIZE and img_h <= TILE_SIZE:
        tiles = [(0, 0, img_w, img_h)]
    else:
        tiles = _make_tiles(img_w, img_h)

    log.debug("detect_shelf: %dx%d → %d tiles", img_w, img_h, len(tiles))

    raw: "list[dict]" = []
    device = get_device()

    for (tx1, ty1, tx2, ty2) in tiles:
        tile_bgr = bgr[ty1:ty2, tx1:tx2]
        results = _model.predict(tile_bgr, conf=conf_threshold,
                                 device=device, verbose=False)
        for r in results:
            if r.boxes is None:
                continue
            names = r.names or {}
            for box in r.boxes:
                x1, y1, x2, y2 = [round(float(v)) for v in box.xyxy[0].tolist()]
                cls   = int(box.cls[0])
                conf  = float(box.conf[0])
                label = names.get(cls, f"class_{cls}")
                raw.append({
                    "x1": x1 + tx1, "y1": y1 + ty1,
                    "x2": x2 + tx1, "y2": y2 + ty1,
                    "label": label,
                    "confidence": conf,
                })

    # Merge overlapping detections from adjacent tiles
    detections = _nms(raw, iou_threshold=iou_threshold)
    log.debug("detect_shelf: %d raw → %d after NMS", len(raw), len(detections))
    return detections


def classify_crop(crop_rgb: np.ndarray, top_k: int = 3) -> "list[dict]":
    """Classify a single pre-cropped image (legacy — kept for compatibility).

    Returns up to top_k predictions sorted by confidence descending:
        [{"label": str, "confidence": float}, ...]
    """
    global _model, _class_map
    if _model is None:
        load_model()

    from backend.ml.models import get_device
    results = _model.predict(crop_rgb, device=get_device(), verbose=False)

    preds = []
    if results and results[0].probs is not None:
        probs = results[0].probs
        top_indices = probs.top5
        top_confs   = probs.top5conf.cpu().numpy()
        for idx, conf in zip(top_indices, top_confs):
            label = _class_map.get(int(idx), f"class_{idx}")
            preds.append({"label": label, "confidence": float(conf)})
            if len(preds) >= top_k:
                break

    return preds
