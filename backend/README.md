# Store Check — Backend

FastAPI service that powers Store Check: shelf-image storage, DINOv2 crop
embeddings, Qdrant vector search, label curation, and YOLO detection
training/inference.

For app-level setup (Qdrant connection, running the stack) see the
[root README](../README.md). This document covers the backend's internals.

---

## Running

From the **project root** (not from `backend/`), so the `backend.*` absolute
imports resolve:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
python3 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Interactive API docs are served at `http://127.0.0.1:8000/docs`.

---

## Layout

```
backend/
  main.py             FastAPI app: router registration, CORS, startup hook
  config.py           Disk paths + first-run Qdrant seed (.env-backed)
  runtime_config.py   Multi-connection config stored in app_config.json
  ml/
    models.py         Model loaders: DINOv2 (timm), FastSAM, YOLO-World,
                      Grounding DINO; crop embedding + segmentation helpers
  services/
    image_store.py    LocalImageStore — content-addressed (SHA-256) shelf images
    yolo_export.py    Build a tiled YOLO dataset from Qdrant annotations
    yolo_inference.py Tiled (SAHI-style) inference with the active trained model
  routers/
    shelves.py        Shelf upload/list, detection, crop→Qdrant matching
    qdrant_ops.py     Add/browse/edit points, label curation, clustering
    search.py         Shared Qdrant client + capped-kNN vote aggregation
    detection.py      Training lifecycle + model archive
    config_router.py  Connection management endpoints
```

---

## Configuration

Two layers, by design:

- **`config.py` (`Settings`)** — `.env`-backed. Holds disk paths
  (`shelf_images_dir`, `yolo_export_dir`, `yolo_archive_dir`, …) and the
  `qdrant_url` / `qdrant_key` used **only to seed the first connection** on a
  fresh install.
- **`runtime_config.py`** — the live source of truth. Reads/writes
  `app_config.json` (gitignored) holding a list of named Qdrant connections and
  the active one. `get_active()` returns the active connection dict
  (`qdrant_url`, `qdrant_key`, `qdrant_collection`, `embed_dim`,
  `dinov2_model`). Every router resolves Qdrant through this, so connections can
  be switched at runtime from the Settings tab without a restart.

`get_qdrant()` (in `search.py`) builds a cached client for the active
connection and **auto-creates the collection** (cosine distance, sized to
`embed_dim`) on first use if it doesn't exist.

---

## Data flow

```
shelf photo ──upload──> LocalImageStore (SHA-256 on disk)
                              │
   annotate box ──crop──> DINOv2 embed ──> Qdrant point
                              │                (vector + product payload + shelf_box)
                              ▼
            ┌─────────────────────────────────┐
            │ Qdrant collection                │
            │  payload: product_name, pack_type,│
            │  product_category, shelf_id,      │
            │  shelf_box, raw_image (b64)       │
            └─────────────────────────────────┘
                   │                       │
        export (tiled) ──> YOLO train ──> model archive ──> tiled inference
                   │
        crop match ──> capped-kNN vote ──> suggested product
```

Annotations live in Qdrant; the shelf JPEGs live on disk keyed by SHA-256
(`shelf_box` ties a Qdrant point back to its region in the original image,
which is what makes YOLO export possible).

---

## API reference

Base URL `/api`. Full schema at `/docs`.

