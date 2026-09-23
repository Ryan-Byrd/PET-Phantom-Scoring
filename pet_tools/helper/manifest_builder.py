#!/usr/bin/env python3
"""
Manifest Builder – patient-name classification + series-name selection

Folder structure:

<SiteName> DICOM Images/
    <PatientName PatientID>/
        <SeriesNumber_SeriesDescription>/
            IMG_001.dcm
            IMG_002.dcm
            ...

Patient folders are classified ONLY by their names:
  - "UNI" in name → uniformity patient
  - "ACR" in name → ACR patient
  - "CRP" in name → CRP patient

Within each patient, the correct series is chosen using
patient folder names for labeling and series folder names for selection.
For ACR/CRP, 10 mm PET is preferred; if unavailable, the first PET
series marked with the DICOM CorrectedImage ATTN value is used.

    - Uses patient folder name text for labels
    - Prefers:
            * For uniformity: PET AC series with most slices
            * For ACR:        PET series likely to be sphere phantom
            * For CRP:        PET series likely to be CRP/performance

Outputs (JSON only) in the site folder:
  series_manifest.json
"""

import os
import json
import math
from collections import Counter

import pydicom


# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------

def safe(s: str) -> str:
    """Clean strings for JSON consistency."""
    bad = '<>:"/\\|?*'
    for b in bad:
        s = s.replace(b, "_")
    return s.strip()


def extract_slice_thickness_mm(ds) -> float:
    """
    Extract SliceThickness (mm) from DICOM header.
    Returns None if not found or not a valid positive number.
    """
    try:
        raw_value = getattr(ds, "SliceThickness", None)
        if raw_value is None:
            return None
        value = float(raw_value)
        if not math.isfinite(value) or value <= 0.0:
            return None
        return value
    except Exception:
        return None


def compute_series_slice_thickness_mm(series_path: str, dicoms: list) -> float:
    """
    Compute the most common SliceThickness across a series.
    Returns None if no valid SliceThickness values are found.
    """
    if not dicoms:
        return None

    counts = Counter()
    for filename in dicoms:
        path = os.path.join(series_path, filename)
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=False)
        except Exception:
            continue

        thickness = extract_slice_thickness_mm(ds)
        if thickness is None:
            continue

        counts[round(thickness, 2)] += 1

    if not counts:
        return None

    return counts.most_common(1)[0][0]


def is_thickness_match(value: float, target: float = 10.0, tol: float = 0.5) -> bool:
    """
    Check whether a slice thickness matches the required target.
    """
    if value is None:
        return False
    return abs(value - target) <= tol


def is_attenuation_corrected_pet(ds) -> bool:
    """
    Return whether a PET image has DICOM attenuation correction applied.

    PET CorrectedImage (0028,0051) records corrections applied during
    reconstruction. The ATTN value distinguishes attenuation-corrected PET
    from non-attenuation-corrected PET without relying on folder naming.
    """
    corrected_image = getattr(ds, "CorrectedImage", [])
    return any(str(value).strip().upper() == "ATTN" for value in corrected_image)


def classify_patient_by_name(patient_folder_name: str) -> str:
    """
    Classify patient purely by folder name (fallback method).
    """
    name = patient_folder_name.upper()
    if "UNI" in name:
        return "uniformity"
    if "ACR" in name:
        return "acr"
    if "CRP" in name:
        return "crp"
    return None


def classify_patients_by_name(patient_folders: list) -> dict:
    """
    Classify multiple patients using folder names only.

    Returns dict: {patient_folder_name: patient_type}
    where patient_type is one of: 'uniformity', 'acr', 'crp', None
    """
    classification = {}
    for pfs in patient_folders:
        classification[pfs] = classify_patient_by_name(pfs)
    return classification


# ------------------------------------------------------------
# Series selection helpers (per patient type)
# ------------------------------------------------------------

