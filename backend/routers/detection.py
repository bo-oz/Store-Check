"""Training management, model archive, and SKU detection endpoints."""
import glob
import json
import logging
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import settings
from backend.runtime_config import get_active

log = logging.getLogger("store_check")
router = APIRouter(prefix="/api", tags=["detection"])

# ── Training state ────────────────────────────────────────────────────────────
_status: dict = {
    "status":       "idle",
    "message":      "",
    "progress":     0,
    "last_trained":   None,
    "best_map50":     None,
    "best_map50_95":  None,
    "n_classes":    0,
    "classes":      [],
    "skipped":      [],
    "n_train":      0,
    "n_val":        0,
    "model_stem":   None,   # which base model is currently training
}
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def _set_status(**kwargs):
    with _lock:
        _status.update(kwargs)


# ── Archive helpers ───────────────────────────────────────────────────────────

def _archive_dir() -> Path:
    p = Path(settings.yolo_archive_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _model_dir(stem: str) -> Path:
    return _archive_dir() / stem


def _active_path() -> Path:
    return _archive_dir() / "active.json"


def _read_active() -> "Optional[str]":
    p = _active_path()
    if p.exists():
        try:
            return json.loads(p.read_text()).get("active")
        except Exception:
            pass
    return None


def _write_active(stem: str):
    _active_path().write_text(json.dumps({"active": stem}))


def _read_meta(stem: str) -> dict:
    meta_file = _model_dir(stem) / "meta.json"
    if meta_file.exists():
        try:
            return json.loads(meta_file.read_text())
        except Exception:
            pass
    return {}


def _write_meta(stem: str, meta: dict):
    d = _model_dir(stem)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, indent=2))


def _list_archived() -> "list[dict]":
    active = _read_active()
    models = []
    for d in sorted(_archive_dir().iterdir()):
        if not d.is_dir():
            continue
        stem = d.name
        weights = d / "best.pt"
        if not weights.exists():
            continue
        meta = _read_meta(stem)
        models.append({
            "stem":        stem,
            "active":      stem == active,
            "trained_at":  meta.get("trained_at"),
            "best_map50":  meta.get("best_map50"),
            "best_map50_95": meta.get("best_map50_95"),
            "n_classes":   meta.get("n_classes", 0),
            "n_train":     meta.get("n_train", 0),
            "n_val":       meta.get("n_val", 0),
            "epochs":      meta.get("epochs", 0),
            "base_model":  meta.get("base_model", stem),
            "size_mb":     round(weights.stat().st_size / 1_048_576, 1),
        })
    return models


def get_active_weights_path() -> "Optional[Path]":
    """Return the weights path for the currently active archived model, or None."""
    stem = _read_active()
    if stem:
        p = _model_dir(stem) / "best.pt"
        if p.exists():
            return p
    # Fall back to legacy fixed path
    legacy = Path(settings.yolo_weights_path)
    return legacy if legacy.exists() else None


# ── Training worker ───────────────────────────────────────────────────────────

