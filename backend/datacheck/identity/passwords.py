import unicodedata
from enum import Enum

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import ARGON2_VERSION as ARGON2_LIBRARY_VERSION

MIN_PASSWORD_LENGTH = 15
MAX_PASSWORD_LENGTH = 128
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65_536
ARGON2_PARALLELISM = 4
ARGON2_HASH_LENGTH = 32
ARGON2_SALT_LENGTH = 16
ARGON2_ENCODING = "utf-8"
ARGON2_VERSION = 19


class PasswordPolicyError(ValueError):
    """Indicate that a candidate does not meet the local password policy."""


class MalformedPasswordHashError(ValueError):
    """Identify corrupt stored state without exposing Argon2 parser details."""


class PasswordVerification(Enum):
    """Keep mismatch distinct from malformed storage for future auth policy."""

    MATCH = "match"
    MISMATCH = "mismatch"
    MALFORMED = "malformed"


def create_production_hasher() -> PasswordHasher:
    """Build the fixed, reviewed Argon2id profile without platform defaults."""
    if ARGON2_LIBRARY_VERSION != ARGON2_VERSION:
        raise RuntimeError("installed Argon2 version does not match the approved profile")
    return PasswordHasher(
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LENGTH,
        salt_len=ARGON2_SALT_LENGTH,
        encoding=ARGON2_ENCODING,
        type=Type.ID,
    )


class PasswordService:
    """Own password normalization, hashing, and stored-hash interpretation."""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or create_production_hasher()

    def normalize_and_validate(self, password: str) -> str:
        if not isinstance(password, str):
            raise TypeError("password must be a string")
        normalized = unicodedata.normalize("NFC", password)
        try:
            normalized.encode(ARGON2_ENCODING)
        except UnicodeEncodeError:
            raise PasswordPolicyError("password must be valid UTF-8") from None
        if not MIN_PASSWORD_LENGTH <= len(normalized) <= MAX_PASSWORD_LENGTH:
            raise PasswordPolicyError("password length is outside the accepted range")
        return normalized

    def hash(self, password: str) -> str:
        return self._hasher.hash(self.normalize_and_validate(password))

    def verify(self, encoded_hash: str, password: str) -> PasswordVerification:
        normalized = self.normalize_and_validate(password)
        try:
            self._hasher.verify(encoded_hash, normalized)
        except VerifyMismatchError:
            return PasswordVerification.MISMATCH
        except (InvalidHashError, VerificationError):
            return PasswordVerification.MALFORMED
        return PasswordVerification.MATCH

    def check_needs_rehash(self, encoded_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(encoded_hash)
        except InvalidHashError:
            raise MalformedPasswordHashError("stored password hash is malformed") from None
