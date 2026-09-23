#!/usr/bin/env python3
"""
Z-Axis Coregistration Analysis — Per-slice center detection with pitch/yaw error calculation.

Purpose
-------
For each slice within the analysis window, computes the center (center-of-mass) of the phantom,
then fits linear regressions to show how center position varies with z-position for each series.
Calculates angular errors (pitch/yaw) and Cartesian coordinate errors between series.

Features
--------
- Per-slice phantom center detection using OpenCV Hough-circle boundary fitting
- Linear regression fits: center_x = m*z + b, center_y = m*z + b
- Angular error calculation (pitch and yaw in degrees and milliradians)
- Cartesian coordinate error (ΔX, ΔY, ΔZ, 3D Euclidean distance)
- Visualization plots showing center positions and regression fits
- Optional debug splash view showing detected centers and estimated circles
- JSON output with complete regression coefficients and error metrics

Usage
-----
    python z_axis_coregistration.py --series1 /path/to/series1 --series2 /path/to/series2
    python z_axis_coregistration.py --series1 s1 --series2 s2 --window 100
    python z_axis_coregistration.py --series1 s1 --series2 s2 --debug
    python z_axis_coregistration.py --series1 s1 --series2 s2 --center-crop-mm 250
    python z_axis_coregistration.py --series1 s1 --series2 s2 --canny-low-q 25 --canny-high-q 70
    python z_axis_coregistration.py --series1 s1 --series2 s2 --hough-radius-step 3 --hough-max-radii 20
    python z_axis_coregistration.py --series1 s1 --series2 s2 --approx-radius-mm 100
    python z_axis_coregistration.py --series1 s1 --series2 s2 --table-exclusion-mm 30
    python z_axis_coregistration.py --series1 s1 --series2 s2 --output results

Inputs
------
series1_dir, series2_dir : str
    Paths to DICOM series folders.
window_mm : float, optional
    Analysis window half-width in mm around FWHM midpoint (default: 75 mm).
output_dir : str, optional
    Directory to save JSON and plots (default: "roi_profiles").

Outputs
-------
z_axis_coregistration.json : data/
    JSON with regression coefficients, angular errors, Cartesian errors
z_axis_coregistration_plot.png : images/
    Visualization of center positions vs z with regression fits

Mathematical Notes
-------------------
**Center Detection:**
    For each 2D slice, detect phantom boundary using Hough-circle transform.
    If Hough detection fails on a slice, fallback uses toolkit/centroid methods:
        center_x = Σ(x * I) / Σ(I)
        center_y = Σ(y * I) / Σ(I)

**Linear Regression:**
  Fit: center_x = slope * z + intercept

**Angular Errors:**
  Yaw:   θ_yaw = arctan(slope_x)
  Pitch: θ_pitch = arctan(slope_y)

**Cartesian Errors:**
  ΔX, ΔY, ΔZ, 3D distance = sqrt(ΔX² + ΔY² + ΔZ²)
"""

import os
import sys
import argparse
import json
import csv
import numpy as np
import importlib
from pathlib import Path
from scipy import stats
from scipy import ndimage
import matplotlib.pyplot as plt
from matplotlib.patches import Circle


# Ensure repo root is on path for module imports
_REPO_ROOT = Path(__file__).parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Logging helpers
def INFO(msg):
    print(f"[INFO] {msg}")

def SUCCESS(msg):
    print(f"[OK] {msg}")

def ERROR(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)


_TOOLKIT_CENTER_DETECTOR_MODULE = None
_TOOLKIT_CENTER_DETECTOR_ERROR = None
_OPENCV_HOUGH_WARNING_EMITTED = False


def _get_toolkit_center_detector_module():
    """Load toolkit center-detector module once and cache success/failure."""
    global _TOOLKIT_CENTER_DETECTOR_MODULE
    global _TOOLKIT_CENTER_DETECTOR_ERROR

    if _TOOLKIT_CENTER_DETECTOR_MODULE is not None:
        return _TOOLKIT_CENTER_DETECTOR_MODULE
    if _TOOLKIT_CENTER_DETECTOR_ERROR is not None:
        return None

    try:
        import CT_Analysis_Toolkit.Modules.find_phantom_center as center_module

        _TOOLKIT_CENTER_DETECTOR_MODULE = center_module
        return _TOOLKIT_CENTER_DETECTOR_MODULE
    except Exception as exc:
        _TOOLKIT_CENTER_DETECTOR_ERROR = exc
        ERROR(
            "CT toolkit center detector unavailable; falling back to centroid detection. "
            f"Reason: {exc}. Install dependency: pip install scikit-image"
        )
        return None


def select_dicom_folders():
    """Open file dialog to select two DICOM series folders."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox
    except ImportError:
        ERROR("tkinter not available. Please specify --series1 and --series2 on command line.")
        sys.exit(1)
    
    root = tk.Tk()
    root.withdraw()  # Hide main window
    
    # Show instruction dialog
    messagebox.showinfo(
        "Z-Axis Coregistration Analysis",
        "You will select TWO DICOM series folders:\n\n"
        "1. First series (e.g., PET)\n"
        "2. Second series (e.g., CT)\n\n"
        "Click OK to begin."
    )
    
    INFO("Opening folder selection for Series 1...")
    series1 = filedialog.askdirectory(title="Select Series 1 (PET/CT) Folder - First Series")
    if not series1:
        ERROR("No Series 1 folder selected")
        sys.exit(1)
    INFO(f"Series 1 selected: {Path(series1).name}")
    
    INFO("Opening folder selection for Series 2...")
    series2 = filedialog.askdirectory(title="Select Series 2 (PET/CT) Folder - Second Series")
    if not series2:
        ERROR("No Series 2 folder selected")
        sys.exit(1)
    INFO(f"Series 2 selected: {Path(series2).name}")
    
    # Optional: Ask for output directory
    INFO("Select output directory (or Cancel to use default 'roi_profiles')")
    output_dir = filedialog.askdirectory(title="Select Output Directory (Cancel for default)")
    if not output_dir:
        output_dir = None  # Will use default
        INFO("Using default output directory: roi_profiles")
    else:
        INFO(f"Output directory selected: {Path(output_dir).name}")
    
    return series1, series2, output_dir


def load_profile_data(csv_path):
    """Load ROI profile data from CSV file."""
    data = {
        'slice_index': [],
        'z_position_mm': [],
        'series1_mean': [],
        'series2_mean': []
    }
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data['slice_index'].append(int(row['slice_index']))
            data['z_position_mm'].append(float(row['z_position_mm']))
            data['series1_mean'].append(float(row['series1_mean']))
            data['series2_mean'].append(float(row['series2_mean']))
    
    return data


def load_peak_data(json_path):
    """Load FWHM peak data from JSON file."""
    with open(json_path, 'r') as f:
        return json.load(f)


def generate_peak_data(series1_dir, series2_dir, output_dir):
    """
    Run roi_axial_profile to generate roi_profile_peaks.json.

    This will create the peaks JSON for PET (2 peaks) and CT (4 peaks)
    using the same series paths provided to this script.
    """
    INFO("Peak data missing; running roi_axial_profile to generate it...")
    try:
        module = importlib.import_module("pet_tools.roi_axial_profile")
    except Exception as exc:
        ERROR(f"Failed to import roi_axial_profile: {exc}")
        return 1

    old_argv = sys.argv[:]
    sys.argv = [
        "roi_axial_profile.py",
        "--series1",
        series1_dir,
        "--series2",
        series2_dir,
        "--output",
        str(output_dir),
    ]
    try:
        return_code = module.main()
    except SystemExit as exc:
        return_code = int(exc.code) if isinstance(exc.code, int) else 1
    except Exception as exc:
        ERROR(f"roi_axial_profile failed: {exc}")
        return_code = 1
    finally:
        sys.argv = old_argv

    return return_code


def compute_slice_center(profile_values_2d, pixel_spacing_mm):
    """
    Compute the center-of-mass (centroid) of a 2D ROI slice.
    
    This mimics the phantom center detection approach: treat intensity
    as a mass distribution and find the weighted center position.
    
    Args:
        profile_values_2d: 2D array of pixel values for a single slice
        pixel_spacing_mm: Pixel spacing in mm
    
    Returns:
        tuple: (center_y_mm, center_x_mm) relative to image center
    """
    # Shift to positive values
    values_shifted = profile_values_2d - np.min(profile_values_2d)
    
    if np.sum(values_shifted) == 0:
        return 0.0, 0.0
    
    # Create coordinate arrays
    rows, cols = profile_values_2d.shape
    y_coords = np.arange(rows) - rows / 2.0  # Relative to center
    x_coords = np.arange(cols) - cols / 2.0
    
    Y, X = np.meshgrid(y_coords, x_coords, indexing='ij')
    
    # Compute center of mass
    total_mass = np.sum(values_shifted)
    center_y = np.sum(Y * values_shifted) / total_mass
    center_x = np.sum(X * values_shifted) / total_mass
    
    # Convert to mm
    center_y_mm = center_y * pixel_spacing_mm
    center_x_mm = center_x * pixel_spacing_mm
    
    return center_y_mm, center_x_mm


def estimate_slice_circle_radius_mm(profile_values_2d, pixel_spacing_mm):
    """
    Estimate an effective phantom radius for debug visualization.

    The radius is derived from the area of a high-intensity mask so reviewers can
    visually verify center placement and approximate phantom footprint.
    """
    values_shifted = profile_values_2d - np.min(profile_values_2d)
    if np.sum(values_shifted) <= 0:
        rows, cols = profile_values_2d.shape
        fallback_radius_px = 0.2 * min(rows, cols)
        return float(fallback_radius_px * pixel_spacing_mm)

    threshold = np.percentile(values_shifted, 75.0)
    mask = values_shifted >= threshold
    area_px = int(np.count_nonzero(mask))

    if area_px <= 0:
        rows, cols = profile_values_2d.shape
        fallback_radius_px = 0.2 * min(rows, cols)
        return float(fallback_radius_px * pixel_spacing_mm)

    radius_px = np.sqrt(area_px / np.pi)
    return float(radius_px * pixel_spacing_mm)


def _center_detector_modality(modality):
    """Map DICOM modality tags to the detector's expected modality names."""
    mod = str(modality).upper()
    if mod == "PT":
        return "PET"
    if mod == "NM":
        return "SPECT"
    return mod


