# DICOM Metadata Overrides for PET SUV

## Purpose

The `--metadata-overrides <json_file>` option in the manual SUV overlay,
automatic SUV overlay, and count-rate performance tools applies reviewed DICOM
metadata corrections for one analysis run. The input DICOM files are not
changed. Each image dataset is copied in memory, corrected, and then used by
the existing SUV calculation.

## JSON Format

The JSON file must contain a non-empty `dicom_overrides` object. Each key is a
DICOM path. A value may be supplied directly or in an object with `value` and
optional `vr`, `units`, and `reason` fields.

```json
{
  "description": "PET SUV correction from reviewed records",
  "reason": "Corrected transcription error",
  "dicom_overrides": {
    "PatientWeight": {
      "value": 72.5,
      "units": "kg",
      "reason": "Verified from patient record"
    },
    "RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose": {
      "value": 185000000,
      "units": "Bq"
    },
    "RadiopharmaceuticalInformationSequence[0].RadiopharmaceuticalStartDateTime": {
      "value": "20260821103000"
    },
    "(0071,1022)": {
      "value": "20260821103000",
      "vr": "DT",
      "reason": "Reviewed Siemens private decay-reference timestamp"
    }
  }
}
```

## DICOM Paths

Use any of the following forms:

- A standard DICOM keyword: `PatientWeight`
- A standard or private DICOM tag: `(0010,1030)` or `(0071,1022)`
- A sequence path with zero-based item indexes:
  `RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose`
- A nested sequence path using the same syntax at each level.

Each sequence specified in a path must already exist and contain the requested
item. A standard absent element may be added when its DICOM VR is known. For an
absent private element, provide `vr` explicitly.

Values use the native DICOM units and formats for the target tag. For example,
PatientWeight is kg, RadionuclideTotalDose is Bq, and DICOM date-time (`DT`)
values are written as `YYYYMMDDHHMMSS` with an optional fractional component.

## Using the Option

```powershell
python -m pet_tools.suv_overlay_auto `
  --input "C:\PET\ACR\PET_AC" `
  --output "C:\PET\Results\ACR" `
  --metadata-overrides "C:\PET\reviewed_suv_metadata.json" `
  --debug
```

The same option is available in `pet_tools.suv_overlay_manual` and
`pet_tools.count_rate_performance`.

## Math Notes

The override system does not implement an independent SUV algorithm. It gives
the existing calculation corrected metadata, including future DICOM fields
that may influence the calculation. The current tools calculate

$$
SUV = C \frac{M}{A_{ref}}
$$

where $C$ is image activity concentration in Bq/mL, $M$ is the selected mass
normalization in grams, and $A_{ref}$ is injected activity in Bq corrected to
the image reference time. Correcting patient weight, injected activity,
injection/assay time, isotope half-life, or decay-correction metadata can
therefore change final SUV values.

## Audit Record

When an override document is used, the tool writes
`metadata_overrides_audit.json` in its output directory. It records the source
document, timestamp, affected series identifiers, each original and
replacement value, DICOM tag, VR, optional units/reason, and the number of
image datasets affected. This record is part of the analysis output and should
be retained with the associated results.

Invalid JSON, unresolved paths, out-of-range sequence indexes, and values that
cannot be assigned to the applicable DICOM VR stop the run before SUV analysis.