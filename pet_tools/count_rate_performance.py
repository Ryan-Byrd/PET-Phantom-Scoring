# -*- coding: utf-8 -*-
"""
Count_Rate_Performance.py — Uniformity-only workflow using accurate SUV handling.

What it does
------------
- Lets you pick a PET DICOM series (input) and an output folder/subfolder.
- You select EXACTLY THREE slices (uniformity slices).
- You click ONE center point on the first selected slice; the same center (in mm) is used for all three.
- For each slice, it computes an SUV image (Siemens-aware; BW by default) and
  measures SUVmean within a 180 mm diameter circular ROI.
- Saves:
  • CSV: Count_Rate_Performance.csv  (SliceIndex, SUVmean)
  • PNG: Count_Rate_Performance.png  (1×3 layout, 0–3 SUV window) with ROI & text "Mean = X.XX SUV".

Notes
-----
- Windowing: each panel uses vmin=0, vmax=3 on the computed SUV image.
- Manufacturer-specific scaling:
  • Siemens with Units=BQML → pixel array is already in Bq/mL; we do NOT reapply RescaleSlope.
  • Others → apply RescaleSlope/Intercept to get Bq/mL before SUV normalization.
- DecayCorrection handling:
  • If DecayCorrection == 'ADMIN' → Aref = A0 (no decay to scan time).
  • Else (e.g., 'START'/'NONE') → Aref = A0 decayed to the reference time (START by default).

Dependencies
------------
- Python 3.x
- pydicom, numpy, matplotlib, tkinter
"""

import os, math, csv, sys
from datetime import datetime, date, time, timedelta
import numpy as np
import pydicom
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Cursor
from pet_tools.dicom_metadata_overrides import (
    apply_metadata_overrides,
    build_metadata_override_audit,
    load_metadata_overrides,
    write_metadata_override_audit,
)


