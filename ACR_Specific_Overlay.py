# -*- coding: utf-8 -*-
"""
ACR_Specific Overlay.py

What it does:
- User selects an INPUT folder containing DICOM images
- User picks ONE image to process from a list of all images in that folder
- User clicks: Center (auto-detected with optional manual override) -> 25 mm -> 16 mm
- Creates an overlay like the hotcell overlay (7 ROIs), PLUS a central ROI of 6.5 cm diameter
- Central ROI reports SUVmean (average)
- Bottom-left text shows SliceThickness and Slice Number (InstanceNumber if present; else index)
- Display FOV is fixed at 220 x 220 mm

Notes:
- Uses Siemens-aware SUV handling similar to the other PET scripts in this project:
  if Manufacturer==SIEMENS and Units==BQML, applies rescale slope/intercept to get Bq/mL,
  then computes SUV with ADMIN vs START/NONE decay logic (BW normalization).
"""

import os
import math
import csv
import sys
import argparse
from datetime import datetime, date, time, timedelta

import numpy as np
import pydicom

import matplotlib


def _has_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401
        from tkinter import filedialog as _fd  # noqa: F401
        return True
    except Exception:
        return False


def _configure_matplotlib_backend():
    """Prefer TkAgg when available; otherwise fall back to a GUI backend.

    This script uses interactive matplotlib figures (ginput/clicks). Some Python
    installs on macOS (notably certain Homebrew builds) do not include `_tkinter`.
    """
    if _has_tkinter():
        try:
            matplotlib.use("TkAgg", force=True)
            return
        except Exception:
            pass

    # On macOS, the native backend usually works without tkinter.
    try:
        matplotlib.use("MacOSX", force=True)
    except Exception:
        # Leave default backend as-is.
        pass


_configure_matplotlib_backend()
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Cursor

from CT_Analysis_Toolkit.Modules.find_phantom_center import find_phantom_center_generalized
import glob


# ---------------------- Config ----------------------
LABEL_ORDER = ["25", "16", "12", "8", "Bone", "Air", "Water"]

FOV_MM = 220.0                 # REQUIRED: 220x220 mm
SUV_ROI_DIAM_MM = 25.0         # hotcell-like ROIs
CENTRAL_ROI_DIAM_MM = 65.0     # REQUIRED: 6.5 cm = 65 mm

SUV_TIME_REF = "START"         # "START" or "MID"
DEFAULT_HEIGHT_CM = 175
DEFAULT_SEX = "M"


# Fixed geometry (mm) relative to phantom center (for angle reference)
REL_COORDS_MM = {
    "25":   (46.28704628704628,  -48.40992341),
    "16":   (67.26606727,          8.200133200133223),
    "12":   (50.61605061605064,   46.82817182817183),
    "8":    (24.309024309024323,  64.47718947718948),
    "Bone": (-29.63702964,        -59.06593407),
    "Air":  (-69.26406926,          5.2031302031302005),
    "Water":(-22.97702298,         66.14219114219117),
}


# ---------------------- Logging ----------------------
def _c(code): return f"\033[{code}m"
CLR = {"reset": _c("0"), "cyan": _c("36"), "yellow": _c("33"), "red": _c("31")}
def INFO(m):  print(f"{CLR['cyan']}[INFO]{CLR['reset']} {m}")
def WARN(m):  print(f"{CLR['yellow']}[WARN]{CLR['reset']} {m}")
def ERROR(m): print(f"{CLR['red']}[ERROR]{CLR['reset']} {m}", file=sys.stderr)


# ---------------------- UI helpers ----------------------
def ask_folder(title: str):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    path = filedialog.askdirectory(title=title)
    try:
        root.destroy()
    except Exception:
        pass
    return path


