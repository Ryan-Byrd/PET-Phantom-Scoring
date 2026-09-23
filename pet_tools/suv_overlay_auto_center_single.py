# -*- coding: utf-8 -*-
"""
SUV overlay - auto center, single ROI.

Purpose / scope:
- Select one PET DICOM slice from a series and place one 5 cm diameter ROI
  centered at an automatically detected phantom center.

Inputs:
- PET DICOM series folder (user-selected or --input-dir)
- Output folder (user-selected or --output-dir)
- Optional CLI settings for slice index, ROI diameter, and FOV

Outputs:
- CSV with SUV mean/max/min for the centered 5 cm ROI
- Overlay PNG with the single ROI drawn
- Optional debug image showing the detected center

Assumptions:
- Pixel spacing is valid and roughly uniform (row/col spacing are used)
- Phantom center can be detected on the selected slice

Math Notes:
- ROI mask is a circle in mm space using $r = \frac{\mathrm{ROI\_diam\_mm}}{2}$. A pixel
    is included when $(x-c_x)^2 + (y-c_y)^2 <= r^2$. SUV stats use the masked values.

Debug:
- Use --debug to enable extra logging and save a center-detection image.
"""

import argparse
import os
import sys

# Add parent directory to path so CT_Analysis_Toolkit can be found
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

from CT_Analysis_Toolkit.Modules.find_phantom_center import find_phantom_center_generalized

from pet_tools.suv_overlay_manual import (
    ask_folder,
    ask_output_folder_and_name,
    load_series,
    imshow_pet,
    suv_from_ds,
    circle_mask_mm,
    roi_inside_image,
    INFO,
    WARN,
    ERROR,
)


FOV_MM_DEFAULT = 250.0
ROI_DIAM_MM_DEFAULT = 50.0


def set_fov_mm(ax, center_mm, fov_mm=FOV_MM_DEFAULT):
    half = fov_mm / 2.0
    cx, cy = center_mm
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy + half, cy - half)


def select_one(images, pixel_mm):
    row_mm, col_mm = pixel_mm
    sel = []
    n = len(images)
    cols = 6
    rows = max(1, int(np.ceil(n / cols)))
    fig, axes = plt.subplots(rows, cols, figsize=(12, 2 + 2 * rows))
    axes = np.atleast_1d(axes).ravel()
    for i, ax in enumerate(axes):
        ax.axis("off")
        if i < n:
            h, w = images[i].shape
            extent = [0, w * col_mm, h * row_mm, 0]
            ax.imshow(images[i], cmap="gray", extent=extent, origin="upper")
            ax.set_aspect("equal")
            set_fov_mm(ax, (w * col_mm / 2.0, h * row_mm / 2.0), fov_mm=FOV_MM_DEFAULT)
            ax.set_title(f"Slice {i}", fontsize=8)
    fig.suptitle("Click 1 image (single-slice ROI)", fontsize=14)

    def onclick(e):
        if e.inaxes not in axes:
            return
        idx = list(axes).index(e.inaxes)
        if idx < n:
            sel[:] = [idx]
            e.inaxes.set_title("Selected", color="tab:blue")
            fig.canvas.draw_idle()
            plt.close(fig)

    fig.canvas.mpl_connect("button_press_event", onclick)
    plt.show()
    if len(sel) != 1:
        raise RuntimeError("Selection cancelled or no image chosen.")
    return sel[0]


def auto_center_px(ds, debug=False):
    modality = getattr(ds, "Modality", "PT").upper()
    pixel_spacing = np.mean([float(x) for x in ds.PixelSpacing])
    px_array = ds.pixel_array.astype(np.float32)

    cy, cx, radius_px = find_phantom_center_generalized(
        px_array,
        pixel_size_mm=pixel_spacing,
        modality=modality,
        debug=debug,
    )
    INFO(f"[{modality}] Auto center: x={cx:.1f}, y={cy:.1f}, radius={radius_px:.1f} px")
    return np.array([cx, cy]), px_array


def parse_args():
    parser = argparse.ArgumentParser(
        description="Select one slice and draw a centered ROI (default 5 cm)."
    )
    parser.add_argument("--input-dir", help="Folder containing PET DICOM files")
    parser.add_argument("--output-dir", help="Folder to write outputs")
    parser.add_argument(
        "--slice-index",
        type=int,
        help="Zero-based slice index (skips the selection UI)",
    )
    parser.add_argument(
        "--roi-diam-mm",
        type=float,
        default=ROI_DIAM_MM_DEFAULT,
        help="ROI diameter in mm (default: 50)",
    )
    parser.add_argument(
        "--fov-mm",
        type=float,
        default=FOV_MM_DEFAULT,
        help="Display field of view in mm (default: 250)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug outputs")
    return parser.parse_args()