def _center_crop_square_mm(profile_values_2d, pixel_spacing_mm, crop_size_mm):
    """Return a centered square crop and its top-left pixel offsets."""
    rows, cols = profile_values_2d.shape
    if crop_size_mm is None or crop_size_mm <= 0:
        return profile_values_2d, 0, 0

    crop_px = int(round(float(crop_size_mm) / float(pixel_spacing_mm)))
    crop_px = max(8, crop_px)
    crop_px = min(crop_px, rows, cols)

    row0 = max(0, (rows - crop_px) // 2)
    col0 = max(0, (cols - crop_px) // 2)
    row1 = row0 + crop_px
    col1 = col0 + crop_px
    return profile_values_2d[row0:row1, col0:col1], row0, col0


def _fit_circle_least_squares(x_pts, y_pts):
    """Fit circle with linear least squares (Kasa form), returns (cx, cy, r)."""
    x = np.asarray(x_pts, dtype=np.float64)
    y = np.asarray(y_pts, dtype=np.float64)
    if x.size < 8 or y.size < 8 or x.size != y.size:
        return None

    A = np.column_stack((x, y, np.ones_like(x)))
    b = -(x * x + y * y)
    coeff, residuals, rank, _ = np.linalg.lstsq(A, b, rcond=None)
    if rank < 3:
        return None

    a, b_coef, c = coeff
    cx = -a / 2.0
    cy = -b_coef / 2.0
    rad_sq = (a * a + b_coef * b_coef) / 4.0 - c
    if not np.isfinite(rad_sq) or rad_sq <= 0:
        return None

    r = float(np.sqrt(rad_sq))
    if not np.isfinite(cx) or not np.isfinite(cy) or not np.isfinite(r):
        return None
    return float(cx), float(cy), r


def _refine_circle_subpixel(edges_bool, cx_px, cy_px, radius_px, r_min_px, r_max_px):
    """
    Refine circle parameters from edge points near detected boundary.

    Uses a narrow annulus around initial radius and a least-squares circle fit to
    achieve sub-pixel center/radius precision.
    """
    rows, cols = edges_bool.shape
    y_idx, x_idx = np.where(edges_bool)
    if x_idx.size < 20:
        return float(cx_px), float(cy_px), float(radius_px)

    x = x_idx.astype(np.float64)
    y = y_idx.astype(np.float64)
    dx = x - float(cx_px)
    dy = y - float(cy_px)
    d = np.hypot(dx, dy)
    angle = np.arctan2(dy, dx)

    # Keep points in a narrow ring around the detected radius.
    band = max(2.0, 0.12 * float(radius_px))
    keep = np.abs(d - float(radius_px)) <= band
    if np.count_nonzero(keep) < 20:
        return float(cx_px), float(cy_px), float(radius_px)

    # Balance samples by angle so a strong top arc cannot dominate the fit.
    n_bins = 48
    bin_edges = np.linspace(-np.pi, np.pi, n_bins + 1)
    selected_idx = []
    ring_error = np.abs(d - float(radius_px))

    keep_idx = np.where(keep)[0]
    ang_keep = angle[keep_idx]
    err_keep = ring_error[keep_idx]

    for b in range(n_bins):
        in_bin = (ang_keep >= bin_edges[b]) & (ang_keep < bin_edges[b + 1])
        if not np.any(in_bin):
            continue
        local_keep_indices = keep_idx[in_bin]
        local_errors = err_keep[in_bin]
        best_local = int(local_keep_indices[np.argmin(local_errors)])
        selected_idx.append(best_local)

    if len(selected_idx) < 16:
        # Fallback to all annulus points if angular coverage is too sparse.
        x_fit = x[keep]
        y_fit = y[keep]
    else:
        x_fit = x[np.array(selected_idx, dtype=np.int64)]
        y_fit = y[np.array(selected_idx, dtype=np.int64)]

        # Ensure both top and bottom arcs are represented; otherwise fall back.
        if not (np.any(y_fit < float(cy_px)) and np.any(y_fit > float(cy_px))):
            x_fit = x[keep]
            y_fit = y[keep]

    fit = _fit_circle_least_squares(x_fit, y_fit)
    if fit is None:
        return float(cx_px), float(cy_px), float(radius_px)

    cx_ref, cy_ref, r_ref = fit
    # Keep refinement bounded to avoid unstable jumps.
    max_shift = max(2.5, 0.20 * float(radius_px))
    if abs(cx_ref - float(cx_px)) > max_shift or abs(cy_ref - float(cy_px)) > max_shift:
        return float(cx_px), float(cy_px), float(radius_px)

    r_ref = float(np.clip(r_ref, float(r_min_px), float(r_max_px)))
    cx_ref = float(np.clip(cx_ref, 0.0, cols - 1.0))
    cy_ref = float(np.clip(cy_ref, 0.0, rows - 1.0))
    return cx_ref, cy_ref, r_ref


def _detect_hough_circle(
    profile_values_2d,
    pixel_spacing_mm,
    modality,
    approx_radius_mm=None,
    center_crop_mm=None,
    table_exclusion_mm=None,
    canny_sigma=1.6,
    canny_low_q=35.0,
    canny_high_q=80.0,
    hough_radius_step=2,
    hough_max_radii=30,
):
    """
    Detect phantom boundary as a circle via Hough transform.

    Returns center and radius in full-image pixel coordinates.
    """
    global _OPENCV_HOUGH_WARNING_EMITTED

    try:
        from skimage import exposure, feature, filters
    except Exception as exc:
        raise RuntimeError(f"Hough detector preprocessing requires scikit-image: {exc}")

    working_img, row_offset_px, col_offset_px = _center_crop_square_mm(
        profile_values_2d,
        pixel_spacing_mm,
        center_crop_mm,
    )

    img = working_img.astype(np.float32)
    mod = _center_detector_modality(modality)

    # Modality-aware contrast prep to stabilize edge extraction.
    if mod == "CT":
        prep = np.clip(img, -1000.0, 2000.0)
        prep = exposure.rescale_intensity(prep, in_range=(-1000.0, 2000.0), out_range=(0.0, 1.0))
    else:
        prep = np.log1p(np.maximum(img, 0.0))
        p2 = float(np.percentile(prep, 2.0))
        p98 = float(np.percentile(prep, 98.0))
        if p98 > p2:
            prep = exposure.rescale_intensity(prep, in_range=(p2, p98), out_range=(0.0, 1.0))
        else:
            prep = exposure.rescale_intensity(prep, out_range=(0.0, 1.0))

    rows, cols = prep.shape
    if table_exclusion_mm is not None and table_exclusion_mm > 0:
        cut_rows = int(np.clip(round(float(table_exclusion_mm) / float(pixel_spacing_mm)), 0, rows))
        if cut_rows > 0:
            prep[rows - cut_rows :, :] = float(np.min(prep))

    # Derive Canny thresholds from gradient magnitude, not raw intensity.
    grad = np.abs(filters.sobel(prep))
    low_q = float(np.clip(canny_low_q, 1.0, 95.0))
    high_q = float(np.clip(canny_high_q, low_q + 1.0, 99.5))
    low_thr = float(np.percentile(grad, low_q))
    high_thr = float(np.percentile(grad, high_q))
    if high_thr <= low_thr:
        high_thr = low_thr + max(1e-6, 0.02 * float(np.max(grad) if np.max(grad) > 0 else 1.0))

    edges = feature.canny(
        prep,
        sigma=float(max(0.5, canny_sigma)),
        low_threshold=low_thr,
        high_threshold=high_thr,
    )
    if not np.any(edges):
        raise RuntimeError("Hough detector found no edges")

    if approx_radius_mm is not None and approx_radius_mm > 0:
        expected_px = float(approx_radius_mm) / float(pixel_spacing_mm)
        r_min = max(6, int(round(0.75 * expected_px)))
        r_max = max(r_min + 2, int(round(1.25 * expected_px)))
    else:
        max_r = int(0.48 * min(rows, cols))
        min_r = int(0.12 * min(rows, cols))
        r_min = max(6, min_r)
        r_max = max(r_min + 2, max_r)

    # Primary backend: OpenCV HoughCircles (faster C++ implementation).
    try:
        import cv2

        prep_u8 = np.clip(np.round(prep * 255.0), 0, 255).astype(np.uint8)
        sigma = float(max(0.5, canny_sigma))
        ksize = int(max(3, 2 * int(round(2.0 * sigma)) + 1))
        prep_blur = cv2.GaussianBlur(prep_u8, (ksize, ksize), sigmaX=sigma, sigmaY=sigma)

        # Map existing tuning knobs to OpenCV parameters conservatively.
        param1 = float(np.interp(float(canny_high_q), [0.0, 100.0], [40.0, 220.0]))
        param2_base = float(np.interp(float(canny_low_q), [0.0, 100.0], [12.0, 50.0]))
        min_dist = float(max(10.0, 0.5 * r_min))

        circles = cv2.HoughCircles(
            prep_blur,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=min_dist,
            param1=param1,
            param2=param2_base,
            minRadius=int(r_min),
            maxRadius=int(r_max),
        )

        # Retry with slightly relaxed accumulator threshold if first pass misses.
        if circles is None:
            circles = cv2.HoughCircles(
                prep_blur,
                cv2.HOUGH_GRADIENT,
                dp=1.2,
                minDist=min_dist,
                param1=param1,
                param2=max(8.0, 0.8 * param2_base),
                minRadius=int(r_min),
                maxRadius=int(r_max),
            )

        if circles is not None and circles.shape[1] > 0:
            c = circles[0][0]
            cx_local = float(c[0])
            cy_local = float(c[1])
            radius_px = float(c[2])
            cx_local, cy_local, radius_px = _refine_circle_subpixel(
                edges,
                cx_local,
                cy_local,
                radius_px,
                r_min_px=r_min,
                r_max_px=r_max,
            )
            cx_px = cx_local + float(col_offset_px)
            cy_px = cy_local + float(row_offset_px)
            return cy_px, cx_px, radius_px

    except Exception as exc:
        if not _OPENCV_HOUGH_WARNING_EMITTED:
            INFO(f"OpenCV Hough unavailable or failed; using skimage fallback. Reason: {exc}")
            _OPENCV_HOUGH_WARNING_EMITTED = True

    # Fallback backend: skimage Hough with bounded radius sampling.
    from skimage.transform import hough_circle

    radius_step = int(max(1, round(hough_radius_step)))
    radii = np.arange(r_min, r_max + 1, radius_step, dtype=np.int32)
    max_radii = int(max(5, round(hough_max_radii)))
    if radii.size > max_radii:
        idx = np.linspace(0, radii.size - 1, max_radii, dtype=int)
        radii = np.unique(radii[idx])
    if radii.size == 0:
        raise RuntimeError("No valid Hough radius candidates")

    hough_res = hough_circle(edges, radii)
    if hough_res.size == 0:
        raise RuntimeError("Hough detector did not find a circle peak")

    r_idx, cy_i, cx_i = np.unravel_index(int(np.argmax(hough_res)), hough_res.shape)
    cx_local = float(cx_i)
    cy_local = float(cy_i)
    radius_px = float(radii[r_idx])
    cx_local, cy_local, radius_px = _refine_circle_subpixel(
        edges,
        cx_local,
        cy_local,
        radius_px,
        r_min_px=r_min,
        r_max_px=r_max,
    )
    cx_px = cx_local + float(col_offset_px)
    cy_px = cy_local + float(row_offset_px)
    return cy_px, cx_px, radius_px


def _refine_center_with_local_window(profile_values_2d, cx_px, cy_px, local_radius_px):
    """
    Refine center using intensity-weighted centroid in a local circular window.

    This keeps center estimation local to phantom body and reduces table influence
    when an approximate phantom radius is available.
    """
    rows, cols = profile_values_2d.shape
    if local_radius_px <= 2:
        return float(cx_px), float(cy_px)

    y = np.arange(rows, dtype=np.float64)
    x = np.arange(cols, dtype=np.float64)
    Y, X = np.meshgrid(y, x, indexing="ij")

    dist2 = (X - float(cx_px)) ** 2 + (Y - float(cy_px)) ** 2
    mask = dist2 <= float(local_radius_px) ** 2

    shifted = profile_values_2d.astype(np.float64) - float(np.min(profile_values_2d))
    weighted = shifted * mask
    total = float(np.sum(weighted))
    if total <= 0:
        return float(cx_px), float(cy_px)

    cy_refined = float(np.sum(Y * weighted) / total)
    cx_refined = float(np.sum(X * weighted) / total)
    return cx_refined, cy_refined


def _refined_hugging_radius_px(
    profile_values_2d,
    cx_px,
    cy_px,
    toolkit_radius_px,
    expected_radius_px=None,
    table_exclusion_px=0.0,
):
    """
    Refine detector radius for debug display so circle hugs the phantom.

    Strategy:
    1. Build a threshold mask from intensity-shifted image.
    2. Keep only the connected component that contains the detected center.
    3. Convert that component area to equivalent circular radius.
    4. Clamp by distance to image edge to avoid oversized circles.
    """
    rows, cols = profile_values_2d.shape
    cx = float(cx_px)
    cy = float(cy_px)

    # Hard geometric cap based on center distance to nearest edge.
    edge_cap_px = 0.95 * max(2.0, min(cx, cy, (cols - 1) - cx, (rows - 1) - cy))

    shifted = profile_values_2d.astype(np.float32) - float(np.min(profile_values_2d))
    max_shift = float(np.max(shifted))
    if max_shift <= 0:
        return float(min(toolkit_radius_px, edge_cap_px))

    # Higher threshold keeps the connected component close to phantom body.
    threshold = max(np.percentile(shifted, 65.0), 0.20 * max_shift)
    mask = shifted >= threshold
    mask = ndimage.binary_closing(mask, iterations=2)
    mask = ndimage.binary_fill_holes(mask)

    # Optional table suppression: clear a bottom strip before component analysis.
    if table_exclusion_px and table_exclusion_px > 0:
        cut_rows = int(np.clip(round(table_exclusion_px), 0, rows))
        if cut_rows > 0:
            mask[rows - cut_rows :, :] = False

    labeled, num = ndimage.label(mask)
    if num <= 0:
        return float(min(toolkit_radius_px, edge_cap_px))

    cy_i = int(np.clip(round(cy), 0, rows - 1))
    cx_i = int(np.clip(round(cx), 0, cols - 1))
    center_label = int(labeled[cy_i, cx_i])

    if center_label == 0:
        # Fallback: choose component closest to detected center.
        labels = np.arange(1, num + 1)
        centers = ndimage.center_of_mass(mask, labeled, labels)
        if not centers:
            return float(min(toolkit_radius_px, edge_cap_px))
        dists = [np.hypot(cy - c[0], cx - c[1]) for c in centers]
        best_idx = int(np.argmin(dists))
        center_label = int(labels[best_idx])

    component = labeled == center_label
    area_px = int(np.count_nonzero(component))
    if area_px <= 0:
        return float(min(toolkit_radius_px, edge_cap_px))

    # Use boundary distances to center for a circle that better hugs the phantom edge.
    eroded = ndimage.binary_erosion(component)
    boundary = component & ~eroded
    by, bx = np.where(boundary)
    if by.size > 0:
        dists = np.hypot(bx.astype(np.float64) - cx, by.astype(np.float64) - cy)
        boundary_radius_px = float(np.percentile(dists, 60.0))
    else:
        boundary_radius_px = float(np.sqrt(area_px / np.pi))

    refined_px = min(float(toolkit_radius_px), float(boundary_radius_px), float(edge_cap_px))

    # Optional prior radius constrains overgrowth from table-connected components.
    if expected_radius_px is not None and expected_radius_px > 0:
        lower = 0.70 * float(expected_radius_px)
        upper = 1.30 * float(expected_radius_px)
        refined_px = float(np.clip(refined_px, lower, upper))

    return float(max(2.0, refined_px))


def detect_slice_center_and_radius(
    profile_values_2d,
    pixel_spacing_mm,
    modality,
    approx_radius_mm=None,
    table_exclusion_mm=None,
    center_crop_mm=None,
    canny_sigma=1.6,
    canny_low_q=35.0,
    canny_high_q=80.0,
    hough_radius_step=2,
    hough_max_radii=30,
):
    """
    Detect phantom center/radius using CT toolkit center-finder.

    Falls back to center-of-mass and percentile radius if detector cannot find a
    phantom-like region for a specific slice.
    """
    try:
        cy_px, cx_px, radius_px = _detect_hough_circle(
            profile_values_2d,
            pixel_spacing_mm,
            modality,
            approx_radius_mm=approx_radius_mm,
            center_crop_mm=center_crop_mm,
            table_exclusion_mm=table_exclusion_mm,
            canny_sigma=canny_sigma,
            canny_low_q=canny_low_q,
            canny_high_q=canny_high_q,
            hough_radius_step=hough_radius_step,
            hough_max_radii=hough_max_radii,
        )

        expected_radius_px = None
        table_exclusion_px = 0.0
        if approx_radius_mm is not None and approx_radius_mm > 0:
            expected_radius_px = float(approx_radius_mm) / float(pixel_spacing_mm)
        # Always apply sub-pixel local centroid refinement around detected circle.
        local_radius_px = 1.25 * (expected_radius_px if expected_radius_px is not None else float(radius_px))
        cx_px, cy_px = _refine_center_with_local_window(
            profile_values_2d,
            cx_px=float(cx_px),
            cy_px=float(cy_px),
            local_radius_px=local_radius_px,
        )
        if table_exclusion_mm is not None and table_exclusion_mm > 0:
            table_exclusion_px = float(table_exclusion_mm) / float(pixel_spacing_mm)

        radius_px = _refined_hugging_radius_px(
            profile_values_2d,
            cx_px=float(cx_px),
            cy_px=float(cy_px),
            toolkit_radius_px=float(radius_px),
            expected_radius_px=expected_radius_px,
            table_exclusion_px=table_exclusion_px,
        )

        rows, cols = profile_values_2d.shape
        cy_mm = (float(cy_px) - (rows / 2.0)) * float(pixel_spacing_mm)
        cx_mm = (float(cx_px) - (cols / 2.0)) * float(pixel_spacing_mm)
        radius_mm = float(radius_px) * float(pixel_spacing_mm)
        return cy_mm, cx_mm, radius_mm, True

    except Exception:
        # Secondary fallback: toolkit detector, then centroid fallback.
        try:
            working_img, row_offset_px, col_offset_px = _center_crop_square_mm(
                profile_values_2d,
                pixel_spacing_mm,
                center_crop_mm,
            )
            center_module = _get_toolkit_center_detector_module()
            if center_module is None:
                raise RuntimeError("Toolkit center detector import failed")
            detector_modality = _center_detector_modality(modality)
            cy_px, cx_px, radius_px = center_module.find_phantom_center_generalized(
                working_img.astype(np.float32),
                pixel_size_mm=float(pixel_spacing_mm),
                modality=detector_modality,
                debug=False,
            )
            cy_px = float(cy_px) + float(row_offset_px)
            cx_px = float(cx_px) + float(col_offset_px)
            rows, cols = profile_values_2d.shape
            cy_mm = (float(cy_px) - (rows / 2.0)) * float(pixel_spacing_mm)
            cx_mm = (float(cx_px) - (cols / 2.0)) * float(pixel_spacing_mm)
            radius_mm = float(radius_px) * float(pixel_spacing_mm)
            return cy_mm, cx_mm, radius_mm, False
        except Exception:
            cy_mm, cx_mm = compute_slice_center(profile_values_2d, pixel_spacing_mm)
            radius_mm = estimate_slice_circle_radius_mm(profile_values_2d, pixel_spacing_mm)
            return cy_mm, cx_mm, radius_mm, False


def create_debug_splash_view_all_slices(
    pixel_slices,
    centers_x_mm,
    centers_y_mm,
    radii_mm,
    z_positions_mm,
    pixel_spacing_mm,
    modality_label,
    output_path,
    show_window,
    cols=6,
):
    """Create an all-slices debug contact sheet with center and circle overlay."""

    def _normalize(arr):
        arr = arr.astype(np.float64)
        arr = arr - np.min(arr)
        vmax = np.max(arr)
        if vmax > 0:
            arr = arr / vmax
        return arr

    def _center_mm_to_pixel(center_mm, img_shape, pixel_spacing_mm):
        rows, cols = img_shape
        cx_mm, cy_mm = center_mm
        cx_px = (cx_mm / pixel_spacing_mm) + (cols / 2.0)
        cy_px = (cy_mm / pixel_spacing_mm) + (rows / 2.0)
        return cx_px, cy_px

    n = len(pixel_slices)
    cols = max(1, int(cols))
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.2 * cols, 3.0 * rows))
    axes = np.atleast_1d(axes).ravel()

    for idx, ax in enumerate(axes):
        ax.axis("off")
        if idx >= n:
            continue

        img = _normalize(pixel_slices[idx])
        ax.imshow(img, cmap="gray", origin="upper")

        center_mm = (float(centers_x_mm[idx]), float(centers_y_mm[idx]))
        cx_px, cy_px = _center_mm_to_pixel(center_mm, pixel_slices[idx].shape, pixel_spacing_mm)
        r_px = max(float(radii_mm[idx]) / float(pixel_spacing_mm), 2.0)

        ax.add_patch(Circle((cx_px, cy_px), r_px, fill=False, color="lime", lw=1.4))
        ax.plot(cx_px, cy_px, marker="+", color="yellow", markersize=9, markeredgewidth=1.6)
        ax.set_title(f"z={float(z_positions_mm[idx]):.1f} mm", fontsize=9)

    fig.suptitle(
        f"Debug Splash ({modality_label}): all slices with detected centers and circles",
        fontsize=12,
        fontweight="bold",
    )
    plt.tight_layout()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=160, bbox_inches="tight")
    SUCCESS(f"Debug splash saved: {output_path}")

    if show_window:
        plt.show()

    plt.close(fig)


