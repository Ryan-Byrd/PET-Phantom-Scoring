import os
import sys
import glob
import csv
import argparse
import tkinter as tk
from tkinter import filedialog

import pydicom
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from scipy.optimize import curve_fit
from scipy.signal import find_peaks
from scipy.ndimage import map_coordinates


def _ensure_ct_toolkit_on_path():
    """Prepend CT toolkit/repo root so imports succeed when run standalone."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ct_path = os.path.join(base_dir, "CT_Analysis_Toolkit")
    for p in (ct_path, base_dir):
        if p and p not in sys.path:
            sys.path.insert(0, p)


_ensure_ct_toolkit_on_path()

from CT_Analysis_Toolkit.Modules.find_phantom_center import find_phantom_center_generalized


def ask_folder(prompt: str) -> str:
    root = tk.Tk()
    root.withdraw()
    return filedialog.askdirectory(title=prompt)


def normalize_results_dir(out_dir: str) -> str:
    """
    Always write into a 'Uniformity_Results' folder, but avoid double-appending.
    """
    out_dir = os.path.abspath(out_dir)
    if os.path.basename(out_dir).lower() == "uniformity_results":
        return out_dir
    return os.path.join(out_dir, "Uniformity_Results")


def _sigmoid_edge(z: np.ndarray, amplitude: float, baseline: float, blur_width: float, z0: float) -> np.ndarray:
    """
    Logistic edge model for axial phantom boundary.

    f(z) = A / (1 + exp(-(z - z0)/k)) + C

    Parameters map to:
      A = amplitude, C = baseline, k = blur_width, z0 = edge location.
    """
    return amplitude / (1.0 + np.exp(-(z - z0) / blur_width)) + baseline


def _select_central_slices_from_profile(
    z_positions_mm: np.ndarray,
    roi_means: np.ndarray,
    central_fraction: float,
    debug: bool,
    debug_dir: str,
) -> tuple[int, int, dict]:
    """
    Select the central fraction of the phantom using edge fits on the ROI mean profile.

    Approach:
      1) Compute derivative of mean vs. z to identify two edge centers.
      2) For each edge center, fit a sigmoid to the ROI mean profile using 10 points
         centered around the derivative peak. The fitted z0 gives the edge location.
      3) Keep the central fraction (default 95%) of the axial extent between the two z0s.

    Returns:
      (start_index, end_index, debug_info)
    """
    if len(z_positions_mm) < 12:
        raise ValueError("Not enough slices to estimate phantom extent.")

    dz = np.gradient(roi_means, z_positions_mm)
    peak_candidates, _ = find_peaks(np.abs(dz))
    if len(peak_candidates) < 2:
        raise ValueError("Could not find two edge peaks in derivative profile.")

    # Take the two strongest peaks in |dmean/dz|
    peak_strength = np.abs(dz[peak_candidates])
    top_two = peak_candidates[np.argsort(peak_strength)[-2:]]
    top_two = np.sort(top_two)

    fit_results = []
    half_window = 5  # 10 points total

    for peak_idx in top_two:
        start = max(0, peak_idx - half_window)
        end = min(len(z_positions_mm), peak_idx + half_window)

        z_fit = z_positions_mm[start:end]
        y_fit = roi_means[start:end]

        if len(z_fit) < 6:
            raise ValueError("Insufficient points for edge fit around derivative peak.")

        y_min = float(np.min(y_fit))
        y_max = float(np.max(y_fit))
        amplitude_guess = y_max - y_min
        baseline_guess = y_min
        blur_guess = max(np.median(np.diff(z_fit)), 1.0)
        z0_guess = float(z_positions_mm[peak_idx])

        p0 = [amplitude_guess, baseline_guess, blur_guess, z0_guess]

        try:
            popt, _ = curve_fit(_sigmoid_edge, z_fit, y_fit, p0=p0, maxfev=10000)
        except Exception as exc:
            raise ValueError(f"Sigmoid fit failed near z={z0_guess:.2f} mm: {exc}")

        amplitude, baseline, blur_width, z0 = popt
        fit_results.append(
            {
                "peak_index": int(peak_idx),
                "z0_mm": float(z0),
                "amplitude": float(amplitude),
                "baseline": float(baseline),
                "blur_width_mm": float(blur_width),
                "fit_start_index": int(start),
                "fit_end_index": int(end - 1),
            }
        )

    z0_low, z0_high = sorted([fit_results[0]["z0_mm"], fit_results[1]["z0_mm"]])
    phantom_extent = z0_high - z0_low
    if phantom_extent <= 0:
        raise ValueError("Invalid phantom extent from edge fits.")

    trim_fraction = (1.0 - central_fraction) / 2.0
    z_min = z0_low + trim_fraction * phantom_extent
    z_max = z0_high - trim_fraction * phantom_extent

    start_index = int(np.searchsorted(z_positions_mm, z_min, side="left"))
    end_index = int(np.searchsorted(z_positions_mm, z_max, side="right") - 1)

    if start_index >= end_index:
        raise ValueError("Central range selection collapsed; check edge fits.")

    debug_info = {
        "z0_low_mm": float(z0_low),
        "z0_high_mm": float(z0_high),
        "phantom_extent_mm": float(phantom_extent),
        "z_min_mm": float(z_min),
        "z_max_mm": float(z_max),
        "fit_results": fit_results,
    }

    if debug:
        os.makedirs(debug_dir, exist_ok=True)
        fig, ax1 = plt.subplots(figsize=(10, 5))
        ax1.plot(z_positions_mm, roi_means, color="black", label="ROI mean")
        ax1.set_xlabel("Z (mm)")
        ax1.set_ylabel("ROI mean (SUV)")

        for res in fit_results:
            z_fit = z_positions_mm[res["fit_start_index"]:res["fit_end_index"] + 1]
            y_fit = _sigmoid_edge(
                z_fit,
                res["amplitude"],
                res["baseline"],
                res["blur_width_mm"],
                res["z0_mm"],
            )
            ax1.plot(z_fit, y_fit, linestyle="--", label=f"Sigmoid fit @ z0={res['z0_mm']:.1f} mm")

        ax1.axvline(z0_low, color="blue", linestyle=":", label="Edge z0")
        ax1.axvline(z0_high, color="blue", linestyle=":")
        ax1.axvspan(z_min, z_max, color="green", alpha=0.1, label="Central 95%")
        ax1.legend(loc="best")
        ax1.grid(True, linestyle="--", linewidth=0.5)

        ax2 = ax1.twinx()
        ax2.plot(z_positions_mm, dz, color="orange", alpha=0.6, label="d(mean)/dz")
        ax2.set_ylabel("d(ROI mean)/dz")
        ax2.legend(loc="upper right")

        plt.tight_layout()
        debug_path = os.path.join(debug_dir, "uniformity_edge_fit_debug.png")
        plt.savefig(debug_path, dpi=200, bbox_inches="tight")
        plt.close(fig)

    return start_index, end_index, debug_info

def auto_radius(
        r_frac: float, 
        mid_img_full: np.ndarray, 
        spacing: float, 
        cx: float, 
        cy: float,
        debug: bool
        ) -> float:
    # -----------------------------
    # Show image and select points
    # -----------------------------
    '''
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(mid_img_full, cmap='gray')
    ax.set_title("Click start and end point")

    points = plt.ginput(2)
    plt.close()

    '''
    distance_mm = 120  # Desired physical distance between points in mm
    distance_px = distance_mm / spacing
    x1, x2 = cx + distance_px, cx - distance_px
    y1, y2 = cy, cy
    #(x1, y1), (x2, y2) = points
    num_points = int(np.hypot(x2 - x1, y2 - y1))

    x = np.linspace(x1, x2, num_points)
    y = np.linspace(y1, y2, num_points)

    profile = map_coordinates(mid_img_full, [y, x], order=1)
    distance = np.arange(len(profile)) * spacing
    grad_mag = np.abs(np.gradient(profile, spacing))
    peaks, _ = find_peaks(grad_mag, height=np.max(grad_mag) * 0.5)
    radius_pix = abs(peaks[0] - peaks[1]) / 2.0 if len(peaks) > 1 else 0.0
    radius_mm = radius_pix * spacing
    adjusted_r = radius_mm * r_frac
    
    # -----------------------------
    # Plot results
    # -----------------------------
    if debug:
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(12, 5))
        print(f"radius_mm={radius_mm:.2f}, radius_px={radius_pix:.2f}, adjusted_r={adjusted_r:.2f}")
        print(f"spacing betwen pixels={spacing:.2f} mm")
        print(peaks)
        ax1.imshow(mid_img_full, cmap='gray')
        ax1.plot([x1, x2], [y1, y2], 'r-', linewidth=2)
        ax1.set_title("Selected Line")
        xlabel = "Distance (mm)"

        ax2.plot(distance, profile)
        ax2.set_title("Line Profile")
        ax2.set_xlabel(xlabel)
        ax2.set_ylabel("Pixel Intensity")
        for peak in peaks:
            ax2.axvline(distance[peak], color='red', linestyle='--', alpha=0.7)

        ax3.plot(distance, grad_mag)
        ax3.set_title("Gradient for Line Profile")
        ax3.set_xlabel(xlabel)
        ax3.set_ylabel("Gradient Intensity")
        for peak in peaks:
            ax3.axvline(distance[peak], color='red', linestyle='--', alpha=0.7)

        plt.tight_layout()
        plt.show()

    return adjusted_r  


def _load_dicom_series(in_dir: str) -> list:
    """Load and Z-sort all DICOM slices in one series folder."""
    files = sorted(glob.glob(os.path.join(in_dir, "*.dcm")))
    if not files:
        raise ValueError(f"No DICOM files found in: {in_dir}")
    slices = [pydicom.dcmread(f) for f in files]
    slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))
    return slices


def _make_suv_getter(slices: list):
    """Build a get_suv(pixel_array_float32) closure using this series' rescale values."""
    slope = float(slices[0].RescaleSlope)
    intercept = float(slices[0].RescaleIntercept)

    def get_suv(slice_data: np.ndarray) -> np.ndarray:
        return slice_data * slope + intercept

    return get_suv


