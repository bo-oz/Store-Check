from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.runtime_config import (
    get_all, get_active, set_active, upsert_connection, delete_connection, SUPPORTED_MODELS
)

router = APIRouter(prefix="/api/config", tags=["config"])


class ConnectionModel(BaseModel):
    name: str
    qdrant_url: str
    qdrant_key: str
    qdrant_collection: str
    embed_dim: int
    dinov2_model: str


class SetActiveRequest(BaseModel):
    active_connection: str


@router.get("")
def read_config():
    cfg = get_all()
    return {
        "connections": cfg.get("connections", []),
        "active_connection": cfg.get("active_connection"),
        "supported_models": SUPPORTED_MODELS,
    }


@router.post("/active")
def set_active_connection(body: SetActiveRequest):
    cfg = get_all()
    names = [c["name"] for c in cfg.get("connections", [])]
    if body.active_connection not in names:
        raise HTTPException(400, f"Unknown connection '{body.active_connection}'")
    set_active(body.active_connection)
    return {"active_connection": body.active_connection}


@router.put("/connections")
def save_connection(conn: ConnectionModel):
    upsert_connection(conn.model_dump())
    return {"ok": True}


@router.delete("/connections/{name}")
def remove_connection(name: str):
    cfg = get_all()
    if len(cfg.get("connections", [])) <= 1:
        raise HTTPException(400, "Cannot delete the last connection")
    delete_connection(name)
    return {"ok": True}
