# -*- coding: utf-8 -*-
"""
ACR_Specific Overlay.py

Based on the automatic SUV overlay pipeline:
- Siemens-aware SUV computation (via existing suv_from_ds logic style)
- Robust display (United vs others, 0–3 SUV window invert w/ fallback)

Changes:
- User selects ONE slice from the input folder, with a preview image in the selector UI
- Produces hotcell overlay + central ROI (65 mm diameter) reporting SUVmean
- Footer bottom-left: SliceThickness + Slice number
- Fixed display FOV: 220 x 220 mm
"""

import os, math, csv, sys, json
from datetime import datetime, date, time, timedelta
import numpy as np
import pydicom
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import matplotlib
matplotlib.use("TkAgg")  # if you prefer Qt: matplotlib.use("Qt5Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Cursor
from scipy import ndimage
from scipy.ndimage import gaussian_filter
from skimage import exposure, filters, morphology, measure
# --- add/confirm these imports near the top ---
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.uid import generate_uid
from pydicom.filewriter import dcmwrite
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

from CT_Analysis_Toolkit.Modules.find_phantom_center import (
    find_phantom_center_generalized,
    _fit_circle_hough,
    _largest_subpixel_contour,
    _fit_circle_least_squares,
)
from CT_Analysis_Toolkit.Modules.auto_center_and_hotcells import detect_hot_cells


# ---------------------- Config ----------------------
LABEL_ORDER   = ["25", "16", "12", "8", "Bone", "Air", "Water"]
FOV_MM        = 250.0          # zoom FOV for all panels
UNIF_DIAM_MM  = 180.0          # uniformity ROI diameter
SUV_ROI_DIAM  = 25.0           # SUV ring ROI diameter
# --- Quant options ---
SUV_TIME_REF  = "START"   # or "START" / "MID"
SUV_MASS_NORM = "BW"    # set to "LBM" to get SUL, else "BW"

# Fallbacks used ONLY if DICOM is missing these fields
DEFAULT_HEIGHT_CM = 175   # pick a value you want to assume.
DEFAULT_SEX       = "M"   # "M" or "F"



# Latest fixed geometry (mm) relative to phantom center
REL_COORDS_MM = {
    "25":   ( 46.28704628704628,  -48.40992341),
    "16":   ( 67.26606727,          8.200133200133223),
    "12":   ( 50.61605061605064,   46.82817182817183),
    "8":    ( 24.309024309024323,  64.47718947718948),
    "Bone": (-29.63702964,        -59.06593407),
    "Air":  (-69.26406926,          5.2031302031302005),
    "Water":(-22.97702298,         66.14219114219117),
}

# Display prefs
DRAW_CENTER_RAYS  = True     # dashed rays from center to each ROI
HIDE_AXES         = True     # remove axes everywhere
SHOW_CENTER_MARK  = False    # no center marker on final images

# --- extend existing Config ---
# SUV_MASS_NORM: "BW" (SUVbw), "LBM" (SUL), "BSA", or "IBW"
SUV_MASS_NORM = "BW"   # existing line: you can change to "LBM" for SUL

# Emit an RWVM sidecar that maps "stored pixel" → "SUV" for the chosen normalization
WRITE_RWVM_SIDECAR = True

# Candidate selection / criteria defaults
HOTCELL_TOP_N_CANDIDATES = 5
HOTCELL_REGION_PERCENTILE = 85
HOTCELL_INTENSITY_PERCENTILE = 98
# Axial subsampling for hot-cell candidate scoring (and the center regression
# built on those candidates):
# - only slices within the central fraction of the series are eligible, so
#   near-end slices without phantom cannot skew the per-slice center solves
# - only every Nth slice is evaluated, reducing compute on thick stacks
HOTCELL_CENTER_FRACTION = 0.80
HOTCELL_SLICE_STRIDE = 2
DEFAULT_CRITERIA_JSON = r"c:\Users\RyanByrd\Downloads\acr_pet_suv_criteria.json"


# ---------------------- Logging ----------------------
def _c(code): return f"\033[{code}m"
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

# Simple, reliable crosshair
class SimpleCrosshair:
    def __init__(self, ax, color='yellow', lw=1.0, ls='--'):
        self.ax = ax
        x0 = (ax.get_xlim()[0] + ax.get_xlim()[1]) / 2.0
        y0 = (ax.get_ylim()[0] + ax.get_ylim()[1]) / 2.0
        self.h = ax.axhline(y0, color=color, lw=lw, ls=ls, zorder=999)
        self.v = ax.axvline(x0, color=color, lw=lw, ls=ls, zorder=999)
        self.t = ax.text(0.72, 0.9, f"x={x0:.1f}, y={y0:.1f}",
                         transform=ax.transAxes, color=color, fontsize=8,
                         backgroundcolor='black', zorder=999)
        ax.figure.canvas.mpl_connect('motion_notify_event', self.on_move)
        ax.figure.canvas.draw_idle()
    def on_move(self, e):
        if e.inaxes != self.ax or e.xdata is None or e.ydata is None: return
        x, y = e.xdata, e.ydata
        self.h.set_ydata([y]); self.v.set_xdata([x])
        self.t.set_text(f"x={x:.1f}, y={y:.1f}")
        self.ax.draw_artist(self.h); self.ax.draw_artist(self.v); self.ax.draw_artist(self.t)
        self.ax.figure.canvas.flush_events()

def attach_crosshair(ax, color='yellow'):
    import matplotlib
    print(f"[INFO] Matplotlib backend → {matplotlib.get_backend()}")
    SimpleCrosshair(ax, color=color)

def _float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def _get_patient_sex(ds):
    s = str(getattr(ds, "PatientSex", "")).upper().strip()
    return s if s in ("M", "F") else DEFAULT_SEX

def _get_height_m(ds):
    # PatientSize is meters if present; else fallback to DEFAULT_HEIGHT_CM
    h = _float(getattr(ds, "PatientSize", 0.0))
    if h > 0:
        return h
    return DEFAULT_HEIGHT_CM / 100.0

def _lbm_kg_james(sex, weight_kg, height_m):
    # James (QIBA-compatible; avoids BMI dependency)
    h_cm = height_m * 100.0
    if sex == "M":
        lbm = 1.10 * weight_kg - 128.0 * (weight_kg / h_cm) ** 2
    else:
        lbm = 1.07 * weight_kg - 148.0 * (weight_kg / h_cm) ** 2
    # clamp to sensible range
    return max(0.1, lbm)

def _ibw_kg_devine(sex, height_m):
    # Devine ideal body weight (uses height in inches)
    h_in = height_m * 39.3700787
    base = 50.0 if sex == "M" else 45.5
    return max(0.1, base + 2.3 * max(0.0, (h_in - 60.0)))

def _bsa_m2_mosteller(weight_kg, height_m):
    return math.sqrt((height_m * 100.0 * weight_kg) / 3600.0)

def _mass_norm_grams(ds):
    """
    Returns the mass normalization (in grams) based on SUV_MASS_NORM.
    - BW : body weight (default)
    - LBM: lean body mass (SUL)
    - BSA: m^2 (BSA) → by convention most use SUVbsa = conc * (BSA / (dose/ (g/mL)))
          Here we return grams-equivalent: BSA[m^2] * 100,000 g (approx 1 m^2 ~ 10,000 cm^2 not a mass unit).
          To keep standard, we treat BSA as 'mass-like' scaler; practical pipelines commonly keep BW or LBM.
    - IBW: ideal body weight
    """
    weight_kg = _float(getattr(ds, "PatientWeight", 0.0))
    if weight_kg <= 0:
        return None

    sex = _get_patient_sex(ds)
    height_m = _get_height_m(ds)

    norm = SUV_MASS_NORM.strip().upper()
    if norm == "BW":
        return weight_kg * 1000.0
    if norm == "LBM":
        return _lbm_kg_james(sex, weight_kg, height_m) * 1000.0
    if norm == "IBW":
        return _ibw_kg_devine(sex, height_m) * 1000.0
    if norm == "BSA":
        # Not a true mass; used in some research variants.
        # Scale so that numeric magnitudes are comparable to BW-based SUVs.
        return _bsa_m2_mosteller(weight_kg, height_m) * 1000.0
    # default fallback
    return weight_kg * 1000.0

def _choose_time_ref(ds):
    """
    Returns reference datetime for dose decay based on SUV_TIME_REF.
    'START' → acquisition_start_dt(ds)
    'MID'   → frame_mid_dt(ds)
    """
    ref = str(SUV_TIME_REF).upper().strip()
    if ref == "MID":
        return frame_mid_dt(ds)
    return acquisition_start_dt(ds)

def find_rwvm_in_dir(input_dir):
    """
    Look for a DICOM Real World Value Mapping object in the input directory.
    Returns a dict: {'slope': float, 'intercept': float, 'meaning': str} or None.
    """
    try:
        for fn in os.listdir(input_dir):
            if not fn.lower().endswith(".dcm"):
                continue
            p = os.path.join(input_dir, fn)
            ds = pydicom.dcmread(p, stop_before_pixels=True, force=True)
            sop_class = str(getattr(ds, "SOPClassUID", ""))
            if sop_class == "1.2.840.10008.5.1.4.1.1.67":  # Real World Value Mapping Storage
                rwvms = getattr(ds, "RealWorldValueMappingSequence", None)
                if not rwvms:
                    continue
                item = rwvms[0]
                slope = _float(getattr(item, "RealWorldValueSlope", 1.0), 1.0)
                intercept = _float(getattr(item, "RealWorldValueIntercept", 0.0), 0.0)
                meaning = ""
                try:
                    mu = item.MeasurementUnitsCodeSequence[0]
                    meaning = (mu.CodeMeaning or "").lower()
                except Exception:
                    pass
                return {"slope": slope, "intercept": intercept, "meaning": meaning}
    except Exception as e:
        WARN(f"RWVM scan error: {e}")
    return None

