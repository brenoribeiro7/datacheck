import csv
from dataclasses import dataclass
from pathlib import Path

from datacheck.datasets.policies import MAX_COLUMN_NAME_LENGTH, MAX_COLUMNS

MAX_CSV_BYTES = 10_485_760
MAX_UPLOAD_REQUEST_BYTES = MAX_CSV_BYTES + 65_536

# The stdlib parser otherwise inherits a smaller process default. The full file
# boundary remains the authoritative cap, including any individual field.
csv.field_size_limit(MAX_CSV_BYTES)


class CsvStructureError(ValueError):
    """Represent a safe structural CSV rejection without carrying row values."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CsvStructure:
    row_count: int
    column_names: tuple[str, ...]


def scan_csv(path: Path) -> CsvStructure:
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as source:
            reader = csv.reader(source, delimiter=",", quotechar='"', strict=True)
            try:
                header = next(reader)
            except StopIteration:
                raise CsvStructureError("empty_csv") from None

            columns = _validate_header(header)
            row_count = 0
            for row in reader:
                if len(row) != len(columns):
                    raise CsvStructureError("inconsistent_row_width")
                row_count += 1
    except UnicodeDecodeError:
        raise CsvStructureError("invalid_utf8") from None
    except csv.Error:
        raise CsvStructureError("malformed_csv") from None

    return CsvStructure(row_count=row_count, column_names=columns)


def _validate_header(header: list[str]) -> tuple[str, ...]:
    if not header or len(header) > MAX_COLUMNS:
        raise CsvStructureError("invalid_header")

    columns: list[str] = []
    for column in header:
        if (
            not column
            or column != column.strip()
            or len(column) > MAX_COLUMN_NAME_LENGTH
            or any(ord(character) < 32 or ord(character) == 127 for character in column)
        ):
            raise CsvStructureError("invalid_header")
        columns.append(column)

    if len(set(columns)) != len(columns):
        raise CsvStructureError("duplicate_columns")
    return tuple(columns)
