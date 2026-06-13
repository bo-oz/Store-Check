import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.config import settings

router = APIRouter(prefix="/api/images", tags=["images"])


@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")

    session_id = str(uuid.uuid4())
    dest = Path(settings.upload_dir) / f"{session_id}.jpg"

    data = await file.read()
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not decode image")

    cv2.imwrite(str(dest), img)
    h, w = img.shape[:2]
    return {"session_id": session_id, "width": w, "height": h}


@router.get("/{session_id}/file")
def get_image(session_id: str):
    path = Path(settings.upload_dir) / f"{session_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "Session not found")
    return FileResponse(str(path), media_type="image/jpeg")
