"""Singleton model loader — imports are heavy, load once at startup."""
import logging
from typing import Optional

import numpy as np
from PIL import Image as PILImage

from backend.config import settings

log = logging.getLogger("store_check")

_fastsam_cache: dict = {}
_yoloworld_cache: dict = {}
_gdino_cache: dict = {}  # Grounding DINO, keyed by model id
_dino_cache: dict = {}   # DINOv2 for embeddings, keyed by timm model name
_DINO_TRANSFORM = None


def _get_transform():
    global _DINO_TRANSFORM
    if _DINO_TRANSFORM is None:
        from torchvision import transforms
        _DINO_TRANSFORM = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
    return _DINO_TRANSFORM

_GDINO_PROMPT = "pharmaceutical package . medicine box . drug bottle . blister pack . supplement"

SUPPORTED_MODELS = {
    "fastsam-s":         {"file": "FastSAM-s.pt",                         "type": "fastsam"},
    "fastsam-x":         {"file": "FastSAM-x.pt",                         "type": "fastsam"},
    "yoloworld-s":       {"file": "yolov8s-worldv2.pt",                   "type": "yoloworld"},
    "yoloworld-m":       {"file": "yolov8m-worldv2.pt",                   "type": "yoloworld"},
    "yoloworld-l":       {"file": "yolov8l-worldv2.pt",                   "type": "yoloworld"},
    "grounding-dino-tiny": {"file": "IDEA-Research/grounding-dino-tiny",  "type": "groundingdino"},
    "grounding-dino-base": {"file": "IDEA-Research/grounding-dino-base",  "type": "groundingdino"},
    "yolov8-sku":          {"file": "yolov8_sku.pt",                      "type": "yolov8sku"},
}

DEFAULT_PARAMS = {
    "fastsam-s":   {"conf": 0.55, "iou": 0.80, "imgsz": 1024},
    "fastsam-x":   {"conf": 0.50, "iou": 0.75, "imgsz": 1024},
    "yoloworld-s": {"conf": 0.05, "iou": 0.45, "imgsz": 1024,
                    "text_prompts": "box, package, bottle, container"},
    "yoloworld-m": {"conf": 0.05, "iou": 0.45, "imgsz": 1024,
                    "text_prompts": "box, package, bottle, container"},
    "yoloworld-l": {"conf": 0.04, "iou": 0.45, "imgsz": 1024,
                    "text_prompts": "box, package, bottle, container"},
    "grounding-dino-tiny": {"conf": 0.20, "iou": 0.50, "imgsz": 1024,
                            "text_prompts": _GDINO_PROMPT},
    "grounding-dino-base": {"conf": 0.20, "iou": 0.50, "imgsz": 1024,
                            "text_prompts": _GDINO_PROMPT},
    "yolov8-sku":          {"conf": 0.40, "iou": 0.45, "imgsz": 640},
}

GEOMETRY_DEFAULTS = {
    "min_area": 1500,
    "max_area_ratio": 0.12,
    "min_aspect": 0.20,
}


def get_device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_fastsam(model_key: str):
    if model_key not in _fastsam_cache:
        from ultralytics import FastSAM
        weights = SUPPORTED_MODELS[model_key]["file"]
        log.info("Loading FastSAM: %s", weights)
        _fastsam_cache[model_key] = FastSAM(weights)
    return _fastsam_cache[model_key]


def load_yoloworld(model_key: str):
    if model_key not in _yoloworld_cache:
        from ultralytics import YOLOWorld
        weights = SUPPORTED_MODELS[model_key]["file"]
        log.info("Loading YOLO-World: %s", weights)
        _yoloworld_cache[model_key] = YOLOWorld(weights)
    return _yoloworld_cache[model_key]


def load_groundingdino(model_key: str):
    if model_key not in _gdino_cache:
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
        model_id = SUPPORTED_MODELS[model_key]["file"]
        log.info("Loading Grounding DINO: %s", model_id)
        processor = AutoProcessor.from_pretrained(model_id)
        model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id)
        model.eval()
        model.to(get_device())
        _gdino_cache[model_key] = (processor, model)
        log.info("Grounding DINO ready on %s", get_device())
    return _gdino_cache[model_key]


