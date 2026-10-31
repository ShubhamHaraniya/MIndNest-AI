import io
import tarfile
from datetime import UTC, datetime
from typing import Any

import pytest
from mindnest_core.storagesync import export_objects, import_objects, safe_key


class FakeClient:
    """Just enough of a boto3 S3 client for the backup code."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = dict(objects or {})

    def get_paginator(self, name: str) -> Any:
        assert name == "list_objects_v2"
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket: str) -> Any:  # noqa: N803
                keys = sorted(objects)
                for start in range(0, max(len(keys), 1), 2):  # two per page
                    chunk = keys[start : start + 2]
                    yield {"Contents": [{"Key": k, "LastModified": datetime(2026, 1, 1, tzinfo=UTC)} for k in chunk]}

        return Paginator()

    def get_object(self, Bucket: str, Key: str) -> Any:  # noqa: N803
        data = self.objects[Key]
        return {"ContentLength": len(data), "Body": io.BytesIO(data)}

    def upload_fileobj(self, fileobj: Any, bucket: str, key: str) -> None:
        self.objects[key] = fileobj.read()


def test_round_trip_keeps_every_file_and_name() -> None:
    source = FakeClient({
        "u1/a.pdf": b"%PDF-1 hello",
        "shared/g1/i1.txt": b"notes",
        "empty.txt": b"",
        "big.bin": bytes(range(256)) * 4000,
        "ünï/cødé.txt": "héllo".encode(),
    })
    buffer = io.BytesIO()
    assert export_objects(source, "b", buffer) == 5
    buffer.seek(0)
    target = FakeClient()
    assert import_objects(target, "b", buffer) == 5
    assert target.objects == source.objects


def test_empty_bucket_gives_a_valid_empty_archive() -> None:
    buffer = io.BytesIO()
    assert export_objects(FakeClient(), "b", buffer) == 0
    buffer.seek(0)
    assert import_objects(FakeClient(), "b", buffer) == 0


@pytest.mark.parametrize("name", ["../evil", "/abs", "a/../b", "a//b", "./x", "a\\b", ""])
def test_unsafe_names_are_refused_on_import(name: str) -> None:
    assert not safe_key(name)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo(name=name or "placeholder")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    buffer.seek(0)
    target = FakeClient()
    if name == "":
        return
    with pytest.raises(ValueError):
        import_objects(target, "b", buffer)
    assert target.objects == {}


def test_directories_and_links_in_the_archive_are_skipped() -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        directory = tarfile.TarInfo("folder")
        directory.type = tarfile.DIRTYPE
        tar.addfile(directory)
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
        info = tarfile.TarInfo("ok.txt")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))
    buffer.seek(0)
    target = FakeClient()
    assert import_objects(target, "b", buffer) == 1
    assert target.objects == {"ok.txt": b"hi"}
