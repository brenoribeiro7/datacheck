import hashlib
from io import BytesIO
from pathlib import Path

import pytest

from datacheck.datasets.csv import MAX_CSV_BYTES
from datacheck.datasets.storage import FileTooLarge, LocalDatasetStorage


def test_storage_writes_installs_opens_and_removes_private_file(tmp_path: Path) -> None:
    storage = LocalDatasetStorage(tmp_path / "datasets")
    content = b"name\nAlice\n"
    candidate = storage.write_candidate(BytesIO(content))
    assert candidate.size_bytes == len(content)
    assert candidate.content_sha256 == hashlib.sha256(content).digest()
    assert candidate.path.parent == storage.root
    assert candidate.path.stat().st_mode & 0o777 == 0o600

    key = storage.new_storage_key()
    assert key.endswith(".csv") and len(key) == 36
    storage.install(candidate, key)
    assert not candidate.path.exists()
    with storage.open_binary(key) as stored:
        assert stored.read() == content
    storage.remove(key)
    assert list(storage.root.iterdir()) == []


def test_storage_rejects_paths_and_cleans_oversized_candidate(tmp_path: Path) -> None:
    storage = LocalDatasetStorage(tmp_path / "datasets")
    for key in ("../escape.csv", "not-a-key.csv", "/tmp/file.csv"):
        with pytest.raises(ValueError):
            storage.open_binary(key)

    with pytest.raises(FileTooLarge):
        storage.write_candidate(BytesIO(b"x" * (MAX_CSV_BYTES + 1)))
    assert list(storage.root.iterdir()) == []


def test_storage_discard_is_idempotent(tmp_path: Path) -> None:
    storage = LocalDatasetStorage(tmp_path / "datasets")
    candidate = storage.write_candidate(BytesIO(b"name\n"))
    storage.discard_candidate(candidate)
    storage.discard_candidate(candidate)
    assert list(storage.root.iterdir()) == []
