from __future__ import annotations

import ast
import csv
import difflib
import os
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from enum import Enum, auto
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .item_type import (
    ItemTypeField,
    format_weko_attributes,
    load_item_type_export,
)
from .registration_config import (
    DEFAULT_DATE_TIMEZONE,
    load_registration_settings,
    validate_publish_date,
    validate_publish_status,
)

DEFAULT_REGISTRATION_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "metadata_registration.json"
)


class ControlValueSource(Enum):
    EMPTY = auto()
    INDEX_ID = auto()
    INDEX_NAME = auto()
    PUBLISH_STATUS = auto()
    KEEP = auto()


@dataclass(frozen=True)
class ImportControlColumn:
    binding: str
    display_name: str
    value_source: ControlValueSource
    required: bool = False
    multiple: bool = False
    identifier_marker: bool = False

    @property
    def attribute(self) -> str:
        if self.identifier_marker:
            return "#"
        return format_weko_attributes(
            hidden=False,
            required=self.required,
            multiple=self.multiple,
        )


WEKO_IMPORT_CONTROL_COLUMNS = (
    ImportControlColumn(
        "#.id", "#ID", ControlValueSource.EMPTY, identifier_marker=True
    ),
    ImportControlColumn(".uri", "URI", ControlValueSource.EMPTY),
    ImportControlColumn(
        ".metadata.path[0]",
        ".IndexID[0]",
        ControlValueSource.INDEX_ID,
        multiple=True,
    ),
    ImportControlColumn(
        ".pos_index[0]",
        ".POS_INDEX[0]",
        ControlValueSource.INDEX_NAME,
        multiple=True,
    ),
    ImportControlColumn(
        ".publish_status",
        ".PUBLISH_STATUS",
        ControlValueSource.PUBLISH_STATUS,
        required=True,
    ),
    ImportControlColumn(
        ".feedback_mail[0]",
        ".FEEDBACK_MAIL[0]",
        ControlValueSource.EMPTY,
        multiple=True,
    ),
    ImportControlColumn(
        ".researchmap_linkage",
        ".RESEAECHMAP_LINKAGE",
        ControlValueSource.EMPTY,
    ),
    ImportControlColumn(".cnri", ".CNRI", ControlValueSource.EMPTY),
    ImportControlColumn(".doi_ra", ".DOI_RA", ControlValueSource.EMPTY),
    ImportControlColumn(".doi", ".DOI", ControlValueSource.EMPTY),
    ImportControlColumn(
        ".edit_mode",
        "Keep/Upgrade Version",
        ControlValueSource.KEEP,
        required=True,
    ),
)


# WEKO3 reads uploaded TSV files with csv.reader at Python's default
# field_size_limit, so it cannot load any cell longer than this.
WEKO_TSV_FIELD_SIZE_LIMIT = 131072

GENERATED_ARTIFACT_NAME_PATTERN = re.compile(
    r"(?:output_write(?:_\d+)?\.tsv|import(?:_\d+)?\.zip|invalid_rows\.tsv)",
    re.IGNORECASE,
)
MAX_LISTED_EXISTING_ARTIFACTS = 10
INVALID_ROWS_REPORT_NAME = "invalid_rows.tsv"
# Leading report columns; a report fed back as input gets fresh values for them.
INVALID_ROWS_REPORT_COLUMNS = ("_invalid_row", "_invalid_reason")
MAX_LISTED_ROW_ERRORS = 50
# ZIP member metadata is fixed (the date comes from the input file's mtime) so
# identical TSV content and input mtime yield identical ZIP bytes (the import
# ledger matches ZIPs by SHA-256). create_system 3 (Unix) makes external_attr
# mean rw-r--r--. Members are stored uncompressed because deflate output
# differs between zlib builds (e.g. zlib-ng on Windows), which would change the
# hash across hosts. ZIP dates have 2-second resolution within this range.
ZIP_MEMBER_COMPRESS_TYPE = zipfile.ZIP_STORED
ZIP_MIN_DATE_TIME = (1980, 1, 1, 0, 0, 0)
ZIP_MAX_DATE_TIME = (2107, 12, 31, 23, 59, 58)
ZIP_MEMBER_CREATE_SYSTEM = 3
ZIP_MEMBER_EXTERNAL_ATTR = 0o644 << 16

# Optional input column giving a row's language for a field with a language child.
LANGUAGE_COLUMN_SUFFIX = "_lang"
WEKO_TITLE_ERROR = "Title is required item."
DEFAULT_TITLE_FALLBACK_PREFIX = "NoTitle"

# Control characters WEKO must not receive: its Python 3.6 csv reader fails on
# NUL with an internal server error, and the others are stored as broken text
# (and are invalid in XML). TAB, LF and CR are legitimate.
FORBIDDEN_CONTROL_CHARACTERS = "\x00-\x08\x0b\x0c\x0e-\x1f\x7f"
FORBIDDEN_CONTROL_PATTERN = re.compile(f"[{FORBIDDEN_CONTROL_CHARACTERS}]")

