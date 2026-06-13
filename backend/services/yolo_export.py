"""Export a YOLOv8 detection dataset from Qdrant + shelf images.

All annotation ground truth lives in Qdrant (shelf_id + shelf_box fields).
Shelf images are loaded from LocalImageStore (content-addressed by SHA-256).

High-res support — SAHI-style tiling:
  Each shelf image is sliced into overlapping 640×640 tiles.
  Boxes whose centre falls inside a tile are clipped to that tile and written
  as YOLO normalised coords.  This means a 4 K shelf image with 40 products
  produces ~48 tiles and ~120+ training instances.

  ┌──────────┬──────────┬──────────┐
  │  tile 0  │  tile 1  │  tile 2  │  ← row 0
  ├──────────┼──────────┼──────────┤
  │  tile 3  │  tile 4  │  tile 5  │  ← row 1  (overlap with row 0)
  └──────────┴──────────┴──────────┘
"""
import json
import logging
import random
import shutil
from pathlib import Path

import cv2

log = logging.getLogger("store_check")

TILE_SIZE   = 640   # pixels — matches default YOLOv8 imgsz
TILE_STRIDE = 512   # 128 px overlap (20 %)


def _make_tiles(img_w: int, img_h: int) -> list[tuple[int, int, int, int]]:
    """Return list of (x1,y1,x2,y2) tile rects covering the image."""
    tiles = []
    y = 0
    while y < img_h:
        x = 0
        while x < img_w:
            x2 = min(x + TILE_SIZE, img_w)
            y2 = min(y + TILE_SIZE, img_h)
            # Pad: slide tile left/up so it's always TILE_SIZE if possible
            if x2 - x < TILE_SIZE and x > 0:
                x = max(0, img_w - TILE_SIZE)
                x2 = img_w
            if y2 - y < TILE_SIZE and y > 0:
                y = max(0, img_h - TILE_SIZE)
                y2 = img_h
            tiles.append((x, y, x2, y2))
            if x2 == img_w:
                break
            x += TILE_STRIDE
        if y2 == img_h:
            break
        y += TILE_STRIDE
    return tiles


def _box_to_yolo(box: list[int], tile: tuple) -> "tuple | None":
    """Convert image-space box to tile-relative YOLO format.

    Returns (cx, cy, bw, bh) normalised to tile size, or None if centre is
    outside the tile.
    """
    bx1, by1, bx2, by2 = box
    tx1, ty1, tx2, ty2 = tile
    tw = tx2 - tx1
    th = ty2 - ty1

    # Centre must be inside tile
    cx = (bx1 + bx2) / 2
    cy = (by1 + by2) / 2
    if not (tx1 <= cx < tx2 and ty1 <= cy < ty2):
        return None

    # Clip box to tile bounds
    cx1 = max(bx1, tx1) - tx1
    cy1 = max(by1, ty1) - ty1
    cx2 = min(bx2, tx2) - tx1
    cy2 = min(by2, ty2) - ty1

    norm_cx = ((cx1 + cx2) / 2) / tw
    norm_cy = ((cy1 + cy2) / 2) / th
    norm_w  = (cx2 - cx1) / tw
    norm_h  = (cy2 - cy1) / th
    return (norm_cx, norm_cy, norm_w, norm_h)


FALLBACK_CLASS = "medicine package"


def count_class_tiles(
    qdrant_url: str,
    qdrant_api_key: str,
    collection: str,
    shelf_images_dir: str,
    min_tiles_for_class: int = 5,
) -> dict:
    """Count how many tiles each product class appears in (without writing files).

    Returns a dict:
      {
        "coverage": [
          {"name": "Aspirine 500mg", "tile_count": 12, "named": true},
          {"name": "Linitul", "tile_count": 3, "named": false},
          ...
        ],
        "threshold": 5,
        "n_named": 8,
        "n_collapsed": 4,
      }
    """
    from qdrant_client import QdrantClient
    from backend.services.image_store import LocalImageStore

    store = LocalImageStore(shelf_images_dir)
    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key or None, timeout=60)

    all_points = []
    cursor = None
    while True:
        records, cursor = client.scroll(
            collection_name=collection,
            offset=cursor,
            limit=500,
            with_payload=True,
            with_vectors=False,
        )
        all_points.extend(records)
        if cursor is None:
            break

    annotated = [
        pt for pt in all_points
        if (pt.payload or {}).get("shelf_id") and (pt.payload or {}).get("shelf_box")
    ]

    by_shelf: "dict[str, list]" = {}
    for pt in annotated:
        sid = pt.payload["shelf_id"]
        by_shelf.setdefault(sid, []).append(pt)

    # Count tiles per class across all shelves
    class_tiles: "dict[str, set]" = {}  # class_name → set of (shelf_id, tile_index)
    for shelf_id, pts in by_shelf.items():
        if not store.exists(shelf_id):
            continue
        img_path = store.path(shelf_id)
        import cv2 as _cv2
        img = _cv2.imread(str(img_path))
        if img is None:
            continue
        img_h, img_w = img.shape[:2]
        tiles = _make_tiles(img_w, img_h)

        for ti, tile in enumerate(tiles):
            for pt in pts:
                p = pt.payload or {}
                label = str(p.get("product_name", "")).strip()
                box = p.get("shelf_box", [])
                if not label or len(box) != 4:
                    continue
                yolo = _box_to_yolo(box, tile)
                if yolo is None:
                    continue
                cx, cy, bw, bh = yolo
                if bw < 0.01 or bh < 0.01:
                    continue
                class_tiles.setdefault(label, set()).add((shelf_id, ti))

    coverage = []
    for name, tiles_set in sorted(class_tiles.items()):
        count = len(tiles_set)
        coverage.append({
            "name": name,
            "tile_count": count,
            "named": count >= min_tiles_for_class,
        })
    coverage.sort(key=lambda x: -x["tile_count"])

    n_named = sum(1 for c in coverage if c["named"])
    n_collapsed = sum(1 for c in coverage if not c["named"])

    return {
        "coverage": coverage,
        "threshold": min_tiles_for_class,
        "n_named": n_named,
        "n_collapsed": n_collapsed,
    }