def pick_uniformity_series(series_list):
    """
    From all series belonging to a uniformity patient, pick the
    best uniformity PET series:

    1) PET series whose label == 'uniformity', max file_count
    2) PET AC series (series name containing 'AC'), max file_count
    3) Any PET series with max file_count
    """
    if not series_list:
        return None

    # PET-only
    pet_series = [s for s in series_list if s["modality"] == "PT"]
    if not pet_series:
        return None

    # 1) Label-based uniformity
    uni_label = [s for s in pet_series if s["label"] == "uniformity"]
    if uni_label:
        return max(uni_label, key=lambda x: x["file_count"])

    # 2) PET AC
    ac_pet = [s for s in pet_series if "AC" in s["series_desc"].upper()]
    if ac_pet:
        return max(ac_pet, key=lambda x: x["file_count"])

    # 3) PET with max slices
    return max(pet_series, key=lambda x: x["file_count"])


def pick_acr_series(series_list):
    """
    From all series belonging to an ACR patient, pick the best ACR PET series:

    1) Any 10 mm PET series with most slices
     2) First PET series with DICOM CorrectedImage value ATTN when no 10 mm
         PET is available
    """
    if not series_list:
        return None

    pet_series = [s for s in series_list if s["modality"] == "PT"]
    if not pet_series:
        return None

    ten_mm_pet_series = [
        series for series in pet_series
        if is_thickness_match(series["slice_thickness_mm"])
    ]
    if ten_mm_pet_series:
        return max(ten_mm_pet_series, key=lambda series: series["file_count"])

    attenuation_corrected_pet_series = [
        series for series in pet_series
        if series.get("is_attenuation_corrected", False)
    ]
    if attenuation_corrected_pet_series:
        return attenuation_corrected_pet_series[0]

    return None


def pick_crp_series(series_list):
    """
    From all series belonging to a CRP patient, pick the best CRP PET series:

    1) Any 10 mm PET series with most slices
     2) First PET series with DICOM CorrectedImage value ATTN when no 10 mm
         PET is available
    """
    if not series_list:
        return None

    pet_series = [s for s in series_list if s["modality"] == "PT"]
    if not pet_series:
        return None

    ten_mm_pet_series = [
        series for series in pet_series
        if is_thickness_match(series["slice_thickness_mm"])
    ]
    if ten_mm_pet_series:
        return max(ten_mm_pet_series, key=lambda series: series["file_count"])

    attenuation_corrected_pet_series = [
        series for series in pet_series
        if series.get("is_attenuation_corrected", False)
    ]
    if attenuation_corrected_pet_series:
        return attenuation_corrected_pet_series[0]

    return None


# ------------------------------------------------------------
# Main manifest builder
# ------------------------------------------------------------