# Largest limit accepted on every platform (sys.maxsize overflows on Windows).
INPUT_FIELD_SIZE_LIMIT = 2**31 - 1


class MetadataInputError(ValueError):
    """Raised when source metadata cannot satisfy the exported ItemType."""


class OutputExistsError(FileExistsError):
    """Raised when output_dir already holds generated artifacts."""


@dataclass(frozen=True)
class MetadataSchema:
    item_type_name: str
    item_schema_url: str
    # Control and fixed columns, one entry per output column in each list.
    base_metadata_bindings: list[str]
    base_display_columns: list[str]
    base_column_values: list[str]
    base_column_attributes: list[str]
    # Templates of repeatable fields contain "{index}" and expand per value.
    column_bindings: dict[str, list[str]]
    default_languages: dict[str, str]
    field_attributes: dict[str, str]
    display_columns: dict[str, list[str]]
    repeatable_fields: frozenset[str]
    # Non-hidden fields mapped to JPCOAR title; WEKO ignores hidden ones.
    title_fields: frozenset[str] = frozenset()
    hidden_title_fields: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        lengths = {
            len(self.base_metadata_bindings),
            len(self.base_display_columns),
            len(self.base_column_values),
            len(self.base_column_attributes),
        }
        if len(lengths) != 1:
            raise ValueError(
                "Base columns have mismatched lengths: "
                f"{len(self.base_metadata_bindings)} bindings, "
                f"{len(self.base_display_columns)} display columns, "
                f"{len(self.base_column_values)} values, "
                f"{len(self.base_column_attributes)} attributes"
            )

    @property
    def language_fields(self) -> list[str]:
        return [
            field_name
            for field_name, binding in self.column_bindings.items()
            if any(column.endswith("_language") for column in binding)
        ]


def language_column(field_name: str) -> str:
    return f"{field_name}{LANGUAGE_COLUMN_SUFFIX}"


@dataclass(frozen=True)
class _MetadataRuntime:
    schema: MetadataSchema
    date_like_fields: frozenset[str]
    date_timezone: tzinfo


@dataclass(frozen=True)
class MetadataGenerationConfig:
    input_path: Path
    output_dir: Path
    index_name: str | None = None
    publish_date: str | None = None
    publish_status: str | None = None
    chunk_size: int | None = None
    zip_outputs: bool = False
    keep_tsv: bool = True
    registration_config_path: Path = DEFAULT_REGISTRATION_CONFIG_PATH
    delimiter: str = "auto"
    overwrite: bool = False
    skip_invalid_rows: bool = False
    strict_columns: bool = False
    # (label, column) pairs tried in order when the title field is empty.
    title_fallbacks: tuple[tuple[str, str], ...] = ()
    title_fallback_prefix: str = DEFAULT_TITLE_FALLBACK_PREFIX


@dataclass(frozen=True)
class TitleFallback:
    """Fill an empty title field with "<prefix> (<label>: <value>)"."""

    field_name: str
    sources: tuple[tuple[str, str], ...]
    prefix: str = DEFAULT_TITLE_FALLBACK_PREFIX


@dataclass(frozen=True)
class RowError:
    row_number: int
    message: str
    cells: dict[str, str]


@dataclass(frozen=True)
class GeneratedArtifact:
    chunk_index: int
    row_count: int
    tsv_path: Path | None
    zip_path: Path | None = None


def _build_metadata_runtime(config: MetadataGenerationConfig) -> _MetadataRuntime:
    settings = load_registration_settings(config.registration_config_path)
    item_type = load_item_type_export(settings.item_type_export_path)
    index_id, index_name = settings.resolve_index(config.index_name)
    publish_date = settings.publish_date
    if config.publish_date:
        publish_date = validate_publish_date(config.publish_date, "--publish-date")
    publish_status = settings.publish_status
    if config.publish_status is not None:
        publish_status = validate_publish_status(
            config.publish_status, "--publish-status"
        )

    base_metadata_bindings = [column.binding for column in WEKO_IMPORT_CONTROL_COLUMNS]
    base_display_columns = [
        column.display_name for column in WEKO_IMPORT_CONTROL_COLUMNS
    ]
    base_column_values = [
        resolve_control_value(
            column.value_source,
            index_id=index_id,
            index_name=index_name,
            publish_status=publish_status,
        )
        for column in WEKO_IMPORT_CONTROL_COLUMNS
    ]
    base_column_attributes = [
        column.attribute for column in WEKO_IMPORT_CONTROL_COLUMNS
    ]
    # Fixed fields are never expanded, so an array item is always index 0.
    for field in item_type.fixed_fields:
        base_metadata_bindings.extend(
            template.format(index=0) for template in field.binding_templates
        )
        base_display_columns.extend(
            template.format(index=0) for template in field.display_templates
        )
        base_column_values.extend(
            resolve_fixed_field_values(field, publish_date=publish_date)
        )
        base_column_attributes.extend([field.attribute] * len(field.binding_templates))

    column_bindings = {
        field.name: list(field.binding_templates) for field in item_type.fields
    }
    display_columns = {
        field.name: list(field.display_templates) for field in item_type.fields
    }

    field_names = {field.name for field in item_type.fields}
    for field in item_type.fields:
        column = language_column(field.name)
        if any(value.language for value in field.values) and column in field_names:
            raise MetadataInputError(
                f"ItemType field {column!r} has the name of the language column "
                f"for field {field.name!r}; rename one of them in the ItemType"
            )

    schema = MetadataSchema(
        item_type_name=item_type.display_name,
        item_schema_url=f"{settings.weko_base_url}/items/jsonschema/{item_type.id}",
        base_metadata_bindings=base_metadata_bindings,
        base_display_columns=base_display_columns,
        base_column_values=base_column_values,
        base_column_attributes=base_column_attributes,
        column_bindings=column_bindings,
        default_languages=dict(settings.default_languages),
        field_attributes={field.name: field.attribute for field in item_type.fields},
        display_columns=display_columns,
        repeatable_fields=frozenset(
            field.name for field in item_type.fields if field.dynamically_repeatable
        ),
        title_fields=frozenset(
            field.name
            for field in item_type.fields
            if field.key in item_type.title_field_keys and not field.hidden
        ),
        hidden_title_fields=frozenset(
            field.name
            for field in item_type.fields
            if field.key in item_type.title_field_keys and field.hidden
        ),
    )
    return _MetadataRuntime(
        schema=schema,
        date_like_fields=frozenset(
            field.name for field in item_type.fields if field.date_like
        ),
        date_timezone=settings.date_timezone,
    )