def ask_output_folder_and_name():
    import tkinter as tk
    from tkinter import filedialog, simpledialog

    root = tk.Tk()
    root.withdraw()
    base = filedialog.askdirectory(title="Select OUTPUT parent folder")
    if not base:
        try:
            root.destroy()
        except Exception:
            pass
        return None
    name = simpledialog.askstring("Output Subfolder", "Enter a name for the output subfolder:")
    try:
        root.destroy()
    except Exception:
        pass
    if not name:
        return None
    out_dir = os.path.join(base, name)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def select_dicom_from_list(folder: str):
    """
    Show a listbox of all DICOM images in folder; user picks one.
    Returns: (selected_path, selected_index_in_sorted_list)
    """
    paths = []
    for fn in os.listdir(folder):
        if fn.lower().endswith(".dcm"):
            paths.append(os.path.join(folder, fn))
    if not paths:
        raise RuntimeError("No .dcm files found in the selected folder.")

    items = []
    meta = []
    for p in paths:
        try:
            ds = pydicom.dcmread(p, stop_before_pixels=True, force=True)
            if not hasattr(ds, "SOPClassUID"):
                continue
            # Require image-ish objects with Rows/Columns; skip non-image objects (e.g., RWVM)
            rows = getattr(ds, "Rows", None)
            cols = getattr(ds, "Columns", None)
            if rows is None or cols is None:
                continue
            inst = getattr(ds, "InstanceNumber", None)
            ipp = getattr(ds, "ImagePositionPatient", None)
            z = None
            if ipp and len(ipp) >= 3:
                try:
                    z = float(ipp[2])
                except Exception:
                    z = None
            items.append((p, inst, z, os.path.basename(p)))
            meta.append(ds)
        except Exception:
            continue

    if not items:
        raise RuntimeError("No usable DICOM image files found (Rows/Columns missing).")

    def sort_key(t):
        _, inst, z, _ = t
        if z is not None:
            return (0, z)
        try:
            return (1, float(inst))
        except Exception:
            return (2, 0.0)

    items.sort(key=sort_key)

    display = []
    for i, (p, inst, z, fn) in enumerate(items):
        inst_s = f"{inst}" if inst is not None else "?"
        z_s = f"{z:.2f}" if isinstance(z, (int, float)) else "?"
        display.append(f"{i:04d} | Inst={inst_s:>4} | z={z_s:>8} | {fn}")

    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("Select DICOM image to process")

    tk.Label(root, text="Select one DICOM image (slice) to process:").pack(padx=10, pady=(10, 0))

    frame = tk.Frame(root)
    frame.pack(padx=10, pady=10, fill="both", expand=True)

    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")

    listbox = tk.Listbox(frame, yscrollcommand=scrollbar.set, width=90, height=20)
    for line in display:
        listbox.insert(tk.END, line)
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=listbox.yview)

    selection = {"idx": None}

    def on_ok():
        sel = listbox.curselection()
        if not sel:
            messagebox.showwarning("No selection", "Please select an image.")
            return
        selection["idx"] = int(sel[0])
        root.destroy()

    def on_cancel():
        selection["idx"] = None
        root.destroy()

    btns = tk.Frame(root)
    btns.pack(padx=10, pady=(0, 10))

    tk.Button(btns, text="OK", width=10, command=on_ok).pack(side="left", padx=5)
    tk.Button(btns, text="Cancel", width=10, command=on_cancel).pack(side="left", padx=5)

    root.mainloop()

    if selection["idx"] is None:
        raise RuntimeError("Selection cancelled.")

    selected_path = items[selection["idx"]][0]
    return selected_path, selection["idx"], items


def build_sorted_items(folder: str):
    """Build the same 'items' list used by select_dicom_from_list but without UI.
    Returns list of tuples: (path, InstanceNumber, z, basename)
    """
    paths = []
    for fn in os.listdir(folder):
        if fn.lower().endswith(".dcm"):
            paths.append(os.path.join(folder, fn))

    items = []
    for p in paths:
        try:
            ds = pydicom.dcmread(p, stop_before_pixels=True, force=True)
            rows = getattr(ds, "Rows", None)
            cols = getattr(ds, "Columns", None)
            if rows is None or cols is None:
                continue
            inst = getattr(ds, "InstanceNumber", None)
            ipp = getattr(ds, "ImagePositionPatient", None)
            z = None
            if ipp and len(ipp) >= 3:
                try:
                    z = float(ipp[2])
                except Exception:
                    z = None
            items.append((p, inst, z, os.path.basename(p)))
        except Exception:
            continue

    def sort_key(t):
        _, inst, z, _ = t
        if z is not None:
            return (0, z)
        try:
            return (1, float(inst))
        except Exception:
            return (2, 0.0)

    items.sort(key=sort_key)
    return items


