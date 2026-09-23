"""
Uniformity_Module.py — ACR CT Phantom Uniformity Analysis
Author: Ryan Byrd
Version: 2.0

Usage:
    python Uniformity_Module.py "C:\path\to\dicom.dcm" "C:\path\to\output"

or programmatically:
    from Uniformity_Module import run_uniformity_analysis
    run_uniformity_analysis("C:/path/to/dicom.dcm", "C:/path/to/output")
"""

import os
import sys
import csv
import numpy as np
import pydicom
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from scipy.ndimage import gaussian_filter, label, center_of_mass


def find_phantom_center(image: np.ndarray, pixel_size_mm: float, modality: str = "CT", debug: bool = False):
    """Automatically locate phantom center using intensity thresholding and centroid detection."""
    blurred = gaussian_filter(image, sigma=2.0)
    threshold = -300 if modality == "CT" else np.percentile(blurred, 30)
    mask = blurred > threshold
    labeled, num = label(mask)
    if num == 0:
        raise RuntimeError("No phantom region detected.")
    sizes = np.bincount(labeled.ravel())
    sizes[0] = 0
    phantom_label = np.argmax(sizes)
    phantom_mask = labeled == phantom_label
    cy, cx = center_of_mass(phantom_mask)
    area_px = np.sum(phantom_mask)
    radius_px = np.sqrt(area_px / np.pi)
    if debug:
        fig, ax = plt.subplots(figsize=(7, 7))
        ax.imshow(image, cmap="gray", vmin=-1000, vmax=1000)
        ax.plot(cx, cy, "rx", ms=12, mew=2)
        ax.add_patch(Circle((cx, cy), radius_px, edgecolor="lime", facecolor="none", lw=1.5))
        ax.set_title("Detected Phantom Center")
        plt.show()
    return cy, cx, radius_px


def run_uniformity_analysis(dicom_path: str, output_dir: str):
    """Perform uniformity analysis on one DICOM image and save overlay and CSV results."""
    if not os.path.isfile(dicom_path):
        raise FileNotFoundError(f"DICOM file not found:\n{dicom_path}")
    os.makedirs(output_dir, exist_ok=True)

    ds = pydicom.dcmread(dicom_path)
    px = ds.pixel_array.astype(np.float32) * float(ds.RescaleSlope) + float(ds.RescaleIntercept)
    pixel_spacing = np.mean(ds.PixelSpacing)
    modality = getattr(ds, "Modality", "CT")

    # --- Find phantom center ---
    cy, cx, radius_px = find_phantom_center(px, pixel_spacing, modality=modality, debug=False)
    center = np.array([cy, cx])

    # --- Define ROIs ---
    roi_radius_mm = np.sqrt(400 / np.pi)
    offset_mm = 65
    roi_radius_px = roi_radius_mm / pixel_spacing
    offset_px = offset_mm / pixel_spacing
    positions = {
        "Center": center,
        "Top": center + np.array([-offset_px, 0]),
        "Bottom": center + np.array([offset_px, 0]),
        "Left": center + np.array([0, -offset_px]),
        "Right": center + np.array([0, offset_px]),
    }

    # --- Compute means and standard deviations ---
    roi_results = {}
    rows, cols = px.shape
    Y, X = np.ogrid[:rows, :cols]
    for label, (y, x) in positions.items():
        mask = (X - x) ** 2 + (Y - y) ** 2 <= roi_radius_px**2
        vals = px[mask]
        roi_results[label] = {"mean": np.mean(vals), "std": np.std(vals), "pos": (x, y)}

    # --- Plot overlay ---
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(px, cmap="gray", vmin=-100, vmax=100)
    ax.set_title("Uniformity Module — HU Distribution", fontsize=14)
    for label, vals in roi_results.items():
        x, y = vals["pos"]
        circ = Circle((x, y), roi_radius_px, edgecolor="coral", facecolor="none", lw=2)
        ax.add_patch(circ)
        ax.text(x, y, f"{label}\n{vals['mean']:.1f} HU", color="maroon",
                ha="center", va="center", fontsize=12, fontname="Verdana")
    ax.axis("off")
    plt.tight_layout()

    # --- Save outputs ---
    overlay_path = os.path.join(output_dir, "Uniformity_Module_Overlay.png")
    fig.savefig(overlay_path, dpi=200, bbox_inches="tight")
    plt.close(fig)

    csv_path = os.path.join(output_dir, "Uniformity_Module_Results.csv")
    roi_order = ["Center", "Top", "Bottom", "Left", "Right"]
    header, values = [], []
    for roi in roi_order:
        if roi in roi_results:
            header.extend([f"{roi} (Mean)", f"{roi} (SD)"])
            values.extend([f"{roi_results[roi]['mean']:.2f}", f"{roi_results[roi]['std']:.2f}"])
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(header)
        csv.writer(f).writerow(values)

    print(f"\n✅ Overlay saved to: {overlay_path}")
    print(f"✅ CSV saved to: {csv_path}")
    for label, vals in roi_results.items():
        print(f"{label:8s}: {vals['mean']:8.2f} ± {vals['std']:6.2f} HU")

    return roi_results


# --- Command-line support ---
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python Uniformity_Module.py <dicom_file> <output_dir>")
        sys.exit(1)
    run_uniformity_analysis(sys.argv[1], sys.argv[2])
