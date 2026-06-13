from fastapi import APIRouter, HTTPException
from qdrant_client import QdrantClient

from backend.runtime_config import get_active

# This module hosts the shared Qdrant client + vote-aggregation helpers used by
# the shelves and qdrant_ops routers. It no longer exposes any endpoints of its
# own (the legacy /search workflow was retired in favour of the Annotation
# Studio), but the router is kept registered for namespace stability.
router = APIRouter(prefix="/api", tags=["search"])

_qdrant_cache: dict = {}  # keyed by (url, key)


def get_qdrant() -> "tuple[QdrantClient, str]":
    """Returns (client, collection_name) for the active connection."""
    conn = get_active()
    url, key = conn["qdrant_url"], conn["qdrant_key"]
    if not url or not key:
        raise HTTPException(503, "Qdrant not configured — check Settings")
    cache_key = (url, key)
    if cache_key not in _qdrant_cache:
        _qdrant_cache[cache_key] = QdrantClient(url=url, api_key=key, timeout=30)
    return _qdrant_cache[cache_key], conn["qdrant_collection"]


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
