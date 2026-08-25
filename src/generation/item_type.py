from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ItemTypeExportError(ValueError):
    """Raised when a WEKO ItemType export cannot define metadata fields."""


def format_weko_attributes(*, hidden: bool, required: bool, multiple: bool) -> str:
    attributes: list[str] = []
    if hidden:
        attributes.append("Hide")
    if required:
        attributes.append("Required")
    if multiple:
        attributes.append("Allow Multiple")
    return ", ".join(attributes)


@dataclass(frozen=True)
class ItemTypeValue:
    key: str | None
    title: str
    language: bool = False


@dataclass(frozen=True)
class ItemTypeField:
    key: str
    name: str
    shape: str
    values: tuple[ItemTypeValue, ...]
    required: bool
    hidden: bool
    multiple: bool
    date_like: bool

    @property
    def dynamically_repeatable(self) -> bool:
        return self.shape == "array" and len(self.values) == 1

    @property
    def binding_templates(self) -> tuple[str, ...]:
        if self.shape == "string":
            return (f".metadata.{self.key}",)

        if self.shape == "array":
            index = "{index}" if self.dynamically_repeatable else "0"
            prefix = f".metadata.{self.key}[{index}]"
        else:
            prefix = f".metadata.{self.key}"
        return tuple(f"{prefix}.{value.key}" for value in self.values)

    @property
    def display_templates(self) -> tuple[str, ...]:
        if self.shape == "string":
            return (self.name,)

        if self.shape == "array":
            index = "{index}" if self.dynamically_repeatable else "0"
            prefix = f"{self.name}[{index}]"
        else:
            prefix = self.name
        return tuple(f"{prefix}.{value.title}" for value in self.values)

    @property
    def attribute(self) -> str:
        return format_weko_attributes(
            hidden=self.hidden,
            required=self.required,
            multiple=self.multiple,
        )


@dataclass(frozen=True)
class ItemTypeDefinition:
    id: int
    name: str
    fields: tuple[ItemTypeField, ...]
    fixed_fields: tuple[ItemTypeField, ...] = ()

    @property
    def display_name(self) -> str:
        return f"{self.name}({self.id})"