def _series_label(slices: list, series_dir: str) -> str:
    """Return the PET reconstruction label from (0054,1103), with fallbacks."""
    ds = slices[0]
    for tag in ("ReconstructionMethod", "SeriesDescription", "ProtocolName"):
        value = str(getattr(ds, tag, "") or "").strip()
        if value:
            return value
    return os.path.basename(os.path.normpath(series_dir))


def _compute_reference_roi_and_range(
    slices: list,
    pixel_spacing: list,
    debug: bool,
    debug_dir: str,
) -> tuple[float, float, float, int, int]:
    """
    Compute the phantom ROI (center/radius) and the central axial slice range
    from one reference series. Compare mode reuses this ROI and range across
    every other series instead of recomputing it, since comparison series are
    reconstructions of the same raw PET data and share identical geometry.
    """
    get_suv = _make_suv_getter(slices)
    mid_index = len(slices) // 2
    mid_img_full = get_suv(slices[mid_index].pixel_array.astype(np.float32))

    cy, cx, _radius_px = find_phantom_center_generalized(
        mid_img_full,
        pixel_size_mm=pixel_spacing[0],
        modality="PET",
        debug=True,
    )

    r_Frac = 0.90  # Fraction of distance to edge to use as ROI radius
    roi_radius_mm = auto_radius(r_Frac, mid_img_full, spacing=pixel_spacing[0], cx=cx, cy=cy, debug=debug)
    roi_radius_px = roi_radius_mm / pixel_spacing[0]

    yy, xx = np.ogrid[:slices[0].pixel_array.shape[0], :slices[0].pixel_array.shape[1]]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= roi_radius_px ** 2

    z_positions_mm = np.array([float(s.ImagePositionPatient[2]) for s in slices], dtype=float)
    roi_means_all = np.array(
        [float(np.mean(get_suv(s.pixel_array.astype(np.float32))[mask])) for s in slices],
        dtype=float,
    )

    central_fraction = 0.85  # Keep central 85% by default
    start_idx, end_idx, edge_debug = _select_central_slices_from_profile(
        z_positions_mm,
        roi_means_all,
        central_fraction=central_fraction,
        debug=debug,
        debug_dir=debug_dir,
    )
    print(
        f"Edge z0 (mm): {edge_debug['z0_low_mm']:.2f} \u2192 {edge_debug['z0_high_mm']:.2f} "
        f"(extent {edge_debug['phantom_extent_mm']:.2f} mm)"
    )
    print(
        f"Auto-selected central {int(central_fraction * 100)}% slice range: "
        f"{start_idx} \u2192 {end_idx}"
    )

    return cx, cy, roi_radius_px, start_idx, end_idx


