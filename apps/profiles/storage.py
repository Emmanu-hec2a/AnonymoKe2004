from io import BytesIO

import boto3
from botocore.config import Config
from django.conf import settings


class MediaStorageUnavailable(RuntimeError):
    pass


class MediaPayloadTooLarge(ValueError):
    pass


class R2MediaStore:
    def __init__(self):
        required = (
            settings.R2_ENDPOINT_URL,
            settings.R2_ACCESS_KEY_ID,
            settings.R2_SECRET_ACCESS_KEY,
            settings.R2_BUCKET_PRIVATE,
            settings.R2_BUCKET_PUBLIC_DERIVED,
        )
        if not all(required):
            raise MediaStorageUnavailable("r2_not_configured")
        self.private_bucket = settings.R2_BUCKET_PRIVATE
        self.derived_bucket = settings.R2_BUCKET_PUBLIC_DERIVED
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
            config=Config(connect_timeout=3, read_timeout=15, retries={"max_attempts": 1}),
        )

    def presign_upload(self, key: str, content_type: str) -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.private_bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=settings.MEDIA_UPLOAD_URL_TTL_SECONDS,
            HttpMethod="PUT",
        )

    def presign_private(self, key: str, ttl_seconds: int = 300) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.private_bucket, "Key": key},
            ExpiresIn=ttl_seconds,
            HttpMethod="GET",
        )

    def presign_derived(self, key: str, ttl_seconds: int = 300) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.derived_bucket, "Key": key},
            ExpiresIn=ttl_seconds,
            HttpMethod="GET",
        )

    def head(self, key: str) -> dict:
        return self.client.head_object(Bucket=self.private_bucket, Key=key)

    def download(self, key: str, *, max_bytes: int = 10485760) -> bytes:
        response = self.client.get_object(Bucket=self.private_bucket, Key=key)
        body = response["Body"]
        try:
            payload = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(payload) > max_bytes:
            raise MediaPayloadTooLarge("media_size_invalid")
        return payload

    def upload_private(self, key: str, payload: bytes, content_type: str) -> None:
        self.client.upload_fileobj(
            BytesIO(payload),
            self.private_bucket,
            key,
            ExtraArgs={"ContentType": content_type, "Metadata": {"processed": "true"}},
        )

    def upload_derived(self, key: str, payload: bytes, content_type: str) -> None:
        self.client.upload_fileobj(
            BytesIO(payload),
            self.derived_bucket,
            key,
            ExtraArgs={"ContentType": content_type, "CacheControl": "private, max-age=300"},
        )