# ---------------------- Utility ----------------------
def _float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def _parse_hhmmss(tstr: str) -> time:
    if not tstr:
        return time(0, 0, 0)
    core = tstr.split(".")[0]
    core = (core + "000000")[:6]
    return time(int(core[0:2]), int(core[2:4]), int(core[4:6]))


def _parse_yyyymmdd(dstr: str) -> date:
    if not dstr:
        now = datetime.now()
        return date(now.year, now.month, now.day)
    return date(int(dstr[0:4]), int(dstr[4:6]), int(dstr[6:8]))


def acquisition_start_dt(ds):
    d = getattr(ds, "SeriesDate", None)
    t = getattr(ds, "SeriesTime", None)
    return datetime.combine(_parse_yyyymmdd(d), _parse_hhmmss(t))


def frame_mid_dt(ds):
    start = acquisition_start_dt(ds)
    afd = getattr(ds, "ActualFrameDuration", None)
    if isinstance(afd, (int, float)) and afd > 0:
        return start + timedelta(milliseconds=float(afd) / 2.0)
    frt = getattr(ds, "FrameReferenceTime", None)
    if isinstance(frt, (int, float)):
        return start + timedelta(milliseconds=float(frt))
    return start


def injection_dt(ds):
    rps = getattr(ds, "RadiopharmaceuticalInformationSequence", None)
    rps = rps[0] if rps else None
    if not rps:
        return None

    sdt = getattr(rps, "RadiopharmaceuticalStartDateTime", None)
    if sdt:
        try:
            return datetime.strptime(sdt.split(".")[0], "%Y%m%d%H%M%S")
        except Exception:
            pass

    st = getattr(rps, "RadiopharmaceuticalStartTime", None)
    sd = getattr(ds, "StudyDate", None)
    if st:
        return datetime.combine(_parse_yyyymmdd(sd), _parse_hhmmss(st))

    return None


def _choose_time_ref(ds):
    ref = str(SUV_TIME_REF).upper().strip()
    if ref == "MID":
        return frame_mid_dt(ds)
    return acquisition_start_dt(ds)


def _mass_norm_grams_bw(ds):
    # BW only (grams)
    w_kg = _float(getattr(ds, "PatientWeight", 0.0))
    if w_kg <= 0:
        return None
    return w_kg * 1000.0


def suv_from_ds_bw(ds, stored_pixels_2d: np.ndarray):
    """
    Siemens-aware SUV (BW) from a single-slice 2D array.

    IMPORTANT: for parity with the existing pipeline in `3b._Auto_SUV_Overlay.py`,
    this function expects its input array to be "concentration-like":
    - Non-Siemens (or non-BQML) images should already have RescaleSlope/Intercept applied.
    - Siemens + Units==BQML images commonly need RescaleSlope/Intercept applied here.

    - ADMIN vs START/NONE decay logic
    """
    a = np.nan_to_num(stored_pixels_2d, nan=0.0).astype(np.float32)

    manuf = str(getattr(ds, "Manufacturer", "")).upper()
    units = str(getattr(ds, "Units", "")).upper()
    dc = str(getattr(ds, "DecayCorrection", "")).upper()

    slope = float(getattr(ds, "RescaleSlope", 1.0))
    inter = float(getattr(ds, "RescaleIntercept", 0.0))

    # Mirror the 3b pipeline: apply RescaleSlope/Intercept only for Siemens BQML
    # here, because the non-Siemens path is pre-rescaled before calling this function.
    if manuf == "SIEMENS" and units == "BQML":
        a_bqml = (a * slope) + inter
    else:
        a_bqml = a

    rps = getattr(ds, "RadiopharmaceuticalInformationSequence", None)
    rps = rps[0] if rps else None
    if not rps:
        WARN("Missing RadiopharmaceuticalInformationSequence; returning concentration image (no SUV).")
        return a_bqml, "No RPS (returned concentration)", None

    A0 = float(getattr(rps, "RadionuclideTotalDose", 0.0) or 0.0)
    HL = float(getattr(rps, "RadionuclideHalfLife", 0.0) or 0.0)
    if A0 <= 0 or HL <= 0:
        WARN("Missing dose/half-life; returning concentration image (no SUV).")
        return a_bqml, "Missing dose/HL (returned concentration)", None

    lam = math.log(2.0) / HL

    inj = injection_dt(ds)
    ref = _choose_time_ref(ds)
    dt_s = (ref - inj).total_seconds() if (inj and ref) else 0.0

    # midnight wrap fix
    if dt_s < 0 and abs(dt_s) < 12 * 3600 and inj:
        inj = inj - timedelta(days=1)
        dt_s = (ref - inj).total_seconds()

    if "ADMIN" in dc:
        Aref = A0
    else:
        Aref = A0 * math.exp(-lam * dt_s)

    M = _mass_norm_grams_bw(ds)
    if not M or M <= 0:
        WARN("Missing patient weight; returning concentration image (no SUV).")
        return a_bqml, "Missing weight (returned concentration)", None

    scale = M / Aref if Aref > 0 else None
    suv = a_bqml * scale if scale else a_bqml
    suv = np.nan_to_num(suv, nan=0.0, posinf=3.0, neginf=0.0).astype(np.float32)

    return suv, "SUV(BW)", scale