def detect_groundingdino(
    image_rgb: np.ndarray,
    model_key: str,
    text_prompts: str,
    conf: float,
    iou: float,
    min_area: int,
    max_area_ratio: float,
    min_aspect: float,
    **_,
) -> list:
    import torch
    from torchvision.ops import nms

    processor, model = load_groundingdino(model_key)
    pil = PILImage.fromarray(image_rgb)
    h, w = image_rgb.shape[:2]
    img_area = w * h

    # Grounding DINO expects ". "-separated phrases
    prompt = text_prompts.strip()
    if not prompt.endswith("."):
        prompt = prompt + "."

    inputs = processor(images=pil, text=prompt, return_tensors="pt")
    inputs = {k: v.to(next(model.parameters()).device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)

    results = processor.post_process_grounded_object_detection(
        outputs, inputs["input_ids"],
        threshold=conf,
        target_sizes=[(h, w)],
    )[0]

    raw_boxes = results["boxes"].cpu()
    scores    = results["scores"].cpu()

    if len(raw_boxes) == 0:
        return []

    # Apply NMS
    keep = nms(raw_boxes, scores, iou_threshold=iou)
    raw_boxes = raw_boxes[keep].numpy().astype(int)

    filtered = []
    for box in raw_boxes:
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        if bw <= 0 or bh <= 0:
            continue
        area = bw * bh
        aspect = min(bw / bh, bh / bw)
        if (
            area >= min_area
            and area <= max_area_ratio * img_area
            and aspect >= min_aspect
        ):
            filtered.append([int(x1), int(y1), int(x2), int(y2)])

    log.info("Grounding DINO: %d raw → %d after geometry filter", len(raw_boxes), len(filtered))
    return filtered


def load_dinov2(model_name: str = "vit_large_patch14_dinov2.lvd142m"):
    if model_name not in _dino_cache:
        import timm
        log.info("Loading DINOv2 via timm: %s", model_name)
        m = timm.create_model(model_name, pretrained=True, num_classes=0, dynamic_img_size=True)
        m.eval()
        m.to(get_device())
        _dino_cache[model_name] = m
        log.info("DINOv2 ready on %s", get_device())
    return _dino_cache[model_name]


def segment_image(
    image_rgb: np.ndarray,
    model_key: str,
    conf: float,
    iou: float,
    imgsz: int,
    min_area: int,
    max_area_ratio: float,
    min_aspect: float,
) -> list:
    import torch
    model = load_fastsam(model_key)
    device = get_device()
    results = model(
        image_rgb,
        device=device,
        retina_masks=True,
        imgsz=imgsz,
        conf=conf,
        iou=iou,
        verbose=False,
    )
    if results[0].boxes is None or len(results[0].boxes) == 0:
        return []

    raw_boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
    h, w = image_rgb.shape[:2]
    img_area = w * h

    filtered = []
    for box in raw_boxes:
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        if bw <= 0 or bh <= 0:
            continue
        area = bw * bh
        aspect = min(bw / bh, bh / bw)
        if (
            area >= min_area
            and area <= max_area_ratio * img_area
            and aspect >= min_aspect
        ):
            filtered.append([int(x1), int(y1), int(x2), int(y2)])

    log.info("Segmentation: %d raw → %d after geometry filter", len(raw_boxes), len(filtered))
    return filtered


def detect_yoloworld(
    image_rgb: np.ndarray,
    model_key: str,
    text_prompts: str,
    conf: float,
    iou: float,
    imgsz: int,
    min_area: int,
    max_area_ratio: float,
    min_aspect: float,
) -> list:
    model = load_yoloworld(model_key)
    classes = [p.strip() for p in text_prompts.split(",") if p.strip()]
    if not classes:
        classes = ["product box"]
    model.set_classes(classes)

    device = get_device()
    results = model.predict(
        image_rgb,
        device=device,
        imgsz=imgsz,
        conf=conf,
        iou=iou,
        verbose=False,
    )
    if results[0].boxes is None or len(results[0].boxes) == 0:
        return []

    raw_boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
    h, w = image_rgb.shape[:2]
    img_area = w * h

    filtered = []
    for box in raw_boxes:
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        if bw <= 0 or bh <= 0:
            continue
        area = bw * bh
        aspect = min(bw / bh, bh / bw)
        if (
            area >= min_area
            and area <= max_area_ratio * img_area
            and aspect >= min_aspect
        ):
            filtered.append([int(x1), int(y1), int(x2), int(y2)])

    log.info("YOLO-World: %d raw → %d after geometry filter", len(raw_boxes), len(filtered))
    return filtered


def embed_crop(crop_rgb: np.ndarray, model_name: str = "vit_large_patch14_dinov2.lvd142m") -> np.ndarray:
    import torch
    import torch.nn.functional as F
    model = load_dinov2(model_name)
    device = next(model.parameters()).device
    pil = PILImage.fromarray(crop_rgb)
    tensor = _get_transform()(pil).unsqueeze(0).to(device)
    with torch.no_grad():
        vec = model(tensor)
    vec = F.normalize(vec, p=2, dim=1)
    return vec.squeeze(0).cpu().numpy()
