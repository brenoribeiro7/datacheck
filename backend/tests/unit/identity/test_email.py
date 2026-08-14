import pytest

from datacheck.identity.email import EmailPolicyError, canonicalize_email


def test_canonical_email_preserves_local_case_and_lowers_domain() -> None:
    result = canonicalize_email("\u2003Local.Tag+filter@Sub.EXAMPLE.COM\u2003")

    assert result.email == "Local.Tag+filter@sub.example.com"
    assert result.email_normalized == "local.tag+filter@sub.example.com"


def test_all_approved_atom_characters_are_accepted() -> None:
    result = canonicalize_email("AZaz09!#$%&'*+-/=?^_`{|}~@Example.Test")

    assert result.email == "AZaz09!#$%&'*+-/=?^_`{|}~@example.test"


def test_email_accepts_approved_length_boundaries() -> None:
    local_part = "a" * 64
    domain = ".".join(("b" * 63, "c" * 63, "d" * 61))

    result = canonicalize_email(f"{local_part}@{domain}")

    assert len(result.email.encode("ascii")) == 254


@pytest.mark.parametrize(
    "candidate",
    [
        "nonascii-\u00e9@example.test",
        "local@ex\u00e4mple.test",
        "missing-separator.example.test",
        "too@many@example.test",
        f"{'a' * 65}@example.test",
        ".leading@example.test",
        "trailing.@example.test",
        "two..dots@example.test",
        '"quoted"@example.test',
        "comment(note)@example.test",
        "Display Name <local@example.test>",
        "local@example",
        "local@-example.test",
        "local@example-.test",
        "local@example..test",
        "local@[127.0.0.1]",
        f"local@{'a' * 64}.test",
        f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 62}",
    ],
)
def test_email_rejects_values_outside_the_conservative_policy(candidate: str) -> None:
    with pytest.raises(EmailPolicyError):
        canonicalize_email(candidate)


def test_email_error_does_not_echo_the_input() -> None:
    candidate = "Sensitive Value@example.test"

    with pytest.raises(EmailPolicyError) as error:
        canonicalize_email(candidate)

    assert candidate not in str(error.value)