def write_rwvm_sidecar_for_suv(ds_ref, out_dir, slope, intercept=0.0):
    try:
        rwvm = Dataset()
        rwvm.SOPClassUID = "1.2.840.10008.5.1.4.1.1.67"
        rwvm.SOPInstanceUID = generate_uid()
        rwvm.StudyInstanceUID = getattr(ds_ref, "StudyInstanceUID", generate_uid())
        rwvm.SeriesInstanceUID = generate_uid()
        rwvm.Modality = "RWV"
        rwvm.ContentLabel = "SUV"
        rwvm.ContentDescription = f"SUV mapping ({SUV_MASS_NORM})"
        rwvm.ContentCreatorName = "PET_ROI_Manager"

        item = Dataset()
        item.RealWorldValueSlope = float(slope)
        item.RealWorldValueIntercept = float(intercept)

        mu = Dataset()
        mu.CodeValue = "1"
        mu.CodingSchemeDesignator = "UCUM"
        mu.CodeMeaning = "unitless"
        item.MeasurementUnitsCodeSequence = Sequence([mu])

        rwvm.RealWorldValueMappingSequence = Sequence([item])

        # Explicitly set TS so pydicom can write without guessing
        rwvm.is_little_endian = True
        rwvm.is_implicit_VR = True  # Implicit VR Little Endian

        out_path = os.path.join(out_dir, "SUV_RWVM.dcm")
        dcmwrite(out_path, rwvm, write_like_original=False, implicit_vr=True, little_endian=True)
        INFO(f"Saved RWVM sidecar → {out_path}")
    except Exception as e:
        WARN(f"RWVM sidecar write failed: {e}")


# ---------------------- DICOM loading ----------------------
def load_series(folder, metadata_overrides=None, override_audit_records=None):
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
            WARN(f"Skipping modality {getattr(ds,'Modality','')}")
            continue
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
        if arr.ndim!=2: WARN("Skipping non-2D frame"); continue
        slope = float(getattr(ds, "RescaleSlope", 1.0))
        inter = float(getattr(ds, "RescaleIntercept", 0.0))

        # --- Fix: Siemens PET images already in BQML should not be rescaled again ---
        manuf = str(getattr(ds, "Manufacturer", "")).upper()
        units = str(getattr(ds, "Units", "")).upper()

        if manuf == "SIEMENS" and units == "BQML":
            # Siemens PET data already in Bq/mL, skip RescaleSlope scaling
            img_res = arr.astype(np.float32)
        else:
            img_res = arr * slope + inter
        # ---------------------------------------------------------------------------

        m = float(np.max(img_res)) if np.max(img_res) else 1.0
        img_disp = img_res / m
        res_imgs.append(img_res); disp_imgs.append(img_disp); dsets.append(ds)

    if len(disp_imgs)<4: raise RuntimeError(f"Only {len(disp_imgs)} usable frames; need ≥4.")
    return disp_imgs, res_imgs, dsets, (row_mm, col_mm)

# ---------------------- Display helper ----------------------
def is_united(ds) -> bool:
    return "UNITED" in str(getattr(ds,"Manufacturer","")).upper()

def imshow_pet(ax, ds, suv_img, raw_img, extent):
    # White background (invert)
    def invert(img):
        img = np.nan_to_num(img, nan=0.0)
        mx = float(np.nanmax(img)) if np.nanmax(img)>0 else 1.0
        return mx - img
    if is_united(ds):
        ax.imshow(invert(suv_img), cmap="gray", extent=extent, origin="upper"); return
    s = np.nan_to_num(suv_img, nan=0.0, posinf=3.0, neginf=0.0)
    s_clip = np.clip(s, 0.0, 3.0); s_inv = 3.0 - s_clip
    if np.nanstd(s_inv) > 1e-6:
        ax.imshow(s_inv, cmap="gray", extent=extent, origin="upper", vmin=0, vmax=3.0); return
    # fallback: robust raw window
    r = np.nan_to_num(raw_img, nan=0.0); p1,p99 = np.nanpercentile(r,[1,99])
    if not np.isfinite(p1) or not np.isfinite(p99) or p99<=p1:
        ax.imshow(invert(r), cmap="gray", extent=extent, origin="upper"); return
    r_st = np.clip((r-p1)/(p99-p1),0,1); r_inv = 1.0 - r_st
    ax.imshow(r_inv, cmap="gray", extent=extent, origin="upper")

# ---------------------- Selection UIs ----------------------
def select_four(images, pixel_mm):
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
            set_fov_mm(ax, (w*col_mm/2.0,h*row_mm/2.0), fov_mm=FOV_MM)
            ax.set_title(f"Slice {i}", fontsize=8)
    fig.suptitle("Click 4 images (first 3 = Uniformity, last = SUV)", fontsize=14)
    def onclick(e):
        if e.inaxes not in axes: return
        idx = list(axes).index(e.inaxes)
        if idx<n and idx not in sel:
            sel.append(idx); e.inaxes.set_title(f"Selected {len(sel)}", color="tab:blue")
            fig.canvas.draw_idle()
        if len(sel)==4: plt.close(fig)
    fig.canvas.mpl_connect("button_press_event", onclick)
    plt.show()
    if len(sel)!=4: raise RuntimeError("Selection cancelled or not enough images chosen.")
    return sel[:3], sel[3]

def click_point_mm(image, pixel_mm, title="Click point"):
    row_mm, col_mm = pixel_mm
    h, w = image.shape
    extent = [0, w * col_mm, h * row_mm, 0]
    fig, ax = plt.subplots()
    ax.imshow(image, cmap="gray", extent=extent, origin="upper")
    ax.set_aspect("equal")
    ax.set_title(title)
    set_fov_mm(ax, (w * col_mm / 2.0, h * row_mm / 2.0), fov_mm=FOV_MM)

    # --- red crosshair cursor ---
    cursor = Cursor(ax, useblit=True, color='red', linewidth=1.2)

    picked = []
    def onclick(e):
        if e.inaxes != ax:
            return
        picked[:] = [(e.xdata, e.ydata)]
        ax.plot(e.xdata, e.ydata, 'ro', ms=4)
        set_fov_mm(ax, picked[0], fov_mm=FOV_MM)
        fig.canvas.draw_idle()
        plt.close(fig)

    fig.canvas.mpl_connect("button_press_event", onclick)
    plt.show()
    if not picked:
        raise RuntimeError("No point selected.")
    return np.array(picked[0])

