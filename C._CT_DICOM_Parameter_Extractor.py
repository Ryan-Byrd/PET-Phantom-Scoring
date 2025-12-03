#!/usr/bin/env python3
"""
CT DICOM Parameter Extractor (v6)
---------------------------------
- Imports per-parameter definitions from Helper/CT_ParameterCalculator.py
- Extracts all CT parameters and writes them vertically to CT-parameters.csv
"""

import csv
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
import pydicom
from Helper.CT_ParameterCalculator import CTParameterCalculator as CT

def extract_ct_parameters(dcm_path):
    ds = pydicom.dcmread(dcm_path, stop_before_pixels=True, force=True)

    results = {
        "kVp": CT.get_kvp(ds),
        "mA": CT.get_ma(ds),
        "Time per Rotation (s)": CT.get_rotation_time(ds),
        "mAs": CT.get_mas(ds),
        "Effective mAs": CT.get_effective_mas(ds),
        "Scan FOV (cm or name)": CT.get_scan_fov(ds),
        "Display FOV (cm)": CT.get_display_fov(ds),
        "Reconstruction Algorithm": CT.get_recon_alg(ds),
        "Axial (A) or Helical (H)": CT.get_scan_mode(ds),
        "No. data channels used (N)": CT.get_n_channels(ds),
        "Z-axis collimation (T, in mm)": CT.get_total_collimation(ds),
        "A: Table increment (mm) or H: Table speed (mm/rot)": (
            CT.get_table_increment(ds)
            if CT.get_scan_mode(ds) == "A"
            else CT.get_table_feed_per_rot(ds)
        ),
        "Pitch": CT.get_pitch(ds),
        "Reconstructed Scan Width (mm)": CT.get_slice_thickness(ds),
        "Reconstructed Scan Interval (mm)": CT.get_spacing(ds),
        "Dose Reduction Technique(s)": CT.get_dose_reduction(ds)
    }

    print("\n--- Extracted Parameters ---")
    for k, v in results.items():
        print(f"{k:45s}: {v}")
    print("--------------------------------------\n")

    return results


def main():
    root = tk.Tk()
    root.withdraw()

    dcm_path = filedialog.askopenfilename(title="Select CT DICOM", filetypes=[("DICOM files", "*.dcm")])
    if not dcm_path:
        return
    results = extract_ct_parameters(dcm_path)

    out_dir = filedialog.askdirectory(title="Select folder to save CT-parameters.csv")
    if not out_dir:
        return

    out_path = Path(out_dir) / "CT-parameters.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for k, v in results.items():
            writer.writerow([k, v])

    messagebox.showinfo("Done", f"CT parameters saved to:\n{out_path}")


if __name__ == "__main__":
    main()