def set_fov_mm(ax, center_mm, fov_mm=FOV_MM):
    half = fov_mm / 2.0
    cx, cy = center_mm
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy + half, cy - half)


def circle_mask_mm(shape, center_mm, radius_mm, pixel_mm):
    h, w = shape
    row_mm, col_mm = pixel_mm
    ys = (np.arange(h) + 0.5) * row_mm
    xs = (np.arange(w) + 0.5) * col_mm
    X, Y = np.meshgrid(xs, ys)
    cx, cy = center_mm
    return (X - cx) ** 2 + (Y - cy) ** 2 <= radius_mm ** 2


def ring_positions_from_angles(center_mm, p25_mm, p16_mm):
    # Compute relative angles from reference coordinates
    ref_angles = {lab: math.atan2(REL_COORDS_MM[lab][1], REL_COORDS_MM[lab][0]) for lab in LABEL_ORDER}
    base = ref_angles["25"]
    ref_angles = {lab: ((ref_angles[lab] - base + math.pi) % (2 * math.pi)) - math.pi for lab in LABEL_ORDER}

    C = np.asarray(center_mm, dtype=float)
    P25 = np.asarray(p25_mm, dtype=float)
    P16 = np.asarray(p16_mm, dtype=float)

    ring_r = np.linalg.norm(P25 - C)
    ang25_img = math.atan2(*(P25 - C)[[1, 0]])
    ang16_img = math.atan2(*(P16 - C)[[1, 0]])

    delta_img = ((ang16_img - ang25_img + math.pi) % (2 * math.pi)) - math.pi
    delta_ref = ref_angles["16"]
    orient_sign = 1.0 if delta_img * delta_ref >= 0 else -1.0

    centers = {}
    for lab in LABEL_ORDER:
        theta = ang25_img + orient_sign * ref_angles[lab]
        x = C[0] + ring_r * math.cos(theta)
        y = C[1] + ring_r * math.sin(theta)
        centers[lab] = (x, y)

    return centers, ring_r


