from pathlib import Path

import pytest

from datacheck.datasets.csv import CsvStructure, CsvStructureError, scan_csv


def _scan(tmp_path: Path, content: bytes) -> CsvStructure:
    path = tmp_path / "candidate"
    path.write_bytes(content)
    return scan_csv(path)


def test_csv_scan_accepts_lf_crlf_bom_and_header_only(tmp_path: Path) -> None:
    parsed = _scan(tmp_path, b"name,age\nAlice,30\nBob,40\n")
    assert parsed.column_names == ("name", "age")
    assert parsed.row_count == 2

    parsed = _scan(tmp_path, b"\xef\xbb\xbfname,age\r\n")
    assert parsed.column_names == ("name", "age")
    assert parsed.row_count == 0


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", "empty_csv"),
        (b"name,name\n1,2\n", "duplicate_columns"),
        (b"name, age\n1,2\n", "invalid_header"),
        (b"name,\n1,2\n", "invalid_header"),
        (b"name,age\n1\n", "inconsistent_row_width"),
        (b"name,age\n1,2,3\n", "inconsistent_row_width"),
        (b'name,age\n"Alice,30\n', "malformed_csv"),
        (b"name,age\n\xff,30\n", "invalid_utf8"),
    ],
)
def test_csv_scan_rejects_invalid_structure(tmp_path: Path, content: bytes, code: str) -> None:
    with pytest.raises(CsvStructureError) as error:
        _scan(tmp_path, content)
    assert error.value.code == code


def test_csv_scan_enforces_column_count_and_name_length(tmp_path: Path) -> None:
    valid_header = ",".join(f"c{index}" for index in range(256)).encode() + b"\n"
    assert len(_scan(tmp_path, valid_header).column_names) == 256

    too_many = ",".join(f"c{index}" for index in range(257)).encode() + b"\n"
    with pytest.raises(CsvStructureError):
        _scan(tmp_path, too_many)

    with pytest.raises(CsvStructureError):
        _scan(tmp_path, ("x" * 129 + "\n").encode())
