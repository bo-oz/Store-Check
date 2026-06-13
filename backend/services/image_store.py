"""Content-addressed shelf image storage.

Images are keyed by SHA-256 of their bytes, so uploading the same photo twice
is a no-op.  LocalImageStore keeps files on disk; swap it for S3ImageStore
(stub below) when you move to cloud storage — the rest of the codebase is
unchanged because both implement the same four-method interface.
"""
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("store_check")


class LocalImageStore:
    def __init__(self, base_dir: str):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    # ── Core interface (same signature needed for S3ImageStore) ───────────────

    @staticmethod
    def sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def put(self, data: bytes, meta: Optional[dict] = None) -> tuple[str, bool]:
        """Store bytes. Returns (sha256_key, already_existed)."""
        key = self.sha256(data)
        img_path = self.base / f"{key}.jpg"
        existed = img_path.exists()
        if not existed:
            img_path.write_bytes(data)
            log.info("Stored shelf image %s… (%d bytes)", key[:12], len(data))
        if meta:
            meta_path = self.base / f"{key}.json"
            if not meta_path.exists():
                meta_path.write_text(json.dumps(meta, ensure_ascii=False))
        return key, existed

    def exists(self, key: str) -> bool:
        return (self.base / f"{key}.jpg").exists()

    def path(self, key: str) -> Path:
        return self.base / f"{key}.jpg"

    def meta(self, key: str) -> dict:
        p = self.base / f"{key}.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def list_keys(self) -> list[str]:
        """All stored shelf IDs, most recent first (by mtime)."""
        paths = sorted(self.base.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.stem for p in paths]

    # ── S3 equivalent — uncomment and swap when ready ─────────────────────────
    # class S3ImageStore:
    #     def __init__(self, bucket: str, prefix: str = "shelf_images"):
    #         import boto3; self.s3 = boto3.client("s3"); self.bucket = bucket; self.prefix = prefix
    #
    #     def _key(self, sha: str): return f"{self.prefix}/{sha}.jpg"
    #
    #     def put(self, data, meta=None):
    #         from botocore.exceptions import ClientError
    #         sha = self.sha256(data)
    #         try: self.s3.head_object(Bucket=self.bucket, Key=self._key(sha)); return sha, True
    #         except ClientError: pass
    #         self.s3.put_object(Bucket=self.bucket, Key=self._key(sha), Body=data,
    #                            Metadata={k: str(v) for k, v in (meta or {}).items()})
    #         return sha, False
    #
    #     def exists(self, sha):
    #         from botocore.exceptions import ClientError
    #         try: self.s3.head_object(Bucket=self.bucket, Key=self._key(sha)); return True
    #         except ClientError: return False
    #
    #     def path(self, sha):  # returns a presigned URL valid for 1 hour
    #         return self.s3.generate_presigned_url("get_object",
    #             Params={"Bucket": self.bucket, "Key": self._key(sha)}, ExpiresIn=3600)
    #
    #     def meta(self, sha):
    #         try: return self.s3.head_object(Bucket=self.bucket, Key=self._key(sha)).get("Metadata", {})
    #         except: return {}
    #
    #     def list_keys(self):
    #         r = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=self.prefix + "/")
    #         return [o["Key"].split("/")[-1].replace(".jpg","") for o in r.get("Contents",[])]