def load_dicom_series_for_centers(series_dir):
    """
    Load DICOM series and extract slice-by-slice data needed for center calculation.
    
    Returns:
        Dict with z_positions, pixel_arrays, pixel_spacing, modality
    """
    import pydicom
    from pathlib import Path
    
    series_path = Path(series_dir)
    dcm_files = sorted(series_path.glob("*.dcm"))
    
    if not dcm_files:
        ERROR(f"No DICOM files found in {series_dir}")
        raise ValueError(f"No DICOM files found in {series_dir}")
    
    INFO(f"Loading {len(dcm_files)} DICOM files from {series_path.name}...")
    
    slices_data = []
    for dcm_file in dcm_files:
        ds = pydicom.dcmread(dcm_file)
        z_pos = float(ds.ImagePositionPatient[2]) if hasattr(ds, 'ImagePositionPatient') else 0.0
        slices_data.append({
            'z': z_pos,
            'pixels': ds.pixel_array,
            'dataset': ds
        })
    
    # Sort by z position
    slices_data.sort(key=lambda s: s['z'])
    
    # Extract metadata from first slice
    ds0 = slices_data[0]['dataset']
    pixel_spacing = float(ds0.PixelSpacing[0])
    modality = ds0.Modality if hasattr(ds0, 'Modality') else 'UN'
    
    return {
        'z_positions': np.array([s['z'] for s in slices_data]),
        'pixel_arrays': [s['pixels'] for s in slices_data],
        'pixel_spacing': pixel_spacing,
        'modality': modality
    }


