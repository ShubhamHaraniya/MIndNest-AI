"""Object storage for uploaded files (S3-compatible: RustFS locally, any S3 service later)."""

import io
from collections.abc import Iterator
from typing import Any, BinaryIO, Protocol


class ObjectStorage(Protocol):
    def put(self, key: str, data: BinaryIO, content_type: str | None = None) -> None: ...

    def get_bytes(self, key: str) -> bytes: ...

    def iter_bytes(self, key: str, chunk_size: int = 65536) -> Iterator[bytes]: ...

    def delete(self, key: str) -> None: ...


class S3Storage:
    """Thin wrapper over boto3. The client is created on first use so importing this module,
    and starting the app, never needs the storage service to be up."""

    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str) -> None:
        self._endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._client: Any = None
        self._bucket_ready = False

    def _s3(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name="us-east-1",
                # Path-style addressing: self-hosted S3 servers have no wildcard DNS.
                config=Config(
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": 3},
                    # Newer boto3 adds checksum trailers that many S3-compatible servers
                    # reject; only send them when the server requires them.
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                ),
            )
        return self._client

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        from botocore.exceptions import ClientError

        client = self._s3()
        try:
            client.head_bucket(Bucket=self._bucket)
        except ClientError:
            client.create_bucket(Bucket=self._bucket)
        self._bucket_ready = True

    def put(self, key: str, data: BinaryIO, content_type: str | None = None) -> None:
        self._ensure_bucket()
        extra = {"ContentType": content_type} if content_type else {}
        self._s3().upload_fileobj(data, self._bucket, key, ExtraArgs=extra)

    def get_bytes(self, key: str) -> bytes:
        body = self._s3().get_object(Bucket=self._bucket, Key=key)["Body"]
        data: bytes = body.read()
        return data

    def iter_bytes(self, key: str, chunk_size: int = 65536) -> Iterator[bytes]:
        body = self._s3().get_object(Bucket=self._bucket, Key=key)["Body"]
        yield from body.iter_chunks(chunk_size)

    def delete(self, key: str) -> None:
        self._s3().delete_object(Bucket=self._bucket, Key=key)


class MemoryStorage:
    """In-memory stand-in for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: BinaryIO, content_type: str | None = None) -> None:
        self.objects[key] = data.read()

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def iter_bytes(self, key: str, chunk_size: int = 65536) -> Iterator[bytes]:
        stream = io.BytesIO(self.objects[key])
        while chunk := stream.read(chunk_size):
            yield chunk

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
