from __future__ import annotations

import ast
import csv
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FIELD_ATTRIBUTES = {
    "Title": "Required, Allow Multiple",
    "Title_g": "",
    "corpusid": "",
    "URI": "",
    "Creator": "Allow Multiple",
    "Contributor": "Allow Multiple",
    "Contributor_g": "",
    "PublicationYear_g": "",
    "ResourceType": "",
    "Subject": "Allow Multiple",
    "Description": "Allow Multiple",
    "Description_g": "",
    "License_g": "",
}

ALL_FIELDS = list(FIELD_ATTRIBUTES.keys())
SINGLE_VALUE_FIELDS = [
    "Title",
    "Title_g",
    "corpusid",
    "URI",
    "Contributor_g",
    "PublicationYear_g",
    "ResourceType",
    "Description_g",
    "License_g",
]
MULTI_VALUE_FIELDS = ["Creator", "Contributor", "Subject", "Description"]

COLUMN_BINDINGS = {
    "Title": [
        ".metadata.item_30001_title0[0].subitem_title",
        ".metadata.item_30001_title0[0].subitem_title_language",
    ],
    "Title_g": [
        ".metadata.item_30001_alternative_title1.subitem_alternative_title",
        ".metadata.item_30001_alternative_title1.subitem_alternative_title_language",
    ],
    "corpusid": [".metadata.item_1748316538548"],
    "URI": [".metadata.item_1748316595513"],
    "Creator": ".metadata.item_1748316642067[{index}].interim",
    "Contributor": ".metadata.item_1748316663969[{index}].interim",
    "Contributor_g": [".metadata.item_1748317876851"],
    "PublicationYear_g": [".metadata.item_1748316953368"],
    "ResourceType": [".metadata.item_1748316686668"],
    "Subject": ".metadata.item_1748316693747[{index}].interim",
    "Description": ".metadata.item_1748316700636[{index}].interim",
    "Description_g": [".metadata.item_1748316707259"],
    "License_g": [".metadata.item_1748316717367"],
}

DISPLAY_COLUMNS = {
    "Title": ["Title[0].Title", "Title[0].Language"],
    "Title_g": ["Alternative Title.Alternative Title", "Alternative Title.Language"],
    "corpusid": ["corpusid"],
    "URI": ["URI"],
    "Creator": "Creator[{index}].None",
    "Contributor": "Contributor[{index}].None",
    "Contributor_g": ["Contributor_g"],
    "PublicationYear_g": ["PublicationYear_g"],
    "ResourceType": ["ResourceType"],
    "Subject": "Subject[{index}].None",
    "Description": "Description[{index}].None",
    "Description_g": ["Description_g"],
    "License_g": ["License_g"],
}

DEFAULT_SCHEMA_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "metadata_schema_40001.json"


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
class MetadataGenerationConfig:
    input_path: Path
    output_dir: Path
    index_id: str | None = None
    index_name: str | None = None
    publish_date: str | None = None
    publish_status: str | None = None
    chunk_size: int | None = None
    zip_outputs: bool = False
    keep_tsv: bool = True
    schema_config_path: Path | None = DEFAULT_SCHEMA_CONFIG_PATH


@dataclass(frozen=True)
class GeneratedArtifact:
    chunk_index: int
    row_count: int
    tsv_path: Path | None
    zip_path: Path | None = None


def load_metadata_schema(schema_config_path: Path) -> MetadataSchema:
    if not schema_config_path.exists():
        raise FileNotFoundError(f"Metadata schema config was not found: {schema_config_path}")

    with schema_config_path.open("r", encoding="utf-8") as file_obj:
        raw = json.load(file_obj)

    return MetadataSchema(
        item_type_name=raw["item_type_name"],
        item_schema_url=raw["item_schema_url"],
        base_metadata_bindings=list(raw["base_metadata_bindings"]),
        template_column_values=dict(raw["template_column_values"]),
        template_column_attributes=dict(raw["template_column_attributes"]),
        column_bindings=dict(raw["column_bindings"]),
        default_languages=dict(raw.get("default_languages", {})),
        field_attributes=dict(raw.get("field_attributes", FIELD_ATTRIBUTES)),
        display_columns=dict(raw.get("display_columns", DISPLAY_COLUMNS)),
    )


def build_runtime_template_values(config: MetadataGenerationConfig, schema: MetadataSchema) -> dict[str, str]:
    values = dict(schema.template_column_values)
    if config.index_id is not None:
        values[".IndexID[0]"] = config.index_id
    if config.index_name is not None:
        values[".POS_INDEX[0]"] = config.index_name
    if config.publish_status is not None:
        values[".PUBLISH_STATUS"] = config.publish_status
    if config.publish_date is not None:
        values["PubDate"] = config.publish_date
    return values


def process_date(date_str: str) -> str:
    return date_str.split("T", 1)[0]


def detect_delimiter(path: Path) -> str:
    return "	" if path.suffix.lower() == ".tsv" else ","


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


