# /// script
# requires-python = ">=3.13"
# ///
#
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from generation.metadata_pipeline import DISPLAY_COLUMNS, FIELD_ATTRIBUTES

FIELD_ORDER = list(FIELD_ATTRIBUTES.keys())
MULTI_VALUE_FIELDS = {"Creator", "Contributor", "Subject", "Description"}
BASE_TEMPLATE_DEFAULTS = {
    "#ID": "",
    "URI": "",
    ".IndexID[0]": "",
    ".POS_INDEX[0]": "",
    ".PUBLISH_STATUS": "public",
    ".FEEDBACK_MAIL[0]": "",
    ".RESEARCHMAP_LINKAGE": "",
    ".RESEAECHMAP_LINKAGE": "",
    ".CNRI": "",
    ".DOI_RA": "",
    ".DOI": "",
    "Keep/Upgrade Version": "keep",
    "PubDate": "",
}
BASE_DISPLAY_COLUMNS = set(BASE_TEMPLATE_DEFAULTS.keys())
READ_FROM_TEMPLATE_BASE_COLUMNS = {
    ".IndexID[0]",
    ".POS_INDEX[0]",
    ".PUBLISH_STATUS",
}
FORCED_BASE_TEMPLATE_VALUES = {
    "#ID": "",
    "URI": "",
    ".FEEDBACK_MAIL[0]": "",
    ".CNRI": "",
    ".DOI_RA": "",
    ".DOI": "",
    "PubDate": "2025-05-27",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create metadata schema JSON from a WEKO template TSV.")
    parser.add_argument("--template", type=Path, required=True, help="Source template TSV file.")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON file path.")
    return parser


def load_template_rows(template_path: Path) -> list[list[str]]:
    with template_path.open("r", encoding="utf-8-sig", newline="") as file_obj:
        rows = list(csv.reader(file_obj, delimiter="\t"))
    if len(rows) < 5:
        raise ValueError("Template TSV must contain at least 5 rows.")
    return rows


def classify_field(display_name: str, binding: str) -> str:
    normalized = display_name.strip()
    if normalized == "corpusid":
        return "corpusid"
    if normalized == "URI" and binding != ".uri":
        return "URI"
    if normalized.startswith("Title[0]."):
        return "Title"
    if normalized.startswith("Alternative Title.") or normalized.startswith("Title_g."):
        return "Title_g"
    if re.fullmatch(r"Creator\[\d+\]\.None", normalized):
        return "Creator"
    if re.fullmatch(r"Contributor\[\d+\]\.None", normalized):
        return "Contributor"
    if normalized == "Contributor_g":
        return "Contributor_g"
    if normalized == "PublicationYear_g":
        return "PublicationYear_g"
    if normalized == "ResourceType":
        return "ResourceType"
    if re.fullmatch(r"Subject\[\d+\]\.None", normalized):
        return "Subject"
    if re.fullmatch(r"Description\[\d+\]\.None", normalized):
        return "Description"
    if normalized == "Description_g":
        return "Description_g"
    if normalized == "License_g":
        return "License_g"
    raise ValueError(f"Unsupported template column: display={display_name!r}, binding={binding!r}")


def normalize_multi_value_pattern(value: str) -> str:
    return re.sub(r"\[\d+\]", "[{index}]", value)


def collect_base_columns(
    bindings: list[str],
    display_columns: list[str],
    attribute_row: list[str],
    first_data_row: list[str] | None,
) -> tuple[dict[str, str], dict[str, str], list[str], int]:
    template_column_values: dict[str, str] = {}
    template_column_attributes: dict[str, str] = {}
    base_metadata_bindings: list[str] = []
    base_count = 0

    for index, (binding, display_name, attribute) in enumerate(zip(bindings, display_columns, attribute_row)):
        if display_name.strip() not in BASE_DISPLAY_COLUMNS:
            break
        base_metadata_bindings.append(binding)
        if display_name in READ_FROM_TEMPLATE_BASE_COLUMNS and first_data_row and index < len(first_data_row):
            template_value = first_data_row[index]
        elif display_name in FORCED_BASE_TEMPLATE_VALUES:
            template_value = FORCED_BASE_TEMPLATE_VALUES[display_name]
        else:
            template_value = BASE_TEMPLATE_DEFAULTS.get(display_name, "")
        template_column_values[display_name] = template_value
        template_column_attributes[display_name] = attribute
        base_count += 1

    return template_column_values, template_column_attributes, base_metadata_bindings, base_count


def collect_field_mappings(
    bindings: list[str],
    display_columns: list[str],
    attribute_row: list[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    column_bindings: dict[str, Any] = {}
    generated_display_columns: dict[str, Any] = {}
    generated_field_attributes: dict[str, str] = {}

    for binding, display_name, attribute in zip(bindings, display_columns, attribute_row):
        field_name = classify_field(display_name, binding)
        if field_name in MULTI_VALUE_FIELDS:
            normalized_binding = normalize_multi_value_pattern(binding)
            normalized_display = normalize_multi_value_pattern(display_name)
            column_bindings.setdefault(field_name, normalized_binding)
            generated_display_columns.setdefault(field_name, normalized_display)
        elif field_name in ("Title", "Title_g"):
            column_bindings.setdefault(field_name, []).append(binding)
            generated_display_columns.setdefault(field_name, []).append(display_name)
        else:
            column_bindings[field_name] = [binding]
            generated_display_columns[field_name] = [display_name]
        if field_name not in generated_field_attributes:
            generated_field_attributes[field_name] = attribute

    missing_fields = [field_name for field_name in FIELD_ORDER if field_name not in column_bindings]
    if missing_fields:
        raise ValueError(f"Template is missing required fields: {', '.join(missing_fields)}")

    ordered_bindings = {field_name: column_bindings[field_name] for field_name in FIELD_ORDER}
    ordered_displays = {field_name: generated_display_columns[field_name] for field_name in FIELD_ORDER}
    ordered_attributes = {field_name: generated_field_attributes[field_name] for field_name in FIELD_ORDER}
    return ordered_bindings, ordered_displays, ordered_attributes


def build_default_languages(bindings: list[str], first_data_row: list[str] | None) -> dict[str, str]:
    if not first_data_row:
        return {}

    binding_to_value = {binding: first_data_row[index] for index, binding in enumerate(bindings) if index < len(first_data_row)}
    default_languages: dict[str, str] = {}
    title_lang = binding_to_value.get(".metadata.item_30001_title0[0].subitem_title_language", "").strip()
    title_g_lang = binding_to_value.get(".metadata.item_30001_alternative_title1.subitem_alternative_title_language", "").strip()
    if title_lang:
        default_languages["Title"] = title_lang
    if title_g_lang:
        default_languages["Title_g"] = title_g_lang
    return default_languages


def create_schema_from_template(template_path: Path) -> dict[str, Any]:
    rows = load_template_rows(template_path)
    item_row, bindings, display_columns, _, attribute_row = rows[:5]
    first_data_row = rows[5] if len(rows) > 5 else None

    template_column_values, template_column_attributes, base_metadata_bindings, base_count = collect_base_columns(
        bindings,
        display_columns,
        attribute_row,
        first_data_row,
    )
    field_bindings, generated_display_columns, generated_field_attributes = collect_field_mappings(
        bindings[base_count:],
        display_columns[base_count:],
        attribute_row[base_count:],
    )

    return {
        "item_type_name": item_row[1],
        "item_schema_url": item_row[2],
        "base_metadata_bindings": base_metadata_bindings,
        "template_column_values": template_column_values,
        "template_column_attributes": template_column_attributes,
        "column_bindings": field_bindings,
        "display_columns": generated_display_columns,
        "field_attributes": generated_field_attributes,
        "default_languages": build_default_languages(bindings, first_data_row),
    }


def main() -> int:
    args = build_parser().parse_args()
    schema = create_schema_from_template(args.template)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as file_obj:
        json.dump(schema, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
