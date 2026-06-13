from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Qdrant URL/key here only seed the first "default" connection on first run.
    # Once you save a connection in the Settings tab, app_config.json takes over
    # (collection, embedding model and dimension are all chosen there).
    qdrant_url: str = ""
    qdrant_key: str = ""
    upload_dir: str = "/tmp/store_check_uploads"
    # YOLO detection model paths
    yolo_weights_path: str = str(Path(__file__).parent / "models" / "yolov8_sku.pt")
    yolo_class_map_path: str = str(Path(__file__).parent / "models" / "yolo_class_map.json")
    yolo_export_dir: str = str(Path(__file__).parent.parent / "data" / "yolo_dataset")
    yolo_archive_dir: str = str(Path(__file__).parent.parent / "data" / "model_archive")
    # Shelf image store — content-addressed by SHA-256
    # Switch to "s3" later; see backend/services/image_store.py for the interface
    shelf_images_dir: str = str(Path(__file__).parent.parent / "data" / "shelf_images")

    class Config:
        env_file = Path(__file__).parent.parent / ".env"
        extra = "ignore"


settings = Settings()
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
