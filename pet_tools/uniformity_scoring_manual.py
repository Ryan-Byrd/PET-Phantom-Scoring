import argparse
import os
import glob
import csv
import tkinter as tk
from tkinter import filedialog, simpledialog

import pydicom
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Cursor
from matplotlib.patches import Circle


def select_start_end(images, pixel_spacing):
    """
    Displays a 16:9 grid of cropped, inverted PET slices
    and lets the user click the first and last slices to process.
    Returns (start_idx, end_idx) in 0-based indices.
    """
    row_mm, col_mm = pixel_spacing
    n = len(images)
    if n == 0:
        print("No images provided.")
        return None

    # --- Crop size in mm (display only) ---
    crop_mm = 300
    crop_pix = int((crop_mm / 2) / row_mm)

    cropped_imgs = []
    for img in images:
        h, w = img.shape
        cy, cx = h // 2, w // 2
        y1, y2 = max(cy - crop_pix, 0), min(cy + crop_pix, h)
        x1, x2 = max(cx - crop_pix, 0), min(cx + crop_pix, w)
        crop = img[y1:y2, x1:x2].astype(np.float32)

        # Normalize and invert (center dark, outside bright)
        denom = (np.max(crop) - np.min(crop) + 1e-8)
        norm = (crop - np.min(crop)) / denom
        inv = 1 - norm
        cropped_imgs.append(inv)

    # --- Choose grid close to 16:9 ---
    cols = int(np.ceil(np.sqrt(n * 16 / 9)))
    rows = int(np.ceil(n / cols))

    fig, axes = plt.subplots(rows, cols, figsize=(16, 9))
    axes = np.atleast_1d(axes).ravel()

    selected = []

    for i, ax in enumerate(axes):
        ax.axis("off")
        if i < n:
            img = cropped_imgs[i]
            h, w = img.shape
            extent = [0, w * col_mm, h * row_mm, 0]
            ax.imshow(img, cmap="gray", extent=extent, origin="upper", vmin=0, vmax=1)
            ax.set_aspect("equal")
            ax.set_title(f"Slice {i+1}", fontsize=8)
            Cursor(ax, useblit=True, color="red", linewidth=1)

    fig.suptitle("Click FIRST and LAST slices to process", fontsize=14)

    def onclick(event):
        if event.inaxes not in axes:
            return
        idx = list(axes).index(event.inaxes)
        if idx >= n or idx in selected:
            return
        selected.append(idx)
        label = "Start" if len(selected) == 1 else "End"
        event.inaxes.set_title(f"{label} (#{idx})", color="tab:blue")
        fig.canvas.draw_idle()
        if len(selected) == 2:
            plt.close(fig)

    fig.canvas.mpl_connect("button_press_event", onclick)
    plt.show()

    if len(selected) != 2:
        print("No valid selection made.")
        return None

    start_idx, end_idx = sorted(selected)
    print(f"Selected slices: {start_idx} → {end_idx}")
    return start_idx, end_idx


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Manual PET uniformity scoring: user picks slice range and ROI center."
    )
    parser.add_argument("--input", "-i", help="Input PET DICOM folder (optional; else dialog)")
    parser.add_argument("--output", "-o", help="Output PARENT folder; a results subfolder name is still prompted (optional; else dialogs)")
    parser.add_argument("--debug", action="store_true", help="Echo resolved parameters to the console")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    # --- Step 1: Select PET DICOM folder ---
    if args.input:
        dicom_folder = os.path.abspath(args.input)
    else:
        root = tk.Tk()
        root.withdraw()
        dicom_folder = filedialog.askdirectory(title="Select folder containing PET DICOM series")
        root.destroy()
    if not dicom_folder:
        print("No DICOM folder selected. Exiting.")
        return 1

    # --- Step 2: Load DICOM series ---
    files = sorted(glob.glob(os.path.join(dicom_folder, "*.dcm")))
    if not files:
        print("No DICOM files found. Exiting.")
        return 1

    slices = [pydicom.dcmread(f) for f in files]
    slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))  # sort by Z position

    pixel_spacing = [float(x) for x in slices[0].PixelSpacing]
    slope = float(slices[0].RescaleSlope)
    intercept = float(slices[0].RescaleIntercept)

    def get_suv(slice_data: np.ndarray) -> np.ndarray:
        return slice_data * slope + intercept

    # --- Step 2a: User selects range of slices to process ---
    preview_imgs = [s.pixel_array.astype(np.float32) for s in slices]
    selection = select_start_end(preview_imgs, pixel_spacing)
    if not selection:
        print("No slices selected. Exiting.")
        return 1

    start_idx, end_idx = selection
    if start_idx < 0 or end_idx >= len(slices):
        print("Invalid slice indices. Exiting.")
        return 1

    slices = slices[start_idx:end_idx + 1]
    print(f"Processing {len(slices)} slices ({start_idx} → {end_idx})")

    # --- Step 3: User clicks ROI center (cropped view) ---
    mid_index = len(slices) // 2
    mid_img_full = get_suv(slices[mid_index].pixel_array.astype(np.float32))

    crop_mm = 250
    crop_pix = int((crop_mm / 2) / pixel_spacing[0])

    cy_center = mid_img_full.shape[0] // 2
    cx_center = mid_img_full.shape[1] // 2
    x1 = max(cx_center - crop_pix, 0)
    x2 = min(cx_center + crop_pix, mid_img_full.shape[1])
    y1 = max(cy_center - crop_pix, 0)
    y2 = min(cy_center + crop_pix, mid_img_full.shape[0])
    mid_img = mid_img_full[y1:y2, x1:x2]

    fig, ax = plt.subplots()
    ax.imshow(mid_img, cmap="gray")
    ax.set_title("Click ROI Center (180 mm diameter, 250×250 mm view)")
    Cursor(ax, useblit=True, color="red", linewidth=1)

    coords = plt.ginput(1, timeout=-1)
    plt.close(fig)
    if not coords:
        print("No center selected. Exiting.")
        return 1

    cx = coords[0][0] + x1
    cy = coords[0][1] + y1

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

    # --- Step 6: Deviation (%) ---
    global_mean = float(np.mean(roi_means))
    deviations = [((m / global_mean) - 1) * 100 for m in roi_means]

    # --- Step 7: Output folder and naming ---
    if args.output:
        base_dir = os.path.abspath(args.output)
        os.makedirs(base_dir, exist_ok=True)
    else:
        base_dir = filedialog.askdirectory(title="Select base folder to save results")
        if not base_dir:
            print("No base folder selected. Exiting.")
            return 1

    folder_name = simpledialog.askstring("Folder Name", "Enter a name for the results folder:")
    if not folder_name:
        print("No folder name provided. Exiting.")
        return 1

    output_dir = os.path.join(base_dir, folder_name)
    os.makedirs(output_dir, exist_ok=True)

    if args.debug:
        print(f"[debug] input  : {dicom_folder}")
        print(f"[debug] output : {output_dir}")
        print(f"[debug] slices : {len(slices)} ({start_idx} to {end_idx})")

    csv_path = os.path.join(output_dir, "PET_ROI_Results.csv")
    deviation_plot_path = os.path.join(output_dir, "PET_DeviationPlot.png")
    splash_path = os.path.join(output_dir, "PET_SplashView.png")

    # --- Step 8: Save CSV ---
    with open(csv_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["SliceNumber", "ROImean", "Deviation(%)"])
        for idx, (m, d) in enumerate(zip(roi_means, deviations), start=1):
            writer.writerow([idx, float(m), float(d)])
    print(f"Results saved to {csv_path}")

    # --- Step 9: Deviation plot ---
    plt.figure(figsize=(9, 6))
    x = np.arange(1, len(deviations) + 1)
    plt.plot(x, deviations, marker="o", color="black", label="Slice deviation")

    plt.fill_between(x, -5, 5, color="green", alpha=0.15, label="Pass band (±5%)")
    plt.fill_between(x, 5, 10, color="yellow", alpha=0.15, label="Warning zone (5–10%)")
    plt.fill_between(x, -10, -5, color="yellow", alpha=0.15)
    plt.axhline(10, color="red", linestyle="--", linewidth=1.5, label="Fail limit (±10%)")
    plt.axhline(-10, color="red", linestyle="--", linewidth=1.5)

    plt.xlabel("Slice Number")
    plt.ylabel("Deviation (%)")
    plt.grid(True, linestyle="--", linewidth=0.5)
    plt.legend(loc="upper right")

    plt.tight_layout()
    plt.savefig(deviation_plot_path, dpi=200, bbox_inches="tight")
    plt.show()
    print(f"Deviation plot saved to {deviation_plot_path}")

    # --- Step 10: Splash view ---
    crop_mm = 250
    crop_pix = int((crop_mm / 2) / pixel_spacing[0])
    ncols = 8
    nrows = int(np.ceil(len(slices) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(12, 12))
    axes = axes.ravel()

    for i, (s, ax) in enumerate(zip(slices, axes)):
        img = get_suv(s.pixel_array.astype(np.float32))

        x1 = int(max(cx - crop_pix, 0))
        x2 = int(min(cx + crop_pix, img.shape[1]))
        y1 = int(max(cy - crop_pix, 0))
        y2 = int(min(cy + crop_pix, img.shape[0]))
        cropped = img[y1:y2, x1:x2]

        denom = (np.max(cropped) - np.min(cropped) + 1e-8)
        norm = (cropped - np.min(cropped)) / denom
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