def compute_profile_center_of_mass(z_positions, profile_values):
    """
    Compute the center of mass of a 1D profile.
    
    Treats profile intensity as a probability distribution and finds
    the weighted mean position (center of mass).
    
    Args:
        z_positions: Array of z coordinates (mm)
        profile_values: Array of intensity values
    
    Returns:
        float: Z position of the center of mass
    """
    # Ensure profile values are positive (shift if necessary)
    profile_shifted = profile_values - np.min(profile_values)
    
    # Avoid division by zero
    if np.sum(profile_shifted) == 0:
        return np.mean(z_positions)
    
    # Center of mass: sum(z * intensity) / sum(intensity)
    com_z = np.sum(z_positions * profile_shifted) / np.sum(profile_shifted)
    
    return com_z


def _is_fwhm_block(value):
    """Return True when a JSON block looks like an FWHM result entry."""
    if not isinstance(value, dict):
        return False
    required = {"fwhm_mm", "z_left_mm", "z_right_mm", "z_mid_mm"}
    return required.issubset(value.keys())


def _resolve_fwhm_blocks(peak_data):
    """
    Resolve Series1/Series2 FWHM blocks from peak JSON.

    Some historical files may carry the second block under a malformed key
    (for example ""). This resolver keeps behavior stable for valid files while
    remaining tolerant to those malformed-but-usable JSON variants.
    """
    s1 = peak_data.get("series1_fwhm") or peak_data.get("pet_fwhm") or peak_data.get("fwhm1")
    s2 = peak_data.get("series2_fwhm") or peak_data.get("ct_fwhm") or peak_data.get("fwhm2")

    if not _is_fwhm_block(s1):
        s1 = None
    if not _is_fwhm_block(s2):
        s2 = None

    # Handle malformed key emitted in some runs.
    if s2 is None and _is_fwhm_block(peak_data.get("")):
        s2 = peak_data[""]
        INFO("Recovered Series2 FWHM from malformed empty key in peaks JSON")

    # Last-resort heuristic: pick remaining FWHM-like block that is not Series1.
    if s2 is None:
        candidates = [v for v in peak_data.values() if _is_fwhm_block(v)]
        if s1 is not None:
            candidates = [v for v in candidates if v is not s1]
        if len(candidates) == 1:
            s2 = candidates[0]
            INFO("Recovered Series2 FWHM from fallback FWHM block detection")

    if s1 is None or s2 is None:
        available_keys = ", ".join(sorted(peak_data.keys()))
        raise KeyError(
            "Unable to resolve FWHM blocks for both series. "
            f"Available JSON keys: {available_keys}"
        )

    return s1, s2


