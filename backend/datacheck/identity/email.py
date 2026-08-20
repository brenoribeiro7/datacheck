import re
from dataclasses import dataclass

_LOCAL_PART_PATTERN = re.compile(
    r"[A-Za-z0-9!#$%&'*+\-/=?^_`{|}~]+(?:\.[A-Za-z0-9!#$%&'*+\-/=?^_`{|}~]+)*"
)
_DOMAIN_LABEL_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


class EmailPolicyError(ValueError):
    """Report a safe, local email-policy failure without echoing the input."""


@dataclass(frozen=True, slots=True)
class CanonicalEmail:
    """Pair the display-preserving address with its login identity."""

    email: str
    email_normalized: str


def canonicalize_email(value: str) -> CanonicalEmail:
    """Validate the conservative ASCII policy and return both stored forms."""
    if not isinstance(value, str):
        raise TypeError("email must be a string")

    stripped = value.strip()
    try:
        encoded = stripped.encode("ascii")
    except UnicodeEncodeError:
        raise EmailPolicyError("email must contain ASCII characters only") from None

    if len(encoded) > 254:
        raise EmailPolicyError("email exceeds the maximum length")
    if stripped.count("@") != 1:
        raise EmailPolicyError("email must contain exactly one separator")

    local_part, domain = stripped.split("@")
    if not 1 <= len(local_part.encode("ascii")) <= 64:
        raise EmailPolicyError("email local part has an invalid length")
    if _LOCAL_PART_PATTERN.fullmatch(local_part) is None:
        raise EmailPolicyError("email local part is not a valid dot-atom")

    if not 1 <= len(domain.encode("ascii")) <= 253:
        raise EmailPolicyError("email domain has an invalid length")
    labels = domain.split(".")
    if len(labels) < 2 or any(_DOMAIN_LABEL_PATTERN.fullmatch(label) is None for label in labels):
        raise EmailPolicyError("email domain is not a valid multi-label domain")

    stored = f"{local_part}@{domain.lower()}"
    return CanonicalEmail(email=stored, email_normalized=stored.lower())
