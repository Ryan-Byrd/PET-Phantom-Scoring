"""
Apply explicit JSON metadata corrections to in-memory DICOM datasets.

Purpose
-------
PET quantification tools use this module to correct DICOM metadata for a
single analysis run without altering the original DICOM files. Corrections
are addressed by DICOM keyword, numeric tag, or a sequence-item path.

Override document
-----------------
The JSON document must contain a ``dicom_overrides`` object. Each key is a
DICOM path and its value is either the replacement value or an object with a
required ``value`` member and optional ``vr``, ``units``, and ``reason``
members. Paths support these forms:

* ``PatientWeight``
* ``(0010,1030)``
* ``RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose``
* ``RadiopharmaceuticalInformationSequence[0].(0054,1016)``

Math Notes
----------
This module does not perform SUV calculations. It supplies corrected metadata
to the existing quantification functions, which calculate
$SUV = C M / A_{ref}$, where activity concentration $C$ is in Bq/mL, mass
normalization $M$ is in grams, and reference activity $A_{ref}$ is in Bq.
Consequently, values must use the native units and DICOM value representation
of the tag being overridden, for example kg for PatientWeight and Bq for
RadionuclideTotalDose.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydicom.datadict import dictionary_VR, tag_for_keyword
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.tag import BaseTag, Tag

_TAG_PATTERN = re.compile(r"^\((?:0x)?([0-9A-Fa-f]{4}),(?:0x)?([0-9A-Fa-f]{4})\)$")
_SEQUENCE_SEGMENT_PATTERN = re.compile(r"^(.+)\[([0-9]+)\]$")


class MetadataOverrideError(ValueError):
    """Raised when an override document cannot be safely applied."""


@dataclass(frozen=True)
class MetadataOverrides:
    """Validated generic DICOM metadata corrections loaded from JSON."""

    source_path: str
    description: str | None
    reason: str | None
    overrides: dict[str, Any]


def load_metadata_overrides(path: str) -> MetadataOverrides:
    """Load and validate an override document without changing any DICOM data."""
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise MetadataOverrideError(f"Metadata override file not found: {source_path}")

    try:
        with source_path.open("r", encoding="utf-8") as source_file:
            document = json.load(source_file)
    except json.JSONDecodeError as error:
        raise MetadataOverrideError(
            f"Metadata override JSON is invalid: {error.msg} (line {error.lineno})"
        ) from error

    if not isinstance(document, dict):
        raise MetadataOverrideError("Metadata override JSON must contain an object.")

    overrides = document.get("dicom_overrides")
    if not isinstance(overrides, dict) or not overrides:
        raise MetadataOverrideError(
            "Metadata override JSON must contain a non-empty 'dicom_overrides' object."
        )

    for path_key, specification in overrides.items():
        if not isinstance(path_key, str) or not path_key.strip():
            raise MetadataOverrideError("Each override path must be a non-empty string.")
        if isinstance(specification, dict) and "value" not in specification:
            raise MetadataOverrideError(
                f"Override '{path_key}' is an object but has no required 'value' member."
            )

    return MetadataOverrides(
        source_path=str(source_path),
        description=_optional_string(document.get("description")),
        reason=_optional_string(document.get("reason")),
        overrides=overrides,
    )


def apply_metadata_overrides(
    dataset: Dataset,
    metadata_overrides: MetadataOverrides,
) -> tuple[Dataset, list[dict[str, Any]]]:
    """Return a deep-copied dataset with generic corrections and audit records."""
    corrected_dataset = copy.deepcopy(dataset)
    audit_records = []

    for path, specification in metadata_overrides.overrides.items():
        value, declared_vr, units, reason = _unpack_specification(specification)
        parent, field_identifier = _resolve_parent_dataset(corrected_dataset, path)
        tag = _resolve_tag(field_identifier)
        existing_element = parent.get(tag)
        vr = declared_vr or (existing_element.VR if existing_element is not None else _lookup_vr(tag))

        if not vr:
            raise MetadataOverrideError(
                f"Override '{path}' targets an absent element with an unknown VR. "
                "Provide a 'vr' value in the override specification."
            )
        if existing_element is not None and existing_element.VR == "SQ":
            raise MetadataOverrideError(
                f"Override '{path}' targets a sequence. Target a sequence item instead."
            )

        original_value = existing_element.value if existing_element is not None else None
        try:
            if existing_element is None:
                parent.add_new(tag, vr, value)
            else:
                existing_element.value = value
        except Exception as error:
            raise MetadataOverrideError(
                f"Override '{path}' value is incompatible with DICOM VR '{vr}': {error}"
            ) from error

        audit_records.append(
            {
                "path": path,
                "tag": str(tag),
                "keyword": _keyword_or_identifier(tag, field_identifier),
                "vr": vr,
                "original_value": _json_value(original_value),
                "replacement_value": _json_value(parent[tag].value),
                "source_element_present": existing_element is not None,
                "units": units,
                "reason": reason,
            }
        )

    return corrected_dataset, audit_records


def build_metadata_override_audit(
    tool_name: str,
    metadata_overrides: MetadataOverrides,
    applied_records: list[dict[str, Any]],
    datasets_affected: int,
    reference_dataset: Dataset | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe, series-level audit record for output alongside results."""
    reference = reference_dataset or Dataset()
    aggregated_records = _aggregate_audit_records(applied_records)
    return {
        "tool": tool_name,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "metadata_overrides_file": metadata_overrides.source_path,
        "description": metadata_overrides.description,
        "reason": metadata_overrides.reason,
        "datasets_affected": datasets_affected,
        "series_instance_uid": str(getattr(reference, "SeriesInstanceUID", "")),
        "study_instance_uid": str(getattr(reference, "StudyInstanceUID", "")),
        "applied_overrides": aggregated_records,
    }


