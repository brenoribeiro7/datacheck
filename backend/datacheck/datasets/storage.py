import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from datacheck.datasets.csv import MAX_CSV_BYTES

_STORAGE_KEY_PATTERN = re.compile(r"[0-9a-f]{32}[.]csv")


class FileTooLarge(ValueError):
    """Indicate that the exact CSV byte boundary was exceeded."""


@dataclass(frozen=True, slots=True)
class CandidateFile:
    path: Path
    size_bytes: int
    content_sha256: bytes


class LocalDatasetStorage:
    """Store complete CSV candidates beneath one controlled local root."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._root.chmod(0o700)

    @property
    def root(self) -> Path:
        return self._root

    def write_candidate(self, source: BinaryIO) -> CandidateFile:
        candidate_path = self._root / f".candidate-{uuid.uuid4().hex}"
        digest = hashlib.sha256()
        size = 0
        descriptor = os.open(candidate_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as destination:
                while chunk := source.read(65_536):
                    size += len(chunk)
                    if size > MAX_CSV_BYTES:
                        raise FileTooLarge("CSV exceeds the byte limit")
                    digest.update(chunk)
                    destination.write(chunk)
        except BaseException:
            candidate_path.unlink(missing_ok=True)
            raise
        return CandidateFile(
            path=candidate_path,
            size_bytes=size,
            content_sha256=digest.digest(),
        )

    def new_storage_key(self) -> str:
        return f"{uuid.uuid4().hex}.csv"

    def install(self, candidate: CandidateFile, storage_key: str) -> None:
        destination = self._path_for_key(storage_key)
        os.replace(candidate.path, destination)
        destination.chmod(0o600)

    def discard_candidate(self, candidate: CandidateFile) -> None:
        candidate.path.unlink(missing_ok=True)

    def remove(self, storage_key: str) -> None:
        self._path_for_key(storage_key).unlink(missing_ok=True)

    def open_binary(self, storage_key: str) -> BinaryIO:
        return self._path_for_key(storage_key).open("rb")

    def _path_for_key(self, storage_key: str) -> Path:
        if _STORAGE_KEY_PATTERN.fullmatch(storage_key) is None:
            raise ValueError("invalid internal storage key")
        return self._root / storage_key