def fit_z_coregistration(
    series1_dir,
    series2_dir,
    peak_data,
    window_mm=75.0,
    debug=False,
    debug_splash_path=None,
    approx_radius_mm=None,
    table_exclusion_mm=None,
    center_crop_mm=None,
    canny_sigma=1.6,
    canny_low_q=35.0,
    canny_high_q=80.0,
    hough_radius_step=2,
    hough_max_radii=30,
):
    """
    Fit linear regression for each series showing center position vs z-coordinate.
    
    For each slice within the analysis window:
    1. Detect phantom center/radius via CT toolkit center detector
    2. Track (z_position, center_x, center_y) for each slice
    3. Fit linear regressions: center_x = m*z + b for each series
    
    This reveals lateral drift/shift along the z-axis.
    
    Args:
        series1_dir: Path to Series1 DICOM directory
        series2_dir: Path to Series2 DICOM directory
        peak_data: Dict with series1_fwhm, series2_fwhm containing z_mid_mm
        window_mm: Half-width of selection window (default 75 mm)
    
    Returns:
        Dict with regression results for both series
    """
    fwhm_s1, fwhm_s2 = _resolve_fwhm_blocks(peak_data)
    z_mid_series1 = fwhm_s1['z_mid_mm']
    z_mid_series2 = fwhm_s2['z_mid_mm']
    
    INFO(f"Loading Series1 from {Path(series1_dir).name}...")
    s1_data = load_dicom_series_for_centers(series1_dir)
    
    INFO(f"Loading Series2 from {Path(series2_dir).name}...")
    s2_data = load_dicom_series_for_centers(series2_dir)
    
    # Select slices within window
    mask1 = np.abs(s1_data['z_positions'] - z_mid_series1) <= window_mm
    mask2 = np.abs(s2_data['z_positions'] - z_mid_series2) <= window_mm
    
    z1_window = s1_data['z_positions'][mask1]
    pixels1_window = [s1_data['pixel_arrays'][i] for i, m in enumerate(mask1) if m]
    
    z2_window = s2_data['z_positions'][mask2]
    pixels2_window = [s2_data['pixel_arrays'][i] for i, m in enumerate(mask2) if m]
    
    INFO(f"Z-axis coregistration analysis (per-slice center detection)")
    INFO(f"Series1 ({s1_data['modality']}) FWHM midpoint: {z_mid_series1:.3f} mm")
    INFO(f"Series2 ({s2_data['modality']}) FWHM midpoint: {z_mid_series2:.3f} mm")
    INFO(f"Window: ±{window_mm} mm")
    INFO(f"Series1 slices in window: {len(z1_window)}")
    INFO(f"Series2 slices in window: {len(z2_window)}")
    if approx_radius_mm is not None and approx_radius_mm > 0:
        INFO(f"Using approximate phantom radius prior: {approx_radius_mm:.2f} mm")
    if table_exclusion_mm is not None and table_exclusion_mm > 0:
        INFO(f"Excluding bottom {table_exclusion_mm:.2f} mm from radius fitting to suppress table")
    if center_crop_mm is not None and center_crop_mm > 0:
        INFO(f"Using centered crop window for detection: {center_crop_mm:.2f} x {center_crop_mm:.2f} mm")
    INFO(
        f"Hough Canny settings: sigma={canny_sigma:.2f}, "
        f"low_q={canny_low_q:.1f}, high_q={canny_high_q:.1f}"
    )
    INFO(
        f"Hough radius sampling: step={int(max(1, round(hough_radius_step)))}, "
        f"max_radii={int(max(5, round(hough_max_radii)))}"
    )
    
    # Compute center for each slice in Series1
    INFO(f"Computing centers for Series1...")
    centers_y1 = []
    centers_x1 = []
    radii_mm1 = []
    fallback_count_s1 = 0
    for pixels in pixels1_window:
        cy, cx, radius_mm, used_toolkit = detect_slice_center_and_radius(
            pixels,
            s1_data['pixel_spacing'],
            s1_data['modality'],
            approx_radius_mm=approx_radius_mm,
            table_exclusion_mm=table_exclusion_mm,
            center_crop_mm=center_crop_mm,
            canny_sigma=canny_sigma,
            canny_low_q=canny_low_q,
            canny_high_q=canny_high_q,
            hough_radius_step=hough_radius_step,
            hough_max_radii=hough_max_radii,
        )
        centers_y1.append(cy)
        centers_x1.append(cx)
        radii_mm1.append(radius_mm)
        if not used_toolkit:
            fallback_count_s1 += 1
    
    centers_y1 = np.array(centers_y1)
    centers_x1 = np.array(centers_x1)
    
    # Compute center for each slice in Series2
    INFO(f"Computing centers for Series2...")
    centers_y2 = []
    centers_x2 = []
    radii_mm2 = []
    fallback_count_s2 = 0
    for pixels in pixels2_window:
        cy, cx, radius_mm, used_toolkit = detect_slice_center_and_radius(
            pixels,
            s2_data['pixel_spacing'],
            s2_data['modality'],
            approx_radius_mm=approx_radius_mm,
            table_exclusion_mm=table_exclusion_mm,
            center_crop_mm=center_crop_mm,
            canny_sigma=canny_sigma,
            canny_low_q=canny_low_q,
            canny_high_q=canny_high_q,
            hough_radius_step=hough_radius_step,
            hough_max_radii=hough_max_radii,
        )
        centers_y2.append(cy)
        centers_x2.append(cx)
        radii_mm2.append(radius_mm)
        if not used_toolkit:
            fallback_count_s2 += 1
    
    centers_y2 = np.array(centers_y2)
    centers_x2 = np.array(centers_x2)
    radii_mm1 = np.array(radii_mm1)
    radii_mm2 = np.array(radii_mm2)

    if fallback_count_s1 > 0:
        INFO(f"Series1 center detector fallback used on {fallback_count_s1} slices")
    if fallback_count_s2 > 0:
        INFO(f"Series2 center detector fallback used on {fallback_count_s2} slices")

    if debug and len(z1_window) > 0 and len(z2_window) > 0:
        splash_base = Path(debug_splash_path) if debug_splash_path else (Path.cwd() / "z_axis_coregistration_debug_splash.png")
        splash_s1 = splash_base.with_name(f"{splash_base.stem}_series1{splash_base.suffix}")
        splash_s2 = splash_base.with_name(f"{splash_base.stem}_series2{splash_base.suffix}")

        create_debug_splash_view_all_slices(
            pixel_slices=pixels1_window,
            centers_x_mm=centers_x1,
            centers_y_mm=centers_y1,
            radii_mm=radii_mm1,
            z_positions_mm=z1_window,
            pixel_spacing_mm=float(s1_data['pixel_spacing']),
            modality_label=f"Series1 {s1_data['modality']}",
            output_path=str(splash_s1),
            show_window=False,
        )
        create_debug_splash_view_all_slices(
            pixel_slices=pixels2_window,
            centers_x_mm=centers_x2,
            centers_y_mm=centers_y2,
            radii_mm=radii_mm2,
            z_positions_mm=z2_window,
            pixel_spacing_mm=float(s2_data['pixel_spacing']),
            modality_label=f"Series2 {s2_data['modality']}",
            output_path=str(splash_s2),
            show_window=True,
        )
    
    INFO(f"Computing linear regressions...")
    
    # Fit linear regressions: center_x = slope * z + intercept
    slope_x1, intercept_x1, r_x1, p_x1, stderr_x1 = stats.linregress(z1_window, centers_x1)
    slope_y1, intercept_y1, r_y1, p_y1, stderr_y1 = stats.linregress(z1_window, centers_y1)
    
    slope_x2, intercept_x2, r_x2, p_x2, stderr_x2 = stats.linregress(z2_window, centers_x2)
    slope_y2, intercept_y2, r_y2, p_y2, stderr_y2 = stats.linregress(z2_window, centers_y2)
    
    # Compute pitch and yaw angles from slopes
    # Yaw: rotation around z-axis (affects x displacement)
    # Pitch: rotation around x-axis (affects y displacement)
    # Angle = arctan(displacement_per_mm) in radians, convert to degrees and milliradians
    
    yaw1_rad = np.arctan(slope_x1)
    yaw1_deg = np.degrees(yaw1_rad)
    yaw1_mrad = yaw1_rad * 1000
    
    pitch1_rad = np.arctan(slope_y1)
    pitch1_deg = np.degrees(pitch1_rad)
    pitch1_mrad = pitch1_rad * 1000
    
    yaw2_rad = np.arctan(slope_x2)
    yaw2_deg = np.degrees(yaw2_rad)
    yaw2_mrad = yaw2_rad * 1000
    
    pitch2_rad = np.arctan(slope_y2)
    pitch2_deg = np.degrees(pitch2_rad)
    pitch2_mrad = pitch2_rad * 1000
    
    # Relative pitch/yaw error between series
    yaw_error_deg = yaw2_deg - yaw1_deg
    pitch_error_deg = pitch2_deg - pitch1_deg
    yaw_error_mrad = yaw2_mrad - yaw1_mrad
    pitch_error_mrad = pitch2_mrad - pitch1_mrad
    
    # Compute Cartesian coordinate errors
    # Average X and Y positions for each series
    avg_x1 = np.mean(centers_x1)
    avg_y1 = np.mean(centers_y1)
    avg_x2 = np.mean(centers_x2)
    avg_y2 = np.mean(centers_y2)
    
    # RMS (root-mean-square) for stability measure
    rms_x1 = np.sqrt(np.mean(centers_x1 ** 2))
    rms_y1 = np.sqrt(np.mean(centers_y1 ** 2))
    rms_x2 = np.sqrt(np.mean(centers_x2 ** 2))
    rms_y2 = np.sqrt(np.mean(centers_y2 ** 2))
    
    # Z-axis center difference from FWHM midpoints
    z_center_diff = z_mid_series2 - z_mid_series1
    
    # Cartesian error between series (difference in average positions)
    x_error = avg_x2 - avg_x1
    y_error = avg_y2 - avg_y1
    
    # 3D Euclidean distance error
    cartesian_distance_error = np.sqrt(x_error**2 + y_error**2 + z_center_diff**2)
    
    INFO(f"Series1 ({s1_data['modality']}) angular errors:")
    INFO(f"  Yaw (x-axis): {yaw1_deg:.6f}° ({yaw1_mrad:.4f} mrad)")
    INFO(f"  Pitch (y-axis): {pitch1_deg:.6f}° ({pitch1_mrad:.4f} mrad)")
    INFO(f"Series2 ({s2_data['modality']}) angular errors:")
    INFO(f"  Yaw (x-axis): {yaw2_deg:.6f}° ({yaw2_mrad:.4f} mrad)")
    INFO(f"  Pitch (y-axis): {pitch2_deg:.6f}° ({pitch2_mrad:.4f} mrad)")
    INFO(f"Relative angular error (Series2 - Series1):")
    INFO(f"  Yaw: {yaw_error_deg:.6f}° ({yaw_error_mrad:.4f} mrad)")
    INFO(f"  Pitch: {pitch_error_deg:.6f}° ({pitch_error_mrad:.4f} mrad)")
    
    INFO(f"Cartesian Coordinate Errors:")
    INFO(f"  Series1 average position: X={avg_x1:.4f} mm, Y={avg_y1:.4f} mm")
    INFO(f"  Series2 average position: X={avg_x2:.4f} mm, Y={avg_y2:.4f} mm")
    INFO(f"  Z center difference (FWHM): {z_center_diff:.4f} mm")
    INFO(f"  X error (Series2 - Series1): {x_error:.4f} mm")
    INFO(f"  Y error (Series2 - Series1): {y_error:.4f} mm")
    INFO(f"  3D Euclidean distance error: {cartesian_distance_error:.4f} mm")
    
    results = {
        'method': 'per-slice center detection with linear regression',
        'window_mm': window_mm,
        'series1': {
            'modality': s1_data['modality'],
            'num_slices': len(z1_window),
            'z_range_mm': {'min': float(z1_window.min()), 'max': float(z1_window.max())},
            'z_positions': z1_window.tolist(),
            'centers_x_mm': centers_x1.tolist(),
            'centers_y_mm': centers_y1.tolist(),
            'regression_x': {
                'slope': float(slope_x1),
                'intercept': float(intercept_x1),
                'r_squared': float(r_x1 ** 2),
                'p_value': float(p_x1),
                'std_err': float(stderr_x1),
                'equation': f'center_x = {slope_x1:.6f} * z + {intercept_x1:.6f}'
            },
            'regression_y': {
                'slope': float(slope_y1),
                'intercept': float(intercept_y1),
                'r_squared': float(r_y1 ** 2),
                'p_value': float(p_y1),
                'std_err': float(stderr_y1),
                'equation': f'center_y = {slope_y1:.6f} * z + {intercept_y1:.6f}'
            },
            'angular_errors': {
                'yaw_deg': float(yaw1_deg),
                'yaw_mrad': float(yaw1_mrad),
                'yaw_rad': float(yaw1_rad),
                'pitch_deg': float(pitch1_deg),
                'pitch_mrad': float(pitch1_mrad),
                'pitch_rad': float(pitch1_rad),
                'note': 'Yaw = rotation around z-axis (x-displacement), Pitch = rotation around x-axis (y-displacement)'
            },
            'cartesian_position': {
                'avg_x_mm': float(avg_x1),
                'avg_y_mm': float(avg_y1),
                'rms_x_mm': float(rms_x1),
                'rms_y_mm': float(rms_y1),
                'note': 'Average and RMS positions relative to image center'
            }
        },
        'series2': {
            'modality': s2_data['modality'],
            'num_slices': len(z2_window),
            'z_range_mm': {'min': float(z2_window.min()), 'max': float(z2_window.max())},
            'z_positions': z2_window.tolist(),
            'centers_x_mm': centers_x2.tolist(),
            'centers_y_mm': centers_y2.tolist(),
            'regression_x': {
                'slope': float(slope_x2),
                'intercept': float(intercept_x2),
                'r_squared': float(r_x2 ** 2),
                'p_value': float(p_x2),
                'std_err': float(stderr_x2),
                'equation': f'center_x = {slope_x2:.6f} * z + {intercept_x2:.6f}'
            },
            'regression_y': {
                'slope': float(slope_y2),
                'intercept': float(intercept_y2),
                'r_squared': float(r_y2 ** 2),
                'p_value': float(p_y2),
                'std_err': float(stderr_y2),
                'equation': f'center_y = {slope_y2:.6f} * z + {intercept_y2:.6f}'
            },
            'angular_errors': {
                'yaw_deg': float(yaw2_deg),
                'yaw_mrad': float(yaw2_mrad),
                'yaw_rad': float(yaw2_rad),
                'pitch_deg': float(pitch2_deg),
                'pitch_mrad': float(pitch2_mrad),
                'pitch_rad': float(pitch2_rad),
                'note': 'Yaw = rotation around z-axis (x-displacement), Pitch = rotation around x-axis (y-displacement)'
            },
            'cartesian_position': {
                'avg_x_mm': float(avg_x2),
                'avg_y_mm': float(avg_y2),
                'rms_x_mm': float(rms_x2),
                'rms_y_mm': float(rms_y2),
                'note': 'Average and RMS positions relative to image center'
            }
        },
        'relative_angular_errors': {
            'yaw_error_deg': float(yaw_error_deg),
            'yaw_error_mrad': float(yaw_error_mrad),
            'pitch_error_deg': float(pitch_error_deg),
            'pitch_error_mrad': float(pitch_error_mrad),
            'note': 'Difference between Series2 and Series1 angular errors (Series2 - Series1)'
        },
        'cartesian_errors': {
            'x_error_mm': float(x_error),
            'y_error_mm': float(y_error),
            'z_center_diff_mm': float(z_center_diff),
            'euclidean_distance_mm': float(cartesian_distance_error),
            'note': 'Cartesian coordinate errors: X and Y are differences in average positions, Z is FWHM midpoint difference'
        }
    }
    
    return results