def click_center_25_16(image_2d, pixel_mm, ds_for_center):
    """
    Center is auto-detected (with optional manual override), then user clicks 25 and 16.
    Returns (C_mm, P25_mm, P16_mm).
    """
    row_mm, col_mm = pixel_mm
    h, w = image_2d.shape

    # Auto phantom center in pixel coords (x,y) using the toolkit
    pixel_spacing = float(np.mean([float(x) for x in getattr(ds_for_center, "PixelSpacing", [row_mm, col_mm])]))
    px_array = ds_for_center.pixel_array.astype(np.float32)

    cy, cx, _radius_px = find_phantom_center_generalized(
        px_array,
        pixel_size_mm=pixel_spacing,
        modality=str(getattr(ds_for_center, "Modality", "PT")).upper(),
        debug=False
    )
    auto_center_px = np.array([cx, cy], dtype=float)

    # Confirm/override
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(px_array, cmap="gray")
    ax.plot(auto_center_px[0], auto_center_px[1], "ro", ms=10)
    ax.set_title("ENTER = keep center | BACKSPACE = redefine manually")
    choice = {"keep": None}

    def on_key(event):
        if event.key == "enter":
            choice["keep"] = True
            plt.close(fig)
        elif event.key == "backspace":
            choice["keep"] = False
            plt.close(fig)

    fig.canvas.mpl_connect("key_press_event", on_key)
    plt.show()

    center_px = auto_center_px
    if choice["keep"] is False:
        fig2, ax2 = plt.subplots(figsize=(7, 7))
        ax2.imshow(px_array, cmap="gray")
        ax2.set_title("Click to define new phantom center")
        pts = plt.ginput(1, timeout=0)
        plt.close(fig2)
        if pts:
            center_px = np.array(pts[0], dtype=float)

    # Now click 25 and 16 in a 220x220 mm view
    center_mm = np.array([center_px[0] * col_mm, center_px[1] * row_mm], dtype=float)

    extent = [0, w * col_mm, h * row_mm, 0]
    fig3, ax3 = plt.subplots(figsize=(8, 8))
    ax3.imshow(image_2d, cmap="gray", extent=extent, origin="upper")
    ax3.set_aspect("equal")
    set_fov_mm(ax3, center_mm, fov_mm=FOV_MM)
    ax3.set_title("Click 25 mm and 16 mm sphere centers (in order)")
    Cursor(ax3, useblit=True, color="red", linewidth=1.2)

    picked_mm = [center_mm]

    def onclick(e):
        if e.inaxes != ax3 or e.xdata is None or e.ydata is None:
            return
        picked_mm.append(np.array([float(e.xdata), float(e.ydata)], dtype=float))
        ax3.plot(e.xdata, e.ydata, "bx", ms=7)
        fig3.canvas.draw_idle()
        if len(picked_mm) == 3:
            plt.close(fig3)

    fig3.canvas.mpl_connect("button_press_event", onclick)
    plt.show()

    if len(picked_mm) != 3:
        raise RuntimeError("Selection cancelled (need center + 25 + 16).")

    return picked_mm[0], picked_mm[1], picked_mm[2]


# ---------------------- Display helper ----------------------
def imshow_pet_basic(ax, suv_img, extent):
    """
    Simple PET display: clamp 0..3 SUV and invert so background is light.
    """
    s = np.nan_to_num(suv_img, nan=0.0, posinf=3.0, neginf=0.0)
    s_clip = np.clip(s, 0.0, 3.0)
    s_inv = 3.0 - s_clip
    ax.imshow(s_inv, cmap="gray", extent=extent, origin="upper", vmin=0, vmax=3.0)