def export_yolo_dataset(
    qdrant_url: str,
    qdrant_api_key: str,
    collection: str,
    export_dir: str,
    shelf_images_dir: str,
    val_split: float = 0.20,
    class_map_path=None,
    min_boxes: int = 1,
    single_class: "str | None" = None,
    min_tiles_for_class: int = 0,
) -> dict:
    """Build a YOLO detection dataset from Qdrant annotations + shelf images.

    Only Qdrant points that have shelf_id + shelf_box in their payload are
    included (points from the old crop-only workflow are silently skipped).

    If single_class is set (e.g. "custom medicine package"), all product labels
    are collapsed into that one class — useful for testing whether the model can
    detect boxes at all before worrying about classification accuracy.

    If min_tiles_for_class > 0, classes that appear in fewer than that many tiles
    are collapsed to FALLBACK_CLASS ("medicine package") instead of getting their
    own class ID.
    """
    from qdrant_client import QdrantClient

    export_path = Path(export_dir)
    if export_path.exists():
        shutil.rmtree(export_path)
    for split in ("train", "val"):
        (export_path / "images" / split).mkdir(parents=True, exist_ok=True)
        (export_path / "labels" / split).mkdir(parents=True, exist_ok=True)

    from backend.services.image_store import LocalImageStore
    store = LocalImageStore(shelf_images_dir)

    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key or None, timeout=60)

    # ── Scroll only annotated points (have shelf_id) ─────────────────────────
    log.info("Scrolling Qdrant for shelf-annotated points…")
    all_points = []
    cursor = None
    while True:
        records, cursor = client.scroll(
            collection_name=collection,
            offset=cursor,
            limit=500,
            with_payload=True,
            with_vectors=False,
        )
        all_points.extend(records)
        if cursor is None:
            break

    # Filter to points that actually have shelf_box
    annotated = [
        pt for pt in all_points
        if (pt.payload or {}).get("shelf_id") and (pt.payload or {}).get("shelf_box")
    ]
    log.info("Found %d annotated points (of %d total scrolled)", len(annotated), len(all_points))

    if not annotated:
        raise ValueError(
            "No shelf-annotated points found. Tag shelf images in the Annotation Studio first."
        )

    # ── Group by shelf_id ─────────────────────────────────────────────────────
    by_shelf: dict[str, list] = {}
    for pt in annotated:
        sid = pt.payload["shelf_id"]
        by_shelf.setdefault(sid, []).append(pt)

    # ── Build class map from all labels ──────────────────────────────────────
    if single_class:
        class_map = {single_class: 0}
        collapsed_to_fallback: "set[str]" = set()
        log.info("Single-class mode: all labels → '%s'", single_class)
    else:
        all_labels = sorted({
            str(pt.payload.get("product_name", "")).strip()
            for pts in by_shelf.values() for pt in pts
            if str(pt.payload.get("product_name", "")).strip()
        })

        if min_tiles_for_class > 0:
            # Pre-count tiles per label to decide which classes to name
            label_tile_counts: "dict[str, set]" = {}
            for shelf_id, pts in by_shelf.items():
                if not store.exists(shelf_id):
                    continue
                img = cv2.imread(str(store.path(shelf_id)))
                if img is None:
                    continue
                img_h, img_w = img.shape[:2]
                tiles = _make_tiles(img_w, img_h)
                for ti, tile in enumerate(tiles):
                    for pt in pts:
                        p = pt.payload or {}
                        lbl = str(p.get("product_name", "")).strip()
                        box = p.get("shelf_box", [])
                        if not lbl or len(box) != 4:
                            continue
                        yolo = _box_to_yolo(box, tile)
                        if yolo is None:
                            continue
                        cx, cy, bw, bh = yolo
                        if bw < 0.01 or bh < 0.01:
                            continue
                        label_tile_counts.setdefault(lbl, set()).add((shelf_id, ti))

            named_labels = sorted(
                lbl for lbl in all_labels
                if len(label_tile_counts.get(lbl, set())) >= min_tiles_for_class
            )
            collapsed_to_fallback = {
                lbl for lbl in all_labels
                if len(label_tile_counts.get(lbl, set())) < min_tiles_for_class
            }
            # Build map: named classes first, then fallback if any were collapsed
            class_map = {name: idx for idx, name in enumerate(named_labels)}
            if collapsed_to_fallback:
                class_map[FALLBACK_CLASS] = len(class_map)
            log.info(
                "Class collapsing: %d named, %d collapsed to '%s' (threshold=%d tiles)",
                len(named_labels), len(collapsed_to_fallback), FALLBACK_CLASS, min_tiles_for_class,
            )
        else:
            class_map = {name: idx for idx, name in enumerate(all_labels)}
            collapsed_to_fallback = set()
        log.info("Classes: %d", len(class_map))

    if class_map_path:
        Path(class_map_path).parent.mkdir(parents=True, exist_ok=True)
        Path(class_map_path).write_text(json.dumps(class_map, indent=2, ensure_ascii=False))

    # ── Split shelf images into train / val ───────────────────────────────────
    shelf_ids = list(by_shelf.keys())
    random.shuffle(shelf_ids)
    n_val = max(1, int(len(shelf_ids) * val_split))
    val_ids  = set(shelf_ids[:n_val])
    train_ids = set(shelf_ids[n_val:])

    n_train_tiles = n_val_tiles = 0
    n_total_boxes = 0
    skipped_shelves = []

    # ── Tile each shelf image and write YOLO files ────────────────────────────
    for shelf_id, pts in by_shelf.items():
        if not store.exists(shelf_id):
            log.warning("Shelf image %s… not found, skipping", shelf_id[:12])
            skipped_shelves.append(shelf_id)
            continue

        img = cv2.imread(str(store.path(shelf_id)))
        if img is None:
            skipped_shelves.append(shelf_id)
            continue

        img_h, img_w = img.shape[:2]
        split = "val" if shelf_id in val_ids else "train"
        tiles = _make_tiles(img_w, img_h)

        for ti, tile in enumerate(tiles):
            tx1, ty1, tx2, ty2 = tile
            tile_labels = []

            for pt in pts:
                p = pt.payload or {}
                raw_label = str(p.get("product_name", "")).strip()
                if single_class:
                    label = single_class
                elif collapsed_to_fallback and raw_label in collapsed_to_fallback:
                    label = FALLBACK_CLASS
                else:
                    label = raw_label
                box   = p.get("shelf_box", [])
                cls   = class_map.get(label)
                if cls is None or len(box) != 4:
                    continue
                yolo = _box_to_yolo(box, tile)
                if yolo is None:
                    continue
                cx, cy, bw, bh = yolo
                # Discard degenerate boxes
                if bw < 0.01 or bh < 0.01:
                    continue
                tile_labels.append(f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

            if len(tile_labels) < min_boxes:
                continue   # skip background-only tiles
            n_total_boxes += len(tile_labels)

            stem = f"{shelf_id[:16]}_{ti:04d}"
            tile_img = img[ty1:ty2, tx1:tx2]
            cv2.imwrite(
                str(export_path / "images" / split / f"{stem}.jpg"),
                tile_img,
                [cv2.IMWRITE_JPEG_QUALITY, 92],
            )
            (export_path / "labels" / split / f"{stem}.txt").write_text("\n".join(tile_labels))

            if split == "train":
                n_train_tiles += 1
            else:
                n_val_tiles += 1

    if n_train_tiles == 0:
        raise ValueError("No training tiles generated. Check that shelf images exist on disk.")

    # ── data.yaml ─────────────────────────────────────────────────────────────
    names = [k for k, _ in sorted(class_map.items(), key=lambda x: x[1])]
    yaml_content = (
        f"path: {export_path.resolve()}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: {len(class_map)}\n"
        f"names: {names}\n"
    )
    (export_path / "data.yaml").write_text(yaml_content)

    log.info(
        "Export done: %d train tiles, %d val tiles, %d boxes, %d classes, %d shelves, %d skipped",
        n_train_tiles, n_val_tiles, n_total_boxes, len(class_map), len(by_shelf), len(skipped_shelves),
    )
    return {
        "class_map":           class_map,
        "n_train":             n_train_tiles,
        "n_val":               n_val_tiles,
        "n_boxes":             n_total_boxes,
        "n_shelves":           len(by_shelf) - len(skipped_shelves),
        "skipped_shelves":     skipped_shelves,
        "collapsed_to_fallback": sorted(collapsed_to_fallback),
    }
