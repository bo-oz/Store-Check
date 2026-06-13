"""Shelf image management — upload, list, serve, annotations, and detection."""
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse, Response

from backend.config import settings
from backend.services.image_store import LocalImageStore

log = logging.getLogger("store_check")
router = APIRouter(prefix="/api/shelves", tags=["shelves"])

_store: Optional[LocalImageStore] = None


def get_store() -> LocalImageStore:
    global _store
    if _store is None:
        _store = LocalImageStore(settings.shelf_images_dir)
    return _store


def _count_shelf_boxes(shelf_id: str) -> int:
    """Count Qdrant points that reference this shelf image."""
    from backend.routers.search import get_qdrant
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    try:
        client, collection = get_qdrant()
        # Use scroll instead of count — more compatible across Qdrant versions
        # when the payload index may not yet exist.
        records, _ = client.scroll(
            collection_name=collection,
            scroll_filter=Filter(must=[
                FieldCondition(key="shelf_id", match=MatchValue(value=shelf_id))
            ]),
            limit=2000,
            with_payload=False,
            with_vectors=False,
        )
        return len(records)
    except Exception:
        return 0


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_shelf(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")

    data = await file.read()
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not decode image")

    h, w = img.shape[:2]

    # Re-encode as high-quality JPEG (normalises format, removes EXIF, stabilises hash)
    _, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    jpeg_bytes = jpeg.tobytes()

    store = get_store()
    shelf_id, existed = store.put(
        jpeg_bytes,
        meta={"width": w, "height": h, "original_name": file.filename or ""},
    )

    box_count = _count_shelf_boxes(shelf_id)

    return {
        "shelf_id": shelf_id,
        "width": w,
        "height": h,
        "already_exists": existed,
        "box_count": box_count,
    }


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("")
def list_shelves():
    store = get_store()
    keys = store.list_keys()
    shelves = []
    for key in keys:
        meta = store.meta(key)
        shelves.append({
            "shelf_id": key,
            "width": meta.get("width", 0),
            "height": meta.get("height", 0),
            "original_name": meta.get("original_name", ""),
            "box_count": _count_shelf_boxes(key),
        })
    return {"shelves": shelves}


# ── Serve image / thumbnail ───────────────────────────────────────────────────

@router.get("/{shelf_id}/image")
def get_shelf_image(shelf_id: str):
    store = get_store()
    if not store.exists(shelf_id):
        raise HTTPException(404, "Shelf image not found")
    return FileResponse(str(store.path(shelf_id)), media_type="image/jpeg")


@router.get("/{shelf_id}/thumbnail")
def get_shelf_thumbnail(shelf_id: str, max_w: int = 280):
    store = get_store()
    if not store.exists(shelf_id):
        raise HTTPException(404, "Shelf image not found")
    img = cv2.imread(str(store.path(shelf_id)))
    h, w = img.shape[:2]
    tw = min(max_w, w)
    th = int(h * tw / w)
    thumb = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
    _, jpeg = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return Response(content=jpeg.tobytes(), media_type="image/jpeg")


# ── Annotations (Qdrant-sourced) ──────────────────────────────────────────────

@router.get("/{shelf_id}/annotations")
def get_shelf_annotations(shelf_id: str):
    """All Qdrant points that belong to this shelf, as annotation objects."""
    from backend.routers.search import get_qdrant
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    store = get_store()
    if not store.exists(shelf_id):
        raise HTTPException(404, "Shelf image not found")

    try:
        client, collection = get_qdrant()
        points, _ = client.scroll(
            collection_name=collection,
            scroll_filter=Filter(must=[
                FieldCondition(key="shelf_id", match=MatchValue(value=shelf_id))
            ]),
            limit=1000,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:
        log.warning("Could not fetch annotations for shelf %s: %s", shelf_id[:12], e)
        points = []

    annotations = []
    for pt in points:
        p = pt.payload or {}
        raw = p.get("raw_image", "")
        image_b64 = raw.split(",", 1)[-1] if "," in raw else raw
        annotations.append({
            "id": pt.id,
            "label": p.get("product_name", ""),
            "box": p.get("shelf_box", []),
            "pack_type": p.get("pack_type", ""),
            "product_category": p.get("product_category", ""),
            "company_product": p.get("company_product", True),
            "image_b64": image_b64,
        })

    return {"annotations": annotations}


# ── Detection models ──────────────────────────────────────────────────────────

@router.get("/models")
def list_detection_models():
    """Available detection models for the annotation canvas."""
    from backend.ml.models import SUPPORTED_MODELS, DEFAULT_PARAMS

    LABELS = {
        "fastsam-s":           "FastSAM-S  (fast, boxes only)",
        "fastsam-x":           "FastSAM-X  (accurate, boxes only)",
        "yoloworld-s":         "YOLO-World S  (text prompt)",
        "yoloworld-m":         "YOLO-World M  (text prompt)",
        "yoloworld-l":         "YOLO-World L  (text prompt)",
        "grounding-dino-tiny": "Grounding-DINO tiny  (text prompt)",
        "grounding-dino-base": "Grounding-DINO base  (text prompt)",
    }

    models = [{"id": "manual", "name": "Manual only", "type": "manual",
               "available": True, "defaults": {}}]

    for key, meta in SUPPORTED_MODELS.items():
        if meta["type"] == "yolov8sku":
            continue   # legacy — replaced by trained YOLO below
        models.append({
            "id":       key,
            "name":     LABELS.get(key, key),
            "type":     meta["type"],
            "available": True,        # auto-downloads on first use
            "defaults": DEFAULT_PARAMS.get(key, {}),
        })

    # Archived trained models — one entry per model in the archive
    try:
        from backend.routers.detection import _list_archived, _read_active
        active_stem = _read_active()
        for m in _list_archived():
            stem = m["stem"]
            is_active = m["active"]
            n_cls  = m["n_classes"]
            map50  = m["best_map50"]
            label_parts = [f"Trained YOLO — {stem}"]
            if is_active:
                label_parts.append("★ active")
            if n_cls:
                label_parts.append(f"{n_cls} class{'es' if n_cls != 1 else ''}")
            if map50:
                label_parts.append(f"mAP50 {map50*100:.0f}%")
            models.append({
                "id":        f"yolo:{stem}",
                "name":      "  ·  ".join(label_parts),
                "type":      "yolo_trained",
                "available": True,
                "active":    is_active,
                "defaults":  {"conf": 0.25},
                "stem":      stem,
            })
    except Exception:
        # Fall back to legacy single-entry if archive not available
        if Path(settings.yolo_weights_path).exists():
            models.append({
                "id":       "yolo",
                "name":     "Trained YOLO  (boxes + labels)",
                "type":     "yolo_trained",
                "available": True,
                "defaults": {"conf": 0.25},
            })

    return {"models": models}


def _iou(a: "list[int]", b: "list[int]") -> float:
    """Max of IoU and IoMin — catches containment cases where a small box sits inside a large one."""
    ix1 = max(a[0], b[0]); iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2]); iy2 = min(a[3], b[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    iou = inter / union if union > 0 else 0.0
    iom = inter / min(area_a, area_b) if min(area_a, area_b) > 0 else 0.0
    return max(iou, iom)


@router.post("/{shelf_id}/detect")
def detect_on_shelf(
    shelf_id: str,
    model: str = Query("fastsam-s"),
    conf_threshold: float = Query(0.25),
    text_prompts: Optional[str] = Query(None),
    iou: Optional[float] = Query(None),            # NMS IoU threshold
    imgsz: Optional[int] = Query(None),            # inference image size (segmentation models)
    min_area: Optional[int] = Query(None),         # geometry filter overrides
    max_area_ratio: Optional[float] = Query(None),
    min_aspect: Optional[float] = Query(None),
    dedupe_iou: float = Query(0.4),                # overlap vs existing annotations
):
    """Run detection on a shelf image and return de-duplicated candidates.

    Supports all segmentation models (fastsam, yoloworld, groundingdino) as
    well as the trained YOLO detection model.  Candidates that overlap
    (IoU ≥ 0.4) with an existing Qdrant annotation are silently filtered out.
    """
    store = get_store()
    if not store.exists(shelf_id):
        raise HTTPException(404, "Shelf image not found")

    if model == "manual":
        return {"candidates": [], "skipped": 0, "total_detected": 0}

    from backend.ml.models import (
        SUPPORTED_MODELS, DEFAULT_PARAMS, GEOMETRY_DEFAULTS,
        segment_image, detect_yoloworld, detect_groundingdino,
    )

    raw_boxes:       "list[list[int]]" = []
    raw_labels:      "list[str]"       = []
    raw_confidences: "list[float]"     = []

    geo = dict(GEOMETRY_DEFAULTS)
    if min_area is not None:
        geo["min_area"] = min_area
    if max_area_ratio is not None:
        geo["max_area_ratio"] = max_area_ratio
    if min_aspect is not None:
        geo["min_aspect"] = min_aspect

    if model == "yolo" or model.startswith("yolo:"):
        # Trained YOLO detection model — returns boxes + class labels
        from backend.services.yolo_inference import detect_shelf as _detect
        from backend.routers.detection import _model_dir, _write_active, get_active_weights_path
        from ultralytics import YOLO as _YOLO

        # If a specific stem was requested, load that model directly
        if model.startswith("yolo:"):
            stem = model[5:]
            weights = _model_dir(stem) / "best.pt"
            if not weights.exists():
                raise HTTPException(404, f"Archived model '{stem}' not found")
            # Load ad-hoc without changing global active model
            try:
                import cv2 as _cv2
                from backend.ml.models import get_device
                _m = _YOLO(str(weights))
                bgr_shelf = _cv2.imread(str(store.path(shelf_id)))
                if bgr_shelf is None:
                    raise HTTPException(500, "Could not read shelf image")
                from backend.services.yolo_inference import _make_tiles, _nms, TILE_SIZE
                img_h, img_w = bgr_shelf.shape[:2]
                tiles = _make_tiles(img_w, img_h) if (img_w > TILE_SIZE or img_h > TILE_SIZE) else [(0, 0, img_w, img_h)]
                raw: "list[dict]" = []
                for (tx1, ty1, tx2, ty2) in tiles:
                    tile_bgr = bgr_shelf[ty1:ty2, tx1:tx2]
                    results = _m.predict(tile_bgr, conf=conf_threshold, device=get_device(), verbose=False)
                    for r in results:
                        if r.boxes is None:
                            continue
                        names = r.names or {}
                        for box in r.boxes:
                            x1, y1, x2, y2 = [round(float(v)) for v in box.xyxy[0].tolist()]
                            raw.append({"x1": x1+tx1, "y1": y1+ty1, "x2": x2+tx1, "y2": y2+ty1,
                                        "label": names.get(int(box.cls[0]), ""), "confidence": float(box.conf[0])})
                detections = _nms(raw, iou_threshold=iou if iou is not None else 0.5)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(500, f"Detection failed: {exc}")
        else:
            try:
                detections = _detect(str(store.path(shelf_id)), conf_threshold,
                                     iou_threshold=iou if iou is not None else 0.5)
            except FileNotFoundError as exc:
                raise HTTPException(400, str(exc))
            except Exception as exc:
                raise HTTPException(500, f"Detection failed: {exc}")

        raw_boxes       = [[d["x1"], d["y1"], d["x2"], d["y2"]] for d in detections]
        raw_labels      = [d["label"]      for d in detections]
        raw_confidences = [d["confidence"] for d in detections]

    elif model in SUPPORTED_MODELS:
        model_type = SUPPORTED_MODELS[model]["type"]
        defaults   = DEFAULT_PARAMS.get(model, {})
        iou        = iou if iou is not None else defaults.get("iou", 0.5)
        imgsz      = imgsz if imgsz is not None else defaults.get("imgsz", 1024)

        # Load image as RGB numpy array
        bgr = cv2.imread(str(store.path(shelf_id)))
        if bgr is None:
            raise HTTPException(500, "Could not read shelf image")
        image_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        try:
            if model_type == "fastsam":
                raw_boxes = segment_image(
                    image_rgb, model_key=model,
                    conf=conf_threshold, iou=iou, imgsz=imgsz, **geo,
                )
            elif model_type == "yoloworld":
                prompts = text_prompts or defaults.get("text_prompts", "product")
                raw_boxes = detect_yoloworld(
                    image_rgb, model_key=model, text_prompts=prompts,
                    conf=conf_threshold, iou=iou, imgsz=imgsz, **geo,
                )
            elif model_type == "groundingdino":
                prompts = text_prompts or defaults.get("text_prompts", "product")
                raw_boxes = detect_groundingdino(
                    image_rgb, model_key=model, text_prompts=prompts,
                    conf=conf_threshold, iou=iou, **geo,
                )
            else:
                raise HTTPException(400, f"Model type '{model_type}' not supported for shelf detection")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"Detection failed: {exc}")

        raw_labels      = [""] * len(raw_boxes)   # segmentation models have no class labels
        raw_confidences = [0.0] * len(raw_boxes)

    else:
        raise HTTPException(400, f"Unknown model: {model}")

    # Fetch existing Qdrant boxes for this shelf (for IoU dedup)
    from backend.routers.search import get_qdrant
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    existing_boxes: "list[list[int]]" = []
    try:
        client, collection = get_qdrant()
        records, _ = client.scroll(
            collection_name=collection,
            scroll_filter=Filter(must=[
                FieldCondition(key="shelf_id", match=MatchValue(value=shelf_id))
            ]),
            limit=2000,
            with_payload=True,
            with_vectors=False,
        )
        for r in records:
            sb = (r.payload or {}).get("shelf_box")
            if sb and len(sb) == 4:
                existing_boxes.append(sb)
    except Exception:
        pass

    candidates = []
    skipped = 0
    for box, label, conf in zip(raw_boxes, raw_labels, raw_confidences):
        if any(_iou(box, e) >= dedupe_iou for e in existing_boxes):
            skipped += 1
        else:
            candidates.append({
                "x1": box[0], "y1": box[1], "x2": box[2], "y2": box[3],
                "label":      label,
                "confidence": round(conf, 4),
            })

    return {
        "candidates":     candidates,
        "total_detected": len(raw_boxes),
        "skipped":        skipped,
    }


# ── Crop matching (DINOv2 → Qdrant) ──────────────────────────────────────────

class MatchCropRequest(BaseModel):
    box: "list[int]"   # [x1, y1, x2, y2]
    score_threshold: float = 0.55


@router.post("/{shelf_id}/match-crop")
def match_crop(shelf_id: str, req: MatchCropRequest):
    """Embed a crop from the shelf image and search Qdrant for the closest match.

    Returns the vote-aggregated winner + its full payload so the annotation
    form can be pre-filled without any user typing.
    """
    store = get_store()
    if not store.exists(shelf_id):
        raise HTTPException(404, "Shelf image not found")

    x1, y1, x2, y2 = req.box
    bgr = cv2.imread(str(store.path(shelf_id)))
    if bgr is None:
        raise HTTPException(500, "Could not read shelf image")
    image_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    crop = image_rgb[y1:y2, x1:x2]
    if crop.shape[0] < 2 or crop.shape[1] < 2:
        raise HTTPException(400, "Crop region too small")

    from backend.ml.models import embed_crop
    from backend.runtime_config import get_active
    from backend.routers.search import get_qdrant, _aggregate_votes, VOTE_N

    conn = get_active()
    vector = embed_crop(crop, model_name=conn["dinov2_model"])

    client, collection = get_qdrant()
    try:
        response = client.query_points(
            collection_name=collection,
            query=vector.tolist(),
            limit=VOTE_N,
            with_payload=True,
        )
        hits = response.points
    except Exception as exc:
        raise HTTPException(500, f"Qdrant query failed: {exc}")

    vote = _aggregate_votes(hits, req.score_threshold)

    # Pull full payload from the best-scoring hit for the winner
    winner_payload: "dict" = {}
    winner_image_b64: "Optional[str]" = None
    if vote["winner"]:
        for h in hits:
            if (h.payload or {}).get("product_name") == vote["winner"]:
                p = h.payload or {}
                winner_payload = {
                    "product_name":     p.get("product_name", ""),
                    "pack_type":        p.get("pack_type", ""),
                    "product_category": p.get("product_category", ""),
                    "company_product":  p.get("company_product", True),
                }
                raw = p.get("raw_image", "")
                winner_image_b64 = raw.split(",", 1)[-1] if "," in raw else raw
                break

    return {
        "winner":            vote["winner"],
        "vote_count":        vote["vote_count"],
        "vote_score":        vote["vote_score"],
        "confidence_tier":   vote["confidence_tier"],  # strong | uncertain | unknown
        "margin":            vote["margin"],           # gap to runner-up class
        "runner_up":         vote["runner_up"],
        "runner_up_score":   vote["runner_up_score"],
        "payload":           winner_payload,
        "match_image_b64":   winner_image_b64,
    }


# ── Known labels (for autocomplete) ──────────────────────────────────────────

@router.get("/labels/all")
def all_labels():
    """Distinct product_name values from Qdrant, sorted alphabetically."""
    from backend.routers.search import get_qdrant
    try:
        client, collection = get_qdrant()
        names: set[str] = set()
        cursor = None
        while True:
            records, cursor = client.scroll(
                collection_name=collection,
                offset=cursor,
                limit=500,
                with_payload=["product_name"],
                with_vectors=False,
            )
            for r in records:
                n = (r.payload or {}).get("product_name", "").strip()
                if n:
                    names.add(n)
            if cursor is None:
                break
        return {"labels": sorted(names)}
    except Exception as e:
        raise HTTPException(500, str(e))
