# 🏪 Store Check

**A self-hosted tool for building product-recognition datasets and training detection models from retail shelf photos.**

Store Check turns photos of pharmacy / retail shelves into a labelled product database and a trained object detector. You annotate shelves once, and the app handles embedding, similarity search, semi-supervised label curation, and YOLO model training — all from a single web interface backed by a [Qdrant](https://qdrant.tech/) vector database.

> Built for pharmacy shelf analytics, but works for any packaged-goods retail category.

---

## What it does

The workflow is a loop: **annotate → curate → train → re-detect → repeat**. Each pass the detector gets better and pre-fills more of your next annotation.

### ✏️ Annotation Studio
- Upload shelf photos; draw or auto-detect product bounding boxes on a zoom/pan canvas.
- One click runs a detection model over the shelf and proposes boxes **with predicted labels and confidence**.
- Each crop is embedded with **DINOv2** and matched against your Qdrant collection, so the label form pre-fills from the most similar products you've already tagged.
- Adjustable model parameters (confidence, NMS IoU, image size, geometry filters) via an inline settings popover.

### 🗂️ Collection & Label Manager
- Browse every stored product crop and its payload.
- **Duplicate detection** — finds near-identical label spellings (`Rino Ebastel` vs `Rino-Ebastel`) via normalized + fuzzy matching, with side-by-side image comparison, and merges them in one click.
- **Cluster analysis** — clusters a label's crops (by colour, visual embedding, or a hybrid) to surface hidden sub-groups, e.g. a `Strepsils` label that's really blue / pink / orange variants.
- **Seeded splitting** — pick a few example crops per group and the rest are assigned automatically. Includes a pack-shape (aspect-ratio) feature for separating look-alikes like square vs portrait packs.
- **Per-entry & batch CRUD** — zoom into any crop to read the packaging, edit its payload, move it to another class, or delete it. Select many and move / edit / delete them in bulk.

### 🎓 Model Training
- Export a YOLO detection dataset straight from your Qdrant annotations (SAHI-style 640×640 tiling for high-res shelves).
- Train **YOLOv8 / YOLO11 / YOLO12** models with live progress, ETA, and mAP50 / mAP50-95 metrics.
- **Frequency-based class collapsing** — rare classes (below a tile threshold) fold into a generic `medicine package` class so the model isn't starved by 1–2-sample products. A coverage report shows which products need more data.
- **Model archive** — every trained model is saved with its metrics; activate any of them for detection without retraining.

---

## Architecture

```
┌─────────────┐      HTTP/JSON      ┌──────────────┐     ┌──────────────┐
│  Vue 3 SPA  │ ◀────────────────▶ │ FastAPI       │ ──▶ │   Qdrant     │
│ (frontend)  │                     │ (backend)     │     │ (vectors +   │
└─────────────┘                     │  DINOv2 +     │     │  payloads)   │
                                    │  Ultralytics  │     └──────────────┘
                                    └──────────────┘
                                           │
                                    local disk: shelf images,
                                    trained models, datasets
```

- **Frontend** — Vue 3 (`<script setup>`), Vite, Axios. No backend secrets ever reach the browser.
- **Backend** — FastAPI. DINOv2 (via `timm`) for crop embeddings, Ultralytics for YOLO training/inference, OpenCV for image ops.
- **Storage** — Qdrant holds vectors + product payloads. Shelf images are content-addressed (SHA-256) on local disk. Trained models live in a local archive.

---

## Prerequisites

- **Python 3.9+**
- **Node.js 18+**
- A **Qdrant** instance — either [Qdrant Cloud](https://cloud.qdrant.io/) (free tier works) or a local Docker container.
- ~3 GB disk for model weights (downloaded automatically on first use).
- A GPU is optional but speeds up training considerably (CPU works for small datasets).

---

## Setup

### 1. Clone and configure

```bash
git clone <your-repo-url> store-check
cd store-check
cp .env.example .env
```

Edit `.env` with your Qdrant connection:

```ini
QDRANT_URL=https://your-cluster-id.region.aws.cloud.qdrant.io
QDRANT_KEY=your-qdrant-api-key
QDRANT_COLLECTION=retail_shelf_analytics_dinov2
DINOV2_MODEL=vit_small_patch14_dinov2.lvd142m
EMBED_DIM=384
UPLOAD_DIR=/tmp/store_check_uploads
```

> **Don't have a Qdrant cluster yet?** Spin one up free at [cloud.qdrant.io](https://cloud.qdrant.io/), or run one locally:
> ```bash
> docker run -p 6333:6333 qdrant/qdrant
> # then set QDRANT_URL=http://localhost:6333 and leave QDRANT_KEY empty
> ```

The collection is created automatically on first write — you don't need to pre-create it. Just make sure `EMBED_DIM` matches your chosen DINOv2 model (see table below).

### 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

### 3. Frontend

```bash
cd frontend
npm install
```

### 4. Run

From the project root:

```bash
./start.sh
```

This launches the FastAPI backend on `:8000` and the Vue dev server on `:5173`. Open **http://localhost:5173**.

(To run them separately: `uvicorn main:app --reload` from `backend/`, and `npm run dev` from `frontend/`.)

---

## Connecting to Qdrant in the app

You can manage connections two ways:

1. **`.env`** — the default connection, loaded on startup.
2. **Settings tab** — add/switch between multiple named connections at runtime (stored in `app_config.json`, which is gitignored). Useful for testing against different collections or embedding dimensions.

### Choosing an embedding model

The DINOv2 model determines your vector dimension. **Pick one before you start tagging** — changing it later means re-embedding everything.

| Model (timm key)                          | Dim  | Notes                          |
|-------------------------------------------|------|--------------------------------|
| `vit_small_patch14_dinov2.lvd142m`        | 384  | Fastest, lowest memory         |
| `vit_base_patch14_dinov2.lvd142m`         | 768  | Balanced                       |
| `vit_large_patch14_dinov2.lvd142m`        | 1024 | Most accurate, slowest         |

---

## Typical first session

1. **Annotate** — open the Annotation Studio, upload a shelf photo, and draw boxes around products (or run a detection model once you've trained one). Tag each box with a product name.
2. Repeat for a dozen or more shelves. The more examples per product, the better.
3. **Curate** — in the Collection → Labels tab, merge duplicate spellings and split any label that's actually several SKUs.
4. **Train** — in the Training tab, check the class-coverage report, then train a YOLO11 model. It saves to the archive and activates automatically.
5. **Re-detect** — back in the Annotation Studio, run your new model on the next shelf. It now proposes labelled boxes, so you just confirm or correct. The loop accelerates.

---

## Project layout

```
backend/
  config.py            # .env-backed settings
  runtime_config.py    # multi-connection config (app_config.json)
  routers/             # FastAPI endpoints (shelves, qdrant_ops, detection, search…)
  services/            # image store, YOLO export & inference
  ml/                  # DINOv2 + detection model loaders
frontend/
  src/components/      # Vue views: AnnotateView, LabelManager, LabelDetail, TrainView…
  src/api.js           # Axios client
scripts/
  train_yolov8.py      # standalone training script
start.sh               # runs backend + frontend together
```

---

## Security & privacy notes

- **Secrets never get committed.** `.env` and `app_config.json` (both contain your Qdrant API key) are gitignored. Use `.env.example` / `app_config.example.json` as templates.
- **Your data stays yours.** Uploaded shelf photos, exported datasets, and trained models live under `data/` and `runs/`, all gitignored. Nothing is sent anywhere except your own Qdrant instance.
- If you ever committed a real key by accident, **rotate it** in the Qdrant dashboard — removing it from a later commit doesn't purge it from git history.

---

## Tech stack

Vue 3 · Vite · FastAPI · Qdrant · DINOv2 (timm) · Ultralytics YOLO · OpenCV · PyTorch

## License

No license is set yet. Add one (e.g. MIT) before publishing if you want others to reuse the code.
