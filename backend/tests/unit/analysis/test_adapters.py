from uuid import uuid4

import polars as pl
import pytest

from datacheck.analysis.adapters import (
    AnalysisDataIntegrityError,
    PersistedRuleSnapshot,
    adapt_rules,
    load_textual_csv,
)
from datacheck.validation import (
    RangeRuleSpec,
    RegexRuleSpec,
    RequiredRuleSpec,
    TypeRuleSpec,
    UniqueRuleSpec,
)


def test_load_textual_csv_preserves_text_empty_whitespace_unicode_and_order() -> None:
    content = (
        b"\xef\xbb\xbfid,value,note\r\n"
        b'1,,"a,b"\r\n'
        b'2,  ,"line one\nline two"\r\n' + "3,café,final\r\n".encode()
    )

    frame = load_textual_csv(
        content,
        expected_columns=("id", "value", "note"),
        expected_row_count=3,
    )

    assert frame.schema == {"id": pl.String, "value": pl.String, "note": pl.String}
    assert frame.to_dict(as_series=False) == {
        "id": ["1", "2", "3"],
        "value": ["", "  ", "café"],
        "note": ["a,b", "line one\nline two", "final"],
    }


def test_load_textual_csv_accepts_header_only_with_string_schema() -> None:
    frame = load_textual_csv(
        b"id,value\n",
        expected_columns=("id", "value"),
        expected_row_count=0,
    )

    assert frame.height == 0
    assert frame.schema == {"id": pl.String, "value": pl.String}


@pytest.mark.parametrize(
    ("content", "columns", "rows"),
    [
        (b"id\n1\n", ("other",), 1),
        (b"id\n1\n", ("id",), 2),
        (b"id\n\xff\n", ("id",), 1),
        (b'"unterminated\n', ("id",), 0),
    ],
)
def test_load_textual_csv_rejects_corrupt_or_mismatched_state(
    content: bytes, columns: tuple[str, ...], rows: int
) -> None:
    with pytest.raises(AnalysisDataIntegrityError):
        load_textual_csv(content, expected_columns=columns, expected_row_count=rows)


def test_adapt_rules_preserves_complete_ordered_canonical_rule_set() -> None:
    snapshots = (
        PersistedRuleSnapshot(uuid4(), "required", "id", {}),
        PersistedRuleSnapshot(uuid4(), "unique", "email", {}),
        PersistedRuleSnapshot(uuid4(), "type", "age", {"expected_type": "integer"}),
        PersistedRuleSnapshot(uuid4(), "range", "age", {"minimum": 0.0, "maximum": 130.0}),
        PersistedRuleSnapshot(uuid4(), "regex", "email", {"pattern": "^[^@]+@[^@]+$"}),
    )

    adapted = adapt_rules(snapshots)

    assert [rule.rule_id for rule in adapted] == [rule.rule_id for rule in snapshots]
    assert [rule.target_column for rule in adapted] == [rule.target_column for rule in snapshots]
    assert [type(rule.spec) for rule in adapted] == [
        RequiredRuleSpec,
        UniqueRuleSpec,
        TypeRuleSpec,
        RangeRuleSpec,
        RegexRuleSpec,
    ]
    assert adapted[2].configuration == {"expected_type": "integer"}
    assert adapted[3].configuration == {"minimum": 0.0, "maximum": 130.0}


@pytest.mark.parametrize(
    "snapshot",
    [
        PersistedRuleSnapshot(uuid4(), "unsupported", "id", {}),
        PersistedRuleSnapshot(uuid4(), "required", "id", {"extra": True}),
        PersistedRuleSnapshot(uuid4(), "type", "id", {"expected_type": "money"}),
        PersistedRuleSnapshot(uuid4(), "range", "id", {"minimum": "1"}),
        PersistedRuleSnapshot(uuid4(), "regex", "id", {"pattern": "("}),
    ],
)
def test_adapt_rules_rejects_corrupt_persisted_configuration(
    snapshot: PersistedRuleSnapshot,
) -> None:
    with pytest.raises(AnalysisDataIntegrityError):
        adapt_rules((snapshot,))
