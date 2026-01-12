import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import pydicom
from find_phantom_center import find_phantom_center


import numpy as np
from scipy.ndimage import gaussian_filter
from numpy.fft import fft2, fftshift
from skimage.feature import peak_local_max

def refine_spatial_rois(image, initial_rois, pixel_spacing, roi_size_mm=15, search_radius_mm=3, debug=False):
    """
    Refine the center of each ACR spatial resolution ROI using local FFT orientation strength.

    Parameters
    ----------
    image : np.ndarray
        CT image (2D HU array)
    initial_rois : dict
        {lp_value: (x_init, y_init)} — initial guesses for each spatial frequency ROI.
    pixel_spacing : float
        Pixel size in mm.
    roi_size_mm : float, optional
        Side length of square ROI (default 15 mm per ACR spec).
    search_radius_mm : float, optional
        Search radius around initial guess to optimize center (default ±3 mm).
    debug : bool, optional
        If True, print intermediate results.

    Returns
    -------
    refined_rois : dict
        {lp_value: (x_refined, y_refined, orientation_deg, strength)}
    """

    refined_rois = {}
    roi_half_px = int((roi_size_mm / 2) / pixel_spacing)
    search_radius_px = int(search_radius_mm / pixel_spacing)

    rows, cols = image.shape

    for lp_val, (x0, y0) in initial_rois.items():
        best_score = 0
        best_center = (x0, y0)
        best_angle = 0

        # Search small region around initial guess
        for dy in range(-search_radius_px, search_radius_px + 1):
            for dx in range(-search_radius_px, search_radius_px + 1):
                yc, xc = int(y0 + dy), int(x0 + dx)

                y1, y2 = yc - roi_half_px, yc + roi_half_px
                x1, x2 = xc - roi_half_px, xc + roi_half_px
                if y1 < 0 or y2 >= rows or x1 < 0 or x2 >= cols:
                    continue

                patch = image[y1:y2, x1:x2]
                if patch.size == 0:
                    continue

                # Remove low frequencies
                patch_hp = patch - gaussian_filter(patch, sigma=2)

                # 2D FFT magnitude
                F = np.abs(fftshift(fft2(patch_hp)))
                F /= np.max(F)

                # Polar orientation histogram (0–180°)
                cy, cx = np.array(F.shape) // 2
                Y, X = np.indices(F.shape)
                angles = np.rad2deg(np.arctan2(Y - cy, X - cx))
                radial = np.sqrt((X - cx)**2 + (Y - cy)**2)
                mask = (radial > 3) & (radial < 0.4 * F.shape[0])
                angle_bins = np.linspace(-90, 90, 180)
                orientation_strength = [
                    np.mean(F[(angles >= a) & (angles < a + 1) & mask])
                    for a in angle_bins
                ]

                dominant_idx = int(np.argmax(orientation_strength))
                dominant_angle = angle_bins[dominant_idx]
                strength = orientation_strength[dominant_idx]

                if strength > best_score:
                    best_score = strength
                    best_center = (xc, yc)
                    best_angle = dominant_angle

        refined_rois[lp_val] = (*best_center, best_angle, best_score)

        if debug:
            print(f"{lp_val} lp/cm refined → ({best_center[0]:.1f}, {best_center[1]:.1f}), "
                  f"angle={best_angle:.1f}°, strength={best_score:.3f}")

    return refined_rois


# -----------------------------------------------------------------
# Spatial Resolution (High Contrast) Module
# -----------------------------------------------------------------
def run_spatial_resolution_analysis():
    """
    Automatic ACR CT Spatial Resolution (High-Contrast) analysis.
    Adds 45° rotated 15 mm ROIs, improved FFT stability, and fixed WL/WW.
    """
    import os
    import numpy as np
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Circle
    import pydicom
    from find_phantom_center import find_phantom_center

    # --- Hardcoded paths ---
    dcm_path = r"C:\Users\RyanByrd\OneDrive - ONE Physics\Desktop\2_ACR ABDOMEN 300 Br40 S3 ax\25275465.dcm"
    output_dir = os.path.join(os.path.dirname(dcm_path), "CT_Output")
    os.makedirs(output_dir, exist_ok=True)

    # --- Load DICOM ---
    ds = pydicom.dcmread(dcm_path)
    px = ds.pixel_array.astype(np.float32) * float(ds.RescaleSlope) + float(ds.RescaleIntercept)
    pixel_spacing = np.mean(ds.PixelSpacing)

    # --- Find phantom center ---
    cy, cx, r = find_phantom_center(px, pixel_spacing)

    # --- Fixed ACR window/level ---
    WL, WW = 1100, 100
    vmin, vmax = WL - WW / 2, WL + WW / 2
    px_disp = np.clip(px, vmin, vmax)
    px_disp = (px_disp - vmin) / (vmax - vmin)

    # --- Initial ROI layout (approximate) ---
    offset_mm = 71
    lp_values = [12, 10, 9, 8, 7, 6, 5, 4]
    angles_deg = [90, 45, 0, -45, -90, -135, 180, 135]
    offset_px = offset_mm / pixel_spacing

    initial_rois = {}
    for lp, ang in zip(lp_values, angles_deg):
        theta = np.deg2rad(ang)
        x_guess = cx + offset_px * np.cos(theta)
        y_guess = cy - offset_px * np.sin(theta)
        initial_rois[lp] = (x_guess, y_guess)

    # --- Refine positions (wider window improves FFT detection) ---
    refined = refine_spatial_rois(px, initial_rois, pixel_spacing,
                                  roi_size_mm=20, search_radius_mm=5, debug=True)

    # --- Draw overlay ---
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(px_disp, cmap="gray", origin="upper")
    ax.add_patch(Circle((cx, cy), r, edgecolor="lime", facecolor="none", lw=1.2))
    ax.plot(cx, cy, "rx", ms=8, mew=2)

    roi_half = 6.5 / pixel_spacing  # 15 mm square half-width

    for lp, (x, y, angle, strength) in refined.items():
        # Draw rotated square ROI (45°)
        rect = Rectangle(
            (x - roi_half, y - roi_half),
            2 * roi_half,
            2 * roi_half,
            linewidth=1.5,
            edgecolor="coral",
            facecolor="none",
            angle=45,  # <-- rotate to match phantom alignment
            rotation_point="center",
        )
        ax.add_patch(rect)
        ax.text(
            x,
            y - (roi_half + 5),
            f"{lp} lp/cm\n({strength:.2f})",
            color="gold",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )

    ax.set_title("ACR CT Spatial Resolution (WW=100 WL=1100)", fontsize=13)
    ax.axis("off")

    overlay_path = os.path.join(output_dir, "SpatialResolution_WL1100_WW100_Overlay.png")
    fig.savefig(overlay_path, dpi=250, bbox_inches="tight")
    plt.close(fig)

    print(f"\n✅ Overlay saved to: {overlay_path}")



# -----------------------------------------------------------------
# Run module
# -----------------------------------------------------------------
if __name__ == "__main__":
    run_spatial_resolution_analysis()
