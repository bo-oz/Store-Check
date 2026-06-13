import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers import search, qdrant_ops, config_router, detection, shelves

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)

app = FastAPI(title="Store Check", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(qdrant_ops.router)
app.include_router(config_router.router)
app.include_router(detection.router)
app.include_router(shelves.router)


@app.on_event("startup")
async def _ensure_payload_indexes():
    """Create Qdrant payload indexes needed for annotation filtering."""
    try:
        from backend.routers.search import get_qdrant
        from qdrant_client.models import PayloadSchemaType
        client, collection = get_qdrant()
        client.create_payload_index(
            collection_name=collection,
            field_name="shelf_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
        logging.getLogger("store_check").info("Qdrant payload index for 'shelf_id' ensured")
    except Exception as e:
        logging.getLogger("store_check").warning("Could not ensure Qdrant indexes: %s", e)


@app.get("/api/health")
def health():
    return {"status": "ok"}
