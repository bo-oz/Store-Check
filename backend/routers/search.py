import base64
import io
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from PIL import Image as PILImage
from pydantic import BaseModel
from qdrant_client import QdrantClient

from backend.config import settings
from backend.ml.models import embed_crop
from backend.runtime_config import get_active

router = APIRouter(prefix="/api", tags=["search"])

_qdrant_cache: dict = {}  # keyed by (url, key)


def get_qdrant() -> tuple[QdrantClient, str]:
    """Returns (client, collection_name) for the active connection."""
    conn = get_active()
    url, key = conn["qdrant_url"], conn["qdrant_key"]
    if not url or not key:
        raise HTTPException(503, "Qdrant not configured — check Settings")
    cache_key = (url, key)
    if cache_key not in _qdrant_cache:
        _qdrant_cache[cache_key] = QdrantClient(url=url, api_key=key, timeout=30)
    return _qdrant_cache[cache_key], conn["qdrant_collection"]


def _crop_to_b64(crop_rgb: np.ndarray) -> str:
    pil = PILImage.fromarray(crop_rgb)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def _decode_payload_image(payload: dict) -> Optional[str]:
    raw = payload.get("raw_image")
    if not raw:
        return None
    b64 = raw.split(",", 1)[-1] if "," in raw else raw
    return b64


def _clean_payload(payload: dict) -> dict:
    skip = {"raw_image", "image_b64", "embedding", "image_bytes", "thumbnail_b64"}
    return {k: v for k, v in payload.items() if k not in skip}


VOTE_N = 30          # internal query size — large enough that rare classes
                     # aren't crowded out of the candidate list by frequent ones
CAP_PER_CLASS = 3    # each class is judged by its best N hits, not by how many
                     # entries it has — kills frequency bias
STRONG_SCORE  = 0.60 # min winner score to be "strong"
STRONG_MARGIN = 0.08 # min gap to the runner-up class to be "strong"


def _aggregate_votes(hits, score_threshold: float) -> dict:
    """Capped-kNN classification over Qdrant hits.

    Each class is scored by the mean of its best CAP_PER_CLASS hits, so a class
    with 150 reference crops competes on quality, not quantity. Confidence is
    margin-based: a winner barely ahead of the runner-up is "uncertain" even if
    its absolute score is high.
    """
    groups: "dict[str, list[float]]" = {}
    for h in hits:
        name = (h.payload or {}).get("product_name", "")
        if name:
            groups.setdefault(name, []).append(h.score)

    if not groups:
        return {"winner": None, "vote_count": 0, "vote_score": 0.0,
                "confidence_tier": "unknown", "margin": 0.0,
                "runner_up": None, "runner_up_score": 0.0}

    ranked = sorted(
        [
            (name, len(scores), sum(sorted(scores, reverse=True)[:CAP_PER_CLASS]) / min(len(scores), CAP_PER_CLASS))
            for name, scores in groups.items()
        ],
        key=lambda x: x[2],
        reverse=True,
    )
    winner_name, winner_votes, winner_score = ranked[0]
    runner_up_name, _, runner_up_score = ranked[1] if len(ranked) > 1 else (None, 0, 0.0)
    margin = winner_score - runner_up_score

    if winner_score < score_threshold:
        # Best class isn't similar enough to call at all
        return {"winner": None, "vote_count": 0, "vote_score": round(winner_score, 4),
                "confidence_tier": "unknown", "margin": round(margin, 4),
                "runner_up": None, "runner_up_score": 0.0}

    if winner_score >= STRONG_SCORE and (runner_up_name is None or margin >= STRONG_MARGIN):
        tier = "strong"
    else:
        tier = "uncertain"

    return {
        "winner": winner_name,
        "vote_count": winner_votes,
        "vote_score": round(winner_score, 4),
        "confidence_tier": tier,
        "margin": round(margin, 4),
        "runner_up": runner_up_name,
        "runner_up_score": round(runner_up_score, 4),
    }


class SearchRequest(BaseModel):
    session_id: str
    boxes: list[list[int]]
    top_k: int = 3
    score_threshold: float = 0.60


@router.post("/search")
def run_search(req: SearchRequest):
    path = Path(settings.upload_dir) / f"{req.session_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "Session not found")

    bgr = cv2.imread(str(path))
    image_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    client, collection = get_qdrant()
    conn = get_active()
    results = []

    for box in req.boxes:
        x1, y1, x2, y2 = box
        crop = image_rgb[y1:y2, x1:x2]
        if crop.size == 0:
            results.append({
                "box": box, "crop_b64": None, "top_score": 0.0,
                "matched": False, "hits": [], "confidence_tier": "unknown",
                "winner": None, "vote_count": 0, "vote_score": 0.0,
            })
            continue

        vector = embed_crop(crop, model_name=conn["dinov2_model"])

        # Query extra hits for vote aggregation
        response = client.query_points(
            collection_name=collection,
            query=vector.tolist(),
            limit=max(VOTE_N, req.top_k),
            with_payload=True,
        )
        all_hits = response.points
        vote = _aggregate_votes(all_hits, req.score_threshold)

        # Display hits — top_k, keeping the winner's best image first when available
        display_hits = all_hits[:req.top_k]
        formatted_hits = [
            {
                "id": h.id,
                "score": h.score,
                "payload": _clean_payload(h.payload),
                "image_b64": _decode_payload_image(h.payload),
            }
            for h in display_hits
        ]

        top_score = all_hits[0].score if all_hits else 0.0
        results.append({
            "box": box,
            "crop_b64": _crop_to_b64(crop),
            "top_score": top_score,
            "matched": vote["confidence_tier"] != "unknown",
            "hits": formatted_hits,
            **vote,
        })

    return {"results": results}
