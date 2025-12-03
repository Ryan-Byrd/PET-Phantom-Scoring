import os
import tkinter as tk
from tkinter import filedialog, simpledialog
import pydicom
import numpy as np
from matplotlib.widgets import Cursor
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import glob
from CT_Analysis_Toolkit.Modules.find_phantom_center import find_phantom_center_generalized
import csv
import argparse

import os
import argparse
from tqdm import tqdm
from tkinter import filedialog
import tkinter as tk
import sys
print("[DEBUG] sys.argv =", sys.argv)


# ---------- CLI or GUI folder selection ----------
parser = argparse.ArgumentParser(
    description="Automatic PET uniformity scoring and slice selection."
)
parser.add_argument("--input", "-i", help="Path to input DICOM folder (optional)")
parser.add_argument("--output", "-o", help="Path to output folder (optional)")
args = parser.parse_args()

def ask_folder(prompt):
    """Opens a folder picker dialog and returns the selected path or None."""
    root = tk.Tk()
    root.withdraw()
    return filedialog.askdirectory(title=prompt)

def ask_output_folder_and_name():
    """Opens a folder picker dialog for the output location."""
    root = tk.Tk()
    root.withdraw()
    return filedialog.askdirectory(title="Select folder to save results")

# ---------- Input / Output path resolution ----------
if args.input:
    in_dir = os.path.abspath(args.input)
    # If output not specified, create a default subfolder
    if args.output:
        out_dir = os.path.abspath(args.output)
    else:
        out_dir = os.path.join(in_dir, "Uniformity_Results")
        print(f"[INFO] Output not specified; creating subfolder: {out_dir}")
else:
    # Fallback to interactive mode
    in_dir = ask_folder("Select PET DICOM Folder (INPUT)")
    if not in_dir:
        print("[INFO] Cancelled: no input folder.")
        exit()

    out_dir = ask_output_folder_and_name()
    if not out_dir:
        print("[INFO] Cancelled: no output folder.")
        exit()

# ---------- Ensure output folder exists ----------
os.makedirs(out_dir, exist_ok=True)

print(f"[INFO] Using input folder: {in_dir}")
print(f"[INFO] Using output folder: {out_dir}")

# Pass to downstream logic
dicom_folder = in_dir
output_dir = out_dir



# --- Step 2: Load DICOM series ---
files = sorted(glob.glob(os.path.join(dicom_folder, "*.dcm")))
if not files:
    print(f"No DICOM files found in: {dicom_folder}")
    exit()

slices = [pydicom.dcmread(f) for f in files]
slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))  # sort by Z position


pixel_spacing = [float(x) for x in slices[0].PixelSpacing]
slope = float(slices[0].RescaleSlope)
intercept = float(slices[0].RescaleIntercept)

def get_suv(slice_data):
    return slice_data * slope + intercept

# --- Step 3: Automatic phantom center detection ---

mid_index = len(slices) // 2
mid_img_full = get_suv(slices[mid_index].pixel_array.astype(np.float32))

# Run auto-detection
cy, cx, radius_px = find_phantom_center_generalized(
    mid_img_full,
    pixel_size_mm=pixel_spacing[0],
    modality="PET",
    debug=True  # set to False to suppress visualization
)


# --- Parameters ---
roi_radius_mm = 180 / 2
roi_radius_px = roi_radius_mm / pixel_spacing[0]

# Build mask once using the detected center (cx, cy)
yy, xx = np.ogrid[:slices[0].pixel_array.shape[0], :slices[0].pixel_array.shape[1]]
mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= roi_radius_px ** 2

# Compute ROI std for every slice (using raw pixel data)
roi_std = []
for s in slices:
    img = s.pixel_array.astype(np.float32)
    roi_std.append(np.std(img[mask]))

# Compute derivative of the std curve
roi_std = np.array(roi_std)
diff_std = np.diff(roi_std)
mid_idx = len(roi_std) // 2

# Robust threshold based on MAD (median absolute deviation)
mad = np.median(np.abs(diff_std - np.median(diff_std)))
threshold = 2.0 * mad

# --- Detect boundaries ---
# Forward: look for strong positive jump (exit of uniformity)
end_idx = mid_idx
for i in range(mid_idx, len(diff_std)):
    if diff_std[i] > threshold:
        end_idx = i
        break

# Backward: look for strong negative jump (entry into uniformity)
start_idx = mid_idx
for i in range(mid_idx - 1, 0, -1):
    if diff_std[i] < -threshold:
        start_idx = i + 2   # step slightly forward into the plateau
        break

