import boto3
from botocore.config import Config
from django.conf import settings


class ObjectStorageDeletionAdapter:
    """Test adapter; production should use R2ObjectStorageDeletionAdapter."""

    def delete_keys(self, keys: list[str]) -> int:
        return len(keys)


class R2ObjectStorageDeletionAdapter(ObjectStorageDeletionAdapter):
    """Deletes recorded media keys from both R2 buckets used by the product."""

    def __init__(self):
        required = (
            settings.R2_ENDPOINT_URL,
            settings.R2_ACCESS_KEY_ID,
            settings.R2_SECRET_ACCESS_KEY,
            settings.R2_BUCKET_PRIVATE,
            settings.R2_BUCKET_PUBLIC_DERIVED,
        )
        if not all(required):
            raise RuntimeError("r2_not_configured")
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
            config=Config(connect_timeout=3, read_timeout=15, retries={"max_attempts": 1}),
        )

    def delete_keys(self, keys: list[str]) -> int:
        if not keys:
            return 0
        deleted = 0
        for bucket in (settings.R2_BUCKET_PRIVATE, settings.R2_BUCKET_PUBLIC_DERIVED):
            for start in range(0, len(keys), 1000):
                batch = keys[start : start + 1000]
                try:
                    response = self.client.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
                    )
                except Exception as exc:  # noqa: BLE001 - never declare an incomplete purge successful
                    raise RuntimeError("erasure_storage_unavailable") from exc
                if response.get("Errors"):
                    raise RuntimeError("erasure_storage_unavailable")
                deleted += len(batch)
        return deleted
