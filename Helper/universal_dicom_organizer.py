#!/usr/bin/env python3

import os
import argparse
import json
import shutil
import pydicom


def safe(s):
    """Sanitize strings for folder and file names."""
    bad = '<>:"/\\|?*'
    for b in bad:
        s = s.replace(b, "_")
    return s.strip().replace(" ", "_")[:60]


def get_site_name(ds):
    """
    Extract the site/institution name from DICOM metadata.
    Fallbacks if missing.
    """
    for tag in ["InstitutionName", "StationName", "ManufacturerModelName"]:
        val = getattr(ds, tag, None)
        if val:
            return safe(str(val))
    return "UnknownSite"


def short_desc(s):
    """Make a short, safe description from SeriesDescription."""
    if not s:
        return "Unknown"
    s = safe(str(s))
    return s[:40]


def organize_dicom(input_dir, output_root):
    """
    Organize converted DICOM files into:
        <SiteName> DICOM Images / PatientName_PatientID / SeriesNumber_Modality_Desc / IMG_###.dcm
    """
    print("\n📁 Scanning input folder for DICOM files...")
    dcm_files = []

    for root, dirs, files in os.walk(input_dir):
        for fn in files:
            if fn.lower().endswith(".dcm"):
                dcm_files.append(os.path.join(root, fn))

    if not dcm_files:
        print("❌ No DICOM files found.")
        return

    print(f"   Found {len(dcm_files)} DICOM files.")

    # Load first valid file to identify site
    first_ds = None
    for f in dcm_files:
        try:
            ds = pydicom.dcmread(f, force=False)
            if hasattr(ds, "PixelData"):
                first_ds = ds
                break
        except:
            continue

    if first_ds is None:
        print("❌ No valid DICOMs with PixelData found.")
        return

    site_name = get_site_name(first_ds)
    site_root = os.path.join(output_root, f"{site_name} DICOM Images")
    os.makedirs(site_root, exist_ok=True)
    print(f"📍 Site detected: {site_name}")

    # Grouping: (PatientName, PatientID, SeriesInstanceUID) → list of files
    groups = {}

    for f in dcm_files:
        try:
            ds = pydicom.dcmread(f, force=False)
        except:
            continue

        if not hasattr(ds, "PixelData"):
            continue

        pname = safe(str(getattr(ds, "PatientName", "Unknown")))
        pid = safe(str(getattr(ds, "PatientID", "NoID")))
        sdesc = short_desc(getattr(ds, "SeriesDescription", ""))
        series_uid = str(getattr(ds, "SeriesInstanceUID", ""))

        try:
            snum = int(getattr(ds, "SeriesNumber", 0))
        except:
            snum = 0

        try:
            inst = int(getattr(ds, "InstanceNumber", 1))
        except:
            inst = 1

        key = (pname, pid, snum, sdesc, series_uid)

        if key not in groups:
            groups[key] = []
        groups[key].append((inst, f))

    print(f"📦 Found {len(groups)} series.")

    manifest = []

    # Organize files for each patient + series
    for (pname, pid, snum, sdesc, uid), file_list in groups.items():
        patient_folder = os.path.join(site_root, f"{pname}_{pid}")
        os.makedirs(patient_folder, exist_ok=True)

        # Build series folder name WITHOUT adding CT or PT (already in description)
        series_folder_name = f"{str(snum).zfill(3)} {sdesc}"
        series_folder_name = safe(series_folder_name)  # ensure no illegal chars

        series_folder = os.path.join(patient_folder, series_folder_name)
        os.makedirs(series_folder, exist_ok=True)

        # Sort by instance number
        file_list.sort(key=lambda x: x[0])

        for idx, (inst, src_path) in enumerate(file_list, start=1):
            dst_path = os.path.join(series_folder, f"IMG_{str(idx).zfill(3)}.dcm")
            shutil.copy2(src_path, dst_path)

        manifest.append({
            "patient_name": pname,
            "patient_id": pid,
            "series_number": snum,
            "series_description": sdesc,
            "series_uid": uid,
            "output_folder": series_folder,
            "num_files": len(file_list)
        })




def main():
    parser = argparse.ArgumentParser(description="Organize DICOM files into site/patient/series structure")
    parser.add_argument("--input", "-i", required=True, help="Input folder (Converted DICOMs)")
    parser.add_argument("--output", "-o", required=True, help="Output root directory")
    args = parser.parse_args()

    input_dir = os.path.abspath(args.input)
    output_root = os.path.abspath(args.output)

    organize_dicom(input_dir, output_root)


if __name__ == "__main__":
    main()
