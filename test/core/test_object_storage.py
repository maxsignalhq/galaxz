from datetime import datetime
from datetime import timezone
from pathlib import Path

import pytest

from core.artifacts.object_storage import ArtifactAccessPolicy, LocalObjectStorage, ObjectStorageError, S3ObjectStorage
from core.artifacts.store import ArtifactStore


def test_local_storage_publishes_hash_and_round_trips(tmp_path):
    storage = LocalObjectStorage(str(tmp_path))
    metadata = storage.put("goal/output.txt", b"hello")
    assert metadata.size_bytes == 5
    assert metadata.media_type == "text/plain"
    assert storage.get("goal/output.txt") == b"hello"
    assert (Path(tmp_path) / "goal/output.txt").exists()


def test_local_storage_rejects_escape_and_oversize(tmp_path):
    storage = LocalObjectStorage(str(tmp_path), max_size_bytes=2)
    with pytest.raises(ValueError):
        storage.put("../escape", b"x")
    with pytest.raises(ObjectStorageError):
        storage.put("large", b"123")


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def get_object(self, **kwargs):
        value = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"Body": type("Body", (), {"read": lambda self: value})()}

    def delete_object(self, **kwargs):
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)


def test_s3_storage_uses_safe_key_and_metadata():
    client = FakeS3()
    storage = S3ObjectStorage("bucket", prefix="artifacts", client=client)
    metadata = storage.put("a.txt", b"hello")
    assert metadata.content_hash
    assert ("bucket", "artifacts/a.txt") in client.objects
    assert storage.get("a.txt") == b"hello"


def test_artifact_store_persists_external_object_metadata_and_reads_backend(tmp_path):
    objects = LocalObjectStorage(str(tmp_path / "objects"))
    store = ArtifactStore(str(tmp_path / "artifacts.db"), object_storage=objects)
    store.record([{"filename": "a.txt", "content": "hello"}], "", "task", "skill")
    row = store.get_version("::a.txt", 1)
    assert row["object_id"] == "::a.txt/v1"
    assert row["object_size_bytes"] == 5
    assert row["content"] == "hello"


def test_artifact_store_deletes_object_when_metadata_write_fails(tmp_path):
    objects = LocalObjectStorage(str(tmp_path / "objects"))
    store = ArtifactStore(str(tmp_path / "artifacts.db"), object_storage=objects)
    store._conn.execute("""CREATE TRIGGER fail_artifact_insert
        BEFORE INSERT ON artifact_versions
        BEGIN SELECT RAISE(ABORT, 'metadata failure'); END""")
    with pytest.raises(Exception, match="metadata failure"):
        store.record([{"filename": "a.txt", "content": "hello"}], "", "task", "skill")
    assert not [path for path in (tmp_path / "objects").rglob("*") if path.is_file()]


def test_artifact_store_cleans_orphans_and_prunes_old_versions(tmp_path):
    objects = LocalObjectStorage(str(tmp_path / "objects"))
    store = ArtifactStore(str(tmp_path / "artifacts.db"), object_storage=objects)
    store.record([{"filename": "a.txt", "content": "one"}], "", "task", "skill")
    store.record([{"filename": "a.txt", "content": "two"}], "", "task", "skill")
    objects.put("orphan", b"unused")
    assert store.cleanup_orphans() == ["orphan"]
    deleted = store.delete_older_than(datetime.now(timezone.utc))
    assert deleted == ["::a.txt/v1"]
    assert store.latest_version_number("::a.txt") == 2


def test_artifact_access_policy_requires_matching_scopes():
    policy = ArtifactAccessPolicy()
    policy.authorize(artifact_project_id="p1", artifact_organization_id="o1", project_id="p1", organization_id="o1")
    with pytest.raises(PermissionError):
        policy.authorize(artifact_project_id="p1", artifact_organization_id="o1", project_id="p2", organization_id="o1")
