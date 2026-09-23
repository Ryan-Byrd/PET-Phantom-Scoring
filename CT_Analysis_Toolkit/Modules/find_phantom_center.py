import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter, label, center_of_mass
from skimage import exposure, filters, morphology, measure
from skimage.transform import hough_circle, hough_circle_peaks
from scipy import ndimage


def _fit_circle_least_squares(points_yx: np.ndarray):
    """
    Fit a circle to (y, x) boundary points using linear least squares.

    Returns
    -------
    cy, cx, radius_px : tuple[float, float, float] | None
        Fitted center and radius in pixels, or None if fitting is ill-conditioned.
    """
    if points_yx is None or len(points_yx) < 3:
        return None

    y = points_yx[:, 0].astype(np.float64)
    x = points_yx[:, 1].astype(np.float64)

    # Linearized circle model: x^2 + y^2 = 2*cx*x + 2*cy*y + c
    a_mat = np.column_stack((2.0 * x, 2.0 * y, np.ones_like(x)))
    b_vec = x * x + y * y

    try:
        sol, *_ = np.linalg.lstsq(a_mat, b_vec, rcond=None)
    except np.linalg.LinAlgError:
        return None

    cx, cy, c0 = sol
    rad_sq = c0 + cx * cx + cy * cy
    if not np.isfinite(rad_sq) or rad_sq <= 0:
        return None

    radius_px = float(np.sqrt(rad_sq))
    return float(cy), float(cx), radius_px


def _largest_subpixel_contour(mask: np.ndarray):
    """
    Extract the longest subpixel contour from a binary mask.

    Using a 0.5 isocontour yields boundary coordinates with subpixel precision.
    """
    contours = measure.find_contours(mask.astype(np.float32), level=0.5)
    if not contours:
        return None
    return max(contours, key=lambda c: len(c))


def _fit_circle_hough(phantom_mask: np.ndarray, approx_radius_px: float):
    """
    Fit a circle to a binary phantom mask using Circle Hough Transform.

    The radius search is constrained around the region-derived radius so the
    transform remains stable and conservative for near-circular phantom masks.
    """
    if phantom_mask is None or phantom_mask.size == 0:
        return None

    approx_radius_px = float(approx_radius_px)
    if not np.isfinite(approx_radius_px) or approx_radius_px <= 0:
        return None

    edge_mask = np.logical_xor(phantom_mask, ndimage.binary_erosion(phantom_mask))
    if not np.any(edge_mask):
        return None

    radius_half_span = max(4, int(round(approx_radius_px * 0.20)))
    radius_min = max(3, int(np.floor(approx_radius_px)) - radius_half_span)
    radius_max = int(np.ceil(approx_radius_px)) + radius_half_span
    hough_radii = np.arange(radius_min, radius_max + 1, dtype=int)
    if hough_radii.size == 0:
        return None

    try:
        hough_res = hough_circle(edge_mask.astype(np.uint8), hough_radii)
        accums, cxs, cys, radii = hough_circle_peaks(
            hough_res,
            hough_radii,
            total_num_peaks=1,
        )
    except Exception:
        return None

    if len(cxs) == 0 or len(cys) == 0 or len(radii) == 0:
        return None

    return float(cys[0]), float(cxs[0]), float(radii[0])


def _refine_center_with_subpixel_circle(phantom_mask: np.ndarray, fallback_cy: float, fallback_cx: float, fallback_radius_px: float):
    """
    Refine center/radius from a Circle Hough Transform fit, with safe fallback.

    If the Hough fit fails, fall back to the previous contour least-squares fit,
    and then finally to the region-derived center/radius.
    """
    fit = _fit_circle_hough(phantom_mask, fallback_radius_px)
    if fit is not None:
        return *fit, "Circle Hough transform"

    contour = _largest_subpixel_contour(phantom_mask)
    fit = _fit_circle_least_squares(contour) if contour is not None else None
    if fit is not None:
        return *fit, "subpixel contour least-squares circle fit"

    return fallback_cy, fallback_cx, fallback_radius_px, "largest-component centroid and area-equivalent radius"

def find_phantom_center(image: np.ndarray, pixel_size_mm: float, debug: bool = False):
    """
    Automatically locate phantom center using intensity thresholding and centroid detection.

    Parameters
    ----------
    image : np.ndarray
        2D image array (HU or grayscale).
    pixel_size_mm : float
        Pixel spacing in mm (used only for scale reference).
    debug : bool
        If True, displays an overlay of the detected center and boundary.

    Returns
    -------
    cy, cx, radius_px : tuple[float, float, float]
        Center coordinates (y, x) and estimated phantom radius in pixels.
    """
    # Step 1: Apply Gaussian smoothing to reduce noise
    blurred = gaussian_filter(image, sigma=2.0)

    # Step 2: Use fixed HU threshold to separate phantom body from air
    threshold = -300  # Typical air-to-water HU cutoff
    mask = blurred > threshold

    labeled, num = label(mask)
    if num == 0:
        raise RuntimeError("No phantom region detected in image.")

    # Step 3: Find the largest connected region — assume it's the phantom
    sizes = np.bincount(labeled.ravel())
    sizes[0] = 0
    phantom_label = np.argmax(sizes)
    phantom_mask = labeled == phantom_label

    # Step 4: Compute baseline center/radius from region geometry
    cy, cx = center_of_mass(phantom_mask)
    area_px = np.sum(phantom_mask)
    radius_px = np.sqrt(area_px / np.pi)

    # Step 5: Subpixel refinement by fitting a circle to the 0.5 isocontour.
    cy, cx, radius_px, _ = _refine_center_with_subpixel_circle(
        phantom_mask,
        fallback_cy=float(cy),
        fallback_cx=float(cx),
        fallback_radius_px=float(radius_px),
    )

    # Step 6: Optional debug plot
    if debug:
        fig, ax = plt.subplots(figsize=(7, 7))
        ax.imshow(image, cmap="gray", vmin=-1000, vmax=1000)
        circ = plt.Circle((cx, cy), radius_px, edgecolor="lime", facecolor="none", lw=2)
        ax.add_patch(circ)
        ax.plot(cx, cy, "rx", ms=10, mew=2)
        ax.set_title("Detected Phantom Center")
        plt.show()

    return cy, cx, radius_px

