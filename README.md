# 🏪 Store Check

**A self-hosted tool for building product-recognition datasets and training detection models from retail shelf photos.**

Store Check turns photos of pharmacy / retail shelves into a labelled product database and a trained object detector. You annotate shelves once, and the app handles embedding, similarity search, semi-supervised label curation, and YOLO model training — all from a single web interface backed by a [Qdrant](https://qdrant.tech/) vector database.

> Built for pharmacy shelf analytics, but works for any packaged-goods retail category.

---

## What it does

The workflow is a loop: **annotate → curate → train → re-detect → repeat**. Each pass the detector gets better and pre-fills more of your next annotation.

### ✏️ Annotation Studio
- Upload shelf photos; draw or auto-detect product bounding boxes on a zoom/pan canvas.
- **Multiple detection models** to assist annotation, selectable per shelf:
  - **Trained YOLO** — your own model, returns boxes *with predicted product labels*.
  - **FastSAM** — segments every object on the shelf (no labels); great before you have a trained model.
  - **YOLO-World** — open-vocabulary, text-prompted (e.g. `box, bottle, blister`).
  - **Grounding DINO** — open-vocabulary, text-prompted, tuned for precise boxes.
- One click runs the chosen model over the shelf and proposes boxes **with predicted labels and confidence** (where the model supports labels).
- Each crop is embedded with **DINOv2** and matched against your Qdrant collection, so the label form pre-fills from the most similar products you've already tagged.
- Adjustable model parameters (confidence, NMS IoU, image size, geometry filters) via an inline settings popover.
- **Uploads are de-duplicated automatically.** Every shelf photo is content-addressed by its SHA-256 hash, so re-uploading the same image just reopens the existing one (with its annotations) instead of creating a duplicate.

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
- **Storage** — Qdrant holds vectors + product payloads. Shelf images are saved to local disk under `data/shelf_images/`, **content-addressed by SHA-256** — identical uploads collapse to one file, so the same photo is never stored (or annotated) twice. Trained models live in a local archive.

---

## Prerequisites

- **Python 3.9+**
- **Node.js 18+**
- A **Qdrant** instance — either [Qdrant Cloud](https://cloud.qdrant.io/) (free tier works) or a local Docker container.
- ~3 GB disk for model weights (downloaded automatically on first use).
- A GPU is optional but speeds up training considerably (CPU works for small datasets).

---

## Setup

### 1. Clone

```bash
git clone https://github.com/bo-oz/Store-Check.git
cd Store-Check
```

> **Qdrant config happens in the app, not in a config file** — see [Connecting to Qdrant](#connecting-to-qdrant) below. You can skip straight to installing the backend.
>
> Optionally, `cp .env.example .env` and set `QDRANT_URL` / `QDRANT_KEY` to pre-fill the first connection on first launch. This is just a convenience — everything is editable from the Settings tab afterwards.

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

## Connecting to Qdrant

Qdrant is configured **entirely from the app's Settings (⚙) tab** — there's no config file to hand-edit. On first launch, open Settings and add a connection:

| Field                | What to enter                                                        |
|----------------------|---------------------------------------------------------------------|
| **Name**             | Any label, e.g. `my-cluster`                                         |
| **Qdrant URL**       | Your cluster URL (or `http://localhost:6333` for local Docker)      |
| **API key**          | Your Qdrant API key (leave blank for a keyless local instance)      |
| **Collection**       | Any name — it's created automatically if it doesn't exist yet       |
| **Embedding model**  | DINOv2 size (see below); its vector dimension is set for you        |

Connections are stored in `app_config.json` (gitignored — it holds your API key). You can add several and switch the active one at any time, which is handy for testing against different collections.

> **The collection is created for you.** If the collection name you enter doesn't exist on the cluster yet, Store Check creates it on first use — sized to your chosen embedding model's dimension, with cosine distance. You don't need to pre-create anything in the Qdrant dashboard. (If a collection with that name *already* exists, it's used as-is and left untouched — just make sure its vector size matches your embedding model.)

> **Don't have a Qdrant cluster yet?** Spin one up free at [cloud.qdrant.io](https://cloud.qdrant.io/), or run one locally:
> ```bash
> docker run -p 6333:6333 qdrant/qdrant
> # then use URL http://localhost:6333 with a blank API key
> ```

### Choosing an embedding model

The DINOv2 model determines your vector dimension. **Pick one before you start tagging** — changing it later means re-embedding everything.

| Model                | Dim  | Notes                          |
|----------------------|------|--------------------------------|
| DINOv2 small         | 384  | Fastest, lowest memory         |
| DINOv2 base          | 768  | Balanced                       |
| DINOv2 large         | 1024 | Most accurate, slowest         |

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
  config.py            # disk paths + first-run Qdrant seed
  runtime_config.py    # multi-connection config (app_config.json) — the live source of truth
  routers/             # FastAPI endpoints: shelves, qdrant_ops, detection, config, search (helpers)
  services/            # image store, YOLO export & inference
  ml/                  # DINOv2 + detection model loaders
frontend/
  src/components/      # Vue views: AnnotateView, QdrantBrowser, LabelManager, LabelDetail, TrainView, SettingsView
  src/api.js           # Axios client
start.sh               # runs backend + frontend together
```

For deeper documentation of each half, see the
**[backend README](backend/README.md)** (architecture, module reference, full
API endpoint list) and the **[frontend README](frontend/README.md)** (views,
`api.js`, conventions).

---

## Security & privacy notes

- **Secrets never get committed.** `app_config.json` (holds your Qdrant API key) and `.env` are gitignored. Use `app_config.example.json` / `.env.example` as templates.
- **Your data stays yours.** Uploaded shelf photos, exported datasets, and trained models live under `data/` and `runs/`, all gitignored. Nothing is sent anywhere except your own Qdrant instance.
- If you ever committed a real key by accident, **rotate it** in the Qdrant dashboard — removing it from a later commit doesn't purge it from git history.

---

## Roadmap / To-do

Ideas and directions for improvement — contributions welcome.

**Data model**
- [ ] **Dynamic payload schema.** Right now the product payload is a fixed set of fields (`product_name`, `pack_type`, `product_category`, `company_product`). Let users define their own schema — choose which fields exist and their types (text, number, boolean, enum/select, tags) — so the annotation form, the Collection browser, and batch-edit adapt automatically. This is the single most impactful change for using Store Check outside pharmacy.
- [ ] Per-field validation and required-field rules.
- [ ] Store a stable product ID / EAN alongside the free-text name, so renames don't lose identity.

**Detection & matching**
- [ ] Active-learning queue: surface the lowest-confidence detections first for review.
- [ ] Use the colour/shape descriptors as a tie-breaker at match time, not just in the Label Manager.
- [ ] Export a trained model + class map as a portable bundle for offline inference.

**Storage & scale**
- [ ] S3-backed image store (the `LocalImageStore` interface already anticipates this — see `backend/services/image_store.py`).
- [ ] Background job queue for training/export instead of an in-process thread.
- [ ] Multi-user support with per-user annotation attribution.

**UX**
- [ ] Keyboard shortcuts for the annotation canvas (next box, confirm, reject).
- [ ] Bulk image upload (folder / zip) with a progress view.
- [ ] Higher-resolution crop inspection by re-cutting from the original shelf image on demand (currently limited to the stored crop's resolution).

**Housekeeping**
- [ ] Add automated tests (backend API + a few frontend component tests).
- [ ] Dockerfile / docker-compose for one-command local setup.

---

## Tech stack

Vue 3 · Vite · FastAPI · Qdrant · DINOv2 (timm) · Ultralytics YOLO · OpenCV · PyTorch

## License

Released under the [MIT License](LICENSE).