def click_center_25_16(image, pixel_mm, dsets, center_hint=None):
    """
    Selects three ROI points on the PET image:
    Center (auto or manual), 25 mm, and 16 mm spheres.

    Args:
        image (ndarray): PET SUV image (2D slice)
        pixel_mm (tuple): (row_mm, col_mm) pixel spacing
        dsets (list): list of DICOM datasets (for modality and pixel info)
        center_hint (np.array, optional): prior center in pixels (from uniformity module)

    Returns:
        np.array, np.array, np.array: coordinates in mm for Center, 25, and 16
    """
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Cursor
    from CT_Analysis_Toolkit.Modules.find_phantom_center import find_phantom_center_generalized

    row_mm, col_mm = pixel_mm
    h, w = image.shape
    extent = [0, w * col_mm, h * row_mm, 0]

    # --- Determine modality and pixel spacing ---
    modality = getattr(dsets[0], "Modality", "PT").upper()
    pixel_spacing = np.mean([float(x) for x in dsets[0].PixelSpacing])
    mid_idx = len(dsets) // 2
    px_array = dsets[mid_idx].pixel_array.astype(np.float32)

    # -----------------------------------------------------------------
    # Step 1 — Detect phantom center automatically or reuse hint
    # -----------------------------------------------------------------
    if center_hint is not None:
        auto_center = np.array(center_hint)
        print(f"[{modality}] Using provided center hint ({auto_center[0]:.1f}, {auto_center[1]:.1f})")
    else:
        cy, cx, radius_px = find_phantom_center_generalized(
            px_array,
            pixel_size_mm=pixel_spacing,
            modality=modality,
            debug=False  # set True to visualize detection
        )
        auto_center = np.array([cx, cy])
        print(f"[Center-{modality}] y={cy:.1f}, x={cx:.1f}, radius={radius_px:.1f}px "
              f"≈ {radius_px * pixel_spacing:.1f} mm")

    # -----------------------------------------------------------------
    # Step 2 — Ask user to confirm or redefine center
    # -----------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(px_array, cmap="gray")
    ax.plot(auto_center[0], auto_center[1], "ro", ms=10)
    ax.set_title("Press ENTER to keep this center, or BACKSPACE to redefine manually")

    center_choice = {"keep": None}

    def on_key(event):
        if event.key == "enter":
            center_choice["keep"] = True
            plt.close(fig)
        elif event.key == "backspace":
            center_choice["keep"] = False
            plt.close(fig)

    fig.canvas.mpl_connect("key_press_event", on_key)
    plt.show()

    # -----------------------------------------------------------------
    # Step 3 — Optional manual redefinition if BACKSPACE pressed
    # -----------------------------------------------------------------
    if not center_choice["keep"]:
        print("Select new center manually (click once)...")
        fig2, ax2 = plt.subplots(figsize=(7, 7))
        ax2.imshow(px_array, cmap="gray")
        ax2.set_title("Click to define new phantom center")
        pts = plt.ginput(1, timeout=0)
        plt.close(fig2)
        if pts:
            auto_center = np.array(pts[0])
            print(f"Manual center selected at ({auto_center[0]:.1f}, {auto_center[1]:.1f})")

    center = auto_center
    print(f"[ROI Manager] Using phantom center: x={center[0]:.1f}, y={center[1]:.1f}")

    # -----------------------------------------------------------------
    # Step 4 — Launch figure for 25 mm and 16 mm ROI clicks
    # -----------------------------------------------------------------
    picked = [tuple(center)]
    labels = ["Center", "25 mm", "16 mm"]

    # Define desired field of view (FOV) in mm
    fov_mm = 220.0
    half_fov_mm = fov_mm / 2.0

    # Convert FOV limits from mm to pixel indices
    center_x_mm = center[0] * col_mm
    center_y_mm = center[1] * row_mm
    x_min_mm, x_max_mm = center_x_mm - half_fov_mm, center_x_mm + half_fov_mm
    y_min_mm, y_max_mm = center_y_mm - half_fov_mm, center_y_mm + half_fov_mm

    # Display cropped, centered view at 220×220 mm
    fig3, ax3 = plt.subplots(figsize=(8, 8))
    ax3.imshow(
        image,
        cmap="gray",
        extent=[0, w * col_mm, h * row_mm, 0],
        origin="upper"
    )
    ax3.set_xlim(x_min_mm, x_max_mm)
    ax3.set_ylim(y_max_mm, y_min_mm)
    ax3.set_aspect("equal")
    ax3.set_title("Click 25 mm and 16 mm sphere centers (in order)")
    cursor = Cursor(ax3, useblit=True, color="red", linewidth=1.2)

    def onclick(e):
        if e.inaxes != ax3:
            return
        picked.append((e.xdata / col_mm, e.ydata / row_mm))  # convert to pixel units
        ax3.plot(e.xdata, e.ydata, "bx", ms=6)
        ax3.text(e.xdata + 3, e.ydata, labels[len(picked) - 1],
                 color="cyan", fontsize=9)
        fig3.canvas.draw_idle()
        if len(picked) == 3:
            plt.close(fig3)

    fig3.canvas.mpl_connect("button_press_event", onclick)
    plt.show()

    # -----------------------------------------------------------------
    # Step 5 — Convert all to mm for output
    # -----------------------------------------------------------------
    picked_mm = [np.array([x * col_mm, y * row_mm]) for x, y in picked]
    C_mm, P25_mm, P16_mm = picked_mm
    print(f"[ROI Manager] Clicks complete — Center({C_mm}), 25({P25_mm}), 16({P16_mm})")

    return C_mm, P25_mm, P16_mm



# ---------------------- Siemens-aware SUV ----------------------
def frame_mid_dt(ds):
    """Estimate mid-frame datetime from SeriesDate/Time + Actual Frame Duration or Frame Reference Time.
       Falls back to START if unknown.
    """
    start = acquisition_start_dt(ds)  # you already have this
    # Prefer Actual Frame Duration (ms)
    afd = getattr(ds, "ActualFrameDuration", None)  # (0018,1242) ms
    if isinstance(afd, (int, float)) and afd > 0:
        return start + timedelta(milliseconds=float(afd) / 2.0)

    # Try Frame Reference Time (0054,1300) in ms since a reference (often series start)
    frt = getattr(ds, "FrameReferenceTime", None)
    if isinstance(frt, (int, float)):
        # treat it as milliseconds offset from START if no absolute ref given
        return start + timedelta(milliseconds=float(frt))

    # Fallback: START
    return start

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
    # Siemens "START" → SeriesDate/Time
    d = getattr(ds,'SeriesDate',None); t = getattr(ds,'SeriesTime',None)
    return datetime.combine(_parse_yyyymmdd(d), _parse_hhmmss(t))

def siemens_private_decay_dt(ds):
    # Private (0071,1022) Decay Correction DateTime if available
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

def decay_corrected_dose_at_start(ds):
    rps = getattr(ds,'RadiopharmaceuticalInformationSequence',None)
    rps = rps[0] if rps else None
    if not rps: return None
    A0 = float(getattr(rps,'RadionuclideTotalDose',0.0) or 0.0)
    HL = float(getattr(rps,'RadionuclideHalfLife',0.0) or 0.0)
    if A0<=0 or HL<=0: return None
    inj = injection_dt(ds)
    start = siemens_private_decay_dt(ds) or acquisition_start_dt(ds)
    if not inj or not start: return None
    dt_s = (start - inj).total_seconds()
    if dt_s < 0 and abs(dt_s) < 12*3600:
        inj = inj - timedelta(days=1); dt_s = (start - inj).total_seconds()
    INFO(f"[DEBUG] Decay Δt = {dt_s/60:.1f} min | Half-life = {HL/60:.2f} min")
    lam = math.log(2.0) / HL
    return A0 * math.exp(-lam * dt_s)

def suv_from_ds(ds, a, external_rwvm=None):
    """
    Computes SUV from PET DICOM dataset.
    Applies Rescale Slope/Intercept to activity concentration (Bq/mL),
    and properly skips decay correction when DecayCorrection == 'ADMIN'.
    """
    import math
    import numpy as np

    # Clean and cast the voxel array
    a = np.nan_to_num(a, nan=0.0).astype(np.float32)

    # Extract DICOM tags
    manuf = str(getattr(ds, "Manufacturer", "")).upper()
    units = str(getattr(ds, "Units", "")).upper()
    dc = str(getattr(ds, "DecayCorrection", "")).upper()

    INFO("──────────────────────────── SUV DEBUG START ────────────────────────────")
    INFO(f"Manufacturer ........... {manuf}")
    INFO(f"Units (0054,1001) ...... {units}")
    INFO(f"DecayCorrection ........ {dc}")

    # --- Apply Rescale Slope/Intercept to activity concentration ---
    slope = float(getattr(ds, "RescaleSlope", 1.0))
    intercept = float(getattr(ds, "RescaleIntercept", 0.0))
    if manuf == "SIEMENS" and units == "BQML":
        a_bqml = (a * slope) + intercept  # already Bq/mL
    else:
        a_bqml = a
    INFO(f"Applied rescale slope={slope}, intercept={intercept} to activity concentration (Bq/mL).")

    # --- Extract Radiopharmaceutical Info ---
    rps = getattr(ds, "RadiopharmaceuticalInformationSequence", None)
    rps = rps[0] if rps else None
    if not rps:
        WARN("Missing Radiopharmaceutical Information Sequence.")
        return a_bqml, "Missing RPS", None

    A0 = float(getattr(rps, "RadionuclideTotalDose", 0.0))
    HL = float(getattr(rps, "RadionuclideHalfLife", 0.0))
    lam = math.log(2.0) / HL if HL > 0 else 0.0

    inj_dt = injection_dt(ds)
    ref_dt = _choose_time_ref(ds)
    dt_s = (ref_dt - inj_dt).total_seconds() if inj_dt and ref_dt else 0.0

    # --- Determine effective activity for normalization ---
    if "ADMIN" in dc:
        # No decay correction – Siemens ADMIN images are already referenced to A0
        Aref = A0
        INFO("DecayCorrection = ADMIN → no decay correction applied (Aref = A0).")
    else:
        # For START or NONE, decay forward to scan start
        Aref = A0 * math.exp(-lam * dt_s)
        INFO("DecayCorrection = START/NONE → decayed activity forward to scan start.")

    # --- Patient body mass normalization ---
    M = _mass_norm_grams(ds)
    if not M or M <= 0:
        WARN("Missing patient mass! Returning raw activity concentration.")
        return a_bqml, "Raw (missing patient mass)", None

    # --- SUV computation ---
    suv = a_bqml * (M / Aref)
    suv = np.nan_to_num(suv, nan=0.0, posinf=3.0, neginf=0.0)

    # --- Logging summary ---
    INFO(f"SUV scaling factor (M/Aref) ...... {M / Aref if Aref else 'N/A'}")
    INFO(f"Voxel mean (Bq/mL, rescaled) ..... {np.mean(a_bqml):.4f}")
    INFO(f"Voxel mean (SUV) ................. {np.mean(suv):.4f}")
    INFO(f"Voxel max (SUV) .................. {np.max(suv):.4f}")
    INFO("──────────────────────────── SUV DEBUG END ──────────────────────────────")

    return suv.astype(np.float32), "SUV from rescaled BQML", M / Aref





