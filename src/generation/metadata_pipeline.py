from __future__ import annotations

import ast
import csv
import zipfile
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

from .item_type import (
    ItemTypeField,
    format_weko_attributes,
    load_item_type_export,
)
from .registration_config import load_registration_settings

DEFAULT_REGISTRATION_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "metadata_registration.json"
)


class ControlValueSource(Enum):
    EMPTY = auto()
    INDEX_ID = auto()
    INDEX_NAME = auto()
    PUBLIC = auto()
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
        ControlValueSource.PUBLIC,
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


class MetadataInputError(ValueError):
    """Raised when source metadata cannot satisfy the exported ItemType."""


@dataclass(frozen=True)
class MetadataSchema:
    item_type_name: str
    item_schema_url: str
    base_metadata_bindings: list[str]
    template_column_values: dict[str, str]
    template_column_attributes: dict[str, str]
    column_bindings: dict[str, list[str] | str]
    default_languages: dict[str, str]
    field_attributes: dict[str, str]
    display_columns: dict[str, list[str] | str]


@dataclass(frozen=True)
class _MetadataRuntime:
    schema: MetadataSchema
    date_like_fields: frozenset[str]


@dataclass(frozen=True)
class MetadataGenerationConfig:
    input_path: Path
    output_dir: Path
    index_name: str | None = None
    publish_date: str | None = None
    chunk_size: int | None = None
    zip_outputs: bool = False
    keep_tsv: bool = True
    registration_config_path: Path = DEFAULT_REGISTRATION_CONFIG_PATH


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
    publish_date = config.publish_date or settings.publish_date

    base_metadata_bindings = [column.binding for column in WEKO_IMPORT_CONTROL_COLUMNS]
    template_column_values = {
        column.display_name: resolve_control_value(
            column.value_source, index_id=index_id, index_name=index_name
        )
        for column in WEKO_IMPORT_CONTROL_COLUMNS
    }
    template_column_attributes = {
        column.display_name: column.attribute for column in WEKO_IMPORT_CONTROL_COLUMNS
    }
    for field in item_type.fixed_fields:
        base_metadata_bindings.extend(field.binding_templates)
        template_column_values[field.name] = resolve_fixed_field_value(
            field, publish_date=publish_date
        )
        template_column_attributes[field.name] = field.attribute

    column_bindings: dict[str, list[str] | str] = {}
    display_columns: dict[str, list[str] | str] = {}
    for field in item_type.fields:
        if field.dynamically_repeatable:
            column_bindings[field.name] = field.binding_templates[0]
            display_columns[field.name] = field.display_templates[0]
        else:
            column_bindings[field.name] = list(field.binding_templates)
            display_columns[field.name] = list(field.display_templates)

    schema = MetadataSchema(
        item_type_name=item_type.display_name,
        item_schema_url=f"{settings.weko_base_url}/items/jsonschema/{item_type.id}",
        base_metadata_bindings=base_metadata_bindings,
        template_column_values=template_column_values,
        template_column_attributes=template_column_attributes,
        column_bindings=column_bindings,
        default_languages=dict(settings.default_languages),
        field_attributes={field.name: field.attribute for field in item_type.fields},
        display_columns=display_columns,
    )
    return _MetadataRuntime(
        schema=schema,
        date_like_fields=frozenset(
            field.name for field in item_type.fields if field.date_like
        ),
    )


def load_metadata_schema(config: MetadataGenerationConfig) -> MetadataSchema:
    return _build_metadata_runtime(config).schema


def resolve_control_value(
    source: ControlValueSource, *, index_id: str, index_name: str
) -> str:
    if source is ControlValueSource.INDEX_ID:
        return index_id
    if source is ControlValueSource.INDEX_NAME:
        return index_name
    if source is ControlValueSource.PUBLIC:
        return "public"
    if source is ControlValueSource.KEEP:
        return "keep"
    return ""


def resolve_fixed_field_value(field: ItemTypeField, *, publish_date: str) -> str:
    if field.key == "pubdate":
        return publish_date
    if field.required:
        raise MetadataInputError(
            f"Required fixed ItemType field {field.name!r} has no configured value"
        )
    return ""