def _run_training(epochs: int, base_model: str, imgsz: int, batch: int, single_class: "str | None" = None, min_tiles_for_class: int = 0):
    # Derive a clean stem from the base model filename: "yolo11s.pt" → "yolo11s"
    # Append "-single" when in single-class mode so it gets its own archive slot
    stem = Path(base_model).stem + ("-single" if single_class else "")

    try:
        _set_status(status="exporting", message="Exporting dataset from Qdrant…",
                    progress=5, model_stem=stem)

        from backend.services.yolo_export import export_yolo_dataset
        conn = get_active()
        result = export_yolo_dataset(
            qdrant_url=conn["qdrant_url"],
            qdrant_api_key=conn["qdrant_key"],
            collection=conn["qdrant_collection"],
            export_dir=settings.yolo_export_dir,
            shelf_images_dir=settings.shelf_images_dir,
            val_split=0.20,
            class_map_path=settings.yolo_class_map_path,
            single_class=single_class or None,
            min_tiles_for_class=min_tiles_for_class,
        )

        _set_status(
            status="training",
            message=(
                f"Training {stem} on {result['n_train']} tiles, "
                f"{result['n_boxes']} boxes, {result['n_shelves']} shelves, "
                f"{len(result['class_map'])} classes…"
            ),
            progress=10,
            n_classes=len(result["class_map"]),
            classes=sorted(result["class_map"].keys()),
            skipped=result.get("skipped_shelves", []),
            n_train=result["n_train"],
            n_val=result["n_val"],
        )

        from ultralytics import YOLO
        model = YOLO(base_model)
        total_epochs = epochs

        def on_epoch_end(trainer):
            e = trainer.epoch + 1
            pct = 10 + int(85 * e / total_epochs)
            metrics = trainer.metrics or {}
            map50 = metrics.get("metrics/mAP50(B)", None)
            map50_95 = metrics.get("metrics/mAP50-95(B)", None)
            msg = f"[{stem}] Epoch {e}/{total_epochs}"
            if map50 is not None:
                msg += f"  mAP50={map50:.3f}"
            if map50_95 is not None:
                msg += f"  mAP50-95={map50_95:.3f}"
            _set_status(progress=pct, message=msg)

        model.add_callback("on_train_epoch_end", on_epoch_end)

        data_yaml = str(Path(settings.yolo_export_dir) / "data.yaml")
        model.train(
            data=data_yaml,
            epochs=epochs,
            imgsz=imgsz,
            batch=batch,
            patience=15,
            augment=True,
            degrees=10,
            flipud=0.0,
            fliplr=0.5,
            hsv_h=0.02,
            hsv_s=0.5,
            hsv_v=0.4,
            verbose=False,
        )

        candidates = glob.glob("runs/detect/train*/weights/best.pt")
        # Pick most recently modified — sorted() is lexicographic and "train/" > "train-N/"
        best = Path(max(candidates, key=os.path.getmtime)) if candidates else None

        if not (best and best.exists()):
            raise FileNotFoundError("best.pt not found after training")

        # ── Save to archive ────────────────────────────────────────────────────
        dest_dir = _model_dir(stem)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_weights = dest_dir / "best.pt"
        shutil.copy(best, dest_weights)

        best_map = None
        best_map_95 = None
        try:
            metrics = model.metrics.results_dict
            best_map = round(float(metrics.get("metrics/mAP50(B)", 0)), 4)
            best_map_95 = round(float(metrics.get("metrics/mAP50-95(B)", 0)), 4)
        except Exception:
            pass

        _write_meta(stem, {
            "base_model":      base_model,
            "trained_at":      datetime.utcnow().isoformat(),
            "best_map50":      best_map,
            "best_map50_95":   best_map_95,
            "n_classes":    len(result["class_map"]),
            "n_train":      result["n_train"],
            "n_val":        result["n_val"],
            "epochs":       epochs,
            "imgsz":        imgsz,
            "single_class": single_class or None,
        })

        # Also copy class map into the archive folder for portability
        class_map_src = Path(settings.yolo_class_map_path)
        if class_map_src.exists():
            shutil.copy(class_map_src, dest_dir / "class_map.json")

        # Make this the active model and reload inference
        _write_active(stem)

        # Keep legacy fixed-path weights in sync for backwards compat
        legacy_dest = Path(settings.yolo_weights_path)
        legacy_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(dest_weights, legacy_dest)

        from backend.services.yolo_inference import reload_model
        reload_model()

        log.info("Archived trained model as '%s'  mAP50=%s", stem, best_map)

        _set_status(
            status="done",
            message=f"Training complete. Model saved as '{stem}'.",
            progress=100,
            last_trained=datetime.utcnow().isoformat(),
            best_map50=best_map,
            best_map50_95=best_map_95,
        )

    except Exception as e:
        log.exception("Training failed")
        _set_status(status="error", message=str(e), progress=0)


# ── Endpoints ─────────────────────────────────────────────────────────────────

class TrainRequest(BaseModel):
    epochs: int = 60
    base_model: str = "yolo11s.pt"
    imgsz: int = 640
    batch: int = 8
    single_class: str = ""        # if non-empty, collapse all labels into this one class
    min_tiles_for_class: int = 0  # 0 = disabled; >0 = collapse rare classes to fallback


