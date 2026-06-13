import base64
import datetime
import io
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from PIL import Image as PILImage
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from backend.config import settings
from backend.ml.models import embed_crop
from backend.routers.search import get_qdrant
from backend.runtime_config import get_active

router = APIRouter(prefix="/api/qdrant", tags=["qdrant"])


class AddCropRequest(BaseModel):
    session_id: str
    box: list[int]
    product_name: str
    pack_type: str = ""
    product_category: str = ""
    company_product: bool = True
    # Shelf reference — populated by Annotation Studio and newImage review mode.
    # shelf_id  = SHA-256 of the full shelf image (enables YOLO training export).
    # shelf_box = [x1,y1,x2,y2] of this crop in the original shelf image.
    # shelf_w/h = dimensions of the original shelf image (for YOLO normalisation).
    shelf_id: Optional[str] = None
    shelf_box: Optional[list[int]] = None
    shelf_w: Optional[int] = None
    shelf_h: Optional[int] = None


def _resolve_image_path(session_id: str, shelf_id: Optional[str]) -> Path:
    """Find the source image for a crop.

    Priority:
    1. /tmp upload session (current workflow review)
    2. Permanent shelf image store (annotation studio)
    """
    tmp_path = Path(settings.upload_dir) / f"{session_id}.jpg"
    if tmp_path.exists():
        return tmp_path
    if shelf_id:
        from backend.services.image_store import LocalImageStore
        store = LocalImageStore(settings.shelf_images_dir)
        shelf_path = store.path(shelf_id)
        if shelf_path.exists():
            return shelf_path
    raise FileNotFoundError("Image not found in session or shelf store")


