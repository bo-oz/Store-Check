#!/usr/bin/env python3
"""Standalone script to train the YOLOv8 SKU model from Qdrant data.

Usage:
    python scripts/train_yolov8.py [--epochs 60] [--model yolov8n.pt] [--imgsz 640] [--batch 8]
"""
import argparse
import sys
from pathlib import Path

# Make sure the project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import settings
from backend.runtime_config import get_active
from backend.services.yolo_export import export_yolo_dataset


def main():
    parser = argparse.ArgumentParser(description="Train YOLOv8 SKU detector")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--model", default="yolov8n-cls.pt")
    parser.add_argument("--imgsz", type=int, default=224)
    parser.add_argument("--batch", type=int, default=8)
    args = parser.parse_args()

    conn = get_active()
    print(f"Exporting dataset from {conn['qdrant_url']} / {conn['qdrant_collection']} …")

    result = export_yolo_dataset(
        qdrant_url=conn["qdrant_url"],
        qdrant_api_key=conn["qdrant_key"],
        collection=conn["qdrant_collection"],
        label_field="product_name",
        export_dir=settings.yolo_export_dir,
        min_samples=settings.yolo_min_samples,
        val_split=0.20,
        class_map_path=settings.yolo_class_map_path,
    )

    print(f"Export done: {result['n_train']} train, {result['n_val']} val, {len(result['class_map'])} classes")
    if result["skipped_classes"]:
        print(f"Skipped (< {settings.yolo_min_samples} samples): {result['skipped_classes']}")

    from ultralytics import YOLO
    import shutil

    model = YOLO(args.model)
    data_yaml = str(Path(settings.yolo_export_dir) / "data.yaml")

    print(f"Training {args.model} for {args.epochs} epochs, imgsz={args.imgsz}, batch={args.batch} …")
    model.train(
        data=settings.yolo_export_dir,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=15,
        augment=True,
        degrees=15,
        flipud=0.0,
        fliplr=0.5,
        hsv_h=0.02,
        hsv_s=0.5,
        hsv_v=0.4,
        verbose=True,
    )

    import glob
    candidates = sorted(glob.glob("runs/classify/train*/weights/best.pt"))
    best = Path(candidates[-1]) if candidates else None

    if best and best.exists():
        dest = Path(settings.yolo_weights_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(best, dest)
        print(f"Saved weights → {dest}")
    else:
        print("ERROR: best.pt not found", file=sys.stderr)
        sys.exit(1)

    try:
        metrics = model.metrics.results_dict
        map50 = metrics.get("metrics/mAP50(B)", None)
        if map50 is not None:
            print(f"Best mAP50: {map50:.4f}")
    except Exception:
        pass

    print("Done.")


if __name__ == "__main__":
    main()
