import base64
import binascii
import hashlib
import re
import secrets

TOKEN_BYTES = 32
TOKEN_ENCODED_LENGTH = 43
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


class TokenEncodingError(ValueError):
    """Report a safe failure for a malformed bearer-token representation."""


def generate_token_bytes() -> bytes:
    return secrets.token_bytes(TOKEN_BYTES)


def encode_token(raw_token: bytes) -> str:
    if not isinstance(raw_token, bytes) or len(raw_token) != TOKEN_BYTES:
        raise TokenEncodingError("token entropy must be exactly 32 bytes")
    encoded = base64.urlsafe_b64encode(raw_token).rstrip(b"=").decode("ascii")
    if len(encoded) != TOKEN_ENCODED_LENGTH:
        raise TokenEncodingError("token encoding has an invalid length")
    return encoded


def decode_token(encoded_token: str) -> bytes:
    if not isinstance(encoded_token, str):
        raise TypeError("encoded token must be a string")
    if len(encoded_token) != TOKEN_ENCODED_LENGTH:
        raise TokenEncodingError("encoded token has an invalid length")
    if _TOKEN_PATTERN.fullmatch(encoded_token) is None:
        raise TokenEncodingError("encoded token has an invalid alphabet")
    try:
        decoded = base64.b64decode(encoded_token + "=", altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise TokenEncodingError("encoded token is invalid") from None
    if len(decoded) != TOKEN_BYTES:
        raise TokenEncodingError("decoded token has an invalid length")
    if encode_token(decoded) != encoded_token:
        raise TokenEncodingError("encoded token is not canonical")
    return decoded


def hash_session_token(raw_token: bytes) -> bytes:
    if not isinstance(raw_token, bytes) or len(raw_token) != TOKEN_BYTES:
        raise TokenEncodingError("session token must be exactly 32 bytes")
    return hashlib.sha256(raw_token).digest()


def csrf_tokens_match(expected: bytes, supplied: bytes) -> bool:
    if len(expected) != TOKEN_BYTES or len(supplied) != TOKEN_BYTES:
        return False
    return secrets.compare_digest(expected, supplied)
