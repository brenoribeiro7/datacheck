import unicodedata

import polars as pl
from polars.exceptions import PolarsError

MAX_DATASET_NAME_LENGTH = 100
MAX_FILENAME_LENGTH = 255
MAX_COLUMN_NAME_LENGTH = 128
MAX_COLUMNS = 256
MAX_REGEX_PATTERN_LENGTH = 256


class DatasetPolicyError(ValueError):
    """Represent invalid public dataset input without retaining its value."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalize_dataset_name(value: str) -> str:
    if not isinstance(value, str):
        raise DatasetPolicyError("invalid_dataset_name")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not 1 <= len(normalized) <= MAX_DATASET_NAME_LENGTH or _contains_control(normalized):
        raise DatasetPolicyError("invalid_dataset_name")
    return normalized


def normalize_csv_filename(value: str | None) -> str:
    if not isinstance(value, str):
        raise DatasetPolicyError("invalid_filename")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not 1 <= len(normalized) <= MAX_FILENAME_LENGTH
        or _contains_control(normalized)
        or "/" in normalized
        or "\\" in normalized
        or not normalized.lower().endswith(".csv")
    ):
        raise DatasetPolicyError("invalid_filename")
    return normalized


def validate_target_column(value: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= MAX_COLUMN_NAME_LENGTH
        or _contains_control(value)
    ):
        raise DatasetPolicyError("invalid_target_column")
    return value


def validate_polars_regex(pattern: str) -> str:
    if (
        not isinstance(pattern, str)
        or not 1 <= len(pattern) <= MAX_REGEX_PATTERN_LENGTH
        or _contains_control(pattern)
    ):
        raise DatasetPolicyError("invalid_regex_pattern")
    try:
        # Compile through the same Rust-regex boundary selected for DC-04 without
        # evaluating any dataset value.
        pl.Series([""], dtype=pl.String).str.contains(pattern).to_list()
    except PolarsError:
        raise DatasetPolicyError("invalid_regex_pattern") from None
    return pattern


def _contains_control(value: str) -> bool:
    return any(unicodedata.category(character).startswith("C") for character in value)
