"""Copy every stored file to or from one tar stream, for backups.

    python -m mindnest_core.storagesync export  > files.tar     (all objects -> tar on stdout)
    python -m mindnest_core.storagesync import  < files.tar     (tar on stdin -> bucket)

Works with any S3-compatible storage the app is configured for, so one backup script serves both
the bundled storage and a hosted bucket. Nothing is written to disk: object names are only ever
used as storage keys, never as file paths.
"""

import sys
import tarfile
from typing import Any, BinaryIO

from mindnest_core.settings import get_settings
from mindnest_core.storage import S3Storage


def safe_key(name: str) -> bool:
    """Object keys are plain relative names. Refuse anything that looks like a path trick."""
    if not name or name.startswith("/") or "\\" in name or "\x00" in name:
        return False
    return all(part not in ("", ".", "..") for part in name.split("/"))


def export_objects(client: Any, bucket: str, out: BinaryIO) -> int:
    """Stream every object in the bucket into a tar written to `out`. Returns the object count."""
    count = 0
    with tarfile.open(fileobj=out, mode="w|") as tar:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for item in page.get("Contents", []):
                key = item["Key"]
                response = client.get_object(Bucket=bucket, Key=key)
                info = tarfile.TarInfo(name=key)
                info.size = int(response["ContentLength"])
                info.mtime = int(item["LastModified"].timestamp()) if "LastModified" in item else 0
                info.mode = 0o600
                tar.addfile(info, fileobj=response["Body"])
                count += 1
    return count


def import_objects(client: Any, bucket: str, source: BinaryIO) -> int:
    """Upload every file in the tar stream `source` to the bucket. Returns the object count."""
    count = 0
    with tarfile.open(fileobj=source, mode="r|") as tar:
        for member in tar:
            if not member.isfile():
                continue
            if not safe_key(member.name):
                raise ValueError(f"refusing unsafe object name in backup: {member.name!r}")
            handle = tar.extractfile(member)
            if handle is None:  # pragma: no cover - isfile() already checked
                continue
            client.upload_fileobj(handle, bucket, member.name)
            count += 1
    return count


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in {"export", "import"}:
        print("usage: python -m mindnest_core.storagesync export|import", file=sys.stderr)
        return 2
    settings = get_settings()
    storage = S3Storage(
        settings.s3_endpoint_url, settings.s3_access_key, settings.s3_secret_key, settings.s3_bucket
    )
    storage._ensure_bucket()  # a fresh storage volume has no bucket yet
    client = storage._s3()
    if argv[1] == "export":
        count = export_objects(client, settings.s3_bucket, sys.stdout.buffer)
        sys.stdout.buffer.flush()
    else:
        count = import_objects(client, settings.s3_bucket, sys.stdin.buffer)
    print(f"{count} file(s) {'exported' if argv[1] == 'export' else 'imported'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
