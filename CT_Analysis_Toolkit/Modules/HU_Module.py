"""
HU_Module.py — CT Number (HU) Analysis Module
Author: Ryan Byrd
Version: 1.1

Performs quantitative HU analysis for the ACR CT Number Module.
Outputs a CSV and an overlay image to the designated output directory.

Usage (command line):
    python HU_Module.py "path/to/image.dcm" "path/to/output_folder"

Usage (from another script):
    from HU_Module import run_hu_analysis
    run_hu_analysis("path/to/image.dcm", "path/to/output_folder")
"""

import os
import sys
import csv
import numpy as np
import pydicom
import matplotlib.pyplot as plt
from matplotlib.patches import Circle


def run_hu_analysis(dicom_path: str, output_dir: str = None) -> list:
    """
    Perform HU ROI analysis on a single ACR CT Number module slice.

    Parameters
    ----------
    dicom_path : str
        Path to the DICOM file representing the CT Number module slice.
    output_dir : str, optional
        Directory to save the CSV and overlay image.
        Defaults to CT_Output folder in the working directory.

    Returns
    -------
    list of tuples
        [(Material, Mean_HU, Std_HU, (x, y)), ...]
    """

    # -----------------------------------------------------------------
    # Validate paths and prepare output
    # -----------------------------------------------------------------
    if not os.path.isfile(dicom_path):
        raise FileNotFoundError(f"DICOM file not found:\n{dicom_path}")

    if output_dir is None:
        output_dir = os.path.join(os.getcwd(), "CT_Output")
    os.makedirs(output_dir, exist_ok=True)

    # -----------------------------------------------------------------
    # Load DICOM data
    # -----------------------------------------------------------------
    ds = pydicom.dcmread(dicom_path)
    px = ds.pixel_array.astype(np.float32) * ds.RescaleSlope + ds.RescaleIntercept
    pixel_spacing = np.mean(ds.PixelSpacing)

    # -----------------------------------------------------------------
    # ROI geometry (based on ACR CT phantom spec)
    # -----------------------------------------------------------------
    roi_radius_mm = 7.9788
    roi_offset_mm = 63
    angles_deg = [180, 225, 316, 47, 135]
    materials = ["Water", "Acrylic", "Air", "Bone", "Polyethylene"]

    rows, cols = px.shape
    center = np.array([rows / 2, cols / 2])
    roi_radius_px = roi_radius_mm / pixel_spacing
    roi_offset_px = roi_offset_mm / pixel_spacing

    # -----------------------------------------------------------------
    # ROI Sampling & HU Calculation
    # -----------------------------------------------------------------
    roi_results = []
    for material, angle in zip(materials, angles_deg):
        theta = np.deg2rad(angle)
        y = center[0] - roi_offset_px * np.sin(theta)
        x = center[1] + roi_offset_px * np.cos(theta)

        Y, X = np.ogrid[:rows, :cols]
        mask = (X - x)**2 + (Y - y)**2 <= roi_radius_px**2
        roi_values = px[mask]

        mean_hu = np.mean(roi_values)
        std_hu = np.std(roi_values)
        roi_results.append((material, mean_hu, std_hu, (x, y)))

    # -----------------------------------------------------------------
    # Generate overlay figure
    # -----------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(px, cmap="gray", vmin=-1000, vmax=1000)
    ax.set_title("CT Number Module — HU Overlay", fontsize=14)

    for (material, mean_hu, std_hu, (x, y)) in roi_results:
        circ = Circle((x, y), roi_radius_px, edgecolor="coral", facecolor="none", lw=2)
        ax.add_patch(circ)
        ax.text(x, y, f"{material}\n{mean_hu:.2f} HU",
                color="maroon", ha="center", va="center", fontsize=12, fontname="Verdana")

    ax.axis("off")
    plt.tight_layout()

    overlay_path = os.path.join(output_dir, "HU_Module_Overlay.png")
    fig.savefig(overlay_path, dpi=200)
    plt.close(fig)

    # -----------------------------------------------------------------
    # Save results to CSV
    # -----------------------------------------------------------------
    csv_path = os.path.join(output_dir, "HU_Module_Results.csv")
    with open(csv_path, mode="w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Material", "Mean HU", "Std HU"])
        for mat, hu, std, _ in roi_results:
            writer.writerow([mat, f"{hu:.4f}", f"{std:.4f}"])

    # -----------------------------------------------------------------
    # Console Output
    # -----------------------------------------------------------------
    print("\n=== HU Results (Clockwise from Water) ===")
    for mat, hu, std, _ in roi_results:
        print(f"{mat:15s}: {hu:8.2f} ± {std:6.2f} HU")

    print(f"\n✅ CSV saved to: {csv_path}")
    print(f"✅ Overlay saved to: {overlay_path}")

    return roi_results


# ---------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python HU_Module.py <dicom_path> [output_dir]")
        sys.exit(1)

    dicom_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    run_hu_analysis(dicom_path, output_dir)