def _read_json_member(archive: zipfile.ZipFile, member_name: str) -> dict[str, Any]:
    matching_names = [
        name for name in archive.namelist() if Path(name).name == member_name
    ]
    if not matching_names:
        raise ItemTypeExportError(f"{member_name} is missing from the ItemType export")
    if len(matching_names) > 1:
        raise ItemTypeExportError(
            f"The ItemType export contains multiple {member_name} files"
        )

    try:
        raw = json.loads(archive.read(matching_names[0]))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ItemTypeExportError(f"{member_name} is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise ItemTypeExportError(f"{member_name} must contain a JSON object")
    return raw


def _object_values(properties: Any, field_name: str) -> tuple[ItemTypeValue, ...]:
    if not isinstance(properties, dict) or not properties:
        raise ItemTypeExportError(f"Field {field_name!r} has no value properties")

    values: list[ItemTypeValue] = []
    for key, definition in properties.items():
        if not isinstance(definition, dict):
            raise ItemTypeExportError(
                f"Value {key!r} in field {field_name!r} is not an object"
            )
        title = definition.get("title") or "None"
        values.append(
            ItemTypeValue(
                key=key,
                title=str(title),
                language=key.endswith("_language"),
            )
        )

    non_language_count = sum(not value.language for value in values)
    if non_language_count != 1:
        raise ItemTypeExportError(
            f"Field {field_name!r} must have exactly one non-language value; "
            f"found {non_language_count}"
        )
    return tuple(values)


def _build_field(
    key: str,
    definition: dict[str, Any],
    render_definition: dict[str, Any],
    schema_required: set[str],
) -> ItemTypeField:
    name = definition.get("title")
    if not isinstance(name, str) or not name:
        raise ItemTypeExportError(f"Field {key!r} has no schema title")

    shape = definition.get("type")
    if shape == "string":
        values = (ItemTypeValue(key=None, title=name),)
    elif shape == "object":
        values = _object_values(definition.get("properties"), name)
    elif shape == "array":
        items = definition.get("items")
        if not isinstance(items, dict):
            raise ItemTypeExportError(f"Array field {name!r} has no item definition")
        values = _object_values(items.get("properties"), name)
    else:
        raise ItemTypeExportError(
            f"Field {name!r} uses unsupported schema type {shape!r}"
        )

    options = render_definition.get("option", {})
    if not isinstance(options, dict):
        raise ItemTypeExportError(f"Field {key!r} has invalid render options")

    return ItemTypeField(
        key=key,
        name=name,
        shape=shape,
        values=values,
        required=bool(options.get("required")) or key in schema_required,
        hidden=bool(options.get("hidden")),
        multiple=bool(options.get("multiple")) or shape == "array",
        date_like=render_definition.get("input_type") == "datetime"
        or definition.get("format") == "datetime",
    )


def load_item_type_export(export_path: Path) -> ItemTypeDefinition:
    if not export_path.exists():
        raise FileNotFoundError(f"ItemType export was not found: {export_path}")

    try:
        with zipfile.ZipFile(export_path) as archive:
            item_type = _read_json_member(archive, "ItemType.json")
            item_type_name = _read_json_member(archive, "ItemTypeName.json")
    except zipfile.BadZipFile as exc:
        raise ItemTypeExportError(
            f"ItemType export is not a valid ZIP file: {export_path}"
        ) from exc

    item_type_id = item_type.get("id")
    name = item_type_name.get("name")
    if not isinstance(item_type_id, int):
        raise ItemTypeExportError("ItemType.json must contain an integer id")
    if not isinstance(name, str) or not name:
        raise ItemTypeExportError("ItemTypeName.json must contain a non-empty name")
    if item_type_name.get("id") != item_type_id:
        raise ItemTypeExportError(
            "ItemType.json and ItemTypeName.json contain different ids"
        )

    schema = item_type.get("schema")
    render = item_type.get("render")
    if not isinstance(schema, dict) or not isinstance(render, dict):
        raise ItemTypeExportError(
            "ItemType.json must contain schema and render objects"
        )
    properties = schema.get("properties")
    field_order = render.get("table_row")
    metadata = render.get("meta_list")
    fixed_metadata = render.get("meta_fix")
    if not isinstance(properties, dict):
        raise ItemTypeExportError("ItemType.json schema.properties must be an object")
    if not isinstance(field_order, list):
        raise ItemTypeExportError("ItemType.json render.table_row must be an array")
    if not isinstance(metadata, dict):
        raise ItemTypeExportError("ItemType.json render.meta_list must be an object")
    if not isinstance(fixed_metadata, dict):
        raise ItemTypeExportError("ItemType.json render.meta_fix must be an object")

    raw_required = schema.get("required", [])
    if not isinstance(raw_required, list) or not all(
        isinstance(key, str) for key in raw_required
    ):
        raise ItemTypeExportError("ItemType.json schema.required must be an array")
    schema_required = set(raw_required)
    fields: list[ItemTypeField] = []
    field_names: set[str] = set()
    for key in field_order:
        definition = properties.get(key)
        metadata_definition = metadata.get(key)
        if not isinstance(definition, dict) or not isinstance(
            metadata_definition, dict
        ):
            raise ItemTypeExportError(
                f"Field {key!r} is missing from schema.properties or render.meta_list"
            )
        field = _build_field(key, definition, metadata_definition, schema_required)
        if field.name in field_names:
            raise ItemTypeExportError(
                f"Multiple exported fields use source name {field.name!r}"
            )
        field_names.add(field.name)
        fields.append(field)

    fixed_fields: list[ItemTypeField] = []
    for key, metadata_definition in fixed_metadata.items():
        definition = properties.get(key)
        if not isinstance(definition, dict) or not isinstance(
            metadata_definition, dict
        ):
            raise ItemTypeExportError(
                f"Fixed field {key!r} is missing from schema.properties or render.meta_fix"
            )
        fixed_fields.append(
            _build_field(key, definition, metadata_definition, schema_required)
        )

    return ItemTypeDefinition(
        id=item_type_id,
        name=name,
        fields=tuple(fields),
        fixed_fields=tuple(fixed_fields),
    )
