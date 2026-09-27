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


def summarize_import_result(result_path: Path, zip_path: Path) -> ImportResultSummary:
    return ImportResultSummary(
        rows=tuple(parse_import_result(result_path)),
        expected_count=count_expected_records(zip_path),
    )