def process_date(date_str: str) -> str:
    return date_str.split("T", 1)[0]


def detect_delimiter(path: Path) -> str:
    return "\t" if path.suffix.lower() == ".tsv" else ","


def parse_literal_list(raw_value: Any) -> list[str]:
    if raw_value in (None, ""):
        return []
    if isinstance(raw_value, list):
        return [str(value) for value in raw_value]

    text = str(raw_value).strip()
    if not text:
        return []

    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return [text]

    if isinstance(parsed, list):
        return ["" if value is None else str(value) for value in parsed]
    if parsed in (None, ""):
        return []
    return [str(parsed)]


def normalize_row(
    source_row: dict[str, Any],
    schema: MetadataSchema,
    date_like_fields: frozenset[str] = frozenset(),
) -> dict[str, str | list[str]]:
    normalized: dict[str, str | list[str]] = {}
    for field_name, binding in schema.column_bindings.items():
        values = parse_literal_list(source_row.get(field_name, ""))
        if "Required" in schema.field_attributes[field_name] and not values:
            raise MetadataInputError(f"Required metadata field {field_name!r} is empty")
        if isinstance(binding, str):
            if field_name in date_like_fields:
                values = [process_date(value) for value in values]
            normalized[field_name] = values
            continue

        value = values[0] if values else ""
        if field_name in date_like_fields and value:
            value = process_date(value)
        normalized[field_name] = value
    return normalized


def load_rows(
    input_path: Path,
    schema: MetadataSchema,
    date_like_fields: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file was not found: {input_path}")

    delimiter = detect_delimiter(input_path)
    with input_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj, delimiter=delimiter)
        rows: list[dict[str, Any]] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                rows.append(normalize_row(row, schema, date_like_fields))
            except MetadataInputError as exc:
                raise MetadataInputError(f"{input_path}:{row_number}: {exc}") from exc
        return rows


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
        for field_name, binding in schema.column_bindings.items()
        if isinstance(binding, str)
    }


def build_dynamic_columns(
    schema: MetadataSchema,
    max_lengths: dict[str, int],
) -> tuple[list[str], list[str], list[str]]:
    metadata_bindings = list(schema.base_metadata_bindings)
    display_columns = list(schema.template_column_values)
    attribute_row = list(schema.template_column_attributes.values())

    for field_name, binding in schema.column_bindings.items():
        display = schema.display_columns[field_name]
        field_attribute = schema.field_attributes[field_name]
        if isinstance(binding, str):
            if not isinstance(display, str):
                raise TypeError(
                    f"Display template for repeatable field {field_name!r} must be a string"
                )
            for index in range(max_lengths[field_name]):
                metadata_bindings.append(binding.format(index=index))
                display_columns.append(display.format(index=index))
                attribute_row.append(field_attribute)
            continue

        if not isinstance(display, list):
            raise TypeError(f"Display columns for field {field_name!r} must be a list")
        metadata_bindings.extend(binding)
        display_columns.extend(display)
        attribute_row.extend([field_attribute] * len(binding))

    return metadata_bindings, display_columns, attribute_row


def build_value_row(
    row: dict[str, Any],
    max_lengths: dict[str, int],
    schema: MetadataSchema,
) -> list[str]:
    values = list(schema.template_column_values.values())

    for field_name, binding in schema.column_bindings.items():
        field_value = row[field_name]
        if isinstance(binding, str):
            entries = field_value
            values.extend(
                entries[index] if index < len(entries) else ""
                for index in range(max_lengths[field_name])
            )
            continue

        for column_binding in binding:
            if column_binding.endswith("_language"):
                values.append(
                    schema.default_languages.get(field_name, "") if field_value else ""
                )
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


def zip_tsv(tsv_path: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(tsv_path, Path("data") / tsv_path.name)


def generate_metadata_artifacts(
    config: MetadataGenerationConfig,
) -> list[GeneratedArtifact]:
    runtime = _build_metadata_runtime(config)
    schema = runtime.schema
    rows = load_rows(config.input_path, schema, runtime.date_like_fields)
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
            zip_tsv(tsv_path, zip_path)
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