# ---------------------------------------------------------------------------
# Ported helper: automatic slice-selection (minimal, from 3b._Auto_SUV_Overlay.py)
# Ported on 2026-01-10 — keep in sync with 3b._Auto_SUV_Overlay.py
# This function is opt-in (user must choose auto-select) so default behavior
# (manual single-slice selection) remains unchanged and outputs are preserved.
# ---------------------------------------------------------------------------
def auto_select_best_slice(input_dir):
    """
    Auto-select a single best slice from a DICOM folder.

    Parity target: `3b._Auto_SUV_Overlay.py` hot-cell slice selection.
    It picks the slice with the highest max voxel value inside a 180mm ROI
    (after applying RescaleSlope/RescaleIntercept), skipping first/last slice.

    Returns: (selected_path, selected_index_in_sorted_list)
    """
    files = [os.path.join(input_dir, f) for f in os.listdir(input_dir) if f.lower().endswith(".dcm")]
    files = sorted(files)
    if not files:
        raise RuntimeError("No DICOM files found for auto-selection.")

    # Read datasets (stop_before_pixels=False because we need pixel arrays)
    dsets = []
    for p in files:
        try:
            ds = pydicom.dcmread(p, stop_before_pixels=False)
            if not hasattr(ds, "PixelData"):
                continue
            # Only keep 2D images with valid matrix size
            rows = int(getattr(ds, "Rows", 0) or 0)
            cols = int(getattr(ds, "Columns", 0) or 0)
            if rows <= 0 or cols <= 0:
                continue
            try:
                arr = ds.pixel_array
                if getattr(arr, "ndim", 0) != 2:
                    continue
            except Exception:
                continue
            dsets.append((p, ds))
        except Exception:
            continue

    if not dsets:
        raise RuntimeError("No usable DICOM image files found for auto-selection.")

    # Sort by ImagePositionPatient z if present, else InstanceNumber
    def sort_key(t):
        _, ds = t
        ipp = getattr(ds, "ImagePositionPatient", None)
        if ipp and len(ipp) >= 3:
            try:
                return float(ipp[2])
            except Exception:
                pass
        try:
            return float(getattr(ds, "InstanceNumber", 0))
        except Exception:
            return 0.0

    dsets.sort(key=sort_key)

    # Filter out any frames with different matrix size to avoid mask/array shape mismatches
    ref_rows = int(getattr(dsets[0][1], "Rows", 0) or 0)
    ref_cols = int(getattr(dsets[0][1], "Columns", 0) or 0)
    filtered = []
    for p, ds in dsets:
        rows = int(getattr(ds, "Rows", 0) or 0)
        cols = int(getattr(ds, "Columns", 0) or 0)
        if rows != ref_rows or cols != ref_cols:
            continue
        filtered.append((p, ds))
    dsets = filtered
    if not dsets:
        raise RuntimeError("No usable DICOM image files found for auto-selection (matrix-size mismatch).")

    # Pixel spacing from first dataset
    row_mm, col_mm = [float(x) for x in getattr(dsets[0][1], "PixelSpacing", [1.0, 1.0])]
    pixel_spacing = float(np.mean([row_mm, col_mm]))

    # Phantom center from middle slice (3b parity)
    mid_index = len(dsets) // 2
    mid_px = dsets[mid_index][1].pixel_array.astype(np.float32)
    cy, cx, _ = find_phantom_center_generalized(
        mid_px,
        pixel_size_mm=pixel_spacing,
        modality=str(getattr(dsets[mid_index][1], "Modality", "PT")).upper(),
        debug=False,
    )

    # Build circular mask (180 mm diameter) in pixel coords
    roi_radius_px = (180.0 / 2.0) / pixel_spacing
    h, w = mid_px.shape
    yy, xx = np.ogrid[:h, :w]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= roi_radius_px ** 2

    # Pick slice with highest max voxel intensity inside ROI (scaled DICOM)
    max_vals = []
    for idx, (_, ds) in enumerate(dsets[1:-1], start=1):
        img = ds.pixel_array.astype(np.float32)
        slope = float(getattr(ds, "RescaleSlope", 1.0))
        intercept = float(getattr(ds, "RescaleIntercept", 0.0))
        img = img * slope + intercept
        roi = img[mask]
        if roi.size == 0:
            max_vals.append((idx, float("nan")))
            continue
        max_vals.append((idx, float(np.nanmax(roi))))

    valid = [(i, v) for i, v in max_vals if not np.isnan(v)]
    if not valid:
        return dsets[mid_index][0], mid_index

    best_idx, _best_max = max(valid, key=lambda t: t[1])
    return dsets[best_idx][0], best_idx


def _rescale_concentration_like(ds, arr_2d: np.ndarray) -> np.ndarray:
    """Match the pre-rescale convention used by `3b._Auto_SUV_Overlay.py`.

    - Siemens + Units==BQML: return raw pixel values (float32)
    - Otherwise: apply RescaleSlope/RescaleIntercept
    """
    a = arr_2d.astype(np.float32)
    manuf = str(getattr(ds, "Manufacturer", "")).upper()
    units = str(getattr(ds, "Units", "")).upper()
    slope = float(getattr(ds, "RescaleSlope", 1.0))
    inter = float(getattr(ds, "RescaleIntercept", 0.0))
    if manuf == "SIEMENS" and units == "BQML":
        return a
    return a * slope + inter



