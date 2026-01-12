"""
detect_hot_cells_contrastbased.py
---------------------------------
Automatic detection of 25-mm and 16-mm ACR PET hot spheres
based on the known ~2.5× activity ratio relative to background.

Inputs
------
px_array : 2D PET slice (SUV-scaled)
pixel_size_mm : float
phantom_center : (x, y) in pixels
output_dir : directory to save debug overlay
debug : show overlay interactively (optional)

Outputs
-------
dict with:
    "25mm" : (x25, y25)
    "16mm" : (x16, y16)
    "bg_mean" : background mean SUV
    "thresh"  : applied threshold SUV
and an overlay image `hotcell_contrast_overlay.png`
"""

import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from scipy.ndimage import label
from skimage.measure import regionprops


def detect_hot_cells(px_array,
                                   pixel_size_mm,
                                   phantom_center,
                                   output_dir=".",
                                   debug=False):
    print("\n[HotCells] === Starting contrast-based detection ===")

    # --- Step 1: Background estimation ---
    h, w = px_array.shape
    cy, cx = phantom_center
    yy, xx = np.indices(px_array.shape)
    r_mm = np.sqrt((xx - cx)**2 + (yy - cy)**2) * pixel_size_mm
    bg_mask = (r_mm < 90)  # 90-mm circular ROI for background
    bg_vals = px_array[bg_mask]
    bg_mean = np.nanmean(bg_vals)
    bg_std = np.nanstd(bg_vals)
    print(f"[Step 1] Background mean SUV ≈ {bg_mean:.3f} (σ={bg_std:.3f})")

    # --- Step 2: High-intensity threshold ---
    thresh = bg_mean * 2.0
    mask = px_array >= thresh
    labeled, num = label(mask)
    print(f"[Step 2] Found {num} regions above threshold {thresh:.2f}")

    if num == 0:
        raise RuntimeError("No bright regions detected – check SUV scaling.")

    # --- Step 3: Evaluate regions ---
    props = regionprops(labeled, intensity_image=px_array)
    candidates = []
    for p in props:
        mean_intensity = p.mean_intensity
        rel_contrast = mean_intensity / bg_mean
        if 1.8 <= rel_contrast <= 3.2:
            candidates.append((p.area, p.centroid, mean_intensity, rel_contrast))
    print(f"[Step 3] {len(candidates)} candidates within expected 2.5× contrast window")

    if len(candidates) < 2:
        raise RuntimeError("Fewer than 2 valid hot-sphere candidates found.")

    # --- Step 4: Choose two largest by area (≈25 mm, 16 mm) ---
    candidates.sort(reverse=True)
    (a25, (y25, x25), i25, c25), (a16, (y16, x16), i16, c16) = candidates[:2]
    print(f"[Step 4] 25-mm sphere → (x={x25:.1f}, y={y25:.1f})  SUV={i25:.2f} (contrast {c25:.2f})")
    print(f"[Step 4] 16-mm sphere → (x={x16:.1f}, y={y16:.1f})  SUV={i16:.2f} (contrast {c16:.2f})")

    # --- Step 5: Save overlay ---
    try:
        os.makedirs(output_dir, exist_ok=True)
        fig, ax = plt.subplots(figsize=(8, 8))
        vmin, vmax = np.percentile(px_array, (1, 99))
        ax.imshow(px_array, cmap="gray", vmin=vmin, vmax=vmax)
        ax.plot(cx, cy, "r+", ms=12, mew=2)
        ax.text(cx + 10, cy, "Center", color="red", fontsize=9)

        for (x, y, label_txt, color) in [
            (x25, y25, "25 mm", "lime"),
            (x16, y16, "16 mm", "yellow")
        ]:
            ax.add_patch(
                patches.Circle(
                    (x, y),
                    radius=10 / pixel_size_mm,  # visual radius only
                    edgecolor=color,
                    facecolor="none",
                    lw=2,
                )
            )
            ax.text(x, y, label_txt, color=color, fontsize=10,
                    ha="center", va="center", weight="bold")

        ax.set_title("Contrast-Based Hot-Sphere Detection", fontsize=12)
        ax.set_axis_off()
        out_path = os.path.join(output_dir, "hotcell_contrast_overlay.png")
        fig.savefig(out_path, dpi=250, bbox_inches="tight")
        #plt.show()
        plt.close(fig)
        print(f"[HotCells] Saved overlay → {out_path}")
        if debug:
            plt.imshow(plt.imread(out_path))
            plt.show()
    except Exception as e:
        print(f"[HotCells Warning] Overlay generation failed: {e}")

    print("[HotCells] === Detection complete ===")
    return {
        "25mm": (float(x25), float(y25)),
        "16mm": (float(x16), float(y16)),
        "bg_mean": float(bg_mean),
        "thresh": float(thresh),
    }
