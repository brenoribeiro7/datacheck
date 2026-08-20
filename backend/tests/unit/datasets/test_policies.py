import pytest

from datacheck.datasets.policies import (
    DatasetPolicyError,
    normalize_csv_filename,
    normalize_dataset_name,
    validate_polars_regex,
    validate_target_column,
)


def test_dataset_name_is_trimmed_normalized_and_bounded() -> None:
    assert normalize_dataset_name("  Cafe\u0301 data  ") == "Café data"
    assert normalize_dataset_name("a" * 100) == "a" * 100
    for value in ("", "   ", "a" * 101, "unsafe\nname"):
        with pytest.raises(DatasetPolicyError) as error:
            normalize_dataset_name(value)
        assert error.value.code == "invalid_dataset_name"


def test_filename_is_metadata_only_and_requires_csv_extension() -> None:
    assert normalize_csv_filename("Cafe\u0301 records.CSV") == "Café records.CSV"
    for value in (None, "", "records.txt", "../records.csv", "dir\\records.csv", "bad\x00.csv"):
        with pytest.raises(DatasetPolicyError) as error:
            normalize_csv_filename(value)
        assert error.value.code == "invalid_filename"


def test_target_column_is_exact_bounded_and_free_of_controls() -> None:
    assert validate_target_column("customer_id") == "customer_id"
    for value in ("", " customer_id", "customer_id ", "bad\ncolumn", "x" * 129):
        with pytest.raises(DatasetPolicyError):
            validate_target_column(value)


def test_regex_uses_the_polars_dialect_without_dataset_evaluation() -> None:
    assert validate_polars_regex(r"^[a-z]+$") == r"^[a-z]+$"
    for pattern in ("", "(", "(?=lookahead)", "x" * 257):
        with pytest.raises(DatasetPolicyError) as error:
            validate_polars_regex(pattern)
        assert error.value.code == "invalid_regex_pattern"
