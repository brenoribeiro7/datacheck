from unittest.mock import patch

import pytest
from argon2 import PasswordHasher, Type, extract_parameters

from datacheck.identity.passwords import (
    ARGON2_ENCODING,
    ARGON2_HASH_LENGTH,
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_SALT_LENGTH,
    ARGON2_TIME_COST,
    ARGON2_VERSION,
    MalformedPasswordHashError,
    PasswordPolicyError,
    PasswordService,
    PasswordVerification,
    create_production_hasher,
)


def _test_service() -> PasswordService:
    return PasswordService(
        PasswordHasher(
            time_cost=1,
            memory_cost=8_192,
            parallelism=1,
            hash_len=16,
            salt_len=8,
            encoding="utf-8",
            type=Type.ID,
        )
    )


@pytest.mark.parametrize("length", [14, 129])
def test_password_rejects_lengths_outside_the_policy(length: int) -> None:
    with pytest.raises(PasswordPolicyError):
        _test_service().normalize_and_validate("a" * length)


@pytest.mark.parametrize("length", [15, 128])
def test_password_accepts_length_boundaries(length: int) -> None:
    password = "a" * length

    assert _test_service().normalize_and_validate(password) == password


def test_oversized_password_fails_before_argon2_hashing() -> None:
    service = PasswordService()

    with patch.object(PasswordHasher, "hash", autospec=True) as hash_password:
        with pytest.raises(PasswordPolicyError):
            service.hash("a" * 129)

    hash_password.assert_not_called()


def test_password_normalizes_nfc_canonical_equivalents() -> None:
    decomposed = "e\u0301" * 15
    composed = "\u00e9" * 15

    assert _test_service().normalize_and_validate(decomposed) == composed


def test_password_preserves_unicode_and_surrounding_spaces() -> None:
    password = " " + "\u5bc6" * 13 + " "

    assert _test_service().normalize_and_validate(password) == password


def test_hashing_uses_random_salts_and_does_not_embed_plaintext() -> None:
    service = _test_service()
    password = "not-shared-value"

    first = service.hash(password)
    second = service.hash(password)

    assert password not in first
    assert first != second


def test_verify_distinguishes_match_mismatch_and_malformed_storage() -> None:
    service = _test_service()
    encoded_hash = service.hash("correct-value-1")

    assert service.verify(encoded_hash, "correct-value-1") is PasswordVerification.MATCH
    assert service.verify(encoded_hash, "different-value") is PasswordVerification.MISMATCH
    assert service.verify("not-an-argon2-hash", "correct-value-1") is PasswordVerification.MALFORMED


def test_needs_rehash_detects_different_parameters_and_safe_malformed_error() -> None:
    encoded_hash = _test_service().hash("rehash-candidate")
    production_service = PasswordService()

    assert production_service.check_needs_rehash(encoded_hash) is True
    with pytest.raises(MalformedPasswordHashError, match="stored password hash is malformed"):
        production_service.check_needs_rehash("not-an-argon2-hash")


def test_production_hasher_uses_the_exact_approved_profile() -> None:
    hasher = create_production_hasher()
    parameters = extract_parameters(hasher.hash("production-test"))

    assert parameters.type is Type.ID
    assert parameters.version == ARGON2_VERSION == 19
    assert parameters.time_cost == ARGON2_TIME_COST == 3
    assert parameters.memory_cost == ARGON2_MEMORY_COST == 65_536
    assert parameters.parallelism == ARGON2_PARALLELISM == 4
    assert parameters.hash_len == ARGON2_HASH_LENGTH == 32
    assert parameters.salt_len == ARGON2_SALT_LENGTH == 16
    assert hasher.encoding == ARGON2_ENCODING == "utf-8"
