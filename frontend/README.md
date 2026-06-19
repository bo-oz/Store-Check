# Store Check — Frontend

Vue 3 single-page app (Vite) for the Store Check workflow: annotate shelf
photos, curate the product collection, and train detection models. Talks to the
FastAPI backend over a small Axios client.

For app-level setup see the [root README](../README.md). This document covers
the frontend's structure.

---

## Running

```bash
npm install
npm run dev          # dev server on http://localhost:5173
npm run build        # production build to dist/
npm run preview      # preview the production build
```

The dev server proxies `/api/*` to the backend at `http://127.0.0.1:8000`
(see `vite.config.js`). `127.0.0.1` is used deliberately rather than
`localhost` so Node doesn't resolve to IPv6 and miss the IPv4-bound backend.

---

## Layout

```
frontend/
  index.html
  vite.config.js          Vite config + /api dev proxy
  src/
    main.js               App bootstrap (createApp)
    App.vue               Shell: top-nav tabs, view switching
    api.js                Axios client — every backend call lives here
    components/
      AnnotateView.vue    Annotation Studio (main tab)
      QdrantBrowser.vue   Collection browser + Labels sub-tab host
      LabelManager.vue    Label curation: dedup, merge, cluster analysis
      LabelDetail.vue     Per-label detail: crop grid, seeded split, batch CRUD
      TrainView.vue       Model training + archive
      SettingsView.vue    Qdrant connection management
```

There is no router library — `App.vue` holds a `view` ref and swaps the active
component. Default tab is **Annotate**.

---

## Views

### `AnnotateView.vue` — Annotation Studio
The core workspace. A zoom/pan canvas with an SVG box overlay over the shelf
image, a left rail of shelves, and a right panel that switches between:
- **detection review** (assistive model proposals),
- **new/edit annotation** form, and
- the **grouped annotation list** (folder view by product, with hover-to-
  highlight on the canvas and an inline edit block).

Key behaviours: model-assisted detection (trained YOLO / FastSAM / YOLO-World /
Grounding DINO) with an adjustable-parameters popover; **auto-approve** of
high-confidence labelled detections; background DINOv2 crop matching that
pre-fills the form; generic fallback-class boxes routed to manual review.

### `QdrantBrowser.vue` — Collection
Paged, searchable grid of stored product crops with inline payload edit/delete.
Hosts the **Labels** sub-tab (`LabelManager`).

### `LabelManager.vue` — Label curation
Aggregated label table with counts; surfaces duplicate-spelling suggestions
(normalized + fuzzy) with image comparison and one-click merge; per-label
cluster analysis (color / visual / hybrid) to spot sub-groups. Opening a label
drills into `LabelDetail`.

### `LabelDetail.vue` — Label detail
Crop grid for one label with: an inspector modal (zoom, edit payload, move,
delete), **seeded splitting** (pick example crops per group → preview → apply),
and **batch operations** (select many → move / edit / delete).

### `TrainView.vue` — Training
Train YOLOv8/11/12 with live progress, ETA and mAP50 / mAP50-95; class-coverage
report; model archive with activate/delete.

### `SettingsView.vue` — Settings
Add/switch/delete Qdrant connections (URL, key, collection, embedding model)
and view collection info.

---

## `api.js`

All HTTP lives here — a single Axios instance with `baseURL: '/api'`. Functions
are grouped by area:

- **Shelves / annotation:** `uploadShelf`, `listShelves`, `getShelfAnnotations`,
  `shelfImageUrl`, `shelfThumbnailUrl`, `listDetectionModels`, `detectShelf`,
  `matchCrop`, `addCrop`, `getAllLabels`
- **Qdrant points:** `browseQdrant`, `collectionInfo`, `updateQdrantPoint`,
  `deleteQdrantPoint`, `batchUpdatePoints`, `batchDeletePoints`
- **Labels:** `getLabels`, `renameLabels`, `getLabelPoints`, `clusterLabel`,
  `seededSplit`, `assignPoints`
- **Training:** `startTraining`, `getTrainingStatus`, `getModelInfo`,
  `getClassCoverage`, `listArchivedModels`, `activateModel`,
  `deleteArchivedModel`
- **Config:** `fetchConfig`, `setActiveConnection`, `saveConnection`,
  `deleteConnection`

To add a backend call, add a function here rather than calling Axios from a
component — keeps every endpoint in one place.

---

## Conventions

- Vue 3 `<script setup>` with the Composition API; refs/computed, no Vuex/Pinia
  store (Pinia is a dependency but state is local to views).
- Component-scoped CSS (`<style scoped>`); the dark theme uses inline hex values
  consistent across components.
- The annotation canvas renders boxes as SVG with zoom-invariant stroke widths
  (scaled by `1/zoom`).

---

## Dependencies

Vue 3 · Vite · Axios · Pinia. Build tooling: `@vitejs/plugin-vue`. See
[`package.json`](package.json).
