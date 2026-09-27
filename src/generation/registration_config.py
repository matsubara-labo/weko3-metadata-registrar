from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PUBLISH_STATUSES = ("public", "private")
DEFAULT_PUBLISH_STATUS = "public"


class RegistrationConfigError(ValueError):
    """Raised when metadata registration configuration is invalid."""


@dataclass(frozen=True)
class RegistrationSettings:
    weko_base_url: str
    item_type_export_path: Path
    indexes: dict[str, str]
    default_index: str
    publish_date: str
    default_languages: dict[str, str]
    publish_status: str = DEFAULT_PUBLISH_STATUS

    def resolve_index(self, index_name: str | None = None) -> tuple[str, str]:
        selected_name = index_name or self.default_index
        configured_id = self.indexes.get(selected_name)
        if configured_id is None:
            raise RegistrationConfigError(
                f"Index {selected_name!r} is not defined in registration config"
            )
        return configured_id, selected_name


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise RegistrationConfigError(f"{key} must be a non-empty string")
    return value


def is_publish_date(value: str) -> bool:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") == value
    except ValueError:
        return False


def validate_publish_date(value: str, source: str = "publish_date") -> str:
    if not is_publish_date(value):
        raise RegistrationConfigError(
            f"{source} {value!r} is not a valid date; WEKO requires PubDate "
            "as YYYY-MM-DD, e.g. 2025-05-27"
        )
    return value


def _string_mapping(raw: dict[str, Any], key: str) -> dict[str, str]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise RegistrationConfigError(f"{key} must be an object")
    mapping: dict[str, str] = {}
    for name, mapped_value in value.items():
        if not isinstance(name, str) or not name:
            raise RegistrationConfigError(f"{key} must contain non-empty names")
        if not isinstance(mapped_value, str) or not mapped_value:
            raise RegistrationConfigError(f"{key} must contain non-empty values")
        mapping[name] = mapped_value
    return mapping


def validate_publish_status(value: object, source: str = "publish_status") -> str:
    if value not in PUBLISH_STATUSES:
        raise RegistrationConfigError(
            f"{source} must be one of {', '.join(PUBLISH_STATUSES)}: {value!r}"
        )
    return value


def load_registration_settings(config_path: Path) -> RegistrationSettings:
    if not config_path.exists():
        raise FileNotFoundError(f"Registration config was not found: {config_path}")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistrationConfigError(
            f"Registration config is not valid JSON: {config_path}"
        ) from exc
    if not isinstance(raw, dict):
        raise RegistrationConfigError("Registration config must contain a JSON object")

    raw_indexes = raw.get("indexes")
    if not isinstance(raw_indexes, dict) or not raw_indexes:
        raise RegistrationConfigError("indexes must be a non-empty object")
    indexes: dict[str, str] = {}
    for name, index_id in raw_indexes.items():
        if not isinstance(name, str) or not name:
            raise RegistrationConfigError("indexes must contain non-empty names")
        if not isinstance(index_id, (str, int)) or not str(index_id):
            raise RegistrationConfigError("indexes must contain non-empty IDs")
        indexes[name] = str(index_id)

    default_index = _required_string(raw, "default_index")
    if default_index not in indexes:
        raise RegistrationConfigError(
            f"default_index {default_index!r} is not defined in indexes"
        )

    export_value = _required_string(raw, "item_type_export")
    export_path = Path(export_value)
    if not export_path.is_absolute():
        export_path = config_path.parent / export_path

    return RegistrationSettings(
        weko_base_url=_required_string(raw, "weko_base_url").rstrip("/"),
        item_type_export_path=export_path,
        indexes=indexes,
        default_index=default_index,
        publish_date=validate_publish_date(_required_string(raw, "publish_date")),
        default_languages=_string_mapping(raw, "default_languages"),
        publish_status=validate_publish_status(
            raw.get("publish_status", DEFAULT_PUBLISH_STATUS)
        ),
    )