def write_metadata_override_audit(output_directory: str, audit: dict[str, Any]) -> str:
    """Write the correction audit record and return its absolute path."""
    output_path = Path(output_directory).resolve() / "metadata_overrides_audit.json"
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(audit, output_file, indent=2)
    return str(output_path)


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _unpack_specification(specification: Any) -> tuple[Any, str | None, str | None, str | None]:
    if not isinstance(specification, dict):
        return specification, None, None, None
    return (
        specification["value"],
        _optional_string(specification.get("vr")),
        _optional_string(specification.get("units")),
        _optional_string(specification.get("reason")),
    )


def _resolve_parent_dataset(dataset: Dataset, path: str) -> tuple[Dataset, str]:
    segments = path.split(".")
    if not segments or not segments[-1]:
        raise MetadataOverrideError(f"Override path '{path}' is invalid.")

    current_dataset = dataset
    for segment in segments[:-1]:
        sequence_match = _SEQUENCE_SEGMENT_PATTERN.fullmatch(segment)
        if not sequence_match:
            raise MetadataOverrideError(
                f"Override path '{path}' must use '[index]' for each sequence segment."
            )
        sequence_identifier, index_text = sequence_match.groups()
        sequence_tag = _resolve_tag(sequence_identifier)
        sequence_element = current_dataset.get(sequence_tag)
        if sequence_element is None or sequence_element.VR != "SQ":
            raise MetadataOverrideError(
                f"Override path '{path}' cannot find sequence '{sequence_identifier}'."
            )
        sequence_value = sequence_element.value
        if not isinstance(sequence_value, Sequence):
            raise MetadataOverrideError(
                f"Override path '{path}' has a non-DICOM sequence at '{sequence_identifier}'."
            )
        sequence_index = int(index_text)
        if sequence_index >= len(sequence_value):
            raise MetadataOverrideError(
                f"Override path '{path}' requests item {sequence_index}, but "
                f"'{sequence_identifier}' has {len(sequence_value)} item(s)."
            )
        current_dataset = sequence_value[sequence_index]

    return current_dataset, segments[-1]


def _resolve_tag(identifier: str) -> BaseTag:
    tag_match = _TAG_PATTERN.fullmatch(identifier)
    if tag_match:
        return Tag(int(tag_match.group(1), 16), int(tag_match.group(2), 16))

    keyword_tag = tag_for_keyword(identifier)
    if keyword_tag is None:
        raise MetadataOverrideError(
            f"DICOM identifier '{identifier}' is neither a known keyword nor '(GGGG,EEEE)'."
        )
    return Tag(keyword_tag)


def _lookup_vr(tag: BaseTag) -> str | None:
    try:
        return dictionary_VR(tag)
    except KeyError:
        return None


def _keyword_or_identifier(tag: BaseTag, identifier: str) -> str:
    keyword = tag_for_keyword(identifier)
    return identifier if keyword is not None else str(tag)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _aggregate_audit_records(applied_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_records: dict[str, dict[str, Any]] = {}
    for record in applied_records:
        key = json.dumps(record, sort_keys=True)
        grouped_record = grouped_records.get(key)
        if grouped_record is None:
            grouped_record = dict(record)
            grouped_record["datasets_affected"] = 0
            grouped_records[key] = grouped_record
        grouped_record["datasets_affected"] += 1
    return list(grouped_records.values())
