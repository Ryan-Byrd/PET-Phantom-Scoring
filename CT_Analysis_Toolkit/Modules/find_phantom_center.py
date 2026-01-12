import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter, label, center_of_mass
from skimage import exposure, filters, morphology, measure
from scipy import ndimage

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

    # Step 4: Compute center of mass and equivalent circular radius
    cy, cx = center_of_mass(phantom_mask)
    area_px = np.sum(phantom_mask)
    radius_px = np.sqrt(area_px / np.pi)

    # Step 5: Optional debug plot
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
):
    """
    Robust phantom center detection across CT, PET, MR, etc.
    Adjusts preprocessing based on modality characteristics.
    """


    img = px.astype(np.float32)

    # ---- Modality-specific normalization ----
    if modality.upper() == "CT":
        img = exposure.rescale_intensity(img, in_range=(-1000, 2000))
    elif modality.upper() in ("PET", "SPECT"):
        # hot-object modality: compress with log scaling
        img = np.log1p(np.maximum(img, 0))
        img = exposure.rescale_intensity(img)
    elif modality.upper() == "MR":
        # arbitrary intensity, normalize to 0–1
        img = exposure.rescale_intensity(img, in_range=(np.percentile(img, 2), np.percentile(img, 98)))
    elif modality.upper() in ("XRAY", "FLUORO"):
        # typically darker phantom on bright background
        img = 1.0 - exposure.rescale_intensity(img)
    else:
        # default generic normalization
        img = exposure.rescale_intensity(img, in_range=(np.percentile(img, 1), np.percentile(img, 99)))

    # ---- Denoise ----
    blurred = gaussian_filter(img, sigma=2)

    # ---- Edge or threshold segmentation ----
    if modality.upper() in ("CT", "XRAY", "FLUORO"):
        edges = filters.sobel(blurred)
        mask = edges > np.percentile(edges, 90)
    else:
        # for PET/MR use adaptive threshold instead of edges
        thresh = filters.threshold_otsu(blurred)
        mask = blurred > thresh

    # ---- Morphological cleanup ----
    mask = morphology.binary_closing(mask, morphology.disk(5))
    from scipy import ndimage
    mask = ndimage.binary_fill_holes(mask)

    # ---- Label & choose largest connected component ----
    labels = measure.label(mask)
    props = measure.regionprops(labels)
    if not props:
        raise RuntimeError("No phantom-like region found.")
    best = max(props, key=lambda r: r.area)
    cy, cx = best.centroid
    radius_px = np.sqrt(best.area / np.pi)
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

    return cy, cx, radius_px