import re
from unittest.mock import patch

import pytest

from datacheck.identity.tokens import (
    TokenEncodingError,
    csrf_tokens_match,
    decode_token,
    encode_token,
    generate_token_bytes,
    hash_session_token,
)


def test_generation_requests_exactly_32_bytes_from_the_entropy_source() -> None:
    entropy = bytes(range(32))

    with patch("datacheck.identity.tokens.secrets.token_bytes", return_value=entropy) as source:
        assert generate_token_bytes() == entropy

    source.assert_called_once_with(32)


def test_token_encoding_is_canonical_urlsafe_unpadded_base64() -> None:
    raw_token = bytes(range(32))

    encoded = encode_token(raw_token)

    assert len(encoded) == 43
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", encoded)
    assert "=" not in encoded
    assert decode_token(encoded) == raw_token
    assert encode_token(decode_token(encoded)) == encoded


@pytest.mark.parametrize(
    "candidate",
    [
        "A" * 42,
        "A" * 44,
        "A" * 42 + "=",
        "A" * 42 + "+",
    ],
)
def test_decoder_rejects_wrong_length_padding_and_bad_alphabet(candidate: str) -> None:
    with pytest.raises(TokenEncodingError):
        decode_token(candidate)


def test_decoder_rejects_noncanonical_equivalent_encoding() -> None:
    canonical = encode_token(bytes(32))
    noncanonical = canonical[:-1] + "B"

    with pytest.raises(TokenEncodingError, match="not canonical"):
        decode_token(noncanonical)


def test_decoder_defensively_rejects_an_unexpected_decoded_length() -> None:
    with patch("datacheck.identity.tokens.base64.b64decode", return_value=b"x" * 31):
        with pytest.raises(TokenEncodingError, match="decoded token"):
            decode_token("A" * 43)


def test_session_hash_is_a_deterministic_32_byte_sha256_digest() -> None:
    raw_token = bytes(range(32))

    first = hash_session_token(raw_token)

    assert len(first) == 32
    assert first == hash_session_token(raw_token)
    assert first != hash_session_token(bytes(reversed(range(32))))


def test_small_random_sample_does_not_repeat_tokens() -> None:
    generated = {generate_token_bytes() for _ in range(8)}

    assert len(generated) == 8


def test_csrf_comparison_accepts_same_raw_secret_and_rejects_a_different_one() -> None:
    expected = bytes(range(32))

    assert csrf_tokens_match(expected, expected) is True
    assert csrf_tokens_match(expected, bytes(reversed(range(32)))) is False
    assert csrf_tokens_match(expected, b"short") is False