def print_results(results):
    """Pretty-print regression results."""
    print()
    print("=" * 80)
    print("Z-AXIS COREGISTRATION: Per-Slice Center Detection")
    print("=" * 80)
    
    s1 = results['series1']
    s2 = results['series2']
    
    print(f"\nSeries1 ({s1['modality']}):")
    print(f"  Slices analyzed: {s1['num_slices']}")
    print(f"  Z range: {s1['z_range_mm']['min']:.2f} to {s1['z_range_mm']['max']:.2f} mm")
    print(f"\n  X-axis regression: {s1['regression_x']['equation']}")
    print(f"    R² = {s1['regression_x']['r_squared']:.6f}")
    print(f"    P-value = {s1['regression_x']['p_value']:.6e}")
    print(f"\n  Y-axis regression: {s1['regression_y']['equation']}")
    print(f"    R² = {s1['regression_y']['r_squared']:.6f}")
    print(f"    P-value = {s1['regression_y']['p_value']:.6e}")
    print(f"\n  Angular Errors:")
    print(f"    Yaw:   {s1['angular_errors']['yaw_deg']:.6f}° ({s1['angular_errors']['yaw_mrad']:.4f} mrad)")
    print(f"    Pitch: {s1['angular_errors']['pitch_deg']:.6f}° ({s1['angular_errors']['pitch_mrad']:.4f} mrad)")
    
    print(f"\nSeries2 ({s2['modality']}):")
    print(f"  Slices analyzed: {s2['num_slices']}")
    print(f"  Z range: {s2['z_range_mm']['min']:.2f} to {s2['z_range_mm']['max']:.2f} mm")
    print(f"\n  X-axis regression: {s2['regression_x']['equation']}")
    print(f"    R² = {s2['regression_x']['r_squared']:.6f}")
    print(f"    P-value = {s2['regression_x']['p_value']:.6e}")
    print(f"\n  Y-axis regression: {s2['regression_y']['equation']}")
    print(f"    R² = {s2['regression_y']['r_squared']:.6f}")
    print(f"    P-value = {s2['regression_y']['p_value']:.6e}")
    print(f"\n  Angular Errors:")
    print(f"    Yaw:   {s2['angular_errors']['yaw_deg']:.6f}° ({s2['angular_errors']['yaw_mrad']:.4f} mrad)")
    print(f"    Pitch: {s2['angular_errors']['pitch_deg']:.6f}° ({s2['angular_errors']['pitch_mrad']:.4f} mrad)")
    
    rel = results['relative_angular_errors']
    print(f"\nRelative Angular Error (Series2 - Series1):")
    print(f"  Yaw error:   {rel['yaw_error_deg']:.6f}° ({rel['yaw_error_mrad']:.4f} mrad)")
    print(f"  Pitch error: {rel['pitch_error_deg']:.6f}° ({rel['pitch_error_mrad']:.4f} mrad)")
    
    cart = results['cartesian_errors']
    print(f"\nCartesian Coordinate Errors (Series2 - Series1):")
    print(f"  ΔX (lateral):      {cart['x_error_mm']:+.4f} mm")
    print(f"  ΔY (vertical):     {cart['y_error_mm']:+.4f} mm")
    print(f"  ΔZ (longitudinal): {cart['z_center_diff_mm']:+.4f} mm")
    print(f"  3D Distance:       {cart['euclidean_distance_mm']:.4f} mm")
    
    print()
    print("Interpretation:")
    print(f"  A slope near 0 indicates phantom center remains stable along z-axis.")
    print(f"  Non-zero slope indicates lateral drift/shift (pitch/yaw error).")
    print(f"  Yaw: Rotation around z-axis (affects x-displacement)")
    print(f"  Pitch: Rotation around x-axis (affects y-displacement)")
    print(f"  Cartesian errors show average position differences between series.")
    print()