def find_phantom_center_generalized(
    px: np.ndarray,
    pixel_size_mm: float | None = None,
    modality: str = "CT",
    debug: bool = False,
    return_details: bool = False,
):
    """
    Robust phantom center detection across CT, PET, MR, etc.
    Adjusts preprocessing based on modality characteristics and fits on the
    native image grid.

    When ``return_details`` is true, also returns a dictionary describing the
    normalization, segmentation, and circle-fit method used for traceability.
    """


    img = px.astype(np.float32)

    # ---- Modality-specific normalization ----
    normalized_modality = modality.upper()
    if normalized_modality == "CT":
        img = exposure.rescale_intensity(img, in_range=(-1000, 2000))
        normalization_method = "CT intensity rescaling (-1000 to 2000)"
    elif normalized_modality in ("PET", "SPECT"):
        # hot-object modality: compress with log scaling
        img = np.log1p(np.maximum(img, 0))
        img = exposure.rescale_intensity(img)
        normalization_method = "log intensity scaling followed by rescaling"
    elif normalized_modality == "MR":
        # arbitrary intensity, normalize to 0–1
        img = exposure.rescale_intensity(img, in_range=(np.percentile(img, 2), np.percentile(img, 98)))
        normalization_method = "MR percentile rescaling (2nd to 98th)"
    elif normalized_modality in ("XRAY", "FLUORO"):
        # typically darker phantom on bright background
        img = 1.0 - exposure.rescale_intensity(img)
        normalization_method = "inverted intensity rescaling"
    else:
        # default generic normalization
        img = exposure.rescale_intensity(img, in_range=(np.percentile(img, 1), np.percentile(img, 99)))
        normalization_method = "generic percentile rescaling (1st to 99th)"

    blurred = gaussian_filter(img, sigma=2)

    # ---- Edge or threshold segmentation ----
    if normalized_modality in ("CT", "XRAY", "FLUORO"):
        edges = filters.sobel(blurred)
        mask = edges > np.percentile(edges, 90)
        segmentation_method = "Sobel edges above the 90th percentile"
    else:
        # for PET/MR use adaptive threshold instead of edges
        thresh = filters.threshold_otsu(blurred)
        mask = blurred > thresh
        segmentation_method = "Otsu intensity threshold"

    # ---- Morphological cleanup ----
    mask = morphology.closing(mask, morphology.disk(5))
    mask = ndimage.binary_fill_holes(mask)

    # ---- Label & choose largest connected component ----
    labels = measure.label(mask)
    props = measure.regionprops(labels)
    if not props:
        raise RuntimeError("No phantom-like region found.")
    best = max(props, key=lambda r: r.area)
    cy, cx = best.centroid
    radius_px = np.sqrt(best.area / np.pi)

    # Subpixel refinement from contour-based circle fit on selected component.
    best_mask = labels == best.label
    fit_cy, fit_cx, fit_radius_px, circle_fit_method = _refine_center_with_subpixel_circle(
        best_mask,
        fallback_cy=float(cy),
        fallback_cx=float(cx),
        fallback_radius_px=float(radius_px),
    )
    cy, cx, radius_px = fit_cy, fit_cx, fit_radius_px
    details = {
        "modality": normalized_modality,
        "normalization_method": normalization_method,
        "segmentation_method": segmentation_method,
        "circle_fit_method": circle_fit_method,
        "circle_fit_scale": 1,
        "circle_fit_pixel_size_mm": pixel_size_mm,
    }
    """
    if debug:
        fig, ax = plt.subplots()
        ax.imshow(img, cmap="gray")
        ax.plot(cx, cy, "rx")
        circ = plt.Circle((cx, cy), radius_px, edgecolor="lime", fill=False)
        ax.add_patch(circ)
        ax.set_title(f"{modality} phantom center detection")
        #plt.show()
    """


    print(f"[Center-{modality}] y={cy:.1f}, x={cx:.1f}, radius={radius_px:.1f}px")
    if pixel_size_mm:
        print(f"   ≈ {radius_px * pixel_size_mm:.1f} mm")
    if debug:
        print(f"   normalization: {normalization_method}")
        print(f"   segmentation: {segmentation_method}")
        print(f"   circle fit: {circle_fit_method}")

    if return_details:
        return cy, cx, radius_px, details
    return cy, cx, radius_px