def build_manifest(site_root: str, debug: bool = False):
    """
    Scan <site_root>, classify patients by name only, then
    use series folder names to select the best series within each patient.

    Classification logic:
    - Patient folder name only

    Writes series_manifest.json in site_root.
    """

    print(f"\n📁 Building manifest from site folder:\n   {site_root}\n")

    # Collect all patient folders first (not all will be phantoms)
    all_patient_folders = sorted(
        f for f in os.listdir(site_root)
        if os.path.isdir(os.path.join(site_root, f)) or os.path.islink(os.path.join(site_root, f))
    )

    # Classify all patients by name only
    patient_classification = classify_patients_by_name(all_patient_folders)

    print("👥 Patient Classification Summary:")
    for patient_name in sorted(patient_classification.keys()):
        pt_type = patient_classification[patient_name] or "unknown"
        print(f"   {patient_name:40s} → {pt_type:12s}")
    print()

    rejected_by_thickness = {
        "acr": [],
        "crp": []
    }

    # Collect all candidate series per phantom type
    per_type_series = {
        "uniformity": [],
        "acr": [],
        "crp": []
    }

    # Walk patient folders
    for patient_name in all_patient_folders:
        patient_path = os.path.join(site_root, patient_name)

        # Handle both real dirs and symlinks (e.g., OneDrive)
        if not (os.path.isdir(patient_path) or os.path.islink(patient_path)):
            continue

        patient_label = patient_classification.get(patient_name)
        if patient_label not in per_type_series:
            # Skip unknown/non-phantom patients
            continue

        # Walk series folders
        for series_name in sorted(os.listdir(patient_path)):
            series_path = os.path.join(patient_path, series_name)
            if not (os.path.isdir(series_path) or os.path.islink(series_path)):
                continue

            # Parse "012_PET_AC_WB_M" → series_num = "012", series_desc = "PET_AC_WB_M"
            parts = series_name.split("_", 1)
            series_num = parts[0]
            series_desc = parts[1] if len(parts) > 1 else ""

            # DICOM files
            dicoms = sorted(
                f for f in os.listdir(series_path)
                if f.lower().endswith(".dcm")
            )
            if not dicoms:
                continue

            rep_path = os.path.join(series_path, dicoms[0])
            try:
                ds = pydicom.dcmread(rep_path, stop_before_pixels=True, force=False)
            except Exception:
                continue

            slice_thickness_mm = compute_series_slice_thickness_mm(series_path, dicoms)

            modality = str(getattr(ds, "Modality", "")).upper()
            is_attenuation_corrected = (
                modality == "PT" and is_attenuation_corrected_pet(ds)
            )

            # Derive label from patient folder name only
            label = patient_label

            # Store series info
            series_info = {
                "patient": patient_name,
                "series_num": series_num,
                "series_desc": series_desc,
                "folder": series_path,
                "file_count": len(dicoms),
                "modality": modality,
                "label": label,
                "slice_thickness_mm": slice_thickness_mm,
                "is_attenuation_corrected": is_attenuation_corrected,
            }
            per_type_series[patient_label].append(series_info)

            if patient_label in rejected_by_thickness:
                if modality == "PT" and not is_thickness_match(slice_thickness_mm):
                    rejected_by_thickness[patient_label].append(series_info)

    # --------------------------------------------------------
    # Use selection helpers to pick one series per category
    # --------------------------------------------------------
    final_manifest = {
        "uniformity": None,
        "acr": None,
        "crp": None
    }

    final_manifest["uniformity"] = pick_uniformity_series(per_type_series["uniformity"])
    final_manifest["acr"] = pick_acr_series(per_type_series["acr"])
    final_manifest["crp"] = pick_crp_series(per_type_series["crp"])

    # --------------------------------------------------------
    # Write JSON only
    # --------------------------------------------------------
    json_out = os.path.join(site_root, "series_manifest.json")
    with open(json_out, "w") as f:
        json.dump(final_manifest, f, indent=2)

    print("📄 Manifest written:")
    print(f"   JSON → {json_out}")
    if debug:
        print("\n🔎 10 mm thickness rejections (ACR/CRP PET only):")
        for label in ["acr", "crp"]:
            rejected = rejected_by_thickness[label]
            if not rejected:
                print(f"   {label.upper():3s}: none")
                continue
            print(f"   {label.upper():3s}: {len(rejected)} series")
            for s in rejected:
                thickness = s["slice_thickness_mm"]
                thickness_str = f"{thickness:.2f} mm" if thickness is not None else "unknown"
                print(f"      {s['patient']} | {s['series_num']}_{s['series_desc']} | {thickness_str}")
    print("\n✅ Completed.\n")


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Build PET phantom manifest using patient-name classification and series-name selection."
    )
    parser.add_argument(
        "--site", "-s",
        required=True,
        help="Path to '<SiteName> DICOM Images' folder"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug details about slice thickness filtering"
    )
    args = parser.parse_args()

    site_root = os.path.abspath(args.site)
    build_manifest(site_root, debug=args.debug)


if __name__ == "__main__":
    main()