def load_metadata_schema(config: MetadataGenerationConfig) -> MetadataSchema:
    return _build_metadata_runtime(config).schema


def resolve_control_value(
    source: ControlValueSource,
    *,
    index_id: str,
    index_name: str,
    publish_status: str,
) -> str:
    if source is ControlValueSource.INDEX_ID:
        return index_id
    if source is ControlValueSource.INDEX_NAME:
        return index_name
    if source is ControlValueSource.PUBLISH_STATUS:
        return publish_status
    if source is ControlValueSource.KEEP:
        return "keep"
    return ""


def resolve_fixed_field_values(field: ItemTypeField, *, publish_date: str) -> list[str]:
    """Return one value per binding of a fixed field."""
    if field.key == "pubdate":
        return ["" if value.language else publish_date for value in field.values]
    if field.required:
        raise MetadataInputError(
            f"Required fixed ItemType field {field.name!r} has no configured value"
        )
    return [""] * len(field.values)


DEFAULT_DATE_TZINFO = ZoneInfo(DEFAULT_DATE_TIMEZONE)


def process_date(date_str: str, date_timezone: tzinfo = DEFAULT_DATE_TZINFO) -> str:
    """Reduce a date or datetime to the calendar date WEKO stores.

    A datetime with a UTC offset is an instant, so it is converted to
    ``date_timezone`` before its date is taken; otherwise the part after ``T``
    is dropped as is.
    """
    date_part, separator, _ = date_str.partition("T")
    if not separator:
        return date_str
    try:
        moment = datetime.fromisoformat(date_str)
    except ValueError:
        return date_part
    if moment.utcoffset() is None:
        return date_part
    try:
        return moment.astimezone(date_timezone).date().isoformat()
    except OverflowError:
        # Out of datetime's range after conversion; reject it as a non-date.
        return date_str


WEKO_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m", "%Y")


def is_weko_date(value: str) -> bool:
    # Mirrors weko-search-ui utils.validation_date_property.
    for fmt in WEKO_DATE_FORMATS:
        try:
            return value == datetime.strptime(value, fmt).strftime(fmt)
        except ValueError:
            pass
    return False


def normalize_date(
    field_name: str, value: str, date_timezone: tzinfo = DEFAULT_DATE_TZINFO
) -> str:
    date = process_date(value.strip(), date_timezone).strip()
    if not is_weko_date(date):
        raise MetadataInputError(
            f"{field_name!r} value {value!r} is not a WEKO date "
            "(YYYY-MM-DD, YYYY-MM or YYYY)"
        )
    return date


DELIMITERS = {"comma": ",", "tab": "\t"}


def resolve_delimiter(name: str) -> str | None:
    if name == "auto":
        return None
    try:
        return DELIMITERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown delimiter {name!r}; use auto, {', '.join(DELIMITERS)}"
        ) from None


