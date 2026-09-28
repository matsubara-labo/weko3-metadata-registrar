from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

RESULT_COLUMN_COUNT = 6
SUCCESS_STATUS_LABELS = frozenset({"Done", "完了"})
SUCCESS_RESULT_LABELS = frozenset({"Success", "成功"})
MAX_REPORTED_FAILED_RESULT_ROWS = 20


class ImportResultError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImportResultRow:
    no: str
    item_id: str
    status: str
    result: str

    @property
    def succeeded(self) -> bool:
        return (
            self.status in SUCCESS_STATUS_LABELS
            and self.result in SUCCESS_RESULT_LABELS
        )


@dataclass(frozen=True)
class ImportResultSummary:
    rows: tuple[ImportResultRow, ...]
    expected_count: int

    @property
    def success_count(self) -> int:
        return sum(1 for row in self.rows if row.succeeded)

    @property
    def failed_rows(self) -> tuple[ImportResultRow, ...]:
        return tuple(row for row in self.rows if not row.succeeded)

    @property
    def succeeded(self) -> bool:
        return (
            len(self.rows) >= 1
            and len(self.rows) == self.expected_count
            and not self.failed_rows
        )

    def describe(self) -> list[str]:
        failed_rows = self.failed_rows
        lines = [
            f"success={self.success_count}/{len(self.rows)} "
            f"failure={len(failed_rows)} expected={self.expected_count}"
        ]
        for row in failed_rows[:MAX_REPORTED_FAILED_RESULT_ROWS]:
            lines.append(
                f"  No.={row.no!r} ItemID={row.item_id!r} "
                f"Status={row.status!r} Result={row.result!r}"
            )
        if len(failed_rows) > MAX_REPORTED_FAILED_RESULT_ROWS:
            lines.append(
                f"  ... {len(failed_rows) - MAX_REPORTED_FAILED_RESULT_ROWS} more failed rows"
            )
        return lines


def result_delimiter(result_path: Path) -> str:
    return "," if result_path.suffix.lower() == ".csv" else "\t"


def parse_import_result(result_path: Path) -> list[ImportResultRow]:
    text = result_path.read_text(encoding="utf-8-sig")
    reader = csv.reader(io.StringIO(text), delimiter=result_delimiter(result_path))
    rows: list[ImportResultRow] = []
    for line_number, cells in enumerate(reader, start=1):
        if line_number == 1:
            if len(cells) < RESULT_COLUMN_COUNT:
                raise ImportResultError(
                    f"Import result header has {len(cells)} columns "
                    f"(expected {RESULT_COLUMN_COUNT}): {result_path}"
                )
            continue
        if not any(cell.strip() for cell in cells):
            continue
        if len(cells) < RESULT_COLUMN_COUNT:
            raise ImportResultError(
                f"Import result row {line_number} has {len(cells)} columns "
                f"(expected {RESULT_COLUMN_COUNT}): {result_path}"
            )
        rows.append(
            ImportResultRow(
                no=cells[0].strip(),
                item_id=cells[3].strip(),
                status=cells[4].strip(),
                result=cells[5].strip(),
            )
        )
    return rows


def count_expected_records(zip_path: Path) -> int:
    count = 0
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".tsv"):
                continue
            text = archive.read(name).decode("utf-8-sig")
            for cells in csv.reader(io.StringIO(text), delimiter="\t"):
                if not cells or not any(cell.strip() for cell in cells):
                    continue
                if not cells[0].startswith("#"):
                    count += 1
    return count


def read_import_tsv_rows(zip_path: Path) -> tuple[list[list[str]], list[list[str]]]:
    """Return (header rows, data rows) of the single TSV in an import ZIP.

    Blank rows are skipped as in count_expected_records, so data row N
    (1-based) is the record WEKO reports as No. N.
    """
    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".tsv")]
        if len(names) != 1:
            raise ImportResultError(
                f"Expected one TSV in {zip_path}, found {len(names)}: {names}"
            )
        text = archive.read(names[0]).decode("utf-8-sig")
    header: list[list[str]] = []
    data: list[list[str]] = []
    for cells in csv.reader(io.StringIO(text), delimiter="\t"):
        if not cells or not any(cell.strip() for cell in cells):
            continue
        (header if cells[0].startswith("#") else data).append(cells)
    return header, data


def write_failed_rows(
    zip_path: Path, summary: ImportResultSummary, output_path: Path
) -> int:
    """Write the failed records of zip_path as a WEKO import TSV.

    The file keeps the ZIP's header rows, so it can be fixed, zipped under
    data/ and imported again. Returns the number of rows written; nothing is
    written without failed rows.

    WEKO numbers the records it actually imported, so when it drops one the
    later numbers shift. The mapping is therefore refused unless the result
    has exactly one row per record.
    """
    header, data = read_import_tsv_rows(zip_path)
    if len(summary.rows) != len(data):
        raise ImportResultError(
            f"the result has {len(summary.rows)} row(s) but {zip_path} has "
            f"{len(data)} record(s), so result No. cannot be matched to records; "
            "check WEKO manually"
        )
    selected: list[list[str]] = []
    for row in summary.failed_rows:
        try:
            number = int(row.no)
        except ValueError:
            raise ImportResultError(
                f"Import result No. {row.no!r} is not a record number"
            ) from None
        if not 1 <= number <= len(data):
            raise ImportResultError(
                f"Import result No. {number} is outside the {len(data)} "
                f"record(s) in {zip_path}"
            )
        selected.append(data[number - 1])
    if selected:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8-sig", newline="") as file_obj:
            writer = csv.writer(file_obj, delimiter="\t", lineterminator="\n")
            writer.writerows(header)
            writer.writerows(selected)
    return len(selected)


def summarize_import_result(result_path: Path, zip_path: Path) -> ImportResultSummary:
    return ImportResultSummary(
        rows=tuple(parse_import_result(result_path)),
        expected_count=count_expected_records(zip_path),
    )