def _decay_corrected_dose_to_ref(ds):
    """
    Compute injected dose decay-corrected to the chosen reference time:
      - If DecayCorrection == ADMIN: images are up-decayed to injection → use A0 (no decay)
      - If DecayCorrection == START (typical Siemens): decay A0 to START or MID (per SUV_TIME_REF)
    """
    rps = getattr(ds, "RadiopharmaceuticalInformationSequence", None)
    rps = rps[0] if rps else None
    if not rps:
        return None

    A0 = _float(getattr(rps, "RadionuclideTotalDose", 0.0))
    HL = _float(getattr(rps, "RadionuclideHalfLife", 0.0))
    if A0 <= 0 or HL <= 0:
        return None

    dc = str(getattr(ds, "DecayCorrection", "")).upper()

    # injection datetime
    inj = injection_dt(ds)
    if not inj:
        return None

    # reference datetime: START or MID
    ref_t = _choose_time_ref(ds)
    if not ref_t:
        ref_t = acquisition_start_dt(ds)

    dt_s = (ref_t - inj).total_seconds()
    # midnight wrap fix
    if dt_s < 0 and abs(dt_s) < 12 * 3600:
        inj = inj - timedelta(days=1)
        dt_s = (ref_t - inj).total_seconds()

    if "ADMIN" in dc:
        # Siemens voxels are up-decayed to injection time.
        return A0

    # default (incl. Siemens START): decay to ref_t
    lam = math.log(2.0) / HL
    return A0 * math.exp(-lam * dt_s)


# ---------------------- Geometry/ROI ----------------------
def ring_positions_from_angles(center_mm, p25_mm, p16_mm):
    ref_angles = {lab: math.atan2(REL_COORDS_MM[lab][1], REL_COORDS_MM[lab][0]) for lab in LABEL_ORDER}
    base = ref_angles["25"]
    ref_angles = {lab: ((ref_angles[lab] - base + math.pi)%(2*math.pi))-math.pi for lab in LABEL_ORDER}
    C = np.asarray(center_mm, dtype=float)
    P25 = np.asarray(p25_mm, dtype=float); P16 = np.asarray(p16_mm, dtype=float)
    ring_r = np.linalg.norm(P25 - C)
    ang25_img = math.atan2(*(P25 - C)[[1,0]])
    ang16_img = math.atan2(*(P16 - C)[[1,0]])
    delta_img = ((ang16_img - ang25_img + math.pi)%(2*math.pi))-math.pi
    delta_ref = ref_angles["16"]
    orient_sign = 1.0 if delta_img * delta_ref >= 0 else -1.0
    centers = {}
    for lab in LABEL_ORDER:
        theta = ang25_img + orient_sign * ref_angles[lab]
        x = C[0] + ring_r * math.cos(theta); y = C[1] + ring_r * math.sin(theta)
        centers[lab] = (x, y)
    return centers, ring_r, (orient_sign>0)

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