def save_results(results, output_path):
    """Save results to JSON file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    SUCCESS(f"Results saved: {output_path}")

def save_csv_summary(results, output_path):
    """Save summary of key results to CSV."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Write header - only relative angular errors and X, Y, Z Cartesian errors
        writer.writerow([
            'Relative_Yaw_deg',
            'Relative_Pitch_deg',
            'Relative_Yaw_mrad',
            'Relative_Pitch_mrad',
            'Delta_X_mm',
            'Delta_Y_mm',
            'Delta_Z_mm'
        ])
        
        # Write data row
        rel_ang = results['relative_angular_errors']
        cart = results['cartesian_errors']
        
        writer.writerow([
            f"{rel_ang['yaw_error_deg']:.6f}",
            f"{rel_ang['pitch_error_deg']:.6f}",
            f"{rel_ang['yaw_error_mrad']:.4f}",
            f"{rel_ang['pitch_error_mrad']:.4f}",
            f"{cart['x_error_mm']:.4f}",
            f"{cart['y_error_mm']:.4f}",
            f"{cart['z_center_diff_mm']:.4f}"
        ])
    
    SUCCESS(f"CSV summary saved: {output_path}")

def save_results_csv(results, output_path):
    """Save summary results to CSV file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    s1 = results['series1']
    s2 = results['series2']
    rel_ang = results['relative_angular_errors']
    cart = results['cartesian_errors']
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # Header section
        writer.writerow(['Z-Axis Coregistration Analysis Results'])
        writer.writerow(['Method', results['method']])
        writer.writerow(['Analysis Window (mm)', f"±{results['window_mm']:.2f}"])
        writer.writerow([])
        
        # Series 1 info
        writer.writerow(['Series 1 Information'])
        writer.writerow(['Modality', s1['modality']])
        writer.writerow(['Number of Slices', s1['num_slices']])
        writer.writerow(['Z Range Min (mm)', f"{s1['z_range_mm']['min']:.2f}"])
        writer.writerow(['Z Range Max (mm)', f"{s1['z_range_mm']['max']:.2f}"])
        writer.writerow(['Average X Position (mm)', f"{s1['cartesian_position']['avg_x_mm']:.4f}"])
        writer.writerow(['Average Y Position (mm)', f"{s1['cartesian_position']['avg_y_mm']:.4f}"])
        writer.writerow(['RMS X Position (mm)', f"{s1['cartesian_position']['rms_x_mm']:.4f}"])
        writer.writerow(['RMS Y Position (mm)', f"{s1['cartesian_position']['rms_y_mm']:.4f}"])
        writer.writerow([])
        
        # Series 1 regression
        writer.writerow(['Series 1 X-Axis Regression'])
        writer.writerow(['Equation', s1['regression_x']['equation']])
        writer.writerow(['Slope', f"{s1['regression_x']['slope']:.6f}"])
        writer.writerow(['Intercept', f"{s1['regression_x']['intercept']:.6f}"])
        writer.writerow(['R²', f"{s1['regression_x']['r_squared']:.6f}"])
        writer.writerow(['P-value', f"{s1['regression_x']['p_value']:.6e}"])
        writer.writerow([])
        
        writer.writerow(['Series 1 Y-Axis Regression'])
        writer.writerow(['Equation', s1['regression_y']['equation']])
        writer.writerow(['Slope', f"{s1['regression_y']['slope']:.6f}"])
        writer.writerow(['Intercept', f"{s1['regression_y']['intercept']:.6f}"])
        writer.writerow(['R²', f"{s1['regression_y']['r_squared']:.6f}"])
        writer.writerow(['P-value', f"{s1['regression_y']['p_value']:.6e}"])
        writer.writerow([])
        
        # Series 1 angular errors
        writer.writerow(['Series 1 Angular Errors'])
        writer.writerow(['Yaw (degrees)', f"{s1['angular_errors']['yaw_deg']:.6f}"])
        writer.writerow(['Yaw (mrad)', f"{s1['angular_errors']['yaw_mrad']:.4f}"])
        writer.writerow(['Pitch (degrees)', f"{s1['angular_errors']['pitch_deg']:.6f}"])
        writer.writerow(['Pitch (mrad)', f"{s1['angular_errors']['pitch_mrad']:.4f}"])
        writer.writerow([])
        
        # Series 2 info
        writer.writerow(['Series 2 Information'])
        writer.writerow(['Modality', s2['modality']])
        writer.writerow(['Number of Slices', s2['num_slices']])
        writer.writerow(['Z Range Min (mm)', f"{s2['z_range_mm']['min']:.2f}"])
        writer.writerow(['Z Range Max (mm)', f"{s2['z_range_mm']['max']:.2f}"])
        writer.writerow(['Average X Position (mm)', f"{s2['cartesian_position']['avg_x_mm']:.4f}"])
        writer.writerow(['Average Y Position (mm)', f"{s2['cartesian_position']['avg_y_mm']:.4f}"])
        writer.writerow(['RMS X Position (mm)', f"{s2['cartesian_position']['rms_x_mm']:.4f}"])
        writer.writerow(['RMS Y Position (mm)', f"{s2['cartesian_position']['rms_y_mm']:.4f}"])
        writer.writerow([])
        
        # Series 2 regression
        writer.writerow(['Series 2 X-Axis Regression'])
        writer.writerow(['Equation', s2['regression_x']['equation']])
        writer.writerow(['Slope', f"{s2['regression_x']['slope']:.6f}"])
        writer.writerow(['Intercept', f"{s2['regression_x']['intercept']:.6f}"])
        writer.writerow(['R²', f"{s2['regression_x']['r_squared']:.6f}"])
        writer.writerow(['P-value', f"{s2['regression_x']['p_value']:.6e}"])
        writer.writerow([])
        
        writer.writerow(['Series 2 Y-Axis Regression'])
        writer.writerow(['Equation', s2['regression_y']['equation']])
        writer.writerow(['Slope', f"{s2['regression_y']['slope']:.6f}"])
        writer.writerow(['Intercept', f"{s2['regression_y']['intercept']:.6f}"])
        writer.writerow(['R²', f"{s2['regression_y']['r_squared']:.6f}"])
        writer.writerow(['P-value', f"{s2['regression_y']['p_value']:.6e}"])
        writer.writerow([])
        
        # Series 2 angular errors
        writer.writerow(['Series 2 Angular Errors'])
        writer.writerow(['Yaw (degrees)', f"{s2['angular_errors']['yaw_deg']:.6f}"])
        writer.writerow(['Yaw (mrad)', f"{s2['angular_errors']['yaw_mrad']:.4f}"])
        writer.writerow(['Pitch (degrees)', f"{s2['angular_errors']['pitch_deg']:.6f}"])
        writer.writerow(['Pitch (mrad)', f"{s2['angular_errors']['pitch_mrad']:.4f}"])
        writer.writerow([])
        
        # Relative errors
        writer.writerow(['Relative Angular Errors (Series2 - Series1)'])
        writer.writerow(['Yaw Error (degrees)', f"{rel_ang['yaw_error_deg']:.6f}"])
        writer.writerow(['Yaw Error (mrad)', f"{rel_ang['yaw_error_mrad']:.4f}"])
        writer.writerow(['Pitch Error (degrees)', f"{rel_ang['pitch_error_deg']:.6f}"])
        writer.writerow(['Pitch Error (mrad)', f"{rel_ang['pitch_error_mrad']:.4f}"])
        writer.writerow([])
        
        # Cartesian errors
        writer.writerow(['Cartesian Coordinate Errors (Series2 - Series1)'])
        writer.writerow(['ΔX Lateral (mm)', f"{cart['x_error_mm']:+.4f}"])
        writer.writerow(['ΔY Vertical (mm)', f"{cart['y_error_mm']:+.4f}"])
        writer.writerow(['ΔZ Longitudinal (mm)', f"{cart['z_center_diff_mm']:+.4f}"])
        writer.writerow(['3D Euclidean Distance (mm)', f"{cart['euclidean_distance_mm']:.4f}"])
    
    SUCCESS(f"CSV results saved: {output_path}")


def create_center_plot(results, output_path):
    """Create 3D visualization of center trajectories and fitted orientation lines."""
    s1 = results['series1']
    s2 = results['series2']
    
    z1 = np.array(s1['z_positions'])
    cx1 = np.array(s1['centers_x_mm'])
    cy1 = np.array(s1['centers_y_mm'])
    
    z2 = np.array(s2['z_positions'])
    cx2 = np.array(s2['centers_x_mm'])
    cy2 = np.array(s2['centers_y_mm'])
    
    # Generate fitted lines
    z1_fit = np.linspace(z1.min(), z1.max(), 100)
    cx1_fit = s1['regression_x']['slope'] * z1_fit + s1['regression_x']['intercept']
    cy1_fit = s1['regression_y']['slope'] * z1_fit + s1['regression_y']['intercept']
    
    z2_fit = np.linspace(z2.min(), z2.max(), 100)
    cx2_fit = s2['regression_x']['slope'] * z2_fit + s2['regression_x']['intercept']
    cy2_fit = s2['regression_y']['slope'] * z2_fit + s2['regression_y']['intercept']

    # Re-center transverse coordinates on CT profile center so (0, 0) is CT center.
    ct_center_x = float(np.mean(cx2))
    ct_center_y = float(np.mean(cy2))

    cx1_rel = cx1 - ct_center_x
    cy1_rel = cy1 - ct_center_y
    cx2_rel = cx2 - ct_center_x
    cy2_rel = cy2 - ct_center_y
    cx1_fit_rel = cx1_fit - ct_center_x
    cy1_fit_rel = cy1_fit - ct_center_y
    cx2_fit_rel = cx2_fit - ct_center_x
    cy2_fit_rel = cy2_fit - ct_center_y

    fig = plt.figure(figsize=(12, 9))
    ax = fig.add_subplot(111, projection='3d')

    # Plot convention: x -> lateral X offset, y -> scanner Z, z -> vertical Y offset.
    # This places scanner Z where the old y-axis direction was shown.
    ax.plot(cx1_rel, z1, cy1_rel, color='royalblue', alpha=0.45, linewidth=1.4)
    ax.scatter(cx1_rel, z1, cy1_rel, s=18, alpha=0.75, color='royalblue', label=f'Series1 ({s1["modality"]}) points')

    ax.plot(cx2_rel, z2, cy2_rel, color='firebrick', alpha=0.45, linewidth=1.4)
    ax.scatter(cx2_rel, z2, cy2_rel, s=18, alpha=0.75, color='firebrick', label=f'Series2 ({s2["modality"]}) points')

    # Regression orientation lines in 3D, with scanner Z on plot y-axis.
    ax.plot(cx1_fit_rel, z1_fit, cy1_fit_rel, color='navy', linewidth=3.0, label='Series1 fitted orientation')
    ax.plot(cx2_fit_rel, z2_fit, cy2_fit_rel, color='darkred', linewidth=3.0, label='Series2 fitted orientation')

    # Inaccuracy vector between average positions (including z midpoint delta)
    avg_x1 = float(np.mean(cx1_rel))
    avg_y1 = float(np.mean(cy1_rel))
    avg_x2 = float(np.mean(cx2_rel))
    avg_y2 = float(np.mean(cy2_rel))
    z_mid1 = float(np.mean(z1))
    z_mid2 = float(np.mean(z2))
    ax.plot(
        [avg_x1, avg_x2],
        [z_mid1, z_mid2],
        [avg_y1, avg_y2],
        color='black',
        linestyle='--',
        linewidth=2.0,
        label='Inter-series inaccuracy vector',
    )

    ax.set_xlabel('Center X Offset from CT Center (mm)', fontsize=11, fontweight='bold')
    ax.set_ylabel('Z Position (mm)', fontsize=11, fontweight='bold')
    ax.set_zlabel('Center Y Offset from CT Center (mm)', fontsize=11, fontweight='bold')
    ax.set_xlim(-10.0, 10.0)
    ax.set_zlim(-10.0, 10.0)
    ax.set_title('Z-Axis Coregistration in 3D (Center Trajectories and Orientation)', fontsize=13, fontweight='bold')
    ax.legend(loc='best', fontsize=9)
    ax.view_init(elev=20, azim=-55)

    fig.suptitle(
        '3D Coregistration View: fitted lines represent orientation, connector shows inaccuracy',
        fontsize=13,
        fontweight='bold'
    )
    
    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    SUCCESS(f"Center plot saved: {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Z-axis coregistration analysis with per-slice center detection and pitch/yaw error calculation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python z_axis_coregistration.py --series1 ./pet_series --series2 ./ct_series
  python z_axis_coregistration.py --series1 s1 --series2 s2 --window 100
    python z_axis_coregistration.py --series1 s1 --series2 s2 --debug
    python z_axis_coregistration.py --series1 s1 --series2 s2 --center-crop-mm 250
    python z_axis_coregistration.py --series1 s1 --series2 s2 --canny-low-q 25 --canny-high-q 70
    python z_axis_coregistration.py --series1 s1 --series2 s2 --hough-radius-step 3 --hough-max-radii 20
    python z_axis_coregistration.py --series1 s1 --series2 s2 --approx-radius-mm 100
    python z_axis_coregistration.py --series1 s1 --series2 s2 --table-exclusion-mm 30
  python z_axis_coregistration.py --series1 s1 --series2 s2 --output results
  python z_axis_coregistration.py  (opens folder selection dialog)
        """,
    )
    
    parser.add_argument(
        "--series1",
        type=str,
        required=False,
        help="Path to first DICOM series folder.",
    )
    parser.add_argument(
        "--series2",
        type=str,
        required=False,
        help="Path to second DICOM series folder.",
    )
    parser.add_argument(
        "--window",
        type=float,
        default=75.0,
        help='Analysis window half-width in mm (default: 75)',
    )
    parser.add_argument(
        "--output",
        type=str,
        default="roi_profiles",
        help="Output directory for JSON, CSV, and plots (default: roi_profiles).",
    )
    parser.add_argument(
        "--peaks",
        type=str,
        default=None,
        help="Path to roi_profile_peaks.json file (default: looks in output directory).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug splash view with detected centers/circles and fused overlay.",
    )
    parser.add_argument(
        "--approx-radius-mm",
        type=float,
        default=None,
        help="Optional approximate phantom radius in mm to constrain circle fitting and reduce table influence.",
    )
    parser.add_argument(
        "--table-exclusion-mm",
        type=float,
        default=0.0,
        help="Bottom strip height in mm excluded from radius fitting to suppress table inclusion (default: 0).",
    )
    parser.add_argument(
        "--center-crop-mm",
        type=float,
        default=250.0,
        help="Centered square crop size in mm used for center/radius detection (default: 250).",
    )
    parser.add_argument(
        "--canny-sigma",
        type=float,
        default=1.6,
        help="Canny smoothing sigma for Hough edge detection (default: 1.6).",
    )
    parser.add_argument(
        "--canny-low-q",
        type=float,
        default=35.0,
        help="Low percentile (0-100) of gradient magnitude for Canny low threshold (default: 35).",
    )
    parser.add_argument(
        "--canny-high-q",
        type=float,
        default=80.0,
        help="High percentile (0-100) of gradient magnitude for Canny high threshold (default: 80).",
    )
    parser.add_argument(
        "--hough-radius-step",
        type=int,
        default=2,
        help="Step size in pixels for Hough radius candidates (default: 2).",
    )
    parser.add_argument(
        "--hough-max-radii",
        type=int,
        default=30,
        help="Maximum number of Hough radius candidates after subsampling (default: 30).",
    )
    
    args = parser.parse_args()
    
    # If no series specified, open folder selection dialog
    output_dir = args.output
    if not args.series1 or not args.series2:
        INFO("No series paths specified, opening folder selection dialog...")
        args.series1, args.series2, selected_output = select_dicom_folders()
        # Use selected output directory if provided, otherwise keep command-line arg
        if selected_output:
            output_dir = selected_output
    
    # Validate inputs
    if not os.path.isdir(args.series1):
        ERROR(f"Series 1 directory not found: {args.series1}")
        return 1
    if not os.path.isdir(args.series2):
        ERROR(f"Series 2 directory not found: {args.series2}")
        return 1
    
    # Setup paths - use absolute path if provided, otherwise relative to script dir
    if os.path.isabs(output_dir):
        output_path = Path(output_dir)
    else:
        script_dir = Path(__file__).parent.parent
        output_path = script_dir / output_dir
    
    # Determine peaks file location
    if args.peaks:
        peaks_json = Path(args.peaks)
    else:
        # Prefer output directory for peaks tied to this run
        peaks_json = output_path / "roi_profile_peaks.json"
    
    output_json = output_path / "z_axis_coregistration.json"
    output_csv = output_path / "z_axis_coregistration.csv"
    plot_output = output_path / "z_axis_coregistration_plot.png"
    debug_splash_output = output_path / "z_axis_coregistration_debug_splash.png"
    
    INFO(f"Output directory: {output_path}")
    
    if not peaks_json.exists():
        INFO(f"Peak data not found at: {peaks_json}")
        if args.peaks:
            ERROR("--peaks was provided but file not found. Aborting.")
            return 1

        gen_code = generate_peak_data(args.series1, args.series2, output_path)
        if gen_code != 0:
            ERROR("Failed to generate peak data via roi_axial_profile.")
        else:
            peaks_json = output_path / "roi_profile_peaks.json"

        # Fallback to default location only if generation failed or file still missing
        if not peaks_json.exists():
            default_peaks = Path(__file__).parent.parent / "roi_profiles" / "roi_profile_peaks.json"
            if default_peaks.exists():
                INFO(f"Using peak data from default location: {default_peaks}")
                peaks_json = default_peaks
            else:
                ERROR(f"Peak data still not found after generation: {peaks_json}")
                return 1
    
    try:
        INFO(f"Loading peak data from {peaks_json.name}...")
        peak_data = load_peak_data(peaks_json)
        
        INFO(f"Fitting Z-axis coregistration...")
        results = fit_z_coregistration(
            args.series1,
            args.series2,
            peak_data,
            window_mm=args.window,
            debug=args.debug,
            debug_splash_path=str(debug_splash_output),
            approx_radius_mm=args.approx_radius_mm,
            table_exclusion_mm=args.table_exclusion_mm,
            center_crop_mm=args.center_crop_mm,
            canny_sigma=args.canny_sigma,
            canny_low_q=args.canny_low_q,
            canny_high_q=args.canny_high_q,
            hough_radius_step=args.hough_radius_step,
            hough_max_radii=args.hough_max_radii,
        )
        
        print()
        print_results(results)
        save_results(results, output_json)
        save_csv_summary(results, output_csv)
        
        INFO(f"Creating center position plot...")
        create_center_plot(results, plot_output)
        
        SUCCESS("Done!")
        return 0
    
    except Exception as e:
        ERROR(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