# ---------------------- Main ----------------------
def main():
    try:
        parser = argparse.ArgumentParser(add_help=True)
        parser.add_argument("--i", "--input", dest="input_dir", help="Input DICOM folder")
        parser.add_argument("--o", "--output", dest="output_dir", help="Output folder (will be created)")
        parser.add_argument(
            "--auto",
            action="store_true",
            help="Auto-select best slice (recommended; avoids tkinter list selection)",
        )
        parser.add_argument(
            "--manual",
            action="store_true",
            help="Manually select slice (requires tkinter)",
        )
        args = parser.parse_args()

        tkinter_ok = _has_tkinter()

        in_dir = args.input_dir
        if not in_dir:
            if not tkinter_ok:
                raise RuntimeError("tkinter is not available; pass --i/--input and --o/--output to run headless from dialogs.")
            in_dir = ask_folder("Select PET DICOM Folder (INPUT)")
        if not in_dir:
            INFO("Cancelled: no input folder.")
            return

        out_dir = args.output_dir
        if not out_dir:
            if not tkinter_ok:
                raise RuntimeError("tkinter is not available; pass --o/--output to select output folder without dialogs.")
            out_dir = ask_output_folder_and_name()
        if not out_dir:
            INFO("Cancelled: no output folder/name.")
            return
        os.makedirs(out_dir, exist_ok=True)

        # Choose whether the user wants automatic best-slice selection.
        if args.auto and args.manual:
            raise RuntimeError("Choose only one of --auto or --manual")

        if args.auto:
            use_auto = True
        elif args.manual:
            use_auto = False
        elif not tkinter_ok:
            # Without tkinter we cannot show the yes/no prompt or the manual listbox.
            use_auto = True
            INFO("tkinter unavailable; defaulting to auto-select best slice.")
        else:
            from tkinter import messagebox
            use_auto = messagebox.askyesno(
                "Auto-select slice?",
                "Use automatic best-slice selection (recommended for ACR)?\n\nChoose 'No' to pick a single slice manually.",
            )

        if use_auto:
            INFO("Auto-selecting best slice...")
            selected_path_auto, _idx = auto_select_best_slice(in_dir)
            # Build sorted_items so we can keep the same index/value semantics as the UI path
            sorted_items = build_sorted_items(in_dir)
            selected_sorted_idx = 0
            # find matching path
            for i, it in enumerate(sorted_items):
                if os.path.normpath(it[0]) == os.path.normpath(selected_path_auto):
                    selected_sorted_idx = i
                    break
            selected_path = selected_path_auto
            INFO(f"Auto-selected: {os.path.basename(selected_path)} (index {selected_sorted_idx})")
        else:
            selected_path, selected_sorted_idx, sorted_items = select_dicom_from_list(in_dir)
            INFO(f"Selected: {os.path.basename(selected_path)}")

        ds = pydicom.dcmread(selected_path, stop_before_pixels=False)
        if not hasattr(ds, "PixelData"):
            raise RuntimeError("Selected DICOM has no PixelData.")

        arr = ds.pixel_array.astype(np.float32)

        # Pixel spacing
        pxsp = getattr(ds, "PixelSpacing", [1.0, 1.0])
        row_mm = float(pxsp[0])
        col_mm = float(pxsp[1])

        # SUV image (match the 3b pipeline rescale convention)
        arr_res = _rescale_concentration_like(ds, arr)
        suv_img, suv_note, _scale = suv_from_ds_bw(ds, arr_res)
        INFO(f"SUV mode: {suv_note}")

        # Click center, 25, 16 and derive 7 ROI centers
        C_mm, P25_mm, P16_mm = click_center_25_16(suv_img, (row_mm, col_mm), ds)
        centers_mm, ring_r = ring_positions_from_angles(C_mm, P25_mm, P16_mm)

        # Compute ROI stats
        roi_r = SUV_ROI_DIAM_MM / 2.0
        results = []
        for lab in LABEL_ORDER:
            ctr = centers_mm[lab]
            mask = circle_mask_mm(suv_img.shape, ctr, roi_r, (row_mm, col_mm))
            vals = suv_img[mask]
            if vals.size == 0:
                results.append((lab, float("nan"), float("nan"), float("nan")))
            else:
                results.append((lab, float(np.nanmean(vals)), float(np.nanmax(vals)), float(np.nanmin(vals))))

        # Central ROI (6.5 cm diameter): report mean
        central_r = CENTRAL_ROI_DIAM_MM / 2.0
        mask_c = circle_mask_mm(suv_img.shape, C_mm, central_r, (row_mm, col_mm))
        central_vals = suv_img[mask_c]
        central_mean = float(np.nanmean(central_vals)) if central_vals.size else float("nan")

        # Slice info text (bottom-left)
        slice_thk = getattr(ds, "SliceThickness", None)
        slice_thk_s = f"{float(slice_thk):g} mm" if slice_thk is not None else "N/A"
        inst = getattr(ds, "InstanceNumber", None)
        slice_num_s = f"{inst}" if inst is not None else f"{selected_sorted_idx}"
        footer = f"Slice {slice_num_s} | Thickness {slice_thk_s}"

        # Save CSV
        out_csv = os.path.join(out_dir, "ACR_Specific_SUV_results.csv")
        with open(out_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ROI Label", "SUVmean", "SUVmax", "SUVmin"])
            for lab, mean_v, max_v, min_v in results:
                w.writerow([lab, f"{mean_v:.6f}", f"{max_v:.6f}", f"{min_v:.6f}"])
            w.writerow([])
            w.writerow(["Central ROI (65 mm diam)", "SUVmean"])
            w.writerow(["Center", f"{central_mean:.6f}"])
        INFO(f"Saved CSV → {out_csv}")

        # Plot overlay
        h, w = suv_img.shape
        extent = [0, w * col_mm, h * row_mm, 0]

        fig, ax = plt.subplots(figsize=(8, 8))
        imshow_pet_basic(ax, suv_img, extent)
        ax.set_aspect("equal")
        set_fov_mm(ax, C_mm, fov_mm=FOV_MM)
        ax.axis("off")

        # Draw hotcell-like ROIs
        for lab in LABEL_ORDER:
            x, y = centers_mm[lab]
            ax.add_patch(Circle((x, y), roi_r, fill=False, color="maroon", lw=1.2))

        # Draw central ROI
        ax.add_patch(Circle((C_mm[0], C_mm[1]), central_r, fill=False, color="gold", lw=1.6))

        # Labels outside ring
        offset_factor = 1.5
        for (lab, mean_v, max_v, min_v) in results:
            x, y = centers_mm[lab]
            v = np.array([x - C_mm[0], y - C_mm[1]], dtype=float)
            theta = math.atan2(v[1], v[0]) if np.linalg.norm(v) > 1e-6 else 0.0
            Rtxt = max(ring_r * offset_factor, np.linalg.norm(v) + roi_r + 5.0)
            tx = C_mm[0] + Rtxt * math.cos(theta)
            ty = C_mm[1] + Rtxt * math.sin(theta)

            if lab in ["25", "16", "12", "8"]:
                text = f"{lab} mm Hot Cell\nMax={max_v:.2f} SUV"
            else:
                text = f"{lab}\nMean={mean_v:.2f} SUV\nMin={min_v:.2f} SUV"

            ax.text(tx, ty, text, color="maroon", fontsize=9, va="center", ha="center")

        # Central ROI label
        ax.text(
            C_mm[0], C_mm[1],
            f"Central ROI\nMean={central_mean:.2f} SUV",
            color="gold", fontsize=10, va="center", ha="center"
        )

        # Bottom-left footer
        x_left = C_mm[0] - (FOV_MM / 2.0) + 4.0
        y_bottom = C_mm[1] + (FOV_MM / 2.0) - 6.0
        ax.text(x_left, y_bottom, footer, color="Black", fontsize=9, va="bottom", ha="left")

        out_png = os.path.join(out_dir, "ACR_Specific_overlay.png")
        fig.savefig(out_png, dpi=300, bbox_inches="tight")
        INFO(f"Saved overlay PNG → {out_png}")

        plt.show()
        INFO("Done.")

    except Exception as e:
        if _has_tkinter():
            try:
                from tkinter import messagebox
                messagebox.showerror("Error", str(e))
            except Exception:
                pass
        ERROR(str(e))


if __name__ == "__main__":
    main()