@router.post("/add")
def add_crop(req: AddCropRequest):
    if not req.product_name.strip():
        raise HTTPException(400, "product_name is required")

    try:
        path = _resolve_image_path(req.session_id, req.shelf_id)
    except FileNotFoundError:
        raise HTTPException(404, "Image not found")

    bgr = cv2.imread(str(path))
    image_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    x1, y1, x2, y2 = req.box
    crop = image_rgb[y1:y2, x1:x2]
    if crop.shape[0] < 2 or crop.shape[1] < 2:
        raise HTTPException(400, "Selected region is too small")

    conn = get_active()
    vector = embed_crop(crop, model_name=conn["dinov2_model"])

    pil = PILImage.fromarray(crop)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()

    h_img, w_img = image_rgb.shape[:2]
    point_id = int(datetime.datetime.utcnow().timestamp() * 1000)
    client, collection = get_qdrant()

    payload = {
        "product_name":     req.product_name.strip(),
        "pack_type":        req.pack_type.strip(),
        "product_category": req.product_category.strip(),
        "company_product":  req.company_product,
        "raw_image":        f"data:image/jpeg;base64,{b64}",
        "source":           "annotation_studio" if req.shelf_id else "shelf_review",
    }
    # Attach shelf reference when available — enables YOLO detection training
    if req.shelf_id:
        payload["shelf_id"]  = req.shelf_id
        payload["shelf_box"] = req.shelf_box or [x1, y1, x2, y2]
        payload["shelf_w"]   = req.shelf_w or w_img
        payload["shelf_h"]   = req.shelf_h or h_img

    client.upsert(
        collection_name=collection,
        points=[PointStruct(id=point_id, vector=vector.tolist(), payload=payload)],
    )

    # Ensure shelf_id payload index exists so filtering by it works
    if req.shelf_id:
        try:
            from qdrant_client.models import PayloadSchemaType
            client.create_payload_index(
                collection_name=collection,
                field_name="shelf_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass  # Index may already exist — that's fine

    return {"point_id": point_id, "product_name": req.product_name.strip()}


@router.get("/collection/info")
def collection_info():
    client, collection = get_qdrant()
    info = client.get_collection(collection)
    count = client.count(collection).count
    return {
        "collection": collection,
        "vector_count": count,
        "vector_dim": info.config.params.vectors.size,
    }


@router.get("/browse")
def browse(
    offset: Optional[str] = None,
    limit: int = 20,
    search: str = "",
    company_product: Optional[str] = None,  # "true" | "false" | None
):
    client, collection = get_qdrant()
    term = search.strip().lower()
    company_filter = None if company_product is None else (company_product.lower() == "true")

    if term or company_filter is not None:
        # No text index available — scroll all records and filter in Python
        all_items = []
        cursor = None
        while True:
            records, cursor = client.scroll(
                collection_name=collection,
                offset=cursor,
                limit=500,
                with_payload=True,
                with_vectors=False,
            )
            for r in records:
                p = r.payload or {}
                name = str(p.get("product_name", "")).lower()
                cp = p.get("company_product")
                if term and term not in name:
                    continue
                if company_filter is not None and bool(cp) != company_filter:
                    continue
                raw = p.get("raw_image", "")
                image_b64 = raw.split(",", 1)[-1] if "," in raw else raw
                all_items.append({"id": r.id, "image_b64": image_b64, "payload": {k: v for k, v in p.items() if k != "raw_image"}})
            if cursor is None:
                break

        total = len(all_items)
        # Manual pagination on filtered results using numeric offset
        page_offset = int(offset) if offset and offset.isdigit() else 0
        page = all_items[page_offset: page_offset + limit]
        next_cur = str(page_offset + limit) if page_offset + limit < total else None
        return {"items": page, "total": total, "next_cursor": next_cur}

    # No filters — use Qdrant cursor-based scroll for efficiency
    cursor = int(offset) if offset and offset.isdigit() else (offset or None)
    records, next_cursor = client.scroll(
        collection_name=collection,
        offset=cursor,
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    items = []
    for r in records:
        p = r.payload or {}
        raw = p.get("raw_image", "")
        image_b64 = raw.split(",", 1)[-1] if "," in raw else raw
        items.append({"id": r.id, "image_b64": image_b64, "payload": {k: v for k, v in p.items() if k != "raw_image"}})

    total = client.count(collection).count
    return {"items": items, "total": total, "next_cursor": str(next_cursor) if next_cursor is not None else None}


# ── Label management ──────────────────────────────────────────────────────────

def _normalize_label(s: str) -> str:
    """Aggressive normalisation for duplicate detection: lowercase, strip
    accents, drop punctuation, collapse whitespace."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _scroll_all_payloads(client, collection):
    """Scroll the full collection, payloads only."""
    points = []
    cursor = None
    while True:
        records, cursor = client.scroll(
            collection_name=collection,
            offset=cursor,
            limit=500,
            with_payload=True,
            with_vectors=False,
        )
        points.extend(records)
        if cursor is None:
            break
    return points


@router.get("/labels")
def list_labels(fuzzy_threshold: float = 0.85):
    """Aggregate product_name labels with counts + duplicate suggestions.

    Suggestions come in two flavours:
      - "normalized": labels that collide after lowercasing/accent-stripping/
        punctuation removal — near-certain duplicates
      - "fuzzy": normalized labels whose SequenceMatcher ratio exceeds the
        threshold — likely typos
    """
    from difflib import SequenceMatcher

    client, collection = get_qdrant()
    points = _scroll_all_payloads(client, collection)

    counts: dict = {}
    for r in points:
        name = str((r.payload or {}).get("product_name", "")).strip()
        if name:
            counts[name] = counts.get(name, 0) + 1

    labels = [{"name": n, "count": c} for n, c in counts.items()]
    labels.sort(key=lambda x: (-x["count"], x["name"].lower()))

    # ── Group labels by normalized form ──────────────────────────────────────
    by_norm: dict = {}
    for name in counts:
        by_norm.setdefault(_normalize_label(name), []).append(name)

    suggestions = []
    seen_in_suggestion = set()

    # Normalized collisions — near-certain duplicates
    for norm, names in by_norm.items():
        if len(names) > 1:
            group = sorted(names, key=lambda n: -counts[n])
            suggestions.append({"labels": group, "reason": "normalized", "similarity": 1.0})
            seen_in_suggestion.update(group)

    # Fuzzy pairs between distinct normalized forms
    norms = sorted(by_norm.keys())
    for i in range(len(norms)):
        for j in range(i + 1, len(norms)):
            a, b = norms[i], norms[j]
            # Quick length pre-filter to keep this O(n²) loop cheap
            if abs(len(a) - len(b)) > max(len(a), len(b)) * (1 - fuzzy_threshold):
                continue
            ratio = SequenceMatcher(None, a, b).ratio()
            if ratio >= fuzzy_threshold:
                names = by_norm[a] + by_norm[b]
                if all(n in seen_in_suggestion for n in names):
                    continue
                group = sorted(names, key=lambda n: -counts[n])
                suggestions.append({"labels": group, "reason": "fuzzy", "similarity": round(ratio, 3)})
                seen_in_suggestion.update(group)

    suggestions.sort(key=lambda s: (-{"normalized": 1, "fuzzy": 0}[s["reason"]], -s["similarity"]))

    # One sample crop image per label that appears in a suggestion, so the UI
    # can show what each spelling actually refers to
    needed = {n for s in suggestions for n in s["labels"]}
    thumbs: dict = {}
    for r in points:
        if len(thumbs) == len(needed):
            break
        name = str((r.payload or {}).get("product_name", "")).strip()
        if name in needed and name not in thumbs:
            raw = (r.payload or {}).get("raw_image", "")
            if raw:
                thumbs[name] = raw

    return {
        "labels": labels,
        "n_labels": len(labels),
        "n_points": sum(counts.values()),
        "suggestions": suggestions,
        "thumbs": thumbs,
    }


def _color_descriptor(raw_image_b64: str):
    """Lighting-robust color signature of a crop: hue histogram weighted by
    saturation. Brightness (V) is ignored entirely and low-saturation pixels
    (white box areas, glare) contribute little — so blue vs pink vs orange
    variants separate even under different shelf lighting."""
    import numpy as np
    try:
        raw = raw_image_b64.split(",", 1)[-1]
        img_bytes = np.frombuffer(base64.b64decode(raw), dtype=np.uint8)
        bgr = cv2.imdecode(img_bytes, cv2.IMREAD_COLOR)
        if bgr is None:
            return None
        # Centre crop (middle 80%) to reduce bleed from neighbouring packs
        h, w = bgr.shape[:2]
        bgr = bgr[int(h * 0.1):int(h * 0.9), int(w * 0.1):int(w * 0.9)]
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0].ravel().astype(np.float32)         # 0..179
        sat = hsv[:, :, 1].ravel().astype(np.float32) / 255.0  # weight
        hist, _ = np.histogram(hue, bins=24, range=(0, 180), weights=sat)
        norm = np.linalg.norm(hist)
        if norm < 1e-6:
            return np.zeros(24, dtype=np.float32)
        return (hist / norm).astype(np.float32)
    except Exception:
        return None


def _scroll_label_points(client, collection, label: str, with_vectors: bool = True):
    """All points whose product_name equals `label`."""
    pts = []
    cursor = None
    while True:
        records, cursor = client.scroll(
            collection_name=collection,
            offset=cursor,
            limit=200,
            with_payload=True,
            with_vectors=with_vectors,
        )
        for r in records:
            if str((r.payload or {}).get("product_name", "")).strip() == label:
                pts.append(r)
        if cursor is None:
            break
    return pts


def _build_features(pts, mode: str, color_weight: float, use_shape: bool = False):
    """Feature matrix for clustering/splitting a label's crops.

    Blocks (concatenated, scaled so squared euclidean = weighted blend):
      - DINOv2 embedding (overall appearance)
      - hue-histogram colour signature (variant colour)
      - optional: box aspect ratio (square vs portrait packs)
    """
    import numpy as np

    dino = np.array([r.vector for r in pts], dtype=np.float32)
    dino /= (np.linalg.norm(dino, axis=1, keepdims=True) + 1e-9)

    color = None
    if mode in ("color", "hybrid"):
        feats = []
        for r in pts:
            d = _color_descriptor((r.payload or {}).get("raw_image", ""))
            feats.append(d if d is not None else np.zeros(24, dtype=np.float32))
        color = np.array(feats, dtype=np.float32)

    if mode == "color":
        vecs = color
    elif mode == "hybrid":
        w = min(max(color_weight, 0.0), 1.0)
        vecs = np.hstack([np.sqrt(1.0 - w) * dino, np.sqrt(w) * color])
    else:
        vecs = dino

    if use_shape:
        # log aspect ratio of the shelf box — separates square landscape packs
        # from portrait ones even when colours/embeddings are similar
        aspects = []
        for r in pts:
            box = (r.payload or {}).get("shelf_box") or []
            if len(box) == 4 and box[3] > box[1] and box[2] > box[0]:
                aspects.append(np.log((box[2] - box[0]) / (box[3] - box[1])))
            else:
                aspects.append(0.0)
        a = np.array(aspects, dtype=np.float32)
        std = a.std()
        if std > 1e-6:
            a = (a - a.mean()) / std
        SHAPE_WEIGHT = 0.45  # roughly half a unit-norm block's influence
        vecs = np.hstack([vecs, (SHAPE_WEIGHT * a).reshape(-1, 1)])

    return vecs


@router.get("/labels/clusters")
def cluster_label(label: str, max_thumbs: int = 6, mode: str = "hybrid", color_weight: float = 0.6):
    """Cluster a label's crops to surface hidden sub-groups (e.g. different
    SKUs tagged under one brand name).

    mode:
      - "visual":  DINOv2 embeddings only (overall appearance)
      - "color":   hue-histogram colour signature only (pack variant colour)
      - "hybrid":  weighted blend of both (default; color_weight = colour share)

    Hierarchical Ward clustering; k is chosen by silhouette score over
    meaningful clusters. Returns per-cluster sample thumbnails (closest to the
    cluster centroid first) and a split verdict.
    """
    import numpy as np
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist, squareform

    client, collection = get_qdrant()
    pts = _scroll_label_points(client, collection, label)
    n = len(pts)
    if n < 6:
        return {"label": label, "n_points": n, "clusters": [],
                "verdict": "not_enough_data",
                "message": f"Only {n} entries — need at least 6 to cluster."}

    vecs = _build_features(pts, mode, color_weight)

    dist_condensed = pdist(vecs, metric="euclidean")
    dist_sq = squareform(dist_condensed)
    # Ward — produces balanced clusters instead of just peeling off outliers
    Z = linkage(vecs, method="ward")

    def silhouette(assign, members):
        """Mean silhouette over the given points, computed from the distance
        matrix. `members` restricts both the scored points and the candidate
        neighbour clusters — this keeps 1–2-point outlier clusters from
        inflating the score."""
        ks = sorted({assign[i] for i in members})
        if len(ks) < 2:
            return -1.0
        idx_of = {k: [i for i in members if assign[i] == k] for k in ks}
        scores = []
        for i in members:
            same = [j for j in idx_of[assign[i]] if j != i]
            if not same:
                continue
            a = dist_sq[i, same].mean()
            b = min(dist_sq[i, idx_of[k]].mean() for k in ks if k != assign[i])
            scores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
        return float(np.mean(scores)) if scores else -1.0

    # Pick k by silhouette over "meaningful" clusters (≥3 members) only, so a
    # single outlier crop can't dominate the choice. Outlier clusters are still
    # returned — they're often mis-tagged crops worth reviewing.
    # A higher k must beat the current best by a clear margin: splitting one
    # real sub-group into two (angle/shade variations) barely moves silhouette,
    # while a genuine extra variant raises it substantially.
    MIN_CLUSTER = 3
    K_MARGIN = 0.05
    best_k, best_assign, best_sil = 1, np.ones(n, dtype=int), -1.0
    for k in range(2, min(6, n // 3) + 1):
        assign = fcluster(Z, t=k, criterion="maxclust")
        cluster_sizes = {c: int((assign == c).sum()) for c in set(assign)}
        meaningful_ks = [c for c in cluster_sizes if cluster_sizes[c] >= MIN_CLUSTER]
        if len(meaningful_ks) < 2:
            continue
        members = [i for i in range(n) if assign[i] in meaningful_ks]
        sil = silhouette(assign, members)
        if sil > best_sil + (K_MARGIN if best_sil > 0 else 0):
            best_k, best_assign, best_sil = k, assign, sil

    # ── Merge pass: collapse clusters whose centroids sit closer together
    # than the clusters' own internal spread (they're the same sub-group seen
    # under different angles/lighting, not different variants) ──────────────
    def centroid_and_radius(idx):
        c = vecs[idx].mean(axis=0)
        r = float(np.sqrt(np.mean(np.sum((vecs[idx] - c) ** 2, axis=1)))) if len(idx) > 1 else 0.0
        return c, r

    MERGE_RATIO = 1.6
    merged = True
    while merged:
        merged = False
        ids = sorted(set(best_assign))
        big = [c for c in ids if (best_assign == c).sum() >= MIN_CLUSTER]
        best_pair, best_ratio = None, MERGE_RATIO
        for a_i in range(len(big)):
            for b_i in range(a_i + 1, len(big)):
                ia = [i for i in range(n) if best_assign[i] == big[a_i]]
                ib = [i for i in range(n) if best_assign[i] == big[b_i]]
                ca, ra = centroid_and_radius(ia)
                cb, rb = centroid_and_radius(ib)
                spread = (ra + rb) / 2 or 1e-9
                ratio = float(np.linalg.norm(ca - cb)) / spread
                if ratio < best_ratio:
                    best_pair, best_ratio = (big[a_i], big[b_i]), ratio
        if best_pair:
            best_assign[best_assign == best_pair[1]] = best_pair[0]
            merged = True
    best_k = len(set(best_assign))
    members = [i for i in range(n) if (best_assign == best_assign[i]).sum() >= MIN_CLUSTER]
    best_sil = silhouette(best_assign, members) if best_k > 1 else -1.0

    # Verdict: clearly separated sub-groups, each with enough members to matter
    cluster_ids = sorted(set(best_assign))
    sizes = {c: int((best_assign == c).sum()) for c in cluster_ids}
    meaningful = [c for c in cluster_ids if sizes[c] >= 3]
    split_suggested = best_sil >= 0.15 and len(meaningful) >= 2

    clusters = []
    for c in cluster_ids:
        idx = [i for i in range(n) if best_assign[i] == c]
        centroid = vecs[idx].mean(axis=0)
        centroid /= (np.linalg.norm(centroid) + 1e-9)
        # Sort members by closeness to centroid so thumbs show the most typical crops
        order = sorted(idx, key=lambda i: -float(vecs[i] @ centroid))
        # Mean pairwise distance within the cluster — lower = tighter
        intra = float(np.mean([dist_sq[i, j] for i in idx for j in idx if i != j])) if len(idx) > 1 else 0.0
        thumbs = []
        for i in order[:max_thumbs]:
            raw = (pts[i].payload or {}).get("raw_image", "")
            if raw:
                thumbs.append(raw)
        clusters.append({
            "size": len(idx),
            "intra_distance": round(intra, 4),
            "point_ids": [pts[i].id for i in order],
            "thumbs": thumbs,
        })
    clusters.sort(key=lambda c: -c["size"])

    return {
        "label": label,
        "n_points": n,
        "k": best_k,
        "silhouette": round(best_sil, 3),
        "split_suggested": split_suggested,
        "verdict": "split_suggested" if split_suggested else "looks_coherent",
        "clusters": clusters,
    }


@router.get("/labels/points")
def label_points(label: str):
    """All crops of a label, for the detail-view grid. Includes box aspect so
    the UI can hint at shape differences."""
    client, collection = get_qdrant()
    pts = _scroll_label_points(client, collection, label, with_vectors=False)
    items = []
    for r in pts:
        p = r.payload or {}
        raw = p.get("raw_image", "")
        box = p.get("shelf_box") or []
        aspect = None
        if len(box) == 4 and box[3] > box[1]:
            aspect = round((box[2] - box[0]) / (box[3] - box[1]), 3)
        items.append({
            "id": r.id,
            "thumb": raw,
            "aspect": aspect,
            "payload": {k: v for k, v in p.items() if k != "raw_image"},
        })
    return {"label": label, "n_points": len(items), "points": items}


class SeedGroup(BaseModel):
    name: str
    point_ids: "list[int]"


class SeededSplitRequest(BaseModel):
    label: str
    groups: "list[SeedGroup]"      # ≥2 groups, each with ≥1 seed crop
    mode: str = "hybrid"
    color_weight: float = 0.6
    use_shape: bool = True


@router.post("/labels/seeded-split")
def seeded_split(req: SeededSplitRequest):
    """Semi-supervised split: the user picks a few example crops per group;
    every other crop of the label is assigned to the nearest group centroid.

    Nothing is written — this returns a preview. Apply with /labels/assign.
    """
    import numpy as np

    groups = [g for g in req.groups if g.point_ids]
    if len(groups) < 2:
        raise HTTPException(400, "Need at least 2 groups with seed examples")

    client, collection = get_qdrant()
    pts = _scroll_label_points(client, collection, req.label)
    if not pts:
        raise HTTPException(404, f"No points found for label '{req.label}'")

    vecs = _build_features(pts, req.mode, req.color_weight, use_shape=req.use_shape)
    id_to_idx = {r.id: i for i, r in enumerate(pts)}

    seed_idx_per_group = []
    for g in groups:
        idx = [id_to_idx[pid] for pid in g.point_ids if pid in id_to_idx]
        if not idx:
            raise HTTPException(400, f"Group '{g.name}': no seed crops belong to label '{req.label}'")
        seed_idx_per_group.append(idx)

    centroids = np.array([vecs[idx].mean(axis=0) for idx in seed_idx_per_group])

    # Assign every point to the nearest centroid; seeds stay where the user put them
    n = len(pts)
    assign = np.empty(n, dtype=int)
    for i in range(n):
        assign[i] = int(np.argmin(np.linalg.norm(centroids - vecs[i], axis=1)))
    for gi, idx in enumerate(seed_idx_per_group):
        assign[idx] = gi

    result_groups = []
    for gi, g in enumerate(groups):
        idx = [i for i in range(n) if assign[i] == gi]
        centroid = vecs[idx].mean(axis=0) if idx else centroids[gi]
        order = sorted(idx, key=lambda i: float(np.linalg.norm(vecs[i] - centroid)))
        seed_set = set(seed_idx_per_group[gi])
        result_groups.append({
            "name": g.name,
            "size": len(idx),
            "point_ids": [pts[i].id for i in order],
            "seed_ids": [pts[i].id for i in order if i in seed_set],
            "thumbs": [
                (pts[i].payload or {}).get("raw_image", "")
                for i in order[:8]
                if (pts[i].payload or {}).get("raw_image")
            ],
        })

    return {"label": req.label, "n_points": n, "groups": result_groups}


class AssignPointsRequest(BaseModel):
    point_ids: list[int]
    to_label: str


@router.post("/labels/assign")
def assign_points(req: AssignPointsRequest):
    """Reassign specific points to a (new or existing) label — used to split a
    cluster off into its own class."""
    to_label = req.to_label.strip()
    if not to_label:
        raise HTTPException(400, "to_label is required")
    if not req.point_ids:
        raise HTTPException(400, "point_ids is required")

    client, collection = get_qdrant()
    for i in range(0, len(req.point_ids), 200):
        client.set_payload(
            collection_name=collection,
            payload={"product_name": to_label},
            points=req.point_ids[i:i + 200],
        )
    return {"ok": True, "updated": len(req.point_ids), "to_label": to_label}


class RenameLabelsRequest(BaseModel):
    from_labels: list[str]
    to_label: str


@router.post("/labels/rename")
def rename_labels(req: RenameLabelsRequest):
    """Batch-rename: every point whose product_name is in from_labels gets
    product_name = to_label. Vectors are untouched."""
    to_label = req.to_label.strip()
    if not to_label:
        raise HTTPException(400, "to_label is required")
    from_set = {l.strip() for l in req.from_labels if l.strip() and l.strip() != to_label}
    if not from_set:
        raise HTTPException(400, "No labels to rename")

    client, collection = get_qdrant()
    points = _scroll_all_payloads(client, collection)

    ids = [
        r.id for r in points
        if str((r.payload or {}).get("product_name", "")).strip() in from_set
    ]
    if not ids:
        return {"ok": True, "updated": 0}

    # Batch in chunks to stay well under request-size limits
    for i in range(0, len(ids), 200):
        client.set_payload(
            collection_name=collection,
            payload={"product_name": to_label},
            points=ids[i:i + 200],
        )

    return {"ok": True, "updated": len(ids), "to_label": to_label}


class BatchUpdateRequest(BaseModel):
    point_ids: "list[int]"
    payload: dict   # fields to set on every point (e.g. pack_type, company_product)


@router.post("/points/batch-update")
def batch_update_points(req: BatchUpdateRequest):
    if not req.point_ids:
        raise HTTPException(400, "point_ids is required")
    if not req.payload:
        raise HTTPException(400, "payload is required")
    client, collection = get_qdrant()
    for i in range(0, len(req.point_ids), 200):
        client.set_payload(
            collection_name=collection,
            payload=req.payload,
            points=req.point_ids[i:i + 200],
        )
    return {"ok": True, "updated": len(req.point_ids)}


class BatchDeleteRequest(BaseModel):
    point_ids: "list[int]"


@router.post("/points/batch-delete")
def batch_delete_points(req: BatchDeleteRequest):
    if not req.point_ids:
        raise HTTPException(400, "point_ids is required")
    client, collection = get_qdrant()
    client.delete(collection_name=collection, points_selector=req.point_ids)
    return {"ok": True, "deleted": len(req.point_ids)}


class PayloadPatch(BaseModel):
    payload: dict


@router.patch("/points/{point_id}")
def update_point(point_id: int, body: PayloadPatch):
    client, collection = get_qdrant()
    client.set_payload(
        collection_name=collection,
        payload=body.payload,
        points=[point_id],
    )
    return {"ok": True}


@router.delete("/points/{point_id}")
def delete_point(point_id: int):
    client, collection = get_qdrant()
    client.delete(
        collection_name=collection,
        points_selector=[point_id],
    )
    return {"ok": True}