print(f"Auto-selected uniform slice range: {start_idx} → {end_idx}")

# --- Trim slice list to uniform region ---
slices = slices[start_idx:end_idx + 1]
print(f"Processing {len(slices)} slices ({start_idx} → {end_idx})")



# --- Step 4: ROI setup ---
radius_mm = 180 / 2
radius_pix = radius_mm / pixel_spacing[0]

# --- Step 5: Calculate ROI mean for each slice ---
roi_means = []
for s in slices:
    img = get_suv(s.pixel_array.astype(np.float32))
    yy, xx = np.ogrid[:img.shape[0], :img.shape[1]]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius_pix ** 2
    roi_means.append(np.mean(img[mask]))

# --- Step 6: Restrict to central 85% of slices ---
total_slices = len(roi_means)
lower_cut = int(total_slices * 0)
upper_cut = int(total_slices * 1)
central_indices = np.arange(lower_cut, upper_cut)
central_roi_means = [roi_means[i] for i in central_indices]

global_mean = np.mean(central_roi_means)
# deviation in percent
deviations = [((m / global_mean) - 1) * 100 for m in roi_means]

# --- Step 7: Output folder (temp: use same study folder) ---
output_dir = os.path.join(output_dir, "Uniformity_Results")
os.makedirs(output_dir, exist_ok=True)

csv_path = os.path.join(output_dir, "PET_ROI_Results.csv")
deviation_plot_path = os.path.join(output_dir, "PET_DeviationPlot.png")
splash_path = os.path.join(output_dir, "PET_SplashView.png")



# --- Step 9: Deviation plot (200 DPI) ---
plt.figure(figsize=(9, 6))
x = np.arange(1, len(deviations) + 1)
plt.plot(x, deviations, marker="o", color="black", label="Slice deviation")

# Pass/fail bands (now in %)
plt.fill_between(x, -5, 5, color="green", alpha=0.15, label="Pass band (±5%)")
plt.fill_between(x, 5, 10, color="yellow", alpha=0.15, label="Warning zone (5–10%)")
plt.fill_between(x, -10, -5, color="yellow", alpha=0.15)
plt.axhline(10, color="red", linestyle="--", linewidth=1.5, label="Fail limit (±10%)")
plt.axhline(-10, color="red", linestyle="--", linewidth=1.5)

# Central 85 % axial region highlight
#plt.axvspan(lower_cut + 1, upper_cut, color="blue", alpha=0.08, label="Central 85% region")

plt.xlabel("Slice Number")
plt.ylabel("Deviation (%)")
plt.grid(True, linestyle="--", linewidth=0.5)
plt.legend(loc="upper right")
plt.ylim(-25, 25)


plt.tight_layout()
plt.savefig(deviation_plot_path, dpi=200, bbox_inches="tight")
plt.show()
print(f"Deviation plot saved to {deviation_plot_path}")

# --- Step 10: Splash view (cropped 250×250 mm, inverted) ---
crop_mm = 220
crop_pix = int((crop_mm / 2) / pixel_spacing[0])
ncols = 8
nrows = int(np.ceil(len(slices) / ncols))
fig, axes = plt.subplots(nrows, ncols, figsize=(12, 12))
axes = axes.ravel()

for i, (s, ax) in enumerate(zip(slices, axes)):
    img = get_suv(s.pixel_array.astype(np.float32))

    # Crop 250×250 mm around center
    x1 = int(max(cx - crop_pix, 0))
    x2 = int(min(cx + crop_pix, img.shape[1]))
    y1 = int(max(cy - crop_pix, 0))
    y2 = int(min(cy + crop_pix, img.shape[0]))
    cropped = img[y1:y2, x1:x2]

    # Invert contrast (outside = white, inside = black)
    norm = (cropped - np.min(cropped)) / (np.max(cropped) - np.min(cropped) + 1e-8)
    img_inv = 1 - norm

    ax.imshow(img_inv, cmap="gray", vmin=0, vmax=1)
    circ = Circle((cx - x1, cy - y1), radius_pix, edgecolor="red", facecolor="none", linewidth=2)
    ax.add_patch(circ)
    ax.axis("off")

for j in range(i + 1, len(axes)):
    axes[j].axis("off")

plt.subplots_adjust(wspace=0.05, hspace=0.05)
plt.tight_layout()
plt.savefig(splash_path, dpi=200)
plt.show()
print(f"Splash view saved as {splash_path}")