def _ensure_ct_toolkit_on_path():
    """Prepend CT toolkit/repo root so imports succeed when run standalone."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ct_path = os.path.join(base_dir, "CT_Analysis_Toolkit")
    for p in (ct_path, base_dir):
        if p and p not in sys.path:
            sys.path.insert(0, p)


_ensure_ct_toolkit_on_path()

from CT_Analysis_Toolkit.Modules.find_phantom_center import find_phantom_center_generalized


# ---------------------- Config ----------------------
FOV_MM        = 250.0          # zoom FOV for panels
UNIF_DIAM_MM  = 180.0          # uniformity ROI diameter
SUV_TIME_REF  = "START"        # 'START' or 'MID'
SUV_MASS_NORM = "BW"           # 'BW' (default), 'LBM', 'IBW', 'BSA'

# Fallbacks used ONLY if DICOM is missing these fields
DEFAULT_HEIGHT_CM = 175
DEFAULT_SEX       = "M"        # "M" or "F"

# ---------------------- Logging ----------------------
def _c(code): return f"\\033[{code}m"
CLR = {"reset": _c("0"), "cyan": _c("36"), "yellow": _c("33"), "red": _c("31")}
def INFO(m):  print(f"{CLR['cyan']}[INFO]{CLR['reset']} {m}")
def WARN(m):  print(f"{CLR['yellow']}[WARN]{CLR['reset']} {m}")
def ERROR(m): print(f"{CLR['red']}[ERROR]{CLR['reset']} {m}", file=sys.stderr)

# ---------------------- UI helpers ----------------------
def ask_folder(title):
    root = tk.Tk(); root.withdraw()
    path = filedialog.askdirectory(title=title)
    try: root.destroy()
    except Exception: pass
    return path

def ask_output_folder_and_name():
    root = tk.Tk(); root.withdraw()
    base = filedialog.askdirectory(title="Select OUTPUT parent folder")
    if not base:
        try: root.destroy()
        except Exception: pass
        return None
    name = simpledialog.askstring("Output Subfolder", "Enter a name for the output subfolder:")
    try: root.destroy()
    except Exception: pass
    if not name: return None
    out_dir = os.path.join(base, name)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir

def set_fov_mm(ax, center_mm, fov_mm=FOV_MM):
    half = fov_mm/2.0
    cx, cy = center_mm
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy + half, cy - half)

# ---------------------- DICOM time helpers ----------------------
def _float(x, default=0.0):
    try: return float(x)
    except Exception: return default

def _get_patient_sex(ds):
    s = str(getattr(ds, "PatientSex", "")).upper().strip()
    return s if s in ("M", "F") else DEFAULT_SEX

def _get_height_m(ds):
    h = _float(getattr(ds, "PatientSize", 0.0))
    if h > 0: return h
    return DEFAULT_HEIGHT_CM / 100.0

def _lbm_kg_james(sex, weight_kg, height_m):
    h_cm = height_m * 100.0
    if sex == "M":
        lbm = 1.10 * weight_kg - 128.0 * (weight_kg / h_cm) ** 2
    else:
        lbm = 1.07 * weight_kg - 148.0 * (weight_kg / h_cm) ** 2
    return max(0.1, lbm)

def _ibw_kg_devine(sex, height_m):
    h_in = height_m * 39.3700787
    base = 50.0 if sex == "M" else 45.5
    return max(0.1, base + 2.3 * max(0.0, (h_in - 60.0)))

def _bsa_m2_mosteller(weight_kg, height_m):
    return math.sqrt((height_m * 100.0 * weight_kg) / 3600.0)

def _mass_norm_grams(ds):
    """Return mass normalization in grams based on SUV_MASS_NORM."""
    weight_kg = _float(getattr(ds, "PatientWeight", 0.0))
    if weight_kg <= 0: return None

    sex = _get_patient_sex(ds)
    height_m = _get_height_m(ds)
    norm = str(SUV_MASS_NORM).upper().strip()

    if norm == "BW":
        return weight_kg *1000
    if norm == "LBM":
        return _lbm_kg_james(sex, weight_kg, height_m) * 1000.0
    if norm == "IBW":
        return _ibw_kg_devine(sex, height_m) * 1000.0
    if norm == "BSA":
        return _bsa_m2_mosteller(weight_kg, height_m) * 1000.0
    return weight_kg * 1000.0

def _parse_hhmmss(tstr: str) -> time:
    if not tstr: return time(0,0,0)
    core = tstr.split('.')[0]; core = (core + "000000")[:6]
    return time(int(core[0:2]), int(core[2:4]), int(core[4:6]))

def _parse_yyyymmdd(dstr: str) -> date:
    if not dstr:
        now=datetime.now(); return date(now.year,now.month,now.day)
    return date(int(dstr[0:4]), int(dstr[4:6]), int(dstr[6:8]))

def _dt_from_str(s):
    return datetime.strptime(s.split('.')[0], "%Y%m%d%H%M%S")

def acquisition_start_dt(ds):
    # Siemens START → SeriesDate/Time
    d = getattr(ds,'SeriesDate',None); t = getattr(ds,'SeriesTime',None)
    return datetime.combine(_parse_yyyymmdd(d), _parse_hhmmss(t))

def frame_mid_dt(ds):
    """Estimate mid-frame datetime from SeriesDate/Time + Actual Frame Duration or Frame Reference Time."""
    start = acquisition_start_dt(ds)
    afd = getattr(ds, "ActualFrameDuration", None)  # ms
    if isinstance(afd, (int, float)) and afd > 0:
        return start + timedelta(milliseconds=float(afd) / 2.0)
    frt = getattr(ds, "FrameReferenceTime", None)   # ms
    if isinstance(frt, (int, float)):
        return start + timedelta(milliseconds=float(frt))
    return start

def siemens_private_decay_dt(ds):
    try:
        tag = ds.get((0x0071,0x1022), None)
        if tag: return _dt_from_str(str(tag.value))
    except Exception: pass
    return None

def injection_dt(ds):
    rps = getattr(ds,'RadiopharmaceuticalInformationSequence',None)
    rps = rps[0] if rps else None
    if not rps: return None
    sdt = getattr(rps,'RadiopharmaceuticalStartDateTime',None)
    if sdt: return _dt_from_str(sdt)
    st = getattr(rps,'RadiopharmaceuticalStartTime',None)
    sd = getattr(ds,'StudyDate',None)
    if st:
        return datetime.combine(_parse_yyyymmdd(sd), _parse_hhmmss(st))
    return None

def _choose_time_ref(ds):
    ref = str(SUV_TIME_REF).upper().strip()
    if ref == "MID":
        return frame_mid_dt(ds)
    return acquisition_start_dt(ds)

# ---------------------- DICOM loading ----------------------
def load_series(folder, metadata_overrides=None, override_audit_records=None):
    """Load a series, return (disp_imgs, res_imgs, dsets, (row_mm, col_mm))."""
    paths = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".dcm")]
    if not paths: raise RuntimeError("No .dcm files found.")
    ds_list = []
    for p in paths:
        try:
            ds = pydicom.dcmread(p, stop_before_pixels=False)
        except Exception as e:
            WARN(f"Skipping unreadable {os.path.basename(p)} ({e})")
            continue
        if not hasattr(ds, "PixelData"):
            WARN("Skipping non-image DICOM"); continue
        if str(getattr(ds, "Modality", "")).upper() not in ("PT","NM","CT"):
            WARN(f"Skipping modality {getattr(ds,'Modality','')}"); continue
        if metadata_overrides is not None:
            ds, applied_records = apply_metadata_overrides(ds, metadata_overrides)
            if override_audit_records is not None:
                override_audit_records.extend(applied_records)
        ds_list.append(ds)
    if not ds_list: raise RuntimeError("No usable images found.")

    def sort_key(ds):
        if "ImagePositionPatient" in ds:
            ipp = ds.ImagePositionPatient
            return float(ipp[2]) if len(ipp)>=3 else float(getattr(ds,"InstanceNumber",0))
        return float(getattr(ds,"InstanceNumber",0))
    ds_list.sort(key=sort_key)

    ref_rows = int(getattr(ds_list[0],"Rows",0)); ref_cols = int(getattr(ds_list[0],"Columns",0))
    if ref_rows==0 or ref_cols==0: raise RuntimeError("Missing Rows/Columns.")
    pxsp = getattr(ds_list[0],"PixelSpacing",[1.0,1.0]); row_mm, col_mm = float(pxsp[0]), float(pxsp[1])

    disp_imgs, res_imgs, dsets = [], [], []
    for ds in ds_list:
        rows, cols = int(getattr(ds,"Rows",0)), int(getattr(ds,"Columns",0))
        if rows!=ref_rows or cols!=ref_cols:
            WARN(f"Skipping matrix {rows}x{cols} (expected {ref_rows}x{ref_cols})"); continue
        try:
            arr = ds.pixel_array
        except Exception as e:
            WARN(f"Skipping pixel read error: {e}"); continue
        if arr.ndim!=2:
            WARN("Skipping non-2D frame"); continue

        slope = float(getattr(ds, "RescaleSlope", 1.0))
        inter = float(getattr(ds, "RescaleIntercept", 0.0))
        manuf = str(getattr(ds, "Manufacturer", "")).upper()
        units = str(getattr(ds, "Units", "")).upper()

        # Siemens PET data already in Bq/mL: skip double scaling
        if manuf == "SIEMENS" and units == "BQML":
            img_res = arr.astype(np.float32)
        else:
            img_res = arr * slope + inter

        m = float(np.max(img_res)) if np.max(img_res) else 1.0
        img_disp = img_res / m
        res_imgs.append(img_res); disp_imgs.append(img_disp); dsets.append(ds)

    if len(disp_imgs) < 3:
        raise RuntimeError(f"Only {len(disp_imgs)} usable frames; need ≥3.")
    return disp_imgs, res_imgs, dsets, (row_mm, col_mm)

# ---------------------- SUV computation ----------------------
def suv_from_ds(ds, a):
    """
    Compute SUV image from raw activity concentration-like pixel array `a`.
    - Applies RescaleSlope/Intercept to activity concentration.
    - Uses ADMIN vs START/NONE logic for decay reference.
    - Normalizes by body weight (default) or other mass scalers if configured.
    Returns: suv_img (float32)
    """
    a = np.nan_to_num(a, nan=0.0).astype(np.float32)

    manuf = str(getattr(ds, "Manufacturer", "")).upper()
    units = str(getattr(ds, "Units", "")).upper()
    dc    = str(getattr(ds, "DecayCorrection", "")).upper()

    # Rescale to Bq/mL
    slope = float(getattr(ds, "RescaleSlope", 1.0))
    inter = float(getattr(ds, "RescaleIntercept", 0.0))
    if manuf == "SIEMENS" and units == "BQML":
        a_bqml = (a * slope) + inter  # already Bq/mL
    else:
        a_bqml = a

    # Radiopharm info
    rps = getattr(ds, "RadiopharmaceuticalInformationSequence", None)
    rps = rps[0] if rps else None
    if not rps:
        WARN("Missing Radiopharmaceutical Information Sequence → returning Bq/mL image.")
        return a_bqml

    A0 = float(getattr(rps, "RadionuclideTotalDose", 0.0))
    HL = float(getattr(rps, "RadionuclideHalfLife", 0.0))
    lam = math.log(2.0) / HL if HL > 0 else 0.0

    inj_dt = injection_dt(ds)
    ref_dt = _choose_time_ref(ds)
    dt_s   = (ref_dt - inj_dt).total_seconds() if inj_dt and ref_dt else 0.0

    # Determine Aref
    if "ADMIN" in dc:
        Aref = A0
    else:
        Aref = A0 * math.exp(-lam * dt_s)

    # Body mass scaler
    M = _mass_norm_grams(ds)
    if not M or M <= 0:
        WARN("Missing patient mass → returning Bq/mL image.")
        return a_bqml

    suv = a_bqml * (M / Aref) if Aref > 0 else a_bqml
    suv = np.nan_to_num(suv, nan=0.0, posinf=3.0, neginf=0.0)
    return suv.astype(np.float32)

# ---------------------- Geometry helpers ----------------------
def circle_mask_mm(shape, center_mm, radius_mm, pixel_mm):
    h,w = shape; row_mm,col_mm = pixel_mm
    ys = (np.arange(h)+0.5)*row_mm; xs=(np.arange(w)+0.5)*col_mm
    X,Y = np.meshgrid(xs,ys)
    cx,cy=center_mm
    return (X-cx)**2 + (Y-cy)**2 <= radius_mm**2

def roi_inside_image(shape, center_mm, radius_mm, pixel_mm):
    h,w = shape; row_mm,col_mm = pixel_mm
    Wmm, Hmm = w*col_mm, h*row_mm; cx,cy=center_mm
    return (radius_mm <= cx <= Wmm-radius_mm) and (radius_mm <= cy <= Hmm-radius_mm)

# ---------------------- Selection UIs ----------------------
def select_three(images, pixel_mm):
    """Grid preview; click EXACTLY three images → returns indices of chosen slices."""
    row_mm, col_mm = pixel_mm
    sel = []
    n = len(images); cols=6; rows=max(1,int(np.ceil(n/cols)))
    fig, axes = plt.subplots(rows, cols, figsize=(12, 2+2*rows))
    axes = np.atleast_1d(axes).ravel()
    for i, ax in enumerate(axes):
        ax.axis('off')
        if i<n:
            h,w = images[i].shape
            extent=[0,w*col_mm,h*row_mm,0]
            ax.imshow(images[i], cmap="gray", extent=extent, origin="upper")
            ax.set_aspect("equal")
            set_fov_mm(ax, (w*col_mm/2.0,h*row_mm/2.0), fov_mm=FOV_MM )
            ax.set_title(f"Slice {i}", fontsize=8)
    fig.suptitle("Click 3 images (Uniformity slices)", fontsize=14)
    def onclick(e):
        if e.inaxes not in axes: return
        idx = list(axes).index(e.inaxes)
        if idx<n and idx not in sel:
            sel.append(idx); e.inaxes.set_title(f"Selected {len(sel)}", color="tab:blue")
            fig.canvas.draw_idle()
        if len(sel)==3: plt.close(fig)
    fig.canvas.mpl_connect("button_press_event", onclick)
    plt.show()
    if len(sel)!=3: raise RuntimeError("Selection cancelled or not enough images chosen.")
    return sel

def click_center(image, pixel_mm):
    """
    Click one center (in mm) on the first uniformity slice; reused for all 3.
    Shows inverted (white background) display and yellow crosshair.
    """
    row_mm, col_mm = pixel_mm
    h, w = image.shape
    extent = [0, w * col_mm, h * row_mm, 0]
    fig, ax = plt.subplots()
    # Invert for display: white background (0 SUV), black-hot (3 SUV)
    ax.imshow(3.0 - np.clip(image, 0, 3), cmap="gray", extent=extent, origin="upper", vmin=0, vmax=3)
    ax.set_aspect("equal")
    ax.set_title("Uniformity: Click CENTER (180 mm ROI)")
    set_fov_mm(ax, (w * col_mm / 2.0, h * row_mm / 2.0), fov_mm=FOV_MM)
    Cursor(ax, useblit=True, color='yellow', linewidth=1.2)

    picked = []
    def onclick(e):
        if e.inaxes != ax:
            return
        picked[:] = [(e.xdata, e.ydata)]
        ax.plot(e.xdata, e.ydata, 'ro', ms=4)
        fig.canvas.draw_idle()
        plt.close(fig)

    fig.canvas.mpl_connect("button_press_event", onclick)
    plt.show()
    if not picked:
        raise RuntimeError("No point selected.")
    return np.array(picked[0])

def auto_select_uniformity_slices(dsets, disp_imgs, pixel_spacing_mm, center_xy_px,
                                  roi_diam_mm=180.0, n_select=3, debug=False):
    """
    Automatically find uniformity slices by choosing the frames whose
    central 180 mm ROI has the highest minimum voxel value.

    Parameters
    ----------
    dsets : list of pydicom.Dataset
        DICOM slices (ordered).
    disp_imgs : list of np.ndarray
        Displayable PET images (SUV or similar scale).
    pixel_spacing_mm : float
        Pixel spacing in mm.
    center_xy_px : tuple(float, float)
        Phantom center (x,y) in pixels.
    roi_diam_mm : float, optional
        Diameter of ROI in mm (default 180).
    n_select : int, optional
        How many slices to choose (default 3).
    debug : bool, optional
        If True, print ranked slice stats.

    Returns
    -------
    list[int]
        Indices of the selected uniformity slices (sorted ascending).
    """
    import numpy as np

    h, w = disp_imgs[0].shape
    Y, X = np.ogrid[:h, :w]
    cx, cy = center_xy_px
    r_px = (roi_diam_mm / 2) / pixel_spacing_mm
    mask = (X - cx)**2 + (Y - cy)**2 <= r_px**2

    mins = []
    for idx, img in enumerate(disp_imgs):
        roi_vals = img[mask]
        mins.append((idx, float(np.nanmin(roi_vals))))

    # Sort by minimum ROI value descending → highest minima = most uniform
    mins.sort(key=lambda t: t[1], reverse=True)
    selected = [idx for idx, _ in mins[:n_select]]
    selected.sort()

    if debug:
        print("\n[Uniformity slice ranking by min(ROI) value]")
        for i, (idx, val) in enumerate(mins[:10]):
            print(f"  {i+1:>2}. slice {idx:>3} → min={val:.3f}")
        print(f"\n[Selected uniformity slices] {selected}")

    return selected



# ---------------------- Main ----------------------
def main(argv=None):
    """
    Count Rate Performance – Uniformity Section Only
    Selects 3 slices with highest min SUV in 180 mm ROI,
    creates 1×3 overlay identical to ACR SEV format,
    and saves SUV stats to CSV.
    """
    import argparse
    import os

    parser = argparse.ArgumentParser(
        description="Count Rate Performance – Uniformity Section Only"
    )
    parser.add_argument(
        "--input", "-i",
        help="Path to input DICOM folder (optional)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Path to output folder (optional)"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--debug-dir",
        help="Directory for debug artifacts; defaults to a debug subfolder in the output directory",
    )
    parser.add_argument(
        "--metadata-overrides",
        help="JSON file containing in-memory DICOM metadata overrides for SUV calculation",
    )
    args = parser.parse_args(argv)

    try:
        import numpy as np
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle

        # --- Select folders (CLI first, fallback to GUI) ---
        if args.input:
            in_dir = os.path.abspath(args.input)
        else:
            in_dir = ask_folder("Select PET DICOM Folder (INPUT)")

        if not in_dir:
            INFO("Cancelled: no input folder.")
            return

        metadata_overrides = (
            load_metadata_overrides(args.metadata_overrides)
            if args.metadata_overrides else None
        )
        override_audit_records = []

        if args.output:
            out_dir = os.path.abspath(args.output)
        else:
            out_dir = ask_output_folder_and_name()

        if not out_dir:
            INFO("Cancelled: no output folder/name.")
            return

        INFO(f"Input: {in_dir}")
        INFO(f"Output: {out_dir}")
        if args.debug and metadata_overrides is not None:
            INFO(f"Metadata overrides: {metadata_overrides.source_path}")

        # --- Load PET DICOMs ---
        INFO("Loading series…")
        disp_imgs, res_imgs, dsets, (row_mm, col_mm) = load_series(
            in_dir,
            metadata_overrides=metadata_overrides,
            override_audit_records=override_audit_records,
        )
        if metadata_overrides is not None:
            audit_path = write_metadata_override_audit(
                out_dir,
                build_metadata_override_audit(
                    "count_rate_performance",
                    metadata_overrides,
                    override_audit_records,
                    len(dsets),
                    dsets[0],
                ),
            )
            INFO(f"Saved metadata override audit -> {audit_path}")

        # --- Auto phantom center ---
        mid_idx = len(dsets) // 2
        px_array = dsets[mid_idx].pixel_array.astype(np.float32)
        pixel_spacing = np.mean([row_mm, col_mm])
        center_result = find_phantom_center_generalized(
            px_array,
            pixel_size_mm=pixel_spacing,
            modality="PT",
            debug=args.debug,
            return_details=args.debug,
        )
        if args.debug:
            cy, cx, radius_px, center_details = center_result
            debug_dir = os.path.abspath(args.debug_dir or os.path.join(out_dir, "debug"))
            os.makedirs(debug_dir, exist_ok=True)

            fig, ax = plt.subplots(figsize=(7, 7))
            ax.imshow(px_array, cmap="gray")
            ax.add_patch(Circle((cx, cy), radius_px, fill=False, color="lime", lw=0.75))
            ax.plot(cx, cy, "rx", ms=10, mew=2)
            ax.set_aspect("equal")
            ax.set_title("PT Phantom Center and Circle Fit")
            overview_path = os.path.join(debug_dir, "center_overview.png")
            fig.savefig(overview_path, dpi=200, bbox_inches="tight")
            plt.close(fig)

            summary_path = os.path.join(debug_dir, "debug_summary.txt")
            with open(summary_path, "w", encoding="utf-8") as summary_file:
                summary_file.write("Count Rate Performance center-finding overview\n")
                summary_file.write(f"Input directory: {in_dir}\n")
                summary_file.write(f"Centering modality argument: {center_details['modality']}\n")
                summary_file.write(f"Normalization: {center_details['normalization_method']}\n")
                summary_file.write(f"Segmentation: {center_details['segmentation_method']}\n")
                summary_file.write(f"Circle fit: {center_details['circle_fit_method']}\n")
                summary_file.write(f"Center: x={cx:.3f} px, y={cy:.3f} px\n")
                summary_file.write(f"Radius: {radius_px:.3f} px ({radius_px * pixel_spacing:.3f} mm)\n")
            INFO(f"Saved centering debug overview -> {overview_path}")
            INFO(f"Saved centering debug summary -> {summary_path}")
        else:
            cy, cx, radius_px = center_result
        center_xy_px = (cx, cy)
        INFO(f"[Auto-center] x={cx:.1f}, y={cy:.1f}, radius={radius_px:.1f}px")

        # --- Select uniformity slices (3) ---
        uniformity_idx = auto_select_uniformity_slices(
            dsets, res_imgs, pixel_spacing, center_xy_px, n_select=3, debug=True
        )
        INFO(f"[INFO] Selected uniformity slices: {uniformity_idx}")

        # --- Measure SUV stats in 180 mm ROI ---
        r_mm = 90.0  # radius of 180 mm diameter ROI
        suv_results = []
        for idx in uniformity_idx:
            suv_img = suv_from_ds(dsets[idx], res_imgs[idx])
            h, w = suv_img.shape
            Y, X = np.ogrid[:h, :w]
            mask = (X - cx)**2 + (Y - cy)**2 <= (r_mm / pixel_spacing)**2
            roi_vals = suv_img[mask]
            suv_mean = float(np.nanmean(roi_vals))
            suv_min = float(np.nanmin(roi_vals))
            suv_max = float(np.nanmax(roi_vals))
            suv_results.append((idx, suv_mean, suv_min, suv_max))
            INFO(f"[Slice {idx}] SUV mean={suv_mean:.3f}, min={suv_min:.3f}, max={suv_max:.3f}")

        # --- Save CSV ---
        csv_path = os.path.join(out_dir, "Count_Rate_Performance_SUV_Measurements.csv")
        with open(csv_path, "w") as f:
            f.write("SliceIndex,SUVmean,SUVmin,SUVmax\n")
            for idx, suv_mean, suv_min, suv_max in suv_results:
                f.write(f"{idx},{suv_mean:.6f},{suv_min:.6f},{suv_max:.6f}\n")
        INFO(f"Saved SUV data → {csv_path}")

        # --- 1×3 ACR-style overlay (inverted gray phantom on white background) ---
        fig, axs = plt.subplots(1, 3, figsize=(15, 5), facecolor="white")

        vmin_fixed = 0.0
        vmax_fixed = 3.0

        # ----- FORCE DISPLAYED FIELD-OF-VIEW TO 250 mm × 250 mm -----
        FOV_MM = 250.0
        half_fov = FOV_MM / 2.0

        for ax, idx in zip(axs, uniformity_idx):
            suv_img = suv_from_ds(dsets[idx], res_imgs[idx])
            h, w = suv_img.shape

            # Physical coordinate extents of the full image (mm)
            extent = [0, w * col_mm, h * row_mm, 0]

            # Draw the image (inverted gray phantom on white)
            ax.imshow(
                suv_img,
                cmap="gray_r",
                extent=extent,
                origin="upper",
                vmin=vmin_fixed,
                vmax=vmax_fixed
            )

            # --- FORCE 250 MM FOV, CENTERED ON (cx, cy) ---
            center_x_mm = cx * col_mm
            center_y_mm = cy * row_mm

            ax.set_xlim(center_x_mm - half_fov, center_x_mm + half_fov)
            ax.set_ylim(center_y_mm + half_fov, center_y_mm - half_fov)

            # ROI circle (still drawn in mm)
            ax.add_patch(
                Circle(
                    (center_x_mm, center_y_mm),
                    r_mm,
                    fill=False,
                    color="dodgerblue",
                    lw=2
                )
            )

            # Text overlay
            suv_mean = suv_results[uniformity_idx.index(idx)][1]
            ax.text(
                center_x_mm,
                center_y_mm,
                f"{suv_mean:.2f} SUV",
                color="dodgerblue",
                fontsize=16,
                fontname="Verdana",
                ha="center",
                va="center"
            )

            ax.set_title(f"Slice {idx}", fontsize=10, color="black", pad=8)
            ax.axis("off")

        plt.subplots_adjust(wspace=0.02, hspace=0)
        overlay_path = os.path.join(out_dir, "Uniformity_SUV_Overlay.png")
        fig.savefig(overlay_path, dpi=300, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        INFO(f"Saved overlay → {overlay_path}")

        composite_path = os.path.join(out_dir, "Uniformity_SUV_Composite.png")
        os.replace(overlay_path, composite_path)
        INFO(f"Renamed overlay to → {composite_path}")

    except Exception as e:
        ERROR(str(e))

if __name__ == "__main__":
    raise SystemExit(main())
