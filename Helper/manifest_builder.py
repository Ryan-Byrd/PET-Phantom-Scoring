#!/usr/bin/env python3
"""
Manifest Builder – patient-name classification + DICOM-based series selection (Option 2)

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

Within each patient, the correct series is chosen using DICOM-based
rules similar to the older "series-description first" logic:

  - Uses SeriesDescription, ProtocolName, StudyDescription
  - Uses slice count and SliceThickness for refinement
  - Prefers:
      * For uniformity: PET AC series with most slices
      * For ACR:        PET series likely to be sphere phantom
      * For CRP:        PET series likely to be CRP/performance

Outputs (JSON only) in the site folder:
  series_manifest.json
"""

import os
import json
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


def classify_patient_by_name(patient_folder_name: str):
    """
    Classify patient purely by folder name.
    """
    name = patient_folder_name.upper()
    if "UNI" in name:
        return "uniformity"
    if "ACR" in name:
        return "acr"
    if "CRP" in name:
        return "crp"
    return None


# ------------------------------------------------------------
# Series-level classification (Option 2 style)
# ------------------------------------------------------------

def classify_text(text: str) -> str:
    """
    Simple keyword-based classifier for a series.
    Returns one of: 'uniformity', 'acr', 'crp', 'transmission', 'other'
    """
    t = text.lower()

    if any(k in t for k in ["flood", "uniform", "uni", "ucm"]):
        return "uniformity"

    if any(k in t for k in ["acr", "spheres", "standard", "normal"]):
        return "acr"

    if any(k in t for k in ["crp", "count rate", "countrate", "performance", "boost"]):
        return "crp"

    if any(k in t for k in ["transmission", "tx", "empty", "blank"]):
        return "transmission"

    return "other"


def classify_series_from_metadata(ds) -> str:
    """
    Combine multiple DICOM fields (SeriesDescription, ProtocolName,
    StudyDescription, ImageType) and apply keyword classification.
    """
    blob = ""
    for tag in ["SeriesDescription", "ProtocolName", "StudyDescription", "ImageType"]:
        if hasattr(ds, tag):
            blob += " " + str(getattr(ds, tag))
    return classify_text(blob)


def refine_label_by_stats(label: str, ds, num_files: int) -> str:
    """
    Refine label using slice count and SliceThickness.
    This approximates your older logic:

    - ACR: ~20–30 slices + keywords
    - CRP: ~20–30 slices + keywords
    - Uniformity: large number of slices or AC-like description
    """
    desc = str(getattr(ds, "SeriesDescription", "")).lower()

    # Try to get slice thickness
    thick = 0.0
    try:
        thick = float(getattr(ds, "SliceThickness", 0.0))
    except Exception:
        thick = 0.0

    # ACR logic: if "other" but ~20–30 slices and acr-ish terms
    if label == "other" and 15 <= num_files <= 30:
        if any(k in desc for k in ["acr", "standard", "normal", "sphere"]):
            return "acr"

    # CRP logic: if "other" but ~20–30 slices and crp-ish terms
    if label == "other" and 15 <= num_files <= 30:
        if any(k in desc for k in ["crp", "performance", "boost"]):
            return "crp"

    # Uniformity: lots of slices OR AC-like terms
    if label == "other":
        if num_files > 40 or any(k in desc for k in ["uni", "uniform", "ucm", "ac", "attn", "atten"]):
            return "uniformity"

    return label


# ------------------------------------------------------------
# Series selection helpers (per patient type)
# ------------------------------------------------------------

def pick_uniformity_series(series_list):
    """
    From all series belonging to a uniformity patient, pick the
    best uniformity PET series:

    1) PET series whose label == 'uniformity', max file_count
    2) PET AC series (SeriesDescription containing 'AC'), max file_count
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

    1) PET series labeled 'acr'
    2) PET series with 15–30 slices, closest to 20
    3) Any PET series
    """
    if not series_list:
        return None

    pet_series = [s for s in series_list if s["modality"] == "PT"]
    if not pet_series:
        return None

    # 1) Label-based acr
    acr_labeled = [s for s in pet_series if s["label"] == "acr"]
    if acr_labeled:
        # choose closest to 20 slices
        return min(acr_labeled, key=lambda x: abs(x["file_count"] - 20))

    # 2) 15–30 slices, closest to 20
    mid_slices = [s for s in pet_series if 15 <= s["file_count"] <= 30]
    if mid_slices:
        return min(mid_slices, key=lambda x: abs(x["file_count"] - 20))

    # 3) Fallback: first PET series
    return pet_series[0]


def pick_crp_series(series_list):
    """
    From all series belonging to a CRP patient, pick the best CRP PET series:

    1) PET series labeled 'crp'
    2) PET series with 'crp'/'performance'/'boost' in SeriesDescription
    3) PET series with 15–30 slices
    4) Any PET series
    """
    if not series_list:
        return None

    pet_series = [s for s in series_list if s["modality"] == "PT"]
    if not pet_series:
        return None

    # 1) Label-based crp
    crp_labeled = [s for s in pet_series if s["label"] == "crp"]
    if crp_labeled:
        return crp_labeled[0]

    # 2) Description keywords
    crp_kw = []
    for s in pet_series:
        desc = s["series_desc"].lower()
        if any(k in desc for k in ["crp", "performance", "boost"]):
            crp_kw.append(s)
    if crp_kw:
        return crp_kw[0]

    # 3) 15–30 slices
    mid_slices = [s for s in pet_series if 15 <= s["file_count"] <= 30]
    if mid_slices:
        return min(mid_slices, key=lambda x: abs(x["file_count"] - 20))

    # 4) Fallback: first PET series
    return pet_series[0]


# ------------------------------------------------------------
# Main manifest builder
# ------------------------------------------------------------

def build_manifest(site_root: str):
    """
    Scan <site_root>, classify patients by folder name, then
    use DICOM-based rules to select the best series within each patient.

    Writes series_manifest.json in site_root.
    """

    print(f"\n📁 Building manifest from site folder:\n   {site_root}\n")

    # Collect all candidate series per phantom type
    per_type_series = {
        "uniformity": [],
        "acr": [],
        "crp": []
    }

    # Walk patient folders
    for patient_name in sorted(os.listdir(site_root)):
        patient_path = os.path.join(site_root, patient_name)

        # Handle both real dirs and symlinks (e.g., OneDrive)
        if not (os.path.isdir(patient_path) or os.path.islink(patient_path)):
            continue

        patient_label = classify_patient_by_name(patient_name)
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

            # Read header
            try:
                ds = pydicom.dcmread(rep_path, stop_before_pixels=True, force=False)
            except Exception:
                continue

            modality = str(getattr(ds, "Modality", "")).upper()

            # Derive label for this series from metadata
            label0 = classify_series_from_metadata(ds)
            label = refine_label_by_stats(label0, ds, len(dicoms))

            # Store series info
            per_type_series[patient_label].append({
                "patient": patient_name,
                "series_num": series_num,
                "series_desc": series_desc,
                "folder": series_path,
                "file_count": len(dicoms),
                "modality": modality,
                "label": label,
            })

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
    print("\n✅ Completed.\n")


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Build PET phantom manifest using patient-name classification and DICOM series selection."
    )
    parser.add_argument(
        "--site", "-s",
        required=True,
        help="Path to '<SiteName> DICOM Images' folder"
    )
    args = parser.parse_args()

    site_root = os.path.abspath(args.site)
    build_manifest(site_root)


if __name__ == "__main__":
    main()
