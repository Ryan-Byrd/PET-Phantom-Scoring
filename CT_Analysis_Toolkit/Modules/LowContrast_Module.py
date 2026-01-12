"""
LowContrast_Module.py — Simplified ACR Low-Contrast Analysis (pylinac-style)
Author: Ryan Byrd
Version: 3.1
"""

import os
import sys
import csv
import numpy as np
import pydicom
import matplotlib.pyplot as plt
from matplotlib.patches import Circle


def run_lowcontrast_analysis(dicom_path: str, output_dir: str):
    """Run low contrast analysis for one DICOM image and save output to output_dir"""
    if not os.path.isfile(dicom_path):
        raise FileNotFoundError(f"DICOM file not found:\n{dicom_path}")

    os.makedirs(output_dir, exist_ok=True)

    # --- Load DICOM and convert to HU ---
    ds = pydicom.dcmread(dicom_path)
    px = ds.pixel_array.astype(np.float32) * float(ds.RescaleSlope) + float(ds.RescaleIntercept)
    pixel_spacing = float(np.mean(ds.PixelSpacing))
    rows, cols = px.shape
    center = np.array([rows / 2, cols / 2])

    # --- Define ROI geometry ---
    roi_dist_mm = 60
    roi_radius_mm = 6
    bg_angle_deg = 90
    contrast_angle_deg = 115

    dist_px = roi_dist_mm / pixel_spacing
    radius_px = roi_radius_mm / pixel_spacing

    def pol2cart(distance_px, angle_deg):
        theta = np.deg2rad(angle_deg)
        y = center[0] - distance_px * np.sin(theta)
        x = center[1] + distance_px * np.cos(theta)
        return x, y

    x_contrast, y_contrast = pol2cart(dist_px, contrast_angle_deg)
    x_bg, y_bg = pol2cart(dist_px, bg_angle_deg)

    # --- Extract ROI pixel data ---
    Y, X = np.ogrid[:rows, :cols]
    mask_contrast = (X - x_contrast) ** 2 + (Y - y_contrast) ** 2 <= radius_px**2
    mask_bg = (X - x_bg) ** 2 + (Y - y_bg) ** 2 <= radius_px**2

    contrast_vals = px[mask_contrast]
    bg_vals = px[mask_bg]

    mean_contrast = np.mean(contrast_vals)
    mean_bg = np.mean(bg_vals)
    std_bg = np.std(bg_vals)
    cnr = abs(mean_contrast - mean_bg) / (std_bg if std_bg > 0 else 1)

    # --- Plot with WL/WW ---
    fig, ax = plt.subplots(figsize=(7, 7))
    wc, ww = 100, 100
    vmin, vmax = wc - ww / 2, wc + ww / 2
    ax.imshow(px, cmap="gray", vmin=vmin, vmax=vmax)
    ax.set_title("Low-Contrast Module — WL=100 WW=100", fontsize=14)
    ax.axis("off")

    # ROI overlays
    ax.add_patch(Circle((x_contrast, y_contrast), radius_px, edgecolor="coral", facecolor="none", lw=1))
    ax.add_patch(Circle((x_bg, y_bg), radius_px, edgecolor="coral", facecolor="none", lw=1))
    ax.text(0.02, 0.98, f"CNR = {cnr:.3f}", transform=ax.transAxes,
            color="maroon", fontsize=12, va="top", ha="left")

    # --- Save visualization ---
    out_png = os.path.join(output_dir, "LowContrast_Module_Overlay.png")
    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    plt.close(fig)

    # --- Save CSV results ---
    csv_path = os.path.join(output_dir, "LowContrast_Module_Results.csv")
    rows_out = [
        ["Contrast ROI Mean (HU)", f"{mean_contrast:.2f}"],
        ["Background ROI Mean (HU)", f"{mean_bg:.2f}"],
        ["Background ROI Std (HU)", f"{std_bg:.2f}"],
        ["CNR", f"{cnr:.3f}"]
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows_out)

    print(f"✅ CNR={cnr:.3f} | CSV saved: {csv_path}")
    print(f"✅ Overlay saved: {out_png}")


# --- Allow direct command-line execution ---
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python LowContrast_Module.py <dicom_file> <output_dir>")
        sys.exit(1)
    dicom_path = sys.argv[1]
    output_dir = sys.argv[2]
    run_lowcontrast_analysis(dicom_path, output_dir)
