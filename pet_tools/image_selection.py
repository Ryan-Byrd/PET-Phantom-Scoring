#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B.__PET_Image_Viewer.py
Multi-slice PET viewer with selection, window/level, colormap, zoom (FOV),
auto phantom-center, and PNG export (per-slice + splash grid).

Requires: 3._PET_ROI_Manager.py in the same folder.
"""

import os, math, importlib.util, argparse, json
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt

import tkinter as tk
from tkinter import ttk, messagebox

# ============= Dynamic import from PET_ROI_Manager =================
HERE = os.path.dirname(os.path.abspath(__file__))

# Ensure workspace root is on sys.path for package imports
import sys as _sys
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if REPO_ROOT not in _sys.path:
    _sys.path.insert(0, REPO_ROOT)

from pet_tools import suv_overlay_manual as PET
# If you intended the auto overlay instead, use:
# from pet_tools import suv_overlay_auto as PET


# Shims to reuse your helpers & constants
ask_folder                   = PET.ask_folder
ask_output_folder_and_name   = PET.ask_output_folder_and_name
load_series                  = PET.load_series
suv_from_ds                  = PET.suv_from_ds
find_phantom_center_generalized = PET.find_phantom_center_generalized
INFO, WARN, ERROR            = PET.INFO, PET.WARN, PET.ERROR

# Defaults
DEFAULT_WL_MIN = 0.0   # SUV
DEFAULT_WL_MAX = 3.0   # SUV
DEFAULT_FOV_MM = 300.0
MAX_PER_PAGE   = 100

CMAPS = [
    # Standard grayscale and medical
    "gray", "bone", "hot", "afmhot", "gist_heat",

    # Perceptually uniform (great for PET/SPECT SUV maps)
    "viridis", "plasma", "inferno", "magma", "cividis", "turbo",

    # Diverging (for symmetrical SPECT residuals, difference images, etc.)
    "coolwarm", "seismic", "bwr", "RdBu_r", "PiYG",

    # Classic nuclear medicine or “rainbow” styles
    "jet", "nipy_spectral", "gist_rainbow", "rainbow",

    # Other useful medical colormaps
    "cubehelix", "twilight", "twilight_shifted", "hsv"
]



def compute_display(suv_img, vmin, vmax):
    """Clip to [vmin,vmax], normalize to [0,1], then invert (white background)."""
    s = np.nan_to_num(suv_img, nan=0.0, posinf=vmax, neginf=vmin)
    s = np.clip(s, vmin, vmax)
    if vmax <= vmin:
        vmax = vmin + 1e-6
    s = (s - vmin) / (vmax - vmin)  # 0..1
    return 1.0 - s                   # invert to white background


def crop_around_center_mm(img, center_mm, fov_mm, pixel_mm):
    """Return (img, extent) but we use axis limits for zoom; no actual crop needed."""
    h, w = img.shape
    row_mm, col_mm = pixel_mm
    extent = [0, w * col_mm, h * row_mm, 0]
    cx, cy = center_mm
    half = fov_mm / 2.0
    x0, x1 = cx - half, cx + half
    y0, y1 = cy - half, cy + half
    return extent, (x0, x1, y0, y1)


def paged_splash_select(images_disp, pixel_mm):
    """
    Paged multi-select: click to toggle selection, ENTER to accept each page.
    Returns sorted list of selected indices.
    """
    n = len(images_disp)
    pages = math.ceil(n / MAX_PER_PAGE)
    selected = set()

    def show_page(page):
        start = page * MAX_PER_PAGE
        end = min((page + 1) * MAX_PER_PAGE, n)
        subset = images_disp[start:end]

        cols = int(np.ceil(np.sqrt(len(subset)))) or 1
        rows = int(np.ceil(len(subset) / cols)) or 1
        fig, axes = plt.subplots(rows, cols, figsize=(12, 12))
        axes = np.array(axes, ndmin=1).ravel()

        def onclick(e):
            if e.inaxes not in axes:
                return
            local_idx = list(axes).index(e.inaxes)
            idx = start + local_idx
            if idx >= end:
                return
            if idx in selected:
                selected.remove(idx)
            else:
                selected.add(idx)
            update_highlight()

        def update_highlight():
            for i, ax in enumerate(axes):
                idx = start + i
                # clear then draw
                for sp in ax.spines.values():
                    sp.set_linewidth(3)
                    sp.set_color("red" if idx in selected else "black")
                # "✓ selected" tag in blue - remove existing text objects
                for txt in ax.texts[:]:
                    txt.remove()
                if idx in selected and idx < end:
                    ax.text(0.5, 0.08, "✓ selected", color="blue", fontsize=10,
                            ha="center", va="bottom", transform=ax.transAxes, weight="bold")
            fig.canvas.draw_idle()

        for i, ax in enumerate(axes):
            ax.axis("off")
            ds_idx = start + i
            if ds_idx < end:
                h, w = images_disp[ds_idx].shape
                row_mm, col_mm = pixel_mm
                extent = [0, w*col_mm, h*row_mm, 0]
                ax.imshow(images_disp[ds_idx], cmap="gray", extent=extent, origin="upper")
                ax.set_aspect("equal")
                ax.set_title(f"Slice {ds_idx}", fontsize=8)

        fig.suptitle(f"Page {page+1}/{pages} — Click to toggle; press Enter for next page",
                     fontsize=12)
        fig.canvas.mpl_connect("button_press_event", onclick)
        fig.canvas.mpl_connect("key_press_event",
                               lambda e: plt.close(fig) if e.key == "enter" else None)

        # Initial highlight update to show any previously selected images
        update_highlight()
        plt.show()
        plt.close(fig)

    for p in range(pages):
        show_page(p)

    if not selected:
        raise RuntimeError("No slices selected.")
    return sorted(selected)


def load_config(path: str | None) -> dict:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main(argv=None) -> int:
    # -------- CLI --------
    parser = argparse.ArgumentParser(
        description="Multi-slice PET viewer with selection, window/level, FOV, and PNG export."
    )
    parser.add_argument("--input", "-i", help="Input DICOM folder (optional; else dialog)")
    parser.add_argument("--output", "-o", help="Output folder (optional; else dialog)")
    parser.add_argument("--indices", help="Comma-separated slice indices to use (bypasses selection UI), e.g., '0,5,10,15'")
    parser.add_argument("--cmap", help=f"Colormap name (default: gray). Options: {', '.join(CMAPS[:5])}...")
    parser.add_argument("--wmin", type=float, help=f"Window min SUV (default: {DEFAULT_WL_MIN})")
    parser.add_argument("--wmax", type=float, help=f"Window max SUV (default: {DEFAULT_WL_MAX})")
    parser.add_argument("--fov", type=float, help=f"Field of view in mm (default: {DEFAULT_FOV_MM})")
    parser.add_argument("--rows", type=int, help="Grid rows for splash view")
    parser.add_argument("--cols", type=int, help="Grid columns for splash view")
    parser.add_argument("--save", action="store_true", help="Skip GUI and automatically save individual slices and splash view")
    parser.add_argument("--config", help="Optional JSON config with keys: input, output, indices, cmap, wmin, wmax, fov, rows, cols, save, debug, debug_dir")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--debug-dir", help="Directory to store debug artifacts/logs")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    debug_enabled = args.debug or bool(cfg.get("debug"))
    debug_dir = args.debug_dir or cfg.get("debug_dir")
    if debug_enabled:
        INFO("Debug logging enabled")
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        INFO(f"Debug artifacts directory: {debug_dir}")

    # -------- I/O selection (same dialogs as PET ROI Manager) --------
    in_dir = args.input or cfg.get("input")
    out_dir = args.output or cfg.get("output")

    if not in_dir:
        in_dir = ask_folder("Select PET DICOM Folder (INPUT)")
    if not in_dir:
        INFO("Cancelled: no input folder."); return 1

    if not out_dir:
        out_dir = ask_output_folder_and_name()
    if not out_dir:
        INFO("Cancelled: no output folder/name."); return 1

    # -------- Load series + compute SUVs (for ALL frames) ------------
    INFO("Loading series...")
    disp_imgs, res_imgs, dsets, pixel_mm = load_series(in_dir)
    row_mm, col_mm = pixel_mm
    INFO(f"Usable frames: {len(disp_imgs)}  |  PixelSpacing: {row_mm} x {col_mm} mm")

    suv_imgs = []
    for ds, raw in zip(dsets, res_imgs):
        suv, _, _ = suv_from_ds(ds, raw)
        suv_imgs.append(suv.astype(np.float32))

    # -------- Auto phantom center (from mid slice), in mm ------------
    mid_idx = len(dsets)//2
    px_spacing = np.mean([float(x) for x in dsets[0].PixelSpacing])
    px_array   = dsets[mid_idx].pixel_array.astype(np.float32)
    cy, cx, _r = find_phantom_center_generalized(
        px_array, pixel_size_mm=px_spacing, modality=getattr(dsets[0], "Modality", "PT"), debug=False
    )
    center_mm = np.array([cx*col_mm, cy*row_mm])
    INFO(f"Auto center (mm): ({center_mm[0]:.1f}, {center_mm[1]:.1f})")

    # -------- Build initial display (0–3 SUV inverted) ---------------
    vmin, vmax = DEFAULT_WL_MIN, DEFAULT_WL_MAX
    images_disp = [compute_display(s, vmin, vmax) for s in suv_imgs]

    # -------- Multi-select which slices to work with ------------------
    # Check if indices provided via CLI or config
    indices_str = args.indices or cfg.get("indices")
    if indices_str:
        # Parse comma-separated indices
        try:
            selected = [int(x.strip()) for x in indices_str.split(",")]
            # Validate indices are within range
            n_frames = len(suv_imgs)
            invalid = [i for i in selected if i < 0 or i >= n_frames]
            if invalid:
                ERROR(f"Invalid indices {invalid}. Must be in range [0, {n_frames-1}]")
                return 1
            selected = sorted(selected)
            INFO(f"Using provided indices: {selected}")
        except ValueError as e:
            ERROR(f"Failed to parse indices: {e}")
            return 1
    else:
        # Interactive selection
        try:
            selected = paged_splash_select(images_disp, pixel_mm)
        except Exception as e:
            ERROR(str(e)); return 1
        INFO(f"Selected indices: {selected}")

    # Get initial values from CLI/config or use defaults
    init_cmap = args.cmap or cfg.get("cmap") or "gray"
    init_wmin = args.wmin if args.wmin is not None else cfg.get("wmin", vmin)
    init_wmax = args.wmax if args.wmax is not None else cfg.get("wmax", vmax)
    init_fov = args.fov if args.fov is not None else cfg.get("fov", DEFAULT_FOV_MM)
    init_rows = args.rows if args.rows is not None else cfg.get("rows", max(1, int(np.ceil(len(selected) / 5))))
    init_cols = args.cols if args.cols is not None else cfg.get("cols", min(len(selected), 5))

    # -------- Auto-save mode (bypass GUI) ---------------------------
    auto_save = args.save or cfg.get("save", False)
    if auto_save:
        INFO("Auto-save mode: saving slices and splash view...")
        os.makedirs(out_dir, exist_ok=True)
        
        # Save individual slices
        for i in selected:
            img = compute_display(suv_imgs[i], init_wmin, init_wmax)
            extent, (x0, x1, y0, y1) = crop_around_center_mm(img, center_mm, init_fov, pixel_mm)

            f = plt.figure(figsize=(5,5))
            ax = f.add_subplot(111)
            ax.imshow(img, cmap=init_cmap, extent=extent, origin="upper", vmin=0, vmax=1)
            ax.set_aspect("equal")
            ax.set_xlim(x0, x1); ax.set_ylim(y1, y0)
            ax.axis("off")
            fname = os.path.join(out_dir, f"Slice_{i:03d}.png")
            f.savefig(fname, dpi=300, bbox_inches="tight", pad_inches=0)
            plt.close(f)
            INFO(f"Saved {fname}")
        
        # Save splash view
        disp_now = [compute_display(suv_imgs[i], init_wmin, init_wmax) for i in selected]
        fig_splash = plt.figure(figsize=(10, 6))
        axes = fig_splash.subplots(init_rows, init_cols).ravel() if init_rows*init_cols > 1 else [fig_splash.add_subplot(111)]
        for idx, ax in enumerate(axes):
            ax.axis("off")
            if idx >= len(disp_now):
                continue
            i_global = selected[idx]
            img = disp_now[idx]
            extent, (x0, x1, y0, y1) = crop_around_center_mm(img, center_mm, init_fov, pixel_mm)
            ax.imshow(img, cmap=init_cmap, extent=extent, origin="upper", vmin=0, vmax=1)
            ax.set_aspect("equal")
            ax.set_xlim(x0, x1); ax.set_ylim(y1, y0)
            ax.set_title(f"Slice {i_global}", fontsize=8)
        fig_splash.tight_layout()
        splash_fname = os.path.join(out_dir, "Splash.png")
        fig_splash.savefig(splash_fname, dpi=300, bbox_inches="tight")
        plt.close(fig_splash)
        INFO(f"Saved splash → {splash_fname}")
        INFO(f"All files saved to: {out_dir}")
        return 0


    # ======================= Control GUI =============================
    # Live splash with controls for cmap, W/L, FOV, rows, cols; save buttons.
    root = tk.Tk()
    root.title("PET Image Viewer — Splash Controls")

    # Ensure closing the window exits the program completely
    def on_close():
        root.destroy()
        plt.close('all')
        import sys
        sys.exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)

    # State (using values from CLI/config)
    state = {
        "cmap": tk.StringVar(value=init_cmap),
        "wmin": tk.DoubleVar(value=init_wmin),
        "wmax": tk.DoubleVar(value=init_wmax),
        "fov":  tk.DoubleVar(value=init_fov),
        "rows": tk.IntVar(value=init_rows),
        "cols": tk.IntVar(value=init_cols),
    }

    # Matplotlib figure
    fig = plt.figure(figsize=(10, 6))
    canvas = matplotlib.backends.backend_tkagg.FigureCanvasTkAgg(fig, master=root)
    canvas.get_tk_widget().grid(row=0, column=0, columnspan=6, sticky="nsew", padx=8, pady=8)

    # Controls
    ttk.Label(root, text="Colormap").grid(row=1, column=0, sticky="w", padx=6)
    cmap_box = ttk.Combobox(root, values=CMAPS, textvariable=state["cmap"], width=12)
    cmap_box.grid(row=1, column=1, sticky="w", padx=6)

    ttk.Label(root, text="Window min (SUV)").grid(row=1, column=2, sticky="e", padx=6)
    e_wmin = ttk.Entry(root, textvariable=state["wmin"], width=8); e_wmin.grid(row=1, column=3, sticky="w", padx=6)

    ttk.Label(root, text="Window max (SUV)").grid(row=1, column=4, sticky="e", padx=6)
    e_wmax = ttk.Entry(root, textvariable=state["wmax"], width=8); e_wmax.grid(row=1, column=5, sticky="w", padx=6)

    ttk.Label(root, text="FOV (mm)").grid(row=2, column=0, sticky="w", padx=6)
    e_fov = ttk.Entry(root, textvariable=state["fov"], width=8); e_fov.grid(row=2, column=1, sticky="w", padx=6)

    ttk.Label(root, text="Grid Rows").grid(row=2, column=2, sticky="e", padx=6)
    e_rows = ttk.Entry(root, textvariable=state["rows"], width=6); e_rows.grid(row=2, column=3, sticky="w", padx=6)

    ttk.Label(root, text="Grid Cols").grid(row=2, column=4, sticky="e", padx=6)
    e_cols = ttk.Entry(root, textvariable=state["cols"], width=6); e_cols.grid(row=2, column=5, sticky="w", padx=6)

    # Redraw
    def render_splash():
        fig.clf()
        try:
            vmin = float(state["wmin"].get())
            vmax = float(state["wmax"].get())
            fov  = float(state["fov"].get())
            rows = max(1, int(state["rows"].get()))
            cols = max(1, int(state["cols"].get()))
        except Exception:
            messagebox.showerror("Value error", "Please enter valid numeric values.")
            return

        cmap = state["cmap"].get() or "gray"

        # compute displayed images for current WL
        disp_now = [compute_display(suv_imgs[i], vmin, vmax) for i in selected]

        axes = fig.subplots(rows, cols).ravel() if rows*cols > 1 else [fig.add_subplot(111)]
        for idx, ax in enumerate(axes):
            ax.axis("off")
            if idx >= len(disp_now):
                continue
            i_global = selected[idx]
            img = disp_now[idx]
            extent, (x0, x1, y0, y1) = crop_around_center_mm(img, center_mm, fov, pixel_mm)
            ax.imshow(img, cmap=cmap, extent=extent, origin="upper", vmin=0, vmax=1)
            ax.set_aspect("equal")
            ax.set_xlim(x0, x1); ax.set_ylim(y1, y0)
            ax.set_title(f"Slice {i_global}", fontsize=8)
        fig.tight_layout()
        canvas.draw_idle()

    # Save per-slice PNGs
    def save_slices():
        try:
            vmin = float(state["wmin"].get())
            vmax = float(state["wmax"].get())
            fov  = float(state["fov"].get())
        except Exception:
            messagebox.showerror("Value error", "Please enter valid numeric values.")
            return
        cmap = state["cmap"].get() or "gray"

        os.makedirs(out_dir, exist_ok=True)
        for i in selected:
            img = compute_display(suv_imgs[i], vmin, vmax)
            extent, (x0, x1, y0, y1) = crop_around_center_mm(img, center_mm, fov, pixel_mm)

            f = plt.figure(figsize=(5,5))
            ax = f.add_subplot(111)
            ax.imshow(img, cmap=cmap, extent=extent, origin="upper", vmin=0, vmax=1)
            ax.set_aspect("equal")
            ax.set_xlim(x0, x1); ax.set_ylim(y1, y0)
            ax.axis("off")
            fname = os.path.join(out_dir, f"Slice_{i:03d}.png")
            f.savefig(fname, dpi=300, bbox_inches="tight", pad_inches=0)
            plt.close(f)
            INFO(f"Saved {fname}")
        messagebox.showinfo("Saved", f"Saved {len(selected)} slices to:\n{out_dir}")

    # Save current splash PNG
    def save_splash():
        fname = os.path.join(out_dir, "Splash.png")
        fig.savefig(fname, dpi=300, bbox_inches="tight")
        INFO(f"Saved splash → {fname}")
        messagebox.showinfo("Saved", f"Splash saved to:\n{fname}")

    # Buttons
    ttk.Button(root, text="Update View", command=render_splash).grid(row=3, column=0, padx=6, pady=10, sticky="w")
    ttk.Button(root, text="Save Selected Slices", command=save_slices).grid(row=3, column=1, padx=6, pady=10, sticky="w")
    ttk.Button(root, text="Save Splash", command=save_splash).grid(row=3, column=2, padx=6, pady=10, sticky="w")
    ttk.Button(root, text="Close", command=on_close).grid(row=3, column=5, padx=6, pady=10, sticky="e")

    # Layout stretch
    root.grid_rowconfigure(0, weight=1)
    for c in range(6):
        root.grid_columnconfigure(c, weight=1)

    # Initial draw
    render_splash()
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        ERROR(str(e))
