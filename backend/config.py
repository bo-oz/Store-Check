from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    qdrant_url: str = ""
    qdrant_key: str = ""
    qdrant_collection: str = "retail_shelf_analytics_dinov2"
    embed_dim: int = 384
    dinov2_model: str = "dinov2_vits14"
    upload_dir: str = "/tmp/store_check_uploads"
    # YOLOv8 SKU model
    yolo_weights_path: str = str(Path(__file__).parent / "models" / "yolov8_sku.pt")
    yolo_class_map_path: str = str(Path(__file__).parent / "models" / "yolo_class_map.json")
    yolo_export_dir: str = str(Path(__file__).parent.parent / "data" / "yolo_dataset")
    yolo_archive_dir: str = str(Path(__file__).parent.parent / "data" / "model_archive")
    yolo_min_samples: int = 2
    # Shelf image store — content-addressed by SHA-256
    # Switch to "s3" later; see backend/services/image_store.py for the interface
    shelf_images_dir: str = str(Path(__file__).parent.parent / "data" / "shelf_images")

    class Config:
        env_file = Path(__file__).parent.parent / ".env"


settings = Settings()
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