def detect_delimiter(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".tsv":
        return "\t"
    if suffix == ".csv":
        return ","
    with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as file_obj:
        header = file_obj.readline()
    return "\t" if header.count("\t") > header.count(",") else ","


def reject_control_characters(value: str) -> str:
    """Raise if value holds a character WEKO must not receive.

    Called before strip(), which would silently drop a leading or trailing
    one, e.g. the decoded "\\infty" of "\\infty-Diff".
    """
    match = FORBIDDEN_CONTROL_PATTERN.search(value)
    if match is not None:
        raise MetadataInputError(
            f"value contains control character U+{ord(match.group(0)):04X} at "
            f"position {match.start()} ({value[: match.start()][-20:]!r}...); "
            "WEKO cannot import it, repair the input with "
            "src/scripts/repair_control_chars.py"
        )
    return value


def parse_literal_list(raw_value: Any) -> list[str]:
    if raw_value in (None, ""):
        return []
    if isinstance(raw_value, list):
        return [reject_control_characters(str(value)).strip() for value in raw_value]

    text = reject_control_characters(str(raw_value)).strip()
    if not text:
        return []

    if not (text.startswith("[") and text.endswith("]")):
        return [text]

    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return [text]
    if not isinstance(parsed, list):
        return [text]

    values: list[str] = []
    for value in parsed:
        if value is None:
            values.append("")
        elif isinstance(value, str):
            values.append(reject_control_characters(value).strip())
        else:
            raise MetadataInputError(
                f"List element {value!r} is of type {type(value).__name__}; "
                "quote each list element as a string, e.g. \"['1.50']\""
            )
    return values


def _resolve_languages(
    source_row: dict[str, Any],
    field_name: str,
    value_count: int,
    schema: MetadataSchema,
) -> list[str]:
    if not value_count:
        return []
    column = language_column(field_name)
    try:
        languages = parse_literal_list(source_row.get(column, ""))
    except MetadataInputError as exc:
        raise MetadataInputError(f"{column!r}: {exc}") from exc
    languages = [language.strip() for language in languages if language.strip()]
    if not languages:
        languages = [schema.default_languages.get(field_name, "")]
    if len(languages) == 1:
        return languages * value_count
    if len(languages) != value_count:
        raise MetadataInputError(
            f"{column!r} has {len(languages)} languages but {field_name!r} has "
            f"{value_count} value(s); give one language per value or a single "
            "language for all"
        )
    return languages


def _has_value_with_language(
    normalized: dict[str, str | list[str]], field_name: str
) -> bool:
    values = normalized[field_name]
    languages = normalized.get(language_column(field_name)) or []
    if isinstance(values, str):
        values = [values]
    if isinstance(languages, str):
        languages = [languages]
    return any(value and language for value, language in zip(values, languages))


def build_title_fallback(
    schema: MetadataSchema,
    sources: tuple[tuple[str, str], ...],
    prefix: str = DEFAULT_TITLE_FALLBACK_PREFIX,
) -> TitleFallback | None:
    """Target the first non-hidden title field in ItemType order."""
    if not sources:
        return None
    labels = [label for label, _ in sources]
    for label, column in sources:
        if not label.strip() or not column.strip():
            raise MetadataInputError(
                f"--title-fallback {label}={column}: label and column must not be empty"
            )
    if len(set(labels)) != len(labels):
        raise MetadataInputError(
            f"--title-fallback labels must be unique, got {', '.join(labels)}"
        )
    field_name = next(
        (name for name in schema.column_bindings if name in schema.title_fields), None
    )
    if field_name is None:
        raise MetadataInputError(
            "--title-fallback needs a non-hidden ItemType field mapped to the "
            "JPCOAR title, but the ItemType has none"
        )
    return TitleFallback(field_name=field_name, sources=sources, prefix=prefix)


def check_title_fallback_columns(
    input_path: Path, fieldnames: list[str], fallback: TitleFallback
) -> None:
    present = set(fieldnames)
    missing = [column for _, column in fallback.sources if column not in present]
    if missing:
        raise MetadataInputError(
            f"{input_path}:1: --title-fallback column(s) not in the input: "
            f"{', '.join(repr(column) for column in missing)}"
        )


def _non_empty_values(raw_value: Any) -> list[str]:
    return [value for value in parse_literal_list(raw_value) if value.strip()]


def fill_missing_title(
    source_row: dict[str, Any], fallback: TitleFallback
) -> str | None:
    """Return the fallback title for a row whose title field is empty.

    Returns None when the title has a value or no fallback column has one.
    """
    try:
        if _non_empty_values(source_row.get(fallback.field_name, "")):
            return None
    except MetadataInputError as exc:
        raise MetadataInputError(f"{fallback.field_name!r}: {exc}") from exc
    for label, column in fallback.sources:
        try:
            values = _non_empty_values(source_row.get(column, ""))
        except MetadataInputError as exc:
            raise MetadataInputError(f"{column!r}: {exc}") from exc
        if values:
            return f"{fallback.prefix} ({label}: {values[0]})"
    return None


def normalize_row(
    source_row: dict[str, Any],
    schema: MetadataSchema,
    date_like_fields: frozenset[str] = frozenset(),
    date_timezone: tzinfo = DEFAULT_DATE_TZINFO,
) -> dict[str, str | list[str]]:
    normalized: dict[str, str | list[str]] = {}
    for field_name in schema.column_bindings:
        try:
            values = parse_literal_list(source_row.get(field_name, ""))
        except MetadataInputError as exc:
            raise MetadataInputError(f"{field_name!r}: {exc}") from exc
        values = [value for value in values if value.strip()]
        if "Required" in schema.field_attributes[field_name] and not values:
            raise MetadataInputError(f"Required metadata field {field_name!r} is empty")
        repeatable = field_name in schema.repeatable_fields
        if not repeatable and len(values) > 1:
            raise MetadataInputError(
                f"{field_name!r} accepts a single value but got {len(values)}"
            )
        if field_name in date_like_fields:
            values = [
                normalize_date(field_name, value, date_timezone) for value in values
            ]
        if repeatable:
            normalized[field_name] = values
        else:
            normalized[field_name] = values[0] if values else ""

    for field_name in schema.language_fields:
        value = normalized[field_name]
        values = value if isinstance(value, list) else [value] if value else []
        languages = _resolve_languages(source_row, field_name, len(values), schema)
        column = language_column(field_name)
        if isinstance(value, list):
            normalized[column] = languages
        else:
            normalized[column] = languages[0] if languages else ""

    if schema.title_fields and not any(
        _has_value_with_language(normalized, field_name)
        for field_name in schema.title_fields
    ):
        names = ", ".join(repr(name) for name in sorted(schema.title_fields))
        raise MetadataInputError(
            f"no title field ({names}) has both a value and a language; WEKO "
            f"rejects the record ({WEKO_TITLE_ERROR!r}); fill a '<field>_lang' "
            "column or set default_languages"
        )

    for field_name, value in normalized.items():
        for entry in value if isinstance(value, list) else [value]:
            if len(entry) > WEKO_TSV_FIELD_SIZE_LIMIT:
                raise MetadataInputError(
                    f"{field_name!r} value is {len(entry)} characters; WEKO cannot "
                    f"read TSV cells longer than {WEKO_TSV_FIELD_SIZE_LIMIT} characters"
                )
    return normalized


def validate_unique_columns(input_path: Path, fieldnames: list[str]) -> None:
    positions: dict[str, list[int]] = {}
    for column_number, name in enumerate(fieldnames, start=1):
        positions.setdefault(name, []).append(column_number)
    duplicates = [
        f"{name!r} (columns {', '.join(str(number) for number in numbers)})"
        for name, numbers in positions.items()
        if len(numbers) > 1
    ]
    if duplicates:
        raise MetadataInputError(
            f"{input_path}:1: duplicate column name(s): {', '.join(duplicates)}"
        )


def validate_header_matches_schema(
    input_path: Path, fieldnames: list[str], schema: MetadataSchema, delimiter: str
) -> None:
    if any(name in schema.column_bindings for name in fieldnames):
        return
    names = {value: key for key, value in DELIMITERS.items()}
    name = names.get(delimiter, delimiter)
    raise MetadataInputError(
        f"{input_path}:1: no column matches the ItemType fields; the delimiter "
        f"may be wrong (used {name!r}); specify --delimiter comma or --delimiter tab"
    )


def _suggest_field(name: str, field_names: list[str]) -> str | None:
    folded = {field_name.casefold(): field_name for field_name in field_names}
    key = name.strip().casefold()
    if key in folded:
        return folded[key]
    matches = difflib.get_close_matches(key, list(folded), n=1)
    return folded[matches[0]] if matches else None


def check_columns(
    input_path: Path,
    fieldnames: list[str],
    schema: MetadataSchema,
    *,
    strict: bool = False,
    extra_known_columns: frozenset[str] = frozenset(),
) -> list[str]:
    field_names = list(schema.column_bindings)
    language_columns = {language_column(name) for name in schema.language_fields}
    present = set(fieldnames)
    # Suggest only fields the header lacks; a present field is not a typo target.
    candidates = [name for name in field_names if name not in present]
    unknown: list[str] = []
    for name in fieldnames:
        if (
            name in schema.column_bindings
            or name in language_columns
            or name in INVALID_ROWS_REPORT_COLUMNS
            or name in extra_known_columns  # e.g. --title-fallback sources
            or not name.strip()  # unnamed, e.g. a pandas index column
        ):
            continue
        suggestion = _suggest_field(name, candidates)
        hint = f" (did you mean {suggestion!r}?)" if suggestion else ""
        unknown.append(f"{name!r}{hint}")
    if unknown and strict:
        raise MetadataInputError(
            f"{input_path}:1: unknown column(s) not in the ItemType: "
            f"{', '.join(unknown)}"
        )
    warnings = [f"unknown column {column} will be ignored" for column in unknown]
    for field_name in field_names:
        if field_name not in present:
            required = "Required" in schema.field_attributes[field_name]
            suffix = " (Required)" if required else ""
            warnings.append(f"missing column {field_name!r}{suffix}")
    return [f"{input_path}:1: {warning}" for warning in warnings]


def check_languages(
    input_path: Path, fieldnames: list[str], schema: MetadataSchema
) -> list[str]:
    present = set(fieldnames)
    if schema.hidden_title_fields and not schema.title_fields:
        names = ", ".join(repr(name) for name in sorted(schema.hidden_title_fields))
        raise MetadataInputError(
            f"{input_path}:1: every title field ({names}) is hidden; WEKO ignores "
            f"hidden title fields, so every record will fail ({WEKO_TITLE_ERROR!r})"
        )

    language_fields = schema.language_fields
    missing = [
        field_name
        for field_name in language_fields
        if field_name not in schema.default_languages
        and language_column(field_name) not in present
    ]
    title_fields = sorted(schema.title_fields)
    if title_fields and all(
        field_name not in language_fields or field_name in missing
        for field_name in title_fields
    ):
        names = ", ".join(repr(name) for name in title_fields)
        raise MetadataInputError(
            f"{input_path}:1: no title field ({names}) has a language; WEKO would "
            f"reject every record ({WEKO_TITLE_ERROR!r}); set default_languages "
            "or add a '<field>_lang' column for one of them"
        )

    warnings: list[str] = []
    for field_name in missing:
        column = language_column(field_name)
        if field_name in present:
            warnings.append(
                f"{input_path}:1: field {field_name!r} has no language and its "
                f"language cells will be empty; set "
                f"default_languages[{field_name!r}] or add a {column!r} column"
            )
    return warnings


def format_row_errors(input_path: Path, errors: list[RowError]) -> str:
    lines = [
        f"{input_path}:{error.row_number}: {error.message}"
        for error in errors[:MAX_LISTED_ROW_ERRORS]
    ]
    remaining = len(errors) - len(lines)
    if remaining > 0:
        lines.append(f"... and {remaining} more")
    return "\n".join(lines)


def load_rows(
    input_path: Path,
    schema: MetadataSchema,
    date_like_fields: frozenset[str] = frozenset(),
    delimiter: str | None = None,
    *,
    strict_columns: bool = False,
    on_warning: Callable[[str], None] | None = None,
    title_fallback: TitleFallback | None = None,
    on_title_filled: Callable[[int, str], None] | None = None,
    date_timezone: tzinfo = DEFAULT_DATE_TZINFO,
) -> list[dict[str, Any]]:
    rows, errors = load_rows_with_errors(
        input_path,
        schema,
        date_like_fields,
        delimiter,
        strict_columns=strict_columns,
        on_warning=on_warning,
        title_fallback=title_fallback,
        on_title_filled=on_title_filled,
        date_timezone=date_timezone,
    )
    if errors:
        raise MetadataInputError(format_row_errors(input_path, errors))
    return rows


def load_rows_with_errors(
    input_path: Path,
    schema: MetadataSchema,
    date_like_fields: frozenset[str] = frozenset(),
    delimiter: str | None = None,
    *,
    strict_columns: bool = False,
    on_warning: Callable[[str], None] | None = None,
    title_fallback: TitleFallback | None = None,
    on_title_filled: Callable[[int, str], None] | None = None,
    date_timezone: tzinfo = DEFAULT_DATE_TZINFO,
) -> tuple[list[dict[str, Any]], list[RowError]]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file was not found: {input_path}")

    if delimiter is None:
        delimiter = detect_delimiter(input_path)
    previous_limit = csv.field_size_limit(INPUT_FIELD_SIZE_LIMIT)
    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
            reader = csv.DictReader(file_obj, delimiter=delimiter)
            try:
                if reader.fieldnames is not None:
                    validate_unique_columns(input_path, list(reader.fieldnames))
                    validate_header_matches_schema(
                        input_path, list(reader.fieldnames), schema, delimiter
                    )
                    warnings = check_columns(
                        input_path,
                        list(reader.fieldnames),
                        schema,
                        strict=strict_columns,
                        extra_known_columns=frozenset(
                            column for _, column in title_fallback.sources
                        )
                        if title_fallback is not None
                        else frozenset(),
                    )
                    warnings.extend(
                        check_languages(input_path, list(reader.fieldnames), schema)
                    )
                    if title_fallback is not None:
                        check_title_fallback_columns(
                            input_path, list(reader.fieldnames), title_fallback
                        )
                    if on_warning is not None:
                        for warning in warnings:
                            on_warning(warning)
                fieldnames = list(reader.fieldnames or [])
                rows: list[dict[str, Any]] = []
                errors: list[RowError] = []
                for row_number, row in enumerate(reader, start=2):
                    try:
                        source_row = row
                        filled = (
                            fill_missing_title(row, title_fallback)
                            if title_fallback is not None
                            else None
                        )
                        if filled is not None:
                            # Keep `row` untouched so invalid_rows.tsv shows the input.
                            source_row = {
                                **row,
                                title_fallback.field_name: repr([filled]),
                            }
                        rows.append(
                            normalize_row(
                                source_row, schema, date_like_fields, date_timezone
                            )
                        )
                        if filled is not None and on_title_filled is not None:
                            on_title_filled(row_number, filled)
                    except MetadataInputError as exc:
                        cells = {name: row.get(name) or "" for name in fieldnames}
                        errors.append(RowError(row_number, str(exc), cells))
            except csv.Error as exc:
                # DictReader.line_num is only updated after a successful row.
                line = reader.reader.line_num
                raise MetadataInputError(
                    f"{input_path}: line {line}: malformed input: {exc}"
                ) from exc
            return rows, errors
    finally:
        csv.field_size_limit(previous_limit)


def chunk_rows(
    rows: list[dict[str, Any]], chunk_size: int | None
) -> list[list[dict[str, Any]]]:
    if not chunk_size or chunk_size <= 0:
        return [rows]
    return [
        rows[index : index + chunk_size] for index in range(0, len(rows), chunk_size)
    ]


def compute_max_lengths(
    rows: list[dict[str, Any]], schema: MetadataSchema
) -> dict[str, int]:
    return {
        field_name: max((len(row[field_name]) for row in rows), default=0)
        for field_name in schema.column_bindings
        if field_name in schema.repeatable_fields
    }


def build_dynamic_columns(
    schema: MetadataSchema,
    max_lengths: dict[str, int],
) -> tuple[list[str], list[str], list[str]]:
    metadata_bindings = list(schema.base_metadata_bindings)
    display_columns = list(schema.base_display_columns)
    attribute_row = list(schema.base_column_attributes)

    for field_name, bindings in schema.column_bindings.items():
        displays = schema.display_columns[field_name]
        if len(displays) != len(bindings):
            raise ValueError(
                f"Field {field_name!r} has {len(bindings)} bindings but "
                f"{len(displays)} display columns"
            )
        field_attribute = schema.field_attributes[field_name]
        if field_name in schema.repeatable_fields:
            for index in range(max_lengths[field_name]):
                metadata_bindings.extend(item.format(index=index) for item in bindings)
                display_columns.extend(item.format(index=index) for item in displays)
                attribute_row.extend([field_attribute] * len(bindings))
            continue

        metadata_bindings.extend(bindings)
        display_columns.extend(displays)
        attribute_row.extend([field_attribute] * len(bindings))

    return metadata_bindings, display_columns, attribute_row


def build_value_row(
    row: dict[str, Any],
    max_lengths: dict[str, int],
    schema: MetadataSchema,
) -> list[str]:
    values = list(schema.base_column_values)

    for field_name, bindings in schema.column_bindings.items():
        field_value = row[field_name]
        if field_name in schema.repeatable_fields:
            languages = row.get(language_column(field_name)) or []
            for index in range(max_lengths[field_name]):
                for binding in bindings:
                    entries = (
                        languages if binding.endswith("_language") else field_value
                    )
                    values.append(entries[index] if index < len(entries) else "")
            continue

        language = ""
        if field_value:
            language = row.get(
                language_column(field_name),
                schema.default_languages.get(field_name, ""),
            )
        for binding in bindings:
            if binding.endswith("_language"):
                values.append(language)
            else:
                values.append(str(field_value))

    return values


def write_tsv(
    rows: list[dict[str, Any]],
    output_path: Path,
    schema: MetadataSchema,
) -> None:
    max_lengths = compute_max_lengths(rows, schema)
    metadata_bindings, display_columns, attribute_row = build_dynamic_columns(
        schema, max_lengths
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.writer(file_obj, delimiter="\t", lineterminator="\n")
        writer.writerow(["#ItemType", schema.item_type_name, schema.item_schema_url])
        writer.writerow(metadata_bindings)
        writer.writerow(display_columns)
        writer.writerow(["#"] + [""] * (len(display_columns) - 1))
        writer.writerow(attribute_row)
        for row in rows:
            writer.writerow(build_value_row(row, max_lengths, schema))


def write_invalid_rows_report(errors: list[RowError], output_path: Path) -> None:
    fieldnames = [
        name
        for name in (errors[0].cells if errors else [])
        if name not in INVALID_ROWS_REPORT_COLUMNS
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.writer(file_obj, delimiter="\t", lineterminator="\n")
        writer.writerow([*INVALID_ROWS_REPORT_COLUMNS, *fieldnames])
        for error in errors:
            writer.writerow(
                [
                    str(error.row_number),
                    error.message,
                    *(error.cells.get(name, "") for name in fieldnames),
                ]
            )


ZipDateTime = tuple[int, int, int, int, int, int]


def zip_date_time_from_timestamp(timestamp: int) -> ZipDateTime:
    minimum = int(datetime(*ZIP_MIN_DATE_TIME, tzinfo=timezone.utc).timestamp())
    maximum = int(datetime(*ZIP_MAX_DATE_TIME, tzinfo=timezone.utc).timestamp())
    seconds = min(max(timestamp, minimum), maximum)
    moment = datetime.fromtimestamp(seconds - seconds % 2, timezone.utc)
    return (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
    )


def zip_tsv(tsv_path: Path, zip_path: Path, date_time: ZipDateTime) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", ZIP_MEMBER_COMPRESS_TYPE) as archive:
        info = zipfile.ZipInfo(f"data/{tsv_path.name}", date_time)
        info.compress_type = ZIP_MEMBER_COMPRESS_TYPE
        info.create_system = ZIP_MEMBER_CREATE_SYSTEM
        info.external_attr = ZIP_MEMBER_EXTERNAL_ATTR
        archive.writestr(info, tsv_path.read_bytes())


def find_generated_artifacts(output_dir: Path) -> list[Path]:
    if not output_dir.is_dir():
        return []
    return sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and GENERATED_ARTIFACT_NAME_PATTERN.fullmatch(path.name)
    )


def find_unrelated_zip_files(output_dir: Path) -> list[Path]:
    if not output_dir.is_dir():
        return []
    return sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".zip"
        and not GENERATED_ARTIFACT_NAME_PATTERN.fullmatch(path.name)
    )


def _format_existing_artifacts_error(output_dir: Path, existing: list[Path]) -> str:
    names = [path.name for path in existing[:MAX_LISTED_EXISTING_ARTIFACTS]]
    listed = ", ".join(names)
    remaining = len(existing) - len(names)
    if remaining > 0:
        listed += f" ... and {remaining} more"
    return (
        f"Output directory already contains generated files: {output_dir} "
        f"({listed}). Move or register them first, or pass --overwrite "
        "to remove all of them before generating."
    )


def _is_same_file(path: Path, other: Path) -> bool:
    if path.exists() and other.exists():
        return os.path.samefile(path, other)
    return path.resolve() == other.resolve()


def generate_metadata_artifacts(
    config: MetadataGenerationConfig,
    *,
    on_remove: Callable[[Path], None] | None = None,
    on_invalid_rows: Callable[[Path, int], None] | None = None,
    on_warning: Callable[[str], None] | None = None,
    on_title_filled: Callable[[int, str], None] | None = None,
) -> list[GeneratedArtifact]:
    existing = find_generated_artifacts(config.output_dir)
    if existing and not config.overwrite:
        raise OutputExistsError(
            _format_existing_artifacts_error(config.output_dir, existing)
        )

    runtime = _build_metadata_runtime(config)
    schema = runtime.schema
    title_fallback = build_title_fallback(
        schema, config.title_fallbacks, config.title_fallback_prefix
    )
    filled_titles: list[tuple[int, str]] = []
    rows, errors = load_rows_with_errors(
        config.input_path,
        schema,
        runtime.date_like_fields,
        resolve_delimiter(config.delimiter),
        strict_columns=config.strict_columns,
        on_warning=on_warning,
        title_fallback=title_fallback,
        on_title_filled=lambda row, title: filled_titles.append((row, title)),
        date_timezone=runtime.date_timezone,
    )
    if errors and not config.skip_invalid_rows:
        raise MetadataInputError(format_row_errors(config.input_path, errors))
    if not rows and not errors:
        return []
    # Read before any output is written: the input may be an invalid_rows.tsv
    # in the output directory that gets replaced below.
    # Integer nanoseconds avoid float rounding pushing the time into the next slot.
    input_mtime = config.input_path.stat().st_mtime_ns // 1_000_000_000
    zip_date_time = zip_date_time_from_timestamp(input_mtime)

    removable = [
        path for path in existing if not _is_same_file(path, config.input_path)
    ]
    if not rows:
        # Without valid rows, keep previous import files and only replace the report.
        removable = [
            path for path in removable if path.name.lower() == INVALID_ROWS_REPORT_NAME
        ]
    for path in removable:
        path.unlink()
        if on_remove is not None:
            on_remove(path)

    if errors:
        report_path = config.output_dir / INVALID_ROWS_REPORT_NAME
        write_invalid_rows_report(errors, report_path)
        if on_invalid_rows is not None:
            on_invalid_rows(report_path, len(errors))
    if not rows:
        return []

    chunks = chunk_rows(rows, config.chunk_size)
    artifacts: list[GeneratedArtifact] = []
    width = max(3, len(str(len(chunks))))

    for chunk_index, chunk in enumerate(chunks, start=1):
        suffix = f"_{chunk_index:0{width}d}" if len(chunks) > 1 else ""
        tsv_path = config.output_dir / f"output_write{suffix}.tsv"
        write_tsv(chunk, tsv_path, schema)

        zip_path: Path | None = None
        artifact_tsv_path: Path | None = tsv_path
        if config.zip_outputs:
            zip_path = config.output_dir / f"import{suffix}.zip"
            zip_tsv(tsv_path, zip_path, zip_date_time)
            if not config.keep_tsv:
                tsv_path.unlink()
                artifact_tsv_path = None

        artifacts.append(
            GeneratedArtifact(
                chunk_index=chunk_index,
                row_count=len(chunk),
                tsv_path=artifact_tsv_path,
                zip_path=zip_path,
            )
        )

    # Report fills only after every TSV/ZIP has been written, so a later
    # I/O error never leaves "filled title" lines for files that do not exist.
    if on_title_filled is not None:
        for row_number, title in filled_titles:
            on_title_filled(row_number, title)
    return artifacts


def summarize_artifacts(artifacts: list[GeneratedArtifact]) -> str:
    if not artifacts:
        return "No rows were loaded from the source file."

    total_rows = sum(artifact.row_count for artifact in artifacts)
    total_chunks = len(artifacts)
    tsv_count = sum(1 for artifact in artifacts if artifact.tsv_path is not None)
    zip_count = sum(1 for artifact in artifacts if artifact.zip_path is not None)
    return (
        f"Generated {total_chunks} artifact(s) for {total_rows} row(s). "
        f"TSV files: {tsv_count}, ZIP files: {zip_count}."
    )
