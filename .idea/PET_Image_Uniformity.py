import os
import tkinter as tk
from tkinter import filedialog, simpledialog
import pydicom
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import glob
import csv

# --- Step 1: Select PET DICOM folder ---
root = tk.Tk()
root.withdraw()
dicom_folder = filedialog.askdirectory(title="Select folder containing PET DICOM series")
if not dicom_folder:
    print("No DICOM folder selected. Exiting.")
    exit()

# --- Step 2: Load DICOM series ---
files = sorted(glob.glob(os.path.join(dicom_folder, "*.dcm")))
if not files:
    print("No DICOM files found. Exiting.")
    exit()

slices = [pydicom.dcmread(f) for f in files]
slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))  # sort by Z

pixel_spacing = [float(x) for x in slices[0].PixelSpacing]
slope = float(slices[0].RescaleSlope)
intercept = float(slices[0].RescaleIntercept)

def get_suv(slice_data):
    return slice_data * slope + intercept

# --- Step 3: User clicks ROI center ---
mid_index = len(slices) // 2
mid_img = get_suv(slices[mid_index].pixel_array.astype(np.float32))
fig, ax = plt.subplots()
ax.imshow(mid_img, cmap="gray")
ax.set_title("Click ROI Center (180 mm diameter)")
coords = plt.ginput(1)
plt.close(fig)
if not coords:
    print("No center selected. Exiting.")
    exit()
cx, cy = coords[0]

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
lower_cut = int(total_slices * 0.075)
upper_cut = int(total_slices * 0.925)
central_indices = np.arange(lower_cut, upper_cut)
central_roi_means = [roi_means[i] for i in central_indices]

global_mean = np.mean(central_roi_means)
# deviation in percent
deviations = [((m / global_mean) - 1) * 100 for m in roi_means]

# --- Step 7: Output folder and naming ---
base_dir = filedialog.askdirectory(title="Select base folder to save results")
if not base_dir:
    print("No base folder selected. Exiting.")
    exit()
folder_name = simpledialog.askstring("Folder Name", "Enter a name for the results folder:")
if not folder_name:
    print("No folder name provided. Exiting.")
    exit()
output_dir = os.path.join(base_dir, folder_name)
os.makedirs(output_dir, exist_ok=True)

csv_path = os.path.join(output_dir, "PET_ROI_Results.csv")
deviation_plot_path = os.path.join(output_dir, "PET_DeviationPlot.png")
splash_path = os.path.join(output_dir, "PET_SplashView.png")

# --- Step 8: Save CSV (deviation in percent) ---
with open(csv_path, "w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["SliceNumber", "ROImean", "Deviation(%)"])
    for idx, (m, d) in enumerate(zip(roi_means, deviations)):
        writer.writerow([idx + 1, m, d])
print(f"Results saved to {csv_path}")

# --- Step 9: Deviation plot (200 DPI, central 85 %) ---
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
plt.axvspan(lower_cut + 1, upper_cut, color="blue", alpha=0.08, label="Central 85% region")

plt.xlabel("Slice Number")
plt.ylabel("Deviation (%)")
plt.grid(True, linestyle="--", linewidth=0.5)
plt.legend(loc="upper right")

plt.tight_layout()
plt.savefig(deviation_plot_path, dpi=200, bbox_inches="tight")
plt.show()
print(f"Deviation plot saved to {deviation_plot_path}")

# --- Step 10: Splash view (cropped 250×250 mm, inverted) ---
crop_mm = 250
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
    circ = Circle((cx - x1, cy - y1), radius_pix, edgecolor="red", facecolor="none", linewidth=3)
    ax.add_patch(circ)
    ax.axis("off")

for j in range(i + 1, len(axes)):
    axes[j].axis("off")

plt.subplots_adjust(wspace=0.05, hspace=0.05)
plt.tight_layout()
plt.savefig(splash_path, dpi=200)
plt.show()
print(f"Splash view saved as {splash_path}")