def main():
    args = parse_args()

    try:
        in_dir = args.input_dir or ask_folder("Select PET DICOM Folder (INPUT)")
        if not in_dir:
            INFO("Cancelled: no input folder.")
            return

        if args.output_dir:
            out_dir = args.output_dir
            os.makedirs(out_dir, exist_ok=True)
        else:
            out_dir = ask_output_folder_and_name()
            if not out_dir:
                INFO("Cancelled: no output folder/name.")
                return

        INFO("Loading series...")
        disp_imgs, res_imgs, dsets, (row_mm, col_mm) = load_series(in_dir)
        INFO(f"Usable frames: {len(disp_imgs)} | PixelSpacing: {row_mm} x {col_mm} mm")

        if args.slice_index is None:
            slice_idx = select_one(disp_imgs, (row_mm, col_mm))
        else:
            if args.slice_index < 0 or args.slice_index >= len(disp_imgs):
                raise RuntimeError("--slice-index out of range for this series.")
            slice_idx = args.slice_index
        INFO(f"Selected slice: {slice_idx}")

        img_disp = disp_imgs[slice_idx]
        img_res = res_imgs[slice_idx]
        ds = dsets[slice_idx]

        suv_img, suv_note, _ = suv_from_ds(ds, img_res)
        suv_img = np.nan_to_num(suv_img, nan=0.0, posinf=3.0, neginf=0.0)
        INFO(f"SUV note: {suv_note}")

        center_px, center_dbg_img = auto_center_px(ds, debug=args.debug)
        center_mm = np.array([center_px[0] * col_mm, center_px[1] * row_mm])
        roi_r = args.roi_diam_mm / 2.0

        if not roi_inside_image(suv_img.shape, center_mm, roi_r, (row_mm, col_mm)):
            WARN("Centered ROI extends outside the image bounds.")
        mask = circle_mask_mm(suv_img.shape, center_mm, roi_r, (row_mm, col_mm))
        vals = suv_img[mask]
        if vals.size == 0:
            roi_mean = roi_max = roi_min = float("nan")
        else:
            roi_mean = float(np.nanmean(vals))
            roi_max = float(np.nanmax(vals))
            roi_min = float(np.nanmin(vals))

        csv_path = os.path.join(out_dir, "SUV_centered_5cm_roi.csv")
        with open(csv_path, "w", newline="") as f:
            f.write("ROI Label,SUVmean,SUVmax,SUVmin\n")
            f.write(
                f"Centered {args.roi_diam_mm:.1f}mm,{roi_mean:.6f},{roi_max:.6f},{roi_min:.6f}\n"
            )
        INFO(f"Saved ROI CSV -> {csv_path}")

        h, w = suv_img.shape
        extent = [0, w * col_mm, h * row_mm, 0]
        fig, ax = plt.subplots()
        imshow_pet(ax, ds, suv_img, img_res, extent)
        ax.set_aspect("equal")
        set_fov_mm(ax, center_mm, fov_mm=args.fov_mm)
        ax.add_patch(Circle((center_mm[0], center_mm[1]), roi_r, fill=False, color="maroon", lw=1))
        ax.text(
            center_mm[0],
            center_mm[1],
            f"Mean={roi_mean:.2f}\nMax={roi_max:.2f}\nMin={roi_min:.2f}",
            color="maroon",
            fontsize=10,
            ha="center",
            va="center",
        )
        ax.axis("off")

        overlay_path = os.path.join(out_dir, "SUV_centered_5cm_overlay.png")
        fig.savefig(overlay_path, dpi=300, bbox_inches="tight")
        INFO(f"Saved overlay PNG -> {overlay_path}")

        if args.debug:
            dbg_path = os.path.join(out_dir, "center_detection_debug.png")
            fig_dbg, ax_dbg = plt.subplots(figsize=(7, 7))
            ax_dbg.imshow(center_dbg_img, cmap="gray")
            ax_dbg.plot(center_px[0], center_px[1], "ro", ms=8)
            ax_dbg.set_title("Auto center (pixel space)")
            fig_dbg.savefig(dbg_path, dpi=200, bbox_inches="tight")
            plt.close(fig_dbg)
            INFO(f"Saved debug center image -> {dbg_path}")

        plt.show()
        INFO("Done.")

    except Exception as e:
        ERROR(str(e))


if __name__ == "__main__":
    main()
