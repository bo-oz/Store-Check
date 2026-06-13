from pathlib import Path
from typing import Optional

import cv2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import settings
from backend.ml.models import (
    GEOMETRY_DEFAULTS, SUPPORTED_MODELS, DEFAULT_PARAMS,
    segment_image, detect_yoloworld, detect_groundingdino,
)

router = APIRouter(prefix="/api", tags=["segment"])


class SegmentRequest(BaseModel):
    session_id: str
    model: str = "fastsam-s"
    conf: float = Field(0.55, ge=0.0, le=1.0)
    iou: float = Field(0.80, ge=0.0, le=1.0)
    imgsz: int = Field(1024, ge=320, le=2048)
    min_area: int = Field(1500, ge=1)
    max_area_ratio: float = Field(0.12, ge=0.01, le=1.0)
    min_aspect: float = Field(0.20, ge=0.01, le=1.0)
    text_prompts: Optional[str] = None  # YOLO-World only


@router.get("/models")
def list_models():
    return {
        "models": [
            {
                "key": k,
                "label": k,
                "type": v["type"],
                "defaults": DEFAULT_PARAMS[k],
            }
            for k, v in SUPPORTED_MODELS.items()
        ],
        "geometry_defaults": GEOMETRY_DEFAULTS,
    }


@router.post("/segment")
def run_segmentation(req: SegmentRequest):
    if req.model not in SUPPORTED_MODELS:
        raise HTTPException(400, f"Unknown model '{req.model}'. Choose from: {list(SUPPORTED_MODELS)}")

    path = Path(settings.upload_dir) / f"{req.session_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "Session not found")

    bgr = cv2.imread(str(path))
    image_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    model_type = SUPPORTED_MODELS[req.model]["type"]
    geo = dict(
        min_area=req.min_area,
        max_area_ratio=req.max_area_ratio,
        min_aspect=req.min_aspect,
    )

    if model_type == "fastsam":
        boxes = segment_image(
            image_rgb,
            model_key=req.model,
            conf=req.conf,
            iou=req.iou,
            imgsz=req.imgsz,
            **geo,
        )
    elif model_type == "yoloworld":
        prompts = req.text_prompts or DEFAULT_PARAMS[req.model]["text_prompts"]
        boxes = detect_yoloworld(
            image_rgb,
            model_key=req.model,
            text_prompts=prompts,
            conf=req.conf,
            iou=req.iou,
            imgsz=req.imgsz,
            **geo,
        )
    elif model_type == "groundingdino":
        prompts = req.text_prompts or DEFAULT_PARAMS[req.model]["text_prompts"]
        boxes = detect_groundingdino(
            image_rgb,
            model_key=req.model,
            text_prompts=prompts,
            conf=req.conf,
            iou=req.iou,
            **geo,
        )
    elif model_type == "yolov8sku":
        # Trained YOLO detection model — returns boxes + class labels in one pass
        from backend.services.yolo_inference import detect_shelf
        try:
            detections = detect_shelf(str(path), conf_threshold=req.conf)
        except FileNotFoundError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(500, f"Detection failed: {exc}")

        boxes       = [[d["x1"], d["y1"], d["x2"], d["y2"]] for d in detections]
        labels      = [d["label"]      for d in detections]
        confidences = [d["confidence"] for d in detections]

        return {"boxes": boxes, "count": len(boxes), "labels": labels, "confidences": confidences}
    else:
        raise HTTPException(400, f"Unknown model type '{model_type}'")

    return {"boxes": boxes, "count": len(boxes)}