### Shelves & annotation — `shelves.py`
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/shelves/upload` | Upload a shelf image (deduped by SHA-256) |
| GET  | `/shelves` | List stored shelves with annotation counts |
| GET  | `/shelves/{id}/image` | Full shelf JPEG |
| GET  | `/shelves/{id}/thumbnail` | Thumbnail |
| GET  | `/shelves/{id}/annotations` | Boxes for a shelf |
| GET  | `/shelves/models` | Available detection models (+ archived YOLO) |
| POST | `/shelves/{id}/detect` | Run detection → de-duplicated candidates |
| POST | `/shelves/{id}/match-crop` | Embed a crop, return capped-kNN winner + payload |
| GET  | `/shelves/labels/all` | Distinct product names (autocomplete) |

`/detect` accepts `model`, `conf_threshold`, `text_prompts`, and optional
overrides `iou`, `imgsz`, `min_area`, `max_area_ratio`, `min_aspect`,
`dedupe_iou`.

### Qdrant points & label curation — `qdrant_ops.py`
| Method | Path | Purpose |
|--------|------|---------|
| POST   | `/qdrant/add` | Embed a crop + upsert a point |
| GET    | `/qdrant/browse` | Paged/filtered point browser |
| GET    | `/qdrant/collection/info` | Vector count + dimension |
| PATCH  | `/qdrant/points/{id}` | Update one point's payload |
| DELETE | `/qdrant/points/{id}` | Delete one point |
| POST   | `/qdrant/points/batch-update` | Set payload fields on many points |
| POST   | `/qdrant/points/batch-delete` | Delete many points |
| GET    | `/qdrant/labels` | Label counts + duplicate suggestions |
| POST   | `/qdrant/labels/rename` | Merge/rename labels in bulk |
| GET    | `/qdrant/labels/points` | All crops for one label (detail view) |
| GET    | `/qdrant/labels/clusters` | Cluster a label's crops (color/visual/hybrid) |
| POST   | `/qdrant/labels/seeded-split` | Semi-supervised split preview |
| POST   | `/qdrant/labels/assign` | Reassign points to a (new) label |

### Training & model archive — `detection.py`
| Method | Path | Purpose |
|--------|------|---------|
| POST   | `/training/start` | Export dataset + train (background thread) |
| GET    | `/training/status` | Live status: stage, progress, mAP metrics |
| GET    | `/training/models` | Archived models + metadata |
| POST   | `/training/models/{stem}/activate` | Make a model active for inference |
| DELETE | `/training/models/{stem}` | Remove an archived model |
| GET    | `/training/class-coverage` | Per-class tile counts vs threshold |
| GET    | `/training/model-info` | Active model + class map |
| POST   | `/export-dataset` | Export only (preview class distribution) |

### Connections — `config_router.py`
| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/config` | All connections + active + supported models |
| POST   | `/config/active` | Switch active connection |
| PUT    | `/config/connections` | Add/replace a connection |
| DELETE | `/config/connections/{name}` | Remove a connection |

---

## Key modules

**`ml/models.py`** — lazy, cached model loaders keyed by name. `embed_crop()`
returns an L2-normalizable DINOv2 vector for a crop. `segment_image()`,
`detect_yoloworld()`, `detect_groundingdino()` are the assistive detectors.
`SUPPORTED_MODELS` / `DEFAULT_PARAMS` / `GEOMETRY_DEFAULTS` define the catalog
and per-model defaults. Uses MPS/CUDA when available (`get_device()`).

**`services/yolo_export.py`** — slices each shelf image into overlapping
640×640 tiles (`TILE_SIZE`/`TILE_STRIDE`), converting Qdrant `shelf_box`
annotations into YOLO labels. Supports single-class mode and
frequency-based class collapsing (`min_tiles_for_class` → rare classes fold
into a generic `medicine package`). `count_class_tiles()` powers the coverage
report.

**`services/yolo_inference.py`** — mirrors the training tiling for inference:
tiles the shelf, runs the active model per tile, offsets boxes back to full-image
coordinates, and merges across tiles with greedy NMS (`detect_shelf`).

**`services/image_store.py`** — `LocalImageStore` saves bytes under their
SHA-256 hash and reports whether the content already existed, giving free
upload de-duplication. The interface is S3-swappable (see the commented stub).

**`routers/search.py`** — besides `get_qdrant()`, hosts `_aggregate_votes()`:
capped-kNN classification (each class scored by its best `CAP_PER_CLASS` hits,
with margin-based confidence tiers) used by both crop matching and detection
review.

---

## Startup behaviour

`main.py` registers all routers, enables CORS for the dev frontend
(`localhost:5173`), and on startup ensures the `shelf_id` payload index exists
on the active collection (best-effort; logged on failure).

---

## Dependencies

FastAPI · Uvicorn · Pydantic-settings · Qdrant-client · PyTorch · Torchvision ·
Ultralytics · timm · OpenCV · Pillow · NumPy. Full pins in
[`requirements.txt`](requirements.txt).

> Model weights (FastSAM, YOLO-World, base YOLO) download on first use or are
> read from disk; trained models live in `data/model_archive/` (gitignored).