def normalize_row(source_row: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {field: "" for field in ALL_FIELDS}

    for field in MULTI_VALUE_FIELDS:
        normalized[field] = parse_literal_list(source_row.get(field, ""))

    title_values = parse_literal_list(source_row.get("Title", ""))
    normalized["Title"] = title_values[0] if title_values else "NoTitle"

    for field in SINGLE_VALUE_FIELDS:
        if field == "Title":
            continue
        value = source_row.get(field, "")
        normalized[field] = "" if value is None else str(value)

    if normalized["PublicationYear_g"]:
        normalized["PublicationYear_g"] = process_date(normalized["PublicationYear_g"])

    return normalized


def load_rows(input_path: Path) -> list[dict[str, Any]]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file was not found: {input_path}")

    delimiter = detect_delimiter(input_path)
    with input_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj, delimiter=delimiter)
        return [normalize_row(row) for row in reader]


def chunk_rows(rows: list[dict[str, Any]], chunk_size: int | None) -> list[list[dict[str, Any]]]:
    if not chunk_size or chunk_size <= 0:
        return [rows]
    return [rows[index : index + chunk_size] for index in range(0, len(rows), chunk_size)]


def compute_max_lengths(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {field: max((len(row[field]) for row in rows), default=0) for field in MULTI_VALUE_FIELDS}


def build_dynamic_columns(
    schema: MetadataSchema,
    template_column_values: dict[str, str],
    max_lengths: dict[str, int],
) -> tuple[list[str], list[str], list[str]]:
    metadata_bindings = list(schema.base_metadata_bindings)
    display_columns = list(template_column_values.keys())
    attribute_row = list(schema.template_column_attributes.values())

    for field in ALL_FIELDS:
        binding = schema.column_bindings[field]
        display = schema.display_columns[field]
        field_attribute = schema.field_attributes[field]

        if field in ("Title", "Title_g"):
            metadata_bindings.extend(binding)
            display_columns.extend(display)
            attribute_row.extend([field_attribute, field_attribute])
            continue

        if field in SINGLE_VALUE_FIELDS:
            metadata_bindings.extend(binding)
            display_columns.extend(display)
            attribute_row.append(field_attribute)
            continue

        for index in range(max_lengths[field]):
            metadata_bindings.append(binding.format(index=index))
            display_columns.append(display.format(index=index))
            attribute_row.append(field_attribute)

    return metadata_bindings, display_columns, attribute_row


def build_value_row(
    row: dict[str, Any],
    max_lengths: dict[str, int],
    schema: MetadataSchema,
    template_column_values: dict[str, str],
) -> list[str]:
    values = list(template_column_values.values())

    for field in ALL_FIELDS:
        if field == "Title":
            values.extend([row["Title"], schema.default_languages.get("Title", "en")])
            continue

        if field == "Title_g":
            values.extend([row["Title_g"], schema.default_languages.get("Title_g", "en")])
            continue

        if field in SINGLE_VALUE_FIELDS:
            values.append(str(row[field]))
            continue

        entries = row[field]
        for index in range(max_lengths[field]):
            values.append(entries[index] if index < len(entries) else "")

    return values


def write_tsv(
    rows: list[dict[str, Any]],
    output_path: Path,
    config: MetadataGenerationConfig,
    schema: MetadataSchema,
) -> None:
    max_lengths = compute_max_lengths(rows)
    template_column_values = build_runtime_template_values(config, schema)
    metadata_bindings, display_columns, attribute_row = build_dynamic_columns(schema, template_column_values, max_lengths)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # WEKO import expects UTF-8 TSVs with a BOM, matching the exported template format.
    with output_path.open("w", encoding="utf-8-sig", newline="") as file_obj:
        writer = csv.writer(file_obj, delimiter="\t", lineterminator="\n")
        writer.writerow(["#ItemType", schema.item_type_name, schema.item_schema_url])
        writer.writerow(metadata_bindings)
        writer.writerow(display_columns)
        writer.writerow(["#"] + [""] * (len(display_columns) - 1))
        writer.writerow(attribute_row)
        for row in rows:
            writer.writerow(build_value_row(row, max_lengths, schema, template_column_values))


def zip_tsv(tsv_path: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(tsv_path, Path("data") / tsv_path.name)


def generate_metadata_artifacts(config: MetadataGenerationConfig) -> list[GeneratedArtifact]:
    schema = load_metadata_schema(config.schema_config_path or DEFAULT_SCHEMA_CONFIG_PATH)
    rows = load_rows(config.input_path)
    if not rows:
        return []

    chunks = chunk_rows(rows, config.chunk_size)
    artifacts: list[GeneratedArtifact] = []
    width = max(3, len(str(len(chunks))))

    for chunk_index, chunk in enumerate(chunks, start=1):
        suffix = f"_{chunk_index:0{width}d}" if len(chunks) > 1 else ""
        tsv_path = config.output_dir / f"output_write{suffix}.tsv"
        write_tsv(chunk, tsv_path, config, schema)

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
