from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

STATUS_STARTED = "started"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"
BLOCKING_STATUSES = frozenset(
    {STATUS_STARTED, STATUS_SUCCEEDED, STATUS_FAILED, STATUS_UNKNOWN}
)
HASH_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class LedgerRecord:
    timestamp: str
    zip_name: str
    sha256: str
    status: str
    result_path: str | None = None
    detail: str | None = None

    def to_json(self) -> str:
        data: dict[str, str] = {
            "timestamp": self.timestamp,
            "zip_name": self.zip_name,
            "sha256": self.sha256,
            "status": self.status,
        }
        if self.result_path is not None:
            data["result_path"] = self.result_path
        if self.detail is not None:
            data["detail"] = self.detail
        return json.dumps(data, ensure_ascii=False)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_ledger_line(line: str) -> LedgerRecord | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    required = ("timestamp", "zip_name", "sha256", "status")
    if not all(isinstance(data.get(key), str) for key in required):
        return None
    optional = {
        key: data[key] if isinstance(data.get(key), str) else None
        for key in ("result_path", "detail")
    }
    return LedgerRecord(**{key: data[key] for key in required}, **optional)


@dataclass(frozen=True)
class ImportLedger:
    path: Path

    def read_records(self) -> list[LedgerRecord]:
        if not self.path.exists():
            return []
        records: list[LedgerRecord] = []
        with self.path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = parse_ledger_line(line)
                if record is None:
                    print(
                        f"Warning: skipping corrupt import ledger line {line_number} "
                        f"in {self.path}"
                    )
                    continue
                records.append(record)
        return records

    def blocking_record(self, sha256: str) -> LedgerRecord | None:
        matches = [
            record
            for record in self.read_records()
            if record.sha256 == sha256 and record.status in BLOCKING_STATUSES
        ]
        return matches[-1] if matches else None

    def append(
        self,
        zip_name: str,
        sha256: str,
        status: str,
        result_path: Path | None = None,
        detail: str | None = None,
    ) -> LedgerRecord:
        record = LedgerRecord(
            timestamp=current_timestamp(),
            zip_name=zip_name,
            sha256=sha256,
            status=status,
            result_path=str(result_path) if result_path is not None else None,
            detail=detail,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        prefix = "" if self._ends_with_newline() else "\n"
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(prefix + record.to_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def _ends_with_newline(self) -> bool:
        try:
            with self.path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    return True
                handle.seek(-1, os.SEEK_END)
                return handle.read(1) == b"\n"
        except FileNotFoundError:
            return True
