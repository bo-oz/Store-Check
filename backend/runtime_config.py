"""Runtime config stored in app_config.json — editable via /api/config without restart."""
import json
from pathlib import Path

from backend.config import settings  # only used to seed defaults from .env

_CONFIG_PATH = Path(__file__).parent.parent / "app_config.json"

SUPPORTED_MODELS = [
    {"key": "vit_small_patch14_dinov2.lvd142m",  "label": "DINOv2 small  (384-dim)",  "dim": 384},
    {"key": "vit_base_patch14_dinov2.lvd142m",   "label": "DINOv2 base   (768-dim)",  "dim": 768},
    {"key": "vit_large_patch14_dinov2.lvd142m",  "label": "DINOv2 large (1024-dim)", "dim": 1024},
]

_DEFAULT_CONNECTION = {
    "name": "default",
    "qdrant_url": settings.qdrant_url,
    "qdrant_key": settings.qdrant_key,
    "qdrant_collection": "retail_shelf_analytics_dinov2_1024",
    "embed_dim": 1024,
    "dinov2_model": "vit_large_patch14_dinov2.lvd142m",
}

DEFAULTS = {
    "connections": [_DEFAULT_CONNECTION],
    "active_connection": "default",
}


def _load() -> dict:
    if _CONFIG_PATH.exists():
        try:
            saved = json.loads(_CONFIG_PATH.read_text())
            # Merge: keep defaults for any missing top-level keys
            result = {**DEFAULTS, **saved}
            # Ensure connections list is valid
            if not result.get("connections"):
                result["connections"] = DEFAULTS["connections"]
            return result
        except Exception:
            pass
    return {
        "connections": [dict(_DEFAULT_CONNECTION)],
        "active_connection": "default",
    }


def _save(cfg: dict):
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


_current: dict = _load()


def get_all() -> dict:
    return dict(_current)


def get_active() -> dict:
    """Return the active connection config dict."""
    conns = _current.get("connections", [])
    name = _current.get("active_connection", "")
    conn = next((c for c in conns if c["name"] == name), None)
    return conn if conn else (conns[0] if conns else _DEFAULT_CONNECTION)


def set_active(name: str):
    global _current
    _current = {**_current, "active_connection": name}
    _save(_current)


def upsert_connection(conn: dict):
    """Add or replace a connection by name."""
    global _current
    conns = [c for c in _current["connections"] if c["name"] != conn["name"]]
    conns.append(conn)
    _current = {**_current, "connections": conns}
    _save(_current)


def delete_connection(name: str):
    global _current
    conns = [c for c in _current["connections"] if c["name"] != name]
    active = _current["active_connection"]
    if active == name:
        active = conns[0]["name"] if conns else ""
    _current = {**_current, "connections": conns, "active_connection": active}
    _save(_current)