def _compute_series_deviations(
    slices: list,
    cx: float,
    cy: float,
    roi_radius_px: float,
    start_idx: int,
    end_idx: int,
) -> tuple[list, list]:
    """Apply a shared ROI and slice range to one series, returning (roi_means, deviations)."""
    get_suv = _make_suv_getter(slices)

    # Clip the reference range to this series' own slice count in case a
    # comparison series was reconstructed with a different number of slices.
    clipped_end = min(end_idx, len(slices) - 1)
    if start_idx > clipped_end:
        raise ValueError("Reference slice range does not fit this series.")
    series_slices = slices[start_idx:clipped_end + 1]

    yy, xx = np.ogrid[:series_slices[0].pixel_array.shape[0], :series_slices[0].pixel_array.shape[1]]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= roi_radius_px ** 2

    roi_means = [
        float(np.mean(get_suv(s.pixel_array.astype(np.float32))[mask]))
        for s in series_slices
    ]
    global_mean = float(np.mean(roi_means)) if roi_means else 0.0
    deviations = (
        [((m / global_mean) - 1) * 100 for m in roi_means] if global_mean != 0 else [0.0] * len(roi_means)
    )
    return roi_means, deviations


def run_compare_mode(series_dirs: list, output_dir: str, debug: bool, debug_dir: str) -> int:
    """
    Overlay uniformity deviation curves for several reconstructions of one exam.

    The first directory in series_dirs is the reference: its ROI (center,
    radius) and central axial slice range are computed once and then reused
    for every other series. Each series' deviation is still normalized against
    its own mean, since uniformity deviation is an intra-series metric; only
    the ROI/slice-range geometry is shared. No splash view is produced in this
    mode -- only a combined CSV and one superimposed deviation plot.
    """
    if len(series_dirs) < 2:
        raise ValueError("Compare mode requires at least two series directories.")

    reference_slices = _load_dicom_series(series_dirs[0])
    pixel_spacing = [float(x) for x in reference_slices[0].PixelSpacing]
    cx, cy, roi_radius_px, start_idx, end_idx = _compute_reference_roi_and_range(
        reference_slices, pixel_spacing, debug=debug, debug_dir=debug_dir,
    )

    series_results = []
    for series_dir in series_dirs:
        slices = reference_slices if series_dir == series_dirs[0] else _load_dicom_series(series_dir)
        label = _series_label(slices, series_dir)
        roi_means, deviations = _compute_series_deviations(
            slices, cx, cy, roi_radius_px, start_idx, end_idx,
        )
        series_results.append({
            "label": label,
            "path": series_dir,
            "roi_means": roi_means,
            "deviations": deviations,
        })
        print(f"[INFO] {label}: {len(deviations)} slices, ROI mean {np.mean(roi_means):.2f}")

    # --- Save combined CSV ---
    csv_path = os.path.join(output_dir, "PET_ROI_Results_Compare.csv")
    max_len = max(len(r["deviations"]) for r in series_results)
    with open(csv_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["SliceNumber"] + [f"{r['label']} Deviation(%)" for r in series_results])
        for i in range(max_len):
            row = [i + 1]
            for r in series_results:
                row.append(r["deviations"][i] if i < len(r["deviations"]) else "")
            writer.writerow(row)
    print(f"Results saved to {csv_path}")

    # --- Overlaid deviation plot ---
    plot_path = os.path.join(output_dir, "PET_DeviationPlot_Compare.png")
    plt.figure(figsize=(10, 6))
    x = np.arange(1, max_len + 1)

    plt.fill_between(x, -5, 5, color="green", alpha=0.15, label="Pass band (\u00b15%)")
    plt.fill_between(x, 5, 10, color="yellow", alpha=0.15, label="Warning zone (5\u201310%)")
    plt.fill_between(x, -10, -5, color="yellow", alpha=0.15)
    plt.axhline(10, color="red", linestyle="--", linewidth=1.5, label="Fail limit (\u00b110%)")
    plt.axhline(-10, color="red", linestyle="--", linewidth=1.5)

    for result in series_results:
        curve_x = np.arange(1, len(result["deviations"]) + 1)
        plt.plot(curve_x, result["deviations"], marker="o", markersize=3, label=result["label"])

    plt.xlabel("Slice Number")
    plt.ylabel("Deviation (%)")
    plt.title("Uniformity Deviation: Multi-Series Comparison")
    plt.grid(True, linestyle="--", linewidth=0.5)
    plt.legend(loc="upper right", fontsize=8)
    plt.ylim(-25, 25)
    plt.tight_layout()
    plt.savefig(plot_path, dpi=200, bbox_inches="tight")
    plt.show()
    print(f"Comparison deviation plot saved to {plot_path}")

    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Automatic PET uniformity scoring and slice selection."
    )
    parser.add_argument("--input", "-i", help="Path to input DICOM folder (optional)")
    parser.add_argument("--output", "-o", help="Path to output folder (optional)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--debug-dir", help="Optional directory for debug artifacts")
    parser.add_argument(
        "--compare",
        nargs="+",
        metavar="SERIES_DIR",
        help=(
            "Compare-mode: two or more DICOM series directories (reconstructions of the "
            "same exam). The ROI and slice range are computed from the first directory "
            "and reused for the rest; deviation curves are superimposed on one plot "
            "instead of the normal single-series report/splash view."
        ),
    )
    args = parser.parse_args(argv)

    # ---------- Compare mode (multi-series overlay) ----------
    if args.compare:
        compare_dirs = [os.path.abspath(d) for d in args.compare]
        out_root = os.path.abspath(args.output) if args.output else compare_dirs[0]
        output_dir = normalize_results_dir(out_root)
        os.makedirs(output_dir, exist_ok=True)
        debug_dir = os.path.abspath(args.debug_dir) if args.debug_dir else output_dir
        return run_compare_mode(compare_dirs, output_dir, debug=args.debug, debug_dir=debug_dir)

    # ---------- Input / Output path resolution ----------
    if args.input:
        in_dir = os.path.abspath(args.input)
    else:
        in_dir = ask_folder("Select PET DICOM Folder (INPUT)")
        if not in_dir:
            print("[INFO] Cancelled: no input folder.")
            return 1

    if args.output:
        out_root = os.path.abspath(args.output)
    else:
        # If output not specified, default to the input folder
        out_root = in_dir

    output_dir = normalize_results_dir(out_root)
    os.makedirs(output_dir, exist_ok=True)

    debug_dir = os.path.abspath(args.debug_dir) if args.debug_dir else output_dir

    print(f"[INFO] Using input folder: {in_dir}")
    print(f"[INFO] Using output folder: {output_dir}")

    # --- Load DICOM series ---
    files = sorted(glob.glob(os.path.join(in_dir, "*.dcm")))
    if not files:
        print(f"No DICOM files found in: {in_dir}")
        return 1

    slices = [pydicom.dcmread(f) for f in files]
    slices.sort(key=lambda x: float(x.ImagePositionPatient[2]))  # sort by Z position

    pixel_spacing = [float(x) for x in slices[0].PixelSpacing]
    slope = float(slices[0].RescaleSlope)
    intercept = float(slices[0].RescaleIntercept)

    def get_suv(slice_data: np.ndarray) -> np.ndarray:
        return slice_data * slope + intercept

    # --- Automatic phantom center detection ---
    mid_index = len(slices) // 2
    mid_img_full = get_suv(slices[mid_index].pixel_array.astype(np.float32))

    cy, cx, radius_px = find_phantom_center_generalized(
        mid_img_full,
        pixel_size_mm=pixel_spacing[0],
        modality="PET",
        debug=True
    )

    # --- Find uniform slice range automatically using edge fits on ROI mean ---
    r_Frac = 0.90  # Fraction of distance to edge to use as ROI radius
    roi_radius_mm = auto_radius(r_Frac, mid_img_full, spacing=pixel_spacing[0], cx=cx, cy=cy, debug=args.debug)
    roi_radius_px = roi_radius_mm / pixel_spacing[0]

    yy, xx = np.ogrid[:slices[0].pixel_array.shape[0], :slices[0].pixel_array.shape[1]]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= roi_radius_px ** 2

    z_positions_mm = np.array([float(s.ImagePositionPatient[2]) for s in slices], dtype=float)
    roi_means_all = np.array(
        [float(np.mean(get_suv(s.pixel_array.astype(np.float32))[mask])) for s in slices],
        dtype=float,
    )

    central_fraction = 0.85  # Keep central 85% by default
    start_idx, end_idx, edge_debug = _select_central_slices_from_profile(
        z_positions_mm,
        roi_means_all,
        central_fraction=central_fraction,
        debug=args.debug,
        debug_dir=debug_dir,
    )

    print(
        f"Edge z0 (mm): {edge_debug['z0_low_mm']:.2f} → {edge_debug['z0_high_mm']:.2f} "
        f"(extent {edge_debug['phantom_extent_mm']:.2f} mm)"
    )

    print(
        f"Auto-selected central {int(central_fraction * 100)}% slice range: "
        f"{start_idx} → {end_idx}"
    )
    slices = slices[start_idx:end_idx + 1]
    print(f"Processing {len(slices)} slices ({start_idx} → {end_idx})")

    # --- ROI mean + deviations ---
    radius_pix = roi_radius_px
    roi_means = []
    for s in slices:
        img = get_suv(s.pixel_array.astype(np.float32))
        yy, xx = np.ogrid[:img.shape[0], :img.shape[1]]
        msk = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius_pix ** 2
        roi_means.append(float(np.mean(img[msk])))

    global_mean = float(np.mean(roi_means)) if roi_means else 0.0
    deviations = [((m / global_mean) - 1) * 100 for m in roi_means] if global_mean != 0 else [0.0] * len(roi_means)

    # --- Save CSV ---
    csv_path = os.path.join(output_dir, "PET_ROI_Results.csv")
    with open(csv_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["SliceNumber", "ROImean", "Deviation(%)"])
        for idx, (m, d) in enumerate(zip(roi_means, deviations), start=1):
            writer.writerow([idx, m, float(d)])
    print(f"Results saved to {csv_path}")

    # --- Deviation plot ---
    deviation_plot_path = os.path.join(output_dir, "PET_DeviationPlot.png")
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
    plt.ylim(-25, 25)

    plt.tight_layout()
    plt.savefig(deviation_plot_path, dpi=200, bbox_inches="tight")
    plt.show()
    print(f"Deviation plot saved to {deviation_plot_path}")

    # --- Splash view ---
    splash_path = os.path.join(output_dir, "PET_SplashView.png")
    crop_mm = auto_radius(1.1, mid_img_full, spacing=pixel_spacing[0], cx=cx, cy=cy, debug=False) * 2.0
    crop_pix = int((crop_mm / 2) / pixel_spacing[0])

    ncols = int((4/3) * np.ceil(np.sqrt(len(slices))))
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
        circ = Circle((cx - x1, cy - y1), radius_pix, edgecolor="#ffe5a8", facecolor="none", linewidth=2)
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