@router.post("/training/start")
def start_training(req: TrainRequest):
    global _thread
    with _lock:
        if _status["status"] in ("exporting", "training"):
            raise HTTPException(400, "Training already in progress")

    _thread = threading.Thread(
        target=_run_training,
        args=(req.epochs, req.base_model, req.imgsz, req.batch, req.single_class, req.min_tiles_for_class),
        daemon=True,
    )
    _set_status(status="exporting", message="Starting…", progress=1,
                best_map50=None, best_map50_95=None, last_trained=None, n_classes=0,
                classes=[], skipped=[], n_train=0, n_val=0,
                model_stem=Path(req.base_model).stem)
    _thread.start()
    return {"ok": True, "message": "Training started"}


@router.get("/training/status")
def get_training_status():
    with _lock:
        s = dict(_status)
    s["weights_exist"] = get_active_weights_path() is not None
    s["active_model"]  = _read_active()
    return s


# ── Model archive endpoints ───────────────────────────────────────────────────

@router.get("/training/models")
def list_models():
    return {"models": _list_archived(), "active": _read_active()}


@router.post("/training/models/{stem}/activate")
def activate_model(stem: str):
    weights = _model_dir(stem) / "best.pt"
    if not weights.exists():
        raise HTTPException(404, f"Model '{stem}' not found in archive")

    _write_active(stem)

    # Sync legacy weights path + reload
    legacy = Path(settings.yolo_weights_path)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(weights, legacy)

    # Sync class map if present in archive
    archive_cm = _model_dir(stem) / "class_map.json"
    if archive_cm.exists():
        shutil.copy(archive_cm, settings.yolo_class_map_path)

    from backend.services.yolo_inference import reload_model
    reload_model()

    log.info("Activated model '%s'", stem)
    return {"ok": True, "active": stem}


@router.delete("/training/models/{stem}")
def delete_model(stem: str):
    active = _read_active()
    if stem == active:
        raise HTTPException(400, "Cannot delete the currently active model — activate another first")

    d = _model_dir(stem)
    if not d.exists():
        raise HTTPException(404, f"Model '{stem}' not found in archive")

    shutil.rmtree(d)
    log.info("Deleted archived model '%s'", stem)
    return {"ok": True}


@router.get("/training/class-coverage")
def class_coverage(min_tiles: int = 5):
    """Return per-class tile counts and named/collapsed status without exporting."""
    try:
        from backend.services.yolo_export import count_class_tiles
        conn = get_active()
        result = count_class_tiles(
            qdrant_url=conn["qdrant_url"],
            qdrant_api_key=conn["qdrant_key"],
            collection=conn["qdrant_collection"],
            shelf_images_dir=settings.shelf_images_dir,
            min_tiles_for_class=min_tiles,
        )
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/export-dataset")
def export_dataset_only():
    """Export only — useful to preview class distribution before training."""
    try:
        from backend.services.yolo_export import export_yolo_dataset
        conn = get_active()
        result = export_yolo_dataset(
            qdrant_url=conn["qdrant_url"],
            qdrant_api_key=conn["qdrant_key"],
            collection=conn["qdrant_collection"],
            export_dir=settings.yolo_export_dir,
            shelf_images_dir=settings.shelf_images_dir,
            val_split=0.20,
            class_map_path=settings.yolo_class_map_path,
        )
        return {
            "n_train":  result["n_train"],
            "n_val":    result["n_val"],
            "n_boxes":  result["n_boxes"],
            "classes":  len(result["class_map"]),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/training/model-info")
def model_info():
    from backend.services.yolo_inference import model_status
    s = model_status()
    class_map_path = Path(settings.yolo_class_map_path)
    if class_map_path.exists():
        raw = json.loads(class_map_path.read_text())
        s["classes"] = sorted(raw.keys())
        s["n_classes"] = len(raw)
    else:
        s["classes"] = []
        s["n_classes"] = 0
    s["active_model"] = _read_active()
    return s