def auto_select_hotcell_slice(
    dsets, pixel_spacing_mm, center_xy_px, roi_diam_mm=180.0, debug=False
):
    """
    Detect the hot-cell (sphere) section automatically by locating the slice
    with the highest raw DICOM pixel intensity inside a 180 mm ROI.
    Skips the first and last slice to avoid boundary noise.
    """
    import numpy as np
    import matplotlib.pyplot as plt

    h, w = dsets[0].pixel_array.shape
    Y, X = np.ogrid[:h, :w]
    cx, cy = center_xy_px
    r_px = (roi_diam_mm / 2) / pixel_spacing_mm
    mask = (X - cx) ** 2 + (Y - cy) ** 2 <= r_px**2

    max_vals = []

    # Skip first and last slice
    for idx, ds in enumerate(dsets[1:-1], start=1):
        img = ds.pixel_array.astype(np.float32)

        # Apply rescale slope/intercept if present
        slope = getattr(ds, "RescaleSlope", 1.0)
        intercept = getattr(ds, "RescaleIntercept", 0.0)
        img = img * slope + intercept

        roi = img[mask]
        if roi.size == 0:
            print(f"[WARN] Empty ROI mask for slice {idx}")
            max_vals.append((idx, np.nan))
            continue

        maxv = np.nanmax(roi)
        max_vals.append((idx, maxv))

    # Filter out NaNs
    valid = [(i, v) for i, v in max_vals if not np.isnan(v)]
    if not valid:
        raise RuntimeError(
            "No valid ROI data found — check phantom center or mask radius."
        )

    hot_idx, best_max = max(valid, key=lambda t: t[1])

    if debug:
        plt.figure()
        plt.plot([i for i, _ in valid], [v for _, v in valid], marker="o")
        plt.axvline(
            hot_idx, color="r", linestyle="--", label=f"Hot-cell slice {hot_idx}"
        )
        plt.xlabel("Slice index")
        plt.ylabel("Max voxel intensity (scaled DICOM)")
        plt.legend()
        plt.show()

        print(f"[Hot-cell slice detection] Slice {hot_idx} → max={best_max:.2f}")

        # Check a few sample slice stats
        for i in [1, len(valid) // 2, len(valid) - 2]:
            idx, v = valid[i]
            print(
                f"Slice {idx}: mean={np.nanmean(dsets[idx].pixel_array):.2f}, max={v:.2f}"
            )

    return hot_idx


def _create_circular_mask_px(shape, center_px, radius_px):
    rows, cols = shape
    cy, cx = center_px
    y, x = np.ogrid[:rows, :cols]
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius_px ** 2


def _compute_slice_roi_stats_for_candidates(suv_images, dsets, pixel_mm, roi_diam_mm=180.0):
    row_mm, col_mm = pixel_mm
    radius_px = (roi_diam_mm / 2.0) / col_mm
    px_spacing = float(np.mean([row_mm, col_mm]))
    modality_raw = str(getattr(dsets[0], "Modality", "PT")).upper()
    modality = "PET" if modality_raw == "PT" else modality_raw

    roi_means = []
    roi_maxs = []
    roi_mins = []
    roi_values_by_slice = []

    for suv_img, ds in zip(suv_images, dsets):
        px_array = ds.pixel_array.astype(np.float32)
        try:
            cy, cx, _ = find_phantom_center_generalized(
                px_array,
                pixel_size_mm=px_spacing,
                modality=modality,
                debug=False,
            )
        except Exception as e:
            WARN(f"[Candidate ROI] Phantom center detect failed ({e}); using slice image-center fallback.")
            h_px, w_px = px_array.shape
            cy, cx = (h_px / 2.0), (w_px / 2.0)
        mask = _create_circular_mask_px(suv_img.shape, (cy, cx), radius_px)
        roi_values = suv_img[mask]
        roi_values = roi_values[np.isfinite(roi_values)]
        roi_values_by_slice.append(roi_values.astype(np.float32, copy=False))

        if roi_values.size > 0:
            roi_means.append(float(np.mean(roi_values)))
            roi_maxs.append(float(np.max(roi_values)))
            roi_mins.append(float(np.min(roi_values)))
        else:
            roi_means.append(0.0)
            roi_maxs.append(0.0)
            roi_mins.append(0.0)

    return {
        "roi_mean": np.array(roi_means, dtype=np.float32),
        "roi_max": np.array(roi_maxs, dtype=np.float32),
        "roi_min": np.array(roi_mins, dtype=np.float32),
        "roi_values": roi_values_by_slice,
    }


def _compute_hot_intensity_concentration(roi_stats, intensity_percentile=98):
    roi_values_by_slice = roi_stats["roi_values"]
    positive_groups = [vals[vals > 0] for vals in roi_values_by_slice if vals.size > 0]
    if not positive_groups:
        return np.zeros(len(roi_values_by_slice), dtype=np.float32), 0.0

    global_values = np.concatenate(positive_groups)
    if global_values.size == 0:
        return np.zeros(len(roi_values_by_slice), dtype=np.float32), 0.0

    intensity_threshold = float(np.percentile(global_values, intensity_percentile))
    hot_score = np.zeros(len(roi_values_by_slice), dtype=np.float32)

    for idx, roi_values in enumerate(roi_values_by_slice):
        positive_vals = roi_values[roi_values > 0]
        if positive_vals.size == 0:
            continue
        bright_vals = positive_vals[positive_vals >= intensity_threshold]
        if bright_vals.size == 0:
            continue
        hot_score[idx] = float(np.sum(bright_vals - intensity_threshold))

    return hot_score, intensity_threshold


def _find_contiguous_segments(indices):
    if not indices:
        return []
    indices = sorted(indices)
    segments = []
    start = indices[0]
    prev = indices[0]
    for idx in indices[1:]:
        if idx != prev + 1:
            segments.append((start, prev))
            start = idx
        prev = idx
    segments.append((start, prev))
    return segments


def _select_best_segment(segments, values):
    if not segments:
        return None
    scored = []
    for start, end in segments:
        length = end - start + 1
        mean_val = float(np.mean(values[start : end + 1])) if end >= start else 0.0
        scored.append((length, mean_val, start, end))
    scored.sort(reverse=True)
    _, _, start, end = scored[0]
    return (start, end)


def _select_hotcell_candidates(dsets, suv_images, pixel_mm, top_n=5):
    roi_stats = _compute_slice_roi_stats_for_candidates(suv_images, dsets, pixel_mm, roi_diam_mm=UNIF_DIAM_MM)
    hot_score, intensity_threshold = _compute_hot_intensity_concentration(
        roi_stats, intensity_percentile=HOTCELL_INTENSITY_PERCENTILE
    )

    # Restrict the candidate pool to the central HOTCELL_CENTER_FRACTION of
    # the series (equal trim at both ends), evaluated every
    # HOTCELL_SLICE_STRIDE slices. Slices near the stack ends often contain
    # little or no phantom, which produces unreliable center estimates that
    # corrupt both candidate ranking and the center regression fit.
    n_slices = len(hot_score)
    trim = (1.0 - HOTCELL_CENTER_FRACTION) / 2.0
    start = int(np.floor(n_slices * trim))
    stop = int(np.ceil(n_slices * (1.0 - trim)))
    eligible = list(range(start, stop, max(1, HOTCELL_SLICE_STRIDE)))
    # Always keep the true center slice available, even if the stride skips it.
    mid_slice = n_slices // 2
    if mid_slice not in eligible:
        eligible.append(mid_slice)
        eligible.sort()

    max_threshold = float(np.percentile(hot_score, HOTCELL_REGION_PERCENTILE))
    max_candidates = [
        i for i in eligible if hot_score[i] >= max_threshold and hot_score[i] > 0
    ]

    if not max_candidates:
        fallback_idx = max(eligible, key=lambda i: float(hot_score[i]))
        max_candidates = [fallback_idx]

    segments = _find_contiguous_segments(max_candidates)
    best_segment = _select_best_segment(segments, hot_score)

    if best_segment is not None:
        seg_start, seg_end = best_segment
        segment_indices = list(range(seg_start, seg_end + 1))
        ordered = sorted(segment_indices, key=lambda i: float(hot_score[i]), reverse=True)
    else:
        ordered = sorted(max_candidates, key=lambda i: float(hot_score[i]), reverse=True)

    selected = ordered[:top_n]

    if len(selected) < top_n:
        supplement = [
            i for i in sorted(eligible, key=lambda j: float(hot_score[j]), reverse=True)
            if i not in selected
        ]
        selected.extend(supplement[: top_n - len(selected)])

    diagnostics = {
        "hot_score": [float(v) for v in hot_score.tolist()],
        "hot_threshold": max_threshold,
        "intensity_threshold": intensity_threshold,
        "center_fraction": HOTCELL_CENTER_FRACTION,
        "slice_stride": HOTCELL_SLICE_STRIDE,
        "eligible_slices": eligible,
        "selected_candidates": selected,
    }
    return selected, diagnostics


def _load_criteria(path):
    if not path:
        return None
    if not os.path.exists(path):
        WARN(f"Criteria JSON not found: {path}")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        WARN(f"Failed to load criteria JSON '{path}': {e}")
        return None


def _check_bounds(value, rule):
    min_v = rule.get("min")
    max_v = rule.get("max")
    min_inclusive = bool(rule.get("min_inclusive", True))
    max_inclusive = bool(rule.get("max_inclusive", True))

    if value is None or not np.isfinite(value):
        return False

    if min_v is not None:
        if min_inclusive and value < min_v:
            return False
        if not min_inclusive and value <= min_v:
            return False
    if max_v is not None:
        if max_inclusive and value > max_v:
            return False
        if not max_inclusive and value >= max_v:
            return False
    return True


def _distance_from_bounds(value, rule):
    if value is None or not np.isfinite(value):
        return 1e9
    min_v = rule.get("min")
    max_v = rule.get("max")
    if min_v is not None and value < min_v:
        return float(min_v - value)
    if max_v is not None and value > max_v:
        return float(value - max_v)
    return 0.0


def _evaluate_candidate_slice(
    slice_idx,
    suv_img,
    suv_ds,
    pixel_mm,
    background_mean_3,
    criteria,
):
    row_mm, col_mm = pixel_mm
    C_mm, P25_mm, P16_mm = auto_center_and_hotcells(suv_img, suv_ds, debug=False)
    centers_mm, ring_r, is_ccw = ring_positions_from_angles(C_mm, P25_mm, P16_mm)

    roi_r = SUV_ROI_DIAM / 2.0
    roi_metrics = {}
    for lab in LABEL_ORDER:
        ctr = centers_mm[lab]
        mask = circle_mask_mm(suv_img.shape, ctr, roi_r, (row_mm, col_mm))
        vals = suv_img[mask]
        if vals.size == 0:
            roi_metrics[lab] = {"mean": float("nan"), "max": float("nan"), "min": float("nan")}
        else:
            roi_metrics[lab] = {
                "mean": float(np.nanmean(vals)),
                "max": float(np.nanmax(vals)),
                "min": float(np.nanmin(vals)),
            }

    v25_max = roi_metrics["25"]["max"]
    v16_max = roi_metrics["16"]["max"]
    ratio_16_25 = float(v16_max / v25_max) if v25_max and np.isfinite(v25_max) else float("nan")
    v8_max = roi_metrics["8"]["max"]

    criterion_values = {
        "background_mean_suv": float(background_mean_3),
        "cylinder_25mm_max_suv": float(v25_max),
        "max_suv_ratio_16mm_to_25mm": float(ratio_16_25),
    }

    scored_criteria_values = {
        "cylinder_25mm_max_suv": float(v25_max),
        "max_suv_ratio_16mm_to_25mm": float(ratio_16_25),
    }

    pass_map = {}
    distance_sum = 0.0
    criteria_rules = (criteria or {}).get("criteria", {}) if criteria else {}

    for name, value in scored_criteria_values.items():
        rule = criteria_rules.get(name)
        if rule is None:
            pass_map[name] = True
            continue
        passed = _check_bounds(value, rule)
        pass_map[name] = bool(passed)
        distance_sum += _distance_from_bounds(value, rule)

    overall_pass = all(pass_map.values()) if pass_map else True

    return {
        "slice_index": int(slice_idx),
        "dicom_path": str(getattr(suv_ds, "filename", "")),
        "criteria_values": criterion_values,
        "criteria_pass": pass_map,
        "overall_pass": bool(overall_pass),
        "distance_score": float(distance_sum),
        "suv8_max": float(v8_max) if np.isfinite(v8_max) else float("nan"),
        "roi_results": roi_metrics,
        "center_mm": [float(C_mm[0]), float(C_mm[1])],
        "p25_mm": [float(P25_mm[0]), float(P25_mm[1])],
        "p16_mm": [float(P16_mm[0]), float(P16_mm[1])],
        "ring_radius_mm": float(ring_r),
        "ring_direction": "CCW" if is_ccw else "CW",
    }


def _rank_and_select_candidate(candidates_eval):
    passing = [c for c in candidates_eval if c.get("overall_pass")]
    if passing:
        passing.sort(
            key=lambda c: (
                float(c.get("suv8_max", float("-inf"))),
                -float(c.get("distance_score", 0.0)),
            ),
            reverse=True,
        )
        winner = passing[0]
        reason = "pass-first; highest 8mm SUVmax"
    else:
        ranked = sorted(
            candidates_eval,
            key=lambda c: (
                float(c.get("distance_score", float("inf"))),
                -float(c.get("suv8_max", float("-inf"))),
            ),
        )
        winner = ranked[0]
        reason = "fallback; lowest criteria distance then highest 8mm SUVmax"
    return winner, reason


def _regress_center_mm(candidates_eval, target_slice_index):
    """
    Fit center x/y as linear functions of slice index and evaluate at target slice.
    Returns (center_mm, diagnostics) or (None, diagnostics) if insufficient data.
    """
    xs = []
    ys_x = []
    ys_y = []
    for c in candidates_eval:
        idx = c.get("slice_index")
        center = c.get("center_mm")
        if idx is None or center is None or len(center) != 2:
            continue
        cx, cy = float(center[0]), float(center[1])
        if not (np.isfinite(cx) and np.isfinite(cy)):
            continue
        xs.append(float(idx))
        ys_x.append(cx)
        ys_y.append(cy)

    diag = {
        "n_points": len(xs),
        "slice_indices_used": [int(x) for x in xs],
        "target_slice_index": int(target_slice_index),
    }

    if len(xs) < 2:
        return None, diag

    slope_x, intercept_x = np.polyfit(xs, ys_x, 1)
    slope_y, intercept_y = np.polyfit(xs, ys_y, 1)
    pred_x = float(slope_x * target_slice_index + intercept_x)
    pred_y = float(slope_y * target_slice_index + intercept_y)

    diag.update({
        "slope_x": float(slope_x),
        "intercept_x": float(intercept_x),
        "slope_y": float(slope_y),
        "intercept_y": float(intercept_y),
        "pred_center_mm": [pred_x, pred_y],
    })
    return np.array([pred_x, pred_y], dtype=float), diag


def _write_candidate_ranking_sidecar(out_dir, winner, reason, diagnostics, candidates_eval, criteria_path):
    out_path = os.path.join(out_dir, "candidate_ranking.json")
    payload = {
        "criteria_path": criteria_path,
        "winner_slice_index": winner.get("slice_index"),
        "winner_dicom_path": winner.get("dicom_path"),
        "winner_reason": reason,
        "selection_diagnostics": diagnostics,
        "candidates": candidates_eval,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    INFO(f"Saved candidate ranking sidecar → {out_path}")


def _build_phantom_mask_for_debug(px_array, modality):
    img = px_array.astype(np.float32)
    mod = str(modality).upper()

    if mod == "PT":
        mod = "PET"

    if mod == "CT":
        img = exposure.rescale_intensity(img, in_range=(-1000, 2000))
    elif mod in ("PET", "SPECT"):
        img = np.log1p(np.maximum(img, 0))
        img = exposure.rescale_intensity(img)
    elif mod == "MR":
        img = exposure.rescale_intensity(
            img,
            in_range=(np.percentile(img, 2), np.percentile(img, 98)),
        )
    elif mod in ("XRAY", "FLUORO"):
        img = 1.0 - exposure.rescale_intensity(img)
    else:
        img = exposure.rescale_intensity(
            img,
            in_range=(np.percentile(img, 1), np.percentile(img, 99)),
        )

    blurred = gaussian_filter(img, sigma=2)

    if mod in ("CT", "XRAY", "FLUORO"):
        edges = filters.sobel(blurred)
        mask = edges > np.percentile(edges, 90)
    else:
        thresh = filters.threshold_otsu(blurred)
        mask = blurred > thresh

    mask = morphology.closing(mask, morphology.disk(5))
    mask = ndimage.binary_fill_holes(mask)

    labels = measure.label(mask)
    props = measure.regionprops(labels)
    if not props:
        return None, None, None, None, mod

    best = max(props, key=lambda r: r.area)
    best_mask = labels == best.label
    contour = _largest_subpixel_contour(best_mask)
    fit = _fit_circle_least_squares(contour) if contour is not None else None
    return img, best_mask, contour, fit, mod


def _save_circle_fit_debug_overlay(out_dir, suv_ds, pixel_mm):
    px_array = suv_ds.pixel_array.astype(np.float32)
    build = _build_phantom_mask_for_debug(px_array, getattr(suv_ds, "Modality", "PT"))
    if build[0] is None:
        WARN("Could not build phantom mask for circle-fit debug overlay.")
        return

    img, best_mask, contour, fit, modality = build
    row_mm, col_mm = pixel_mm
    h, w = img.shape
    extent = [0, w * col_mm, h * row_mm, 0]

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(img, cmap="gray", extent=extent, origin="upper")
    ax.set_aspect("equal")

    if contour is not None and len(contour) > 0:
        contour_x_mm = contour[:, 1] * col_mm
        contour_y_mm = contour[:, 0] * row_mm
        ax.plot(contour_x_mm, contour_y_mm, color="yellow", lw=1.0, label="Subpixel contour")

    hough_fit = _fit_circle_hough(best_mask, approx_radius_px=np.sqrt(np.sum(best_mask) / np.pi))
    final_fit = hough_fit if hough_fit is not None else fit

    if final_fit is not None:
        cy_px, cx_px, radius_px = final_fit
        cx_mm = cx_px * col_mm
        cy_mm = cy_px * row_mm
        radius_mm = radius_px * float(np.mean([row_mm, col_mm]))
        label = "CHT fitted circle" if hough_fit is not None else "Least-squares fitted circle"
        ax.add_patch(Circle((cx_mm, cy_mm), radius_mm, fill=False, color="lime", lw=2, label=label))
        ax.plot(cx_mm, cy_mm, "r+", ms=12, mew=2, label="Geometric center")
        set_fov_mm(ax, np.array([cx_mm, cy_mm], dtype=float), fov_mm=FOV_MM)
    else:
        WARN("Circle fit failed for debug overlay; showing contour/mask only.")

    ax.set_title(f"Winner Slice Phantom Circle Fit ({modality})")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.8)
    if HIDE_AXES:
        ax.axis("off")

    out_path = os.path.join(out_dir, "winner_circle_fit_debug.png")
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    INFO(f"Saved winner circle-fit debug overlay → {out_path}")


def _save_center_debug_overlay(
    out_dir,
    suv_ds,
    suv_img,
    suv_img_res,
    col_mm,
    row_mm,
    candidate_evals,
    winner_center_mm,
    regressed_center_mm,
    final_center_mm,
    centers_mm,
    roi_r,
):
    """Save a visual overlay of the center-finding method used for final placement."""
    h, w = suv_img.shape
    extent = [0, w * col_mm, h * row_mm, 0]

    fig, ax = plt.subplots(figsize=(8, 8))
    imshow_pet(ax, suv_ds, suv_img, suv_img_res, extent)
    ax.set_aspect("equal")
    set_fov_mm(ax, final_center_mm, fov_mm=FOV_MM)

    # Candidate centers used for trend fitting
    cand_x = []
    cand_y = []
    for c in candidate_evals:
        center = c.get("center_mm")
        if center and len(center) == 2:
            x, y = float(center[0]), float(center[1])
            if np.isfinite(x) and np.isfinite(y):
                cand_x.append(x)
                cand_y.append(y)
    if cand_x:
        ax.scatter(cand_x, cand_y, s=24, c="yellow", edgecolors="black", linewidths=0.5, label="Candidate centers")

    # Winner center from slice-local solve (before regression shift)
    if winner_center_mm is not None and len(winner_center_mm) == 2:
        ax.plot(winner_center_mm[0], winner_center_mm[1], marker="x", color="red", ms=10, mew=2, label="Winner raw center")

    # Regression-predicted center
    if regressed_center_mm is not None and len(regressed_center_mm) == 2:
        ax.plot(regressed_center_mm[0], regressed_center_mm[1], marker="+", color="cyan", ms=14, mew=2, label="Regression center")

    # Final center used for overlay placement
    if final_center_mm is not None and len(final_center_mm) == 2:
        ax.plot(final_center_mm[0], final_center_mm[1], marker="o", color="lime", ms=6, label="Final center used")

    # Draw final ROI rings to show resulting placement
    for lab in LABEL_ORDER:
        if lab not in centers_mm:
            continue
        x, y = centers_mm[lab]
        ax.add_patch(Circle((x, y), roi_r, fill=False, color="magenta", lw=1))

    ax.legend(loc="upper right", fontsize=8, framealpha=0.8)
    ax.set_title("Center Finding Debug Overlay")
    if HIDE_AXES:
        ax.axis("off")

    out_path = os.path.join(out_dir, "center_finding_debug_overlay.png")
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    INFO(f"Saved center debug overlay → {out_path}")



def auto_select_uniformity_slices(dsets, disp_imgs, pixel_spacing_mm, center_xy_px, roi_diam_mm=180.0, n_select=4, debug=False):
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
        How many slices to choose (default 4).
    debug : bool, optional
        If True, print ranked slice stats.

    Returns
    -------
    list[int]
        Indices of the selected uniformity slices (sorted ascending).
    """
    from math import sqrt

    h, w = disp_imgs[0].shape
    Y, X = np.ogrid[:h, :w]
    cx, cy = center_xy_px
    r_px = (roi_diam_mm / 2) / pixel_spacing_mm
    mask = (X - cx)**2 + (Y - cy)**2 <= r_px**2

    mins = []
    for idx, img in enumerate(disp_imgs):
        roi_vals = img[mask]
        mins.append((idx, float(np.nanmin(roi_vals))))

    # Sort by min value descending → highest minima = most uniform
    mins.sort(key=lambda t: t[1], reverse=True)
    selected = [idx for idx, val in mins[:n_select]]
    selected.sort()

    if debug:
        print("\n[Uniformity slice ranking by min(ROI) value]")
        for i, (idx, val) in enumerate(mins[:10]):
            print(f"  {i+1:>2}. slice {idx:>3} → min={val:.3f}")
        print(f"\n[Selected uniformity slices] {selected}")

    return selected


def _localization_upsample_scale(pixel_spacing_mm):
    """
    Choose an integer upsample factor for coarse PET grids.

    The goal is not to change quantitation. It only reduces centroid
    quantization when sphere localization is based on very few native pixels.
    """
    if pixel_spacing_mm <= 2.5:
        return 1
    return min(4, max(2, int(math.ceil(pixel_spacing_mm / 1.5))))


def auto_center_and_hotcells(suv_img, suv_ds, debug=True):
    """
    Automatically detect phantom center and 25/16 mm hot spheres
    using the find_phantom_center_generalized() and detect_hot_cells().
    """
    import numpy as np
    from scipy.ndimage import zoom

    # --- Step 1: Metadata ---
    modality_raw = getattr(suv_ds, "Modality", "PT").upper()
    modality = "PET" if modality_raw == "PT" else modality_raw
    pixel_spacing = np.mean([float(x) for x in suv_ds.PixelSpacing])
    px_array = suv_ds.pixel_array.astype(np.float32)
    upsample_scale = _localization_upsample_scale(pixel_spacing)

    localized_px_array = px_array
    localized_suv_img = suv_img
    localized_pixel_spacing = pixel_spacing

    if upsample_scale > 1:
        localized_px_array = zoom(px_array, upsample_scale, order=1)
        localized_suv_img = zoom(suv_img, upsample_scale, order=1)
        localized_pixel_spacing = pixel_spacing / upsample_scale
        INFO(
            f"[Auto ROI] Upsampling localization grid x{upsample_scale} "
            f"for {pixel_spacing:.3f} mm pixels."
        )

    # --- Step 2: Auto phantom center ---
    try:
        cy, cx, radius_px = find_phantom_center_generalized(
            localized_px_array,
            pixel_size_mm=localized_pixel_spacing,
            modality=modality,
            debug=False,
        )
        center_px = np.array([cx, cy], dtype=float)
    except Exception as e:
        WARN(f"[Auto ROI] Phantom center detect failed ({e}); using image-center fallback.")
        h_loc, w_loc = localized_px_array.shape
        center_px = np.array([w_loc / 2.0, h_loc / 2.0], dtype=float)

    if upsample_scale > 1:
        center_px = center_px / upsample_scale

    # --- Step 3: Auto hot sphere detection ---
    try:
        if upsample_scale > 1:
            detection_center = tuple(center_px * upsample_scale)
        else:
            detection_center = tuple(center_px)

        res = detect_hot_cells(
            localized_suv_img,
            localized_pixel_spacing,
            detection_center,
            debug=debug,
        )

        # --- Compatibility for contrast-based detector ---
        if "labels_px" in res:  # legacy format
            labels_px = res["labels_px"]
            P25_px = np.array(labels_px.get("25") or labels_px.get("25mm"))
            P16_px = np.array(labels_px.get("16") or labels_px.get("16mm"))
        else:  # new format (contrast-based)
            P25_px = np.array(res.get("25mm") or res.get("25"))
            P16_px = np.array(res.get("16mm") or res.get("16"))

        if upsample_scale > 1:
            P25_px = P25_px / upsample_scale
            P16_px = P16_px / upsample_scale

        if P25_px is None or P16_px is None or P25_px.size == 0 or P16_px.size == 0:
            raise RuntimeError("Hot spheres not fully detected.")

        C_mm = center_px * pixel_spacing
        P25_mm = P25_px * pixel_spacing
        P16_mm = P16_px * pixel_spacing

        print(f"[Auto ROI] Found 25 mm at {P25_mm.round(2)}, 16 mm at {P16_mm.round(2)}")
        return C_mm, P25_mm, P16_mm

    except Exception as e:
        print(f"[Auto ROI] Detection failed ({e}); using fallback.")
        C_mm = center_px * pixel_spacing
        P25_mm = C_mm + np.array([40, 0])
        P16_mm = C_mm + np.array([60, 0])
        return C_mm, P25_mm, P16_mm

# ---------------------- Main ----------------------

def main(argv=None):
    import argparse
    from tqdm import tqdm

    # ---------- CLI or GUI folder selection ----------
    parser = argparse.ArgumentParser(
        description="Automatic PET phantom scoring with Siemens-aware SUV computation."
    )
    parser.add_argument("--input", "-i", help="Path to input DICOM folder (optional)")
    parser.add_argument("--output", "-o", help="Path to output folder (optional)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--debug-dir", help="Optional directory for debug artifacts")
    parser.add_argument("--criteria-json", help="Optional criteria JSON path for candidate scoring")
    parser.add_argument(
        "--metadata-overrides",
        help="JSON file containing in-memory DICOM metadata overrides for SUV calculation",
    )
    args = parser.parse_args(argv)

    # If not provided via CLI, open File Explorer pickers
    in_dir = os.path.abspath(args.input) if args.input else ask_folder("Select PET DICOM Folder (INPUT)")
    if not in_dir:
        INFO("Cancelled: no input folder."); return
    external_rwvm = find_rwvm_in_dir(in_dir)

    metadata_overrides = (
        load_metadata_overrides(args.metadata_overrides)
        if args.metadata_overrides else None
    )
    override_audit_records = []

    out_dir = os.path.abspath(args.output) if args.output else ask_output_folder_and_name()
    if not out_dir:
        INFO("Cancelled: no output folder/name."); return
    os.makedirs(out_dir, exist_ok=True)

    criteria_path = args.criteria_json or (DEFAULT_CRITERIA_JSON if os.path.exists(DEFAULT_CRITERIA_JSON) else None)
    criteria = _load_criteria(criteria_path)

    # ---------- Progress bar scaffold (non-invasive) ----------
    steps = ["Load series", "Detect center", "Pick slices", "Compute SUVs", "Write outputs"]
    pbar = tqdm(total=len(steps), desc="Processing", ncols=90)

    try:
        # ========== FROM HERE DOWN: EXACTLY AS BEFORE ==========
        INFO("Loading series…")
        disp_imgs, res_imgs, dsets, (row_mm, col_mm) = load_series(
            in_dir,
            metadata_overrides=metadata_overrides,
            override_audit_records=override_audit_records,
        )
        INFO(f"Usable frames: {len(disp_imgs)}  |  PixelSpacing: {row_mm} x {col_mm} mm")
        if metadata_overrides is not None:
            audit_path = write_metadata_override_audit(
                out_dir,
                build_metadata_override_audit(
                    "suv_overlay_auto",
                    metadata_overrides,
                    override_audit_records,
                    len(dsets),
                    dsets[0],
                ),
            )
            INFO(f"Saved metadata override audit -> {audit_path}")
        pbar.update(1)  # Load series

        # Auto phantom center detection
        pixel_spacing = np.mean([float(x) for x in dsets[0].PixelSpacing])
        mid_idx = len(dsets) // 2
        try:
            cy, cx, _ = find_phantom_center_generalized(
                dsets[mid_idx].pixel_array.astype(np.float32),
                pixel_size_mm=pixel_spacing,
                modality="PET",
                debug=False,
            )
        except Exception as e:
            WARN(f"Phantom center auto-detect failed on mid-slice ({e}); using image center fallback.")
            h0, w0 = dsets[mid_idx].pixel_array.shape
            cy, cx = (h0 / 2.0), (w0 / 2.0)
        pbar.update(1)  # Detect center

        # Auto slice detection (3 background slices)
        uni_idx = auto_select_uniformity_slices(
            dsets,
            disp_imgs,
            pixel_spacing,
            (cx, cy),
            n_select=3,
            debug=False,
        )
        INFO(f"Uniformity slices (background): {uni_idx}")
        pbar.update(1)  # Pick slices

        uni_imgs_disp = [disp_imgs[i] for i in uni_idx]
        uni_imgs_res = [res_imgs[i] for i in uni_idx]
        uni_dsets = [dsets[i] for i in uni_idx]

        # --- Build SUV images for all slices (used by candidate scoring) ---
        suv_all_imgs = []
        for ds_i, img_i in zip(dsets, res_imgs):
            suv_i, _, _ = suv_from_ds(ds_i, img_i, external_rwvm=external_rwvm)
            suv_all_imgs.append(np.nan_to_num(suv_i, nan=0.0, posinf=3.0, neginf=0.0))
        suv_uni_imgs = [suv_all_imgs[i] for i in uni_idx]

        # --- Automatic phantom center detection for uniformity panel ---
        try:
            modality = getattr(dsets[0], "Modality", "PT").upper()
            uniformity_slice_index = uni_idx[0] if isinstance(uni_idx, (list, tuple)) else uni_idx
            px_array = dsets[uniformity_slice_index].pixel_array.astype(np.float32)

            cy, cx, radius_px = find_phantom_center_generalized(
                px_array,
                pixel_size_mm=pixel_spacing,
                modality=modality,
                debug=False  # change to True for overlay check
            )

            auto_center = np.array([cx, cy])
            print(f"[{modality}] Auto phantom center detected at ({cx:.1f}, {cy:.1f})")

            DEBUG = False
            if DEBUG:
                fig, ax = plt.subplots(figsize=(7, 7))
                ax.imshow(px_array, cmap="gray", vmin=-1000, vmax=1000)
                ax.plot(auto_center[0], auto_center[1], "ro", ms=10)
                circ = plt.Circle((auto_center[0], auto_center[1]), radius_px, color="lime", fill=False, lw=2)
                ax.add_patch(circ)
                ax.set_title(f"Detected center ({cx:.1f}, {cy:.1f})")
                fig.savefig(os.path.join(out_dir, "phantom_center_debug.png"), dpi=300, bbox_inches="tight")
                plt.close(fig)

            center_px = auto_center
            center_uni_mm = center_px * pixel_spacing
            print(f"[Uniformity] Using center: {center_uni_mm[0]:.2f} mm, {center_uni_mm[1]:.2f} mm")

        except Exception as e:
            print(f"[Warning] Uniformity auto-detect failed: {e}")
            h, w = uni_imgs_disp[0].shape
            center_uni_mm = np.array([w * col_mm / 2, h * row_mm / 2])
            print(f"[Fallback] Using image center ({center_uni_mm[0]:.1f}, {center_uni_mm[1]:.1f})")

        # --- Compute uniformity means ---
        uni_r = UNIF_DIAM_MM / 2.0
        if not roi_inside_image(uni_imgs_disp[0].shape, center_uni_mm, uni_r, (row_mm, col_mm)):
            WARN("Uniformity ROI extends outside the image.")
        uni_means = []
        for suv_u in suv_uni_imgs:
            mask = circle_mask_mm(suv_u.shape, center_uni_mm, uni_r, (row_mm, col_mm))
            vals = suv_u[mask]
            uni_means.append(float(np.nanmean(vals)) if vals.size else float('nan'))

        background_mean_3 = float(np.nanmean(uni_means[:3])) if uni_means else float("nan")

        # --- Manifest-style hotcell candidate selection + criteria scoring ---
        candidate_indices, selector_diag = _select_hotcell_candidates(
            dsets=dsets,
            suv_images=suv_all_imgs,
            pixel_mm=(row_mm, col_mm),
            top_n=HOTCELL_TOP_N_CANDIDATES,
        )
        INFO(f"Hotcell candidate slices: {candidate_indices}")

        candidate_evals = []
        for idx in candidate_indices:
            candidate_evals.append(
                _evaluate_candidate_slice(
                    slice_idx=idx,
                    suv_img=suv_all_imgs[idx],
                    suv_ds=dsets[idx],
                    pixel_mm=(row_mm, col_mm),
                    background_mean_3=background_mean_3,
                    criteria=criteria,
                )
            )

        winner, winner_reason = _rank_and_select_candidate(candidate_evals)
        suv_idx = int(winner["slice_index"])

        regressed_center_mm, reg_diag = _regress_center_mm(candidate_evals, suv_idx)
        selector_diag["center_regression"] = reg_diag

        _write_candidate_ranking_sidecar(
            out_dir=out_dir,
            winner=winner,
            reason=winner_reason,
            diagnostics=selector_diag,
            candidates_eval=candidate_evals,
            criteria_path=criteria_path,
        )

        INFO(f"Selected SUV slice: {suv_idx} | DICOM: {winner.get('dicom_path', '')}")
        INFO(f"Selection rule: {winner_reason}")

        suv_img_disp = disp_imgs[suv_idx]
        suv_img_res = res_imgs[suv_idx]
        suv_ds = dsets[suv_idx]
        suv_img = suv_all_imgs[suv_idx]

        INFO(f"Manufacturer: {getattr(suv_ds,'Manufacturer','N/A')}")
        INFO(f"Units tag: {getattr(suv_ds,'Units','N/A')}")
        print(
            "SUV slice stats:",
            "min=", float(np.nanmin(suv_img)),
            "max=", float(np.nanmax(suv_img)),
            "std=", float(np.nanstd(suv_img)),
        )
        pbar.update(1)  # Compute SUVs

        # --- SUV ROI section ---
        # Reuse winner-evaluated geometry, then optionally apply center regression trend.
        try:
            C_mm = np.array(winner.get("center_mm"), dtype=float)
            P25_mm = np.array(winner.get("p25_mm"), dtype=float)
            P16_mm = np.array(winner.get("p16_mm"), dtype=float)
            if C_mm.size != 2 or P25_mm.size != 2 or P16_mm.size != 2:
                raise ValueError("Winner geometry missing/invalid")
        except Exception:
            WARN("Winner geometry unavailable; recomputing center/hotcells for final overlay.")
            C_mm, P25_mm, P16_mm = auto_center_and_hotcells(suv_img, suv_ds, debug=False)

        if regressed_center_mm is not None and regressed_center_mm.size == 2:
            delta = regressed_center_mm - C_mm
            C_mm = regressed_center_mm
            P25_mm = P25_mm + delta
            P16_mm = P16_mm + delta
            INFO(
                f"Applied center regression at slice {suv_idx}: "
                f"C_mm=({C_mm[0]:.2f}, {C_mm[1]:.2f})"
            )
        else:
            WARN("Center regression unavailable (insufficient points); using winner center directly.")

        centers_mm, ring_r, is_ccw = ring_positions_from_angles(C_mm, P25_mm, P16_mm)
        INFO(f"Ring radius: {ring_r:.2f} mm  |  Direction: {'CCW' if is_ccw else 'CW'}")

        roi_r = SUV_ROI_DIAM / 2.0
        results = []
        for lab in LABEL_ORDER:
            ctr = centers_mm[lab]
            if not roi_inside_image(suv_img.shape, ctr, roi_r, (row_mm, col_mm)):
                WARN(f"{lab} ROI extends outside image bounds.")
            mask = circle_mask_mm(suv_img.shape, ctr, roi_r, (row_mm, col_mm))
            vals = suv_img[mask]
            if vals.size == 0:
                results.append((lab, float('nan'), float('nan'), float('nan')))
            else:
                results.append((lab,
                                float(np.nanmean(vals)),
                                float(np.nanmax(vals)),
                                float(np.nanmin(vals))))

        # --- Write SUV CSV + Append Uniformity stats (unchanged) ---
        out_csv = os.path.join(out_dir, "SUV_results.csv")
        with open(out_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ROI Label", "SUVmean", "SUVmax", "SUVmin"])
            for lab, mx, Ma, mi in results:
                w.writerow([lab, f"{mx:.6f}", f"{Ma:.6f}", f"{mi:.6f}"])
        INFO(f"Saved SUV ROI CSV → {out_csv}")  # :contentReference[oaicite:0]{index=0}

        with open(out_csv, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([])
            w.writerow(["--- Uniformity Statistics ---"])
            w.writerow(["ROI Label", "SUVmean", "SUVmax", "SUVmin"])
            for j, suv_u in enumerate(suv_uni_imgs, start=1):
                mask = circle_mask_mm(suv_u.shape, center_uni_mm, uni_r, (row_mm, col_mm))
                vals = suv_u[mask]
                if vals.size > 0:
                    umean = float(np.nanmean(vals))
                    umax  = float(np.nanmax(vals))
                    umin  = float(np.nanmin(vals))
                else:
                    umean = umax = umin = float('nan')
                w.writerow([f"Uniformity Slice {j}",
                            f"{umean:.6f}", f"{umax:.6f}", f"{umin:.6f}"])
        INFO(f"Appended Uniformity stats → {out_csv}")  # :contentReference[oaicite:1]{index=1}

        # --- Single overlay (SUV) ---
        h, w = suv_img.shape
        extent = [0, w * col_mm, h * row_mm, 0]
        fig, ax = plt.subplots()
        imshow_pet(ax, suv_ds, suv_img, suv_img_res, extent)
        ax.set_aspect("equal")
        set_fov_mm(ax, C_mm, fov_mm=FOV_MM)
        if HIDE_AXES: ax.axis('off')

        for lab in LABEL_ORDER:
            x, y = centers_mm[lab]
            ax.add_patch(Circle((x, y), roi_r, fill=False, color='maroon', lw=1))

        offset_factor = 1.5
        for (lab, mean_v, max_v, min_v) in results:
            x, y = centers_mm[lab]
            v = np.array([x - C_mm[0], y - C_mm[1]])
            theta = math.atan2(v[1], v[0]) if not np.allclose(v, 0) else 0.0
            Rtxt = max(ring_r * offset_factor, np.linalg.norm(v) + roi_r + 5.0)
            tx = C_mm[0] + Rtxt * math.cos(theta)
            ty = C_mm[1] + Rtxt * math.sin(theta)
            if lab in ["25", "16", "12", "8"]:
                text = f"{lab} mm Hot Cell\nMax={max_v:.2f} SUV"
            else:
                text = f"{lab}\nMean={mean_v:.2f} SUV\nMin={min_v:.2f} SUV"
            ax.text(tx, ty, text, color='maroon', fontsize=9, va='center', ha='center')

        png_overlay = os.path.join(out_dir, "SUV_overlay.png")
        fig.savefig(png_overlay, dpi=300, bbox_inches='tight')
        INFO(f"Saved overlay PNG → {png_overlay}")  # :contentReference[oaicite:2]{index=2}

        # --- Composite 2×2 (SUV top-left) ---
        fig, axs = plt.subplots(2, 2, figsize=(12, 10))

        # (0,0) SUV
        ax0 = axs[0, 0]
        imshow_pet(ax0, suv_ds, suv_img, suv_img_res, extent)
        ax0.set_aspect("equal")
        for lab in LABEL_ORDER:
            x, y = centers_mm[lab]
            ax0.add_patch(Circle((x, y), roi_r, fill=False, color='teal', lw=1))
            ax0.text(x, y, lab, color='teal', fontsize=15, ha='center', va='center')
        set_fov_mm(ax0, C_mm, fov_mm=FOV_MM)
        if HIDE_AXES: ax0.axis('off')

        # Uniformity panels
        positions = [(0, 1), (1, 0), (1, 1)]
        for (i, suv_u), pos in zip(enumerate(suv_uni_imgs, start=1), positions):
            axu = axs[pos]
            hU, wU = suv_u.shape
            extentU = [0, wU * col_mm, hU * row_mm, 0]
            imshow_pet(axu, uni_dsets[i - 1], suv_u, uni_imgs_res[i - 1], extentU)
            axu.set_aspect("equal")
            axu.add_patch(Circle((center_uni_mm[0], center_uni_mm[1]),
                                 UNIF_DIAM_MM / 2.0, fill=False,
                                 color='dodgerblue', lw=2))
            axu.text(center_uni_mm[0], center_uni_mm[1],
                     f"Mean={uni_means[i - 1]:.2f}",
                     color='dodgerblue', fontsize=18,
                     ha='center', va='center')
            set_fov_mm(axu, center_uni_mm, fov_mm=FOV_MM)
            if HIDE_AXES: axu.axis('off')

        composite_path = os.path.join(out_dir, "SUV_composite.png")
        fig.tight_layout()
        fig.savefig(composite_path, dpi=300, bbox_inches='tight')
        #plt.show()
        INFO(f"Saved composite PNG → {composite_path}")  # :contentReference[oaicite:3]{index=3}
        INFO("Done.")
        pbar.update(1)  # Write outputs

    except Exception as e:
        try:
            messagebox.showerror("Error", str(e))
        except Exception:
            pass
        ERROR(str(e))
    finally:
        pbar.close()


if __name__ == "__main__":
    raise SystemExit(main())