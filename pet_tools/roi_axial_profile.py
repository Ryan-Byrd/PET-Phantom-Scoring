# -*- coding: utf-8 -*-
"""
ROI Axial Profile — Extract center ROI values across axial slices and plot intensity profiles.

Purpose
-------
Extract a region of interest (ROI) at the center of each image slice for both series
and plot the mean/median intensity values across all slices (z-axis).
This provides an intensity profile showing how values vary through the anatomy.

Features
--------
- Define circular or square ROI at image center
- Extract ROI statistics (mean, median, std) for each slice
- Plot intensity profiles for both series on a single graph
- Compute differential ROI profiles $d(ROI)/dz$ for both series
- Export profile data as CSV and plots as PNG
- Optional debug output: ROI visualization on sample slices
- Support for custom ROI size and statistics

Usage
-----
    python roi_axial_profile.py --series1 /path/to/series1 --series2 /path/to/series2
    python roi_axial_profile.py --series1 s1 --series2 s2 --roi-radius 50 --output profiles
    python roi_axial_profile.py --series1 s1 --series2 s2 --roi-type square --roi-size 100

Inputs
------
series1_dir, series2_dir : str
    Paths to DICOM series folders.
roi_type : str, optional
    'circle' (default) or 'square' for ROI shape.
roi_radius : int, optional
    Radius in pixels for circular ROI (default: 50).
roi_size : int, optional
    Width/height in pixels for square ROI (default: 100).
statistic : str, optional
    'mean' (default), 'median', or 'std' to extract from ROI.
output_dir : str, optional
    Directory to save CSV and plots (default: "roi_profiles").
debug : str, optional
    Save debug artifacts (ROI visualization) to this directory.

Outputs
-------
roi_profile_data.csv : data/
    CSV with columns: slice_index, z_position, series1_value, series2_value,
    series1_differential, series2_differential
profile_comparison.png : images/
    Line plot comparing intensity profiles of both series and their differentials.
Debug artifacts (if --debug): debug_dir/
    - roi_visualization_NNN.png: Sample slices with ROI overlaid

Assumptions
-----------
1. Both series have the same FOV (centered anatomy).
2. Center of image is at approximately (rows/2, columns/2).
3. ROI size is small enough to fit within image dimensions.

Mathematical Notes
-------------------
**ROI Definition (Circular):**
  For each pixel (i, j) in image, include in ROI if:
    distance = sqrt((i - center_i)^2 + (j - center_j)^2)
    included = (distance <= radius)

**ROI Definition (Square):**
  For each pixel (i, j), include if:
    i_min <= i <= i_max  AND  j_min <= j <= j_max
  where bounds are computed from center and ROI size.

**Profile Extraction:**
  For each slice k and statistic S:
    profile[k] = S(pixels in ROI for slice k)
  
  Common statistics:
    mean = sum(ROI) / count(ROI)
    median = middle value of sorted ROI pixels
    std = sqrt(sum((pixel - mean)^2) / count(ROI))

**Differential Profile:**
    The differential profile is computed as a numerical derivative with respect
    to $z$:
        $\\frac{d\\,ROI}{dz} \\approx \\frac{ROI_{k+1} - ROI_{k-1}}{z_{k+1} - z_{k-1}}$
    The implementation uses a centered finite difference via `numpy.gradient`.

"""

import os
import sys
import argparse
import json
import csv
import glob
from pathlib import Path
from typing import Tuple, List, Dict, Optional, Any

import numpy as np
import pydicom
from pydicom.dataset import Dataset
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from scipy.ndimage import zoom
from scipy.signal import find_peaks
from scipy.interpolate import interp1d


# Color codes for logging
def _c(code):
    return f"\033[{code}m"

CLR = {
    "reset": _c("0"),
    "cyan": _c("36"),
    "yellow": _c("33"),
    "red": _c("31"),
    "green": _c("32"),
}


def INFO(m):
    print(f"{CLR['cyan']}[INFO]{CLR['reset']} {m}")


def WARN(m):
    print(f"{CLR['yellow']}[WARN]{CLR['reset']} {m}")


def ERROR(m):
    print(f"{CLR['red']}[ERROR]{CLR['reset']} {m}", file=sys.stderr)


def SUCCESS(m):
    print(f"{CLR['green']}[OK]{CLR['reset']} {m}")


# ============================================================================
# Axial FWHM Computation
# ============================================================================

def compute_axial_fwhm(z: np.ndarray, profile: np.ndarray, mode: str) -> Dict[str, float]:
    """
    Compute axial Full Width at Half Maximum (FWHM) for PET or CT slab profile.
    
    This function is used for Z-axis coregistration analysis in PET/CT QA.
    It measures the axial extent of a phantom slab by finding where the profile
    crosses a threshold value (half-maximum for PET, half-value for CT).
    
    Parameters
    ----------
    z : np.ndarray
        1D array of slice positions in mm (monotonic, contiguous).
    profile : np.ndarray
        1D array of ROI mean values corresponding to each z position.
    mode : str
        Either "pet" or "ct" to determine threshold calculation method.
    
    Returns
    -------
    results : Dict[str, float]
        Dictionary containing:
        - fwhm_mm: Full width at half maximum in mm
        - z_left_mm: Left crossing position in mm
        - z_right_mm: Right crossing position in mm
        - z_mid_mm: Midpoint position (z_left + z_right) / 2 in mm
    
    Raises
    ------
    ValueError
        If z and profile have different lengths, mode is invalid, or crossings
        cannot be found.
    
    Notes
    -----
    **Threshold Calculation:**
    
    - PET mode: plateau = mean of central 20% of profile; half-max = plateau / 2
    - CT mode: acrylic = mean of highest 20%; water = mean of lowest 20%;
      half-value = (acrylic + water) / 2
    
    **Algorithm:**
    
    1. Linearly interpolate profile to fine grid (0.1 mm spacing)
    2. Compute threshold based on mode
    3. Find first crossing from left (z_left)
    4. Find first crossing from right (z_right)
    5. Compute FWHM = z_right - z_left
    
    The function uses linear interpolation only (no cubic) to avoid overshoot
    artifacts at sharp edges.
    """
    # Validate inputs
    z = np.asarray(z, dtype=np.float64)
    profile = np.asarray(profile, dtype=np.float64)
    
    if len(z) != len(profile):
        raise ValueError(f"z and profile must have same length: {len(z)} vs {len(profile)}")
    
    if len(z) < 3:
        raise ValueError(f"Need at least 3 points for interpolation, got {len(z)}")
    
    mode = mode.lower()
    if mode not in {"pet", "ct"}:
        raise ValueError(f"mode must be 'pet' or 'ct', got '{mode}'")
    
    # Infer slice spacing and create fine grid
    z_spacing = np.mean(np.diff(z))
    fine_spacing = min(0.1, z_spacing / 10.0)  # At least 10x finer
    z_fine = np.arange(z.min(), z.max() + fine_spacing, fine_spacing)
    
    # Linear interpolation to fine grid
    interpolator = interp1d(z, profile, kind='linear', bounds_error=False, fill_value='extrapolate')
    profile_fine = interpolator(z_fine)
    
    # Determine half-maximum threshold based on mode
    if mode == "pet":
        # PET: plateau is mean of central 20%
        n = len(profile_fine)
        center_start = int(n * 0.4)
        center_end = int(n * 0.6)
        plateau = np.mean(profile_fine[center_start:center_end])
        threshold = plateau / 2.0
    else:  # mode == "ct"
        # CT: half-value between acrylic (highest 20%) and water (lowest 20%)
        sorted_vals = np.sort(profile_fine)
        n = len(sorted_vals)
        n_20pct = max(1, int(n * 0.2))
        water = np.mean(sorted_vals[:n_20pct])
        acrylic = np.mean(sorted_vals[-n_20pct:])
        threshold = (acrylic + water) / 2.0
    
    # Find left crossing (first point above threshold)
    above_threshold = profile_fine > threshold
    if not np.any(above_threshold):
        raise ValueError(f"No points above threshold {threshold:.2f} (mode={mode})")
    
    idx_left_region = np.where(above_threshold)[0][0]
    if idx_left_region == 0:
        z_left = z_fine[0]
    else:
        # Linear interpolation between points straddling threshold
        idx_before = idx_left_region - 1
        idx_after = idx_left_region
        z_before = z_fine[idx_before]
        z_after = z_fine[idx_after]
        val_before = profile_fine[idx_before]
        val_after = profile_fine[idx_after]
        
        # Linear interpolation: z = z_before + (threshold - val_before) * (z_after - z_before) / (val_after - val_before)
        frac = (threshold - val_before) / (val_after - val_before + 1e-12)
        z_left = z_before + frac * (z_after - z_before)
    
    # Find right crossing (last point above threshold)
    idx_right_region = np.where(above_threshold)[0][-1]
    if idx_right_region == len(z_fine) - 1:
        z_right = z_fine[-1]
    else:
        # Linear interpolation between points straddling threshold
        idx_before = idx_right_region
        idx_after = idx_right_region + 1
        z_before = z_fine[idx_before]
        z_after = z_fine[idx_after]
        val_before = profile_fine[idx_before]
        val_after = profile_fine[idx_after]
        
        frac = (threshold - val_before) / (val_after - val_before + 1e-12)
        z_right = z_before + frac * (z_after - z_before)
    
    # Compute FWHM and midpoint
    fwhm_mm = z_right - z_left
    z_mid_mm = (z_left + z_right) / 2.0
    
    if fwhm_mm <= 0:
        raise ValueError(f"Invalid FWHM: {fwhm_mm:.2f} mm (z_left={z_left:.2f}, z_right={z_right:.2f})")
    
    return {
        "fwhm_mm": float(fwhm_mm),
        "z_left_mm": float(z_left),
        "z_right_mm": float(z_right),
        "z_mid_mm": float(z_mid_mm),
    }


# ============================================================================
# DICOM Utilities (shared with dual_series_overlay)
# ============================================================================

def load_dicom_series(series_dir: str, debug: bool = False) -> Tuple[List[Dataset], Dict[str, Any]]:
    """
    Load all DICOM files from a directory and sort by slice location.
    
    Parameters
    ----------
    series_dir : str
        Directory containing DICOM files.
    debug : bool
        If True, print diagnostic info during loading.
    
    Returns
    -------
    datasets : List[pydicom.dataset.Dataset]
        List of DICOM datasets sorted by z-coordinate.
    metadata : Dict[str, Any]
        Series metadata: rows, columns, pixel spacing, slice positions.
    """
    dicom_files = sorted(glob.glob(os.path.join(series_dir, "*.dcm")))
    if not dicom_files:
        raise ValueError(f"No DICOM files found in {series_dir}")
    
    datasets = []
    z_positions = []
    
    for dcm_file in dicom_files:
        try:
            ds = pydicom.dcmread(dcm_file, stop_before_pixels=False)
            datasets.append(ds)
            
            # Extract z-coordinate (slice location)
            if hasattr(ds, "SliceLocation"):
                z = float(ds.SliceLocation)
            elif hasattr(ds, "ImagePositionPatient"):
                z = float(ds.ImagePositionPatient[2])
            else:
                raise ValueError(f"No SliceLocation or ImagePositionPatient in {dcm_file}")
            
            z_positions.append(z)
        except Exception as e:
            WARN(f"Failed to load {dcm_file}: {e}")
            continue
    
    if not datasets:
        raise ValueError(f"No valid DICOM files in {series_dir}")
    
    # Sort by z-coordinate
    sorted_indices = np.argsort(z_positions)
    datasets = [datasets[i] for i in sorted_indices]
    z_positions = [z_positions[i] for i in sorted_indices]
    
    # Extract geometry from first slice
    ds0 = datasets[0]
    rows = int(ds0.Rows)
    columns = int(ds0.Columns)
    pixel_spacing = [float(x) for x in ds0.PixelSpacing]
    
    metadata = {
        "rows": rows,
        "columns": columns,
        "pixel_spacing": pixel_spacing,
        "z_positions": z_positions,
        "num_slices": len(datasets),
    }
    
    if debug:
        INFO(f"Loaded {len(datasets)} slices from {series_dir}")
        INFO(f"  Dimensions: {rows} × {columns} pixels")
        INFO(f"  Pixel spacing: {pixel_spacing[0]:.3f} × {pixel_spacing[1]:.3f} mm")
        INFO(f"  Z range: {z_positions[0]:.2f} to {z_positions[-1]:.2f} mm")
    
    return datasets, metadata


def extract_pixel_array(ds: Dataset, debug: bool = False) -> np.ndarray:
    """
    Extract and scale pixel array from DICOM dataset.
    
    Applies RescaleSlope and RescaleIntercept if present.
    """
    arr = ds.pixel_array.astype(np.float32)
    
    if hasattr(ds, "RescaleSlope") and hasattr(ds, "RescaleIntercept"):
        slope = float(ds.RescaleSlope)
        intercept = float(ds.RescaleIntercept)
        arr = arr * slope + intercept
    
    return arr


# ============================================================================
# ROI Utilities
# ============================================================================

def create_circular_roi_mask(rows: int, columns: int, radius: int) -> np.ndarray:
    """
    Create a circular ROI mask centered at image center.
    
    Parameters
    ----------
    rows, columns : int
        Image dimensions.
    radius : int
        ROI radius in pixels.
    
    Returns
    -------
    mask : np.ndarray
        Boolean mask where True indicates pixels inside ROI.
    """
    center_i = rows / 2.0
    center_j = columns / 2.0
    
    i, j = np.ogrid[:rows, :columns]
    distance = np.sqrt((i - center_i) ** 2 + (j - center_j) ** 2)
    mask = distance <= radius
    
    return mask


def create_square_roi_mask(rows: int, columns: int, size: int) -> np.ndarray:
    """
    Create a square ROI mask centered at image center.
    
    Parameters
    ----------
    rows, columns : int
        Image dimensions.
    size : int
        ROI width/height in pixels (should be odd for perfect centering).
    
    Returns
    -------
    mask : np.ndarray
        Boolean mask where True indicates pixels inside ROI.
    """
    center_i = rows / 2.0
    center_j = columns / 2.0
    half_size = size / 2.0
    
    i_min = int(np.ceil(center_i - half_size))
    i_max = int(np.floor(center_i + half_size))
    j_min = int(np.ceil(center_j - half_size))
    j_max = int(np.floor(center_j + half_size))
    
    mask = np.zeros((rows, columns), dtype=bool)
    mask[i_min:i_max+1, j_min:j_max+1] = True
    
    return mask


def extract_roi_statistic(image: np.ndarray, mask: np.ndarray, statistic: str = "mean") -> float:
    """
    Extract a statistic from ROI-masked image.
    
    Parameters
    ----------
    image : np.ndarray
        2D image array.
    mask : np.ndarray
        Boolean mask.
    statistic : str
        'mean', 'median', or 'std'.
    
    Returns
    -------
    value : float
        Statistic value from ROI.
    """
    roi_values = image[mask]
    
    if statistic == "mean":
        return float(np.mean(roi_values))
    elif statistic == "median":
        return float(np.median(roi_values))
    elif statistic == "std":
        return float(np.std(roi_values))
    else:
        raise ValueError(f"Unknown statistic: {statistic}")


# ============================================================================
# Profile Analysis
# ============================================================================

class ROIAxisProfileAnalyzer:
    """
    Extract and analyze ROI intensity profiles across axial slices.
    """
    
    def __init__(
        self,
        datasets1: List[Dataset],
        datasets2: List[Dataset],
        metadata1: Dict[str, Any],
        metadata2: Dict[str, Any],
        roi_type: str = "circle",
        roi_radius: Optional[int] = None,
        roi_size: Optional[int] = None,
        statistic: str = "mean",
        output_dir: str = "roi_profiles",
        debug_dir: Optional[str] = None,
    ):
        """
        Initialize analyzer.
        
        Parameters
        ----------
        datasets1, datasets2 : List[pydicom.dataset.Dataset]
            DICOM datasets for each series.
        metadata1, metadata2 : Dict[str, Any]
            Series metadata.
        roi_type : str
            'circle' or 'square'.
        roi_radius : int, optional
            Radius for circular ROI (default: 50 pixels).
        roi_size : int, optional
            Size for square ROI (default: 100 pixels).
        statistic : str
            'mean', 'median', or 'std'.
        output_dir : str
            Directory for output files.
        debug_dir : str, optional
            Directory for debug artifacts.
        """
        self.datasets1 = datasets1
        self.datasets2 = datasets2
        self.metadata1 = metadata1
        self.metadata2 = metadata2
        self.roi_type = roi_type
        self.statistic = statistic
        self.output_dir = output_dir
        self.debug_dir = debug_dir
        
        os.makedirs(output_dir, exist_ok=True)
        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
        
        # Set default ROI parameters
        if roi_radius is None:
            roi_radius = 50
        if roi_size is None:
            roi_size = 100
        self.roi_radius = roi_radius
        self.roi_size = roi_size
        
        # Create ROI masks
        INFO(f"Creating {roi_type} ROI (radius={roi_radius}, size={roi_size})...")
        self.mask1 = self._create_roi_mask(metadata1["rows"], metadata1["columns"])
        self.mask2 = self._create_roi_mask(metadata2["rows"], metadata2["columns"])
        SUCCESS("ROI masks created")
        
        # Load and extract pixel arrays
        INFO("Loading pixel arrays and extracting ROI profiles...")
        self.arrays1 = [extract_pixel_array(ds) for ds in datasets1]
        self.arrays2 = [extract_pixel_array(ds) for ds in datasets2]
        
        # Handle dimension mismatch (resample if needed)
        shape1 = self.arrays1[0].shape
        shape2 = self.arrays2[0].shape
        if shape1 != shape2:
            INFO(f"Dimension mismatch: Series 1 {shape1} vs Series 2 {shape2}")
            INFO(f"Resampling Series 2 to match Series 1 dimensions...")
            zoom_factors = (shape1[0] / shape2[0], shape1[1] / shape2[1])
            self.arrays2 = [zoom(arr, zoom_factors, order=1) for arr in self.arrays2]
            # Recreate mask for resampled series
            self.mask2 = self._create_roi_mask(shape1[0], shape1[1])
        
        # Extract profiles
        self.profile1 = self._extract_profile(self.arrays1, self.mask1)
        self.profile2 = self._extract_profile(self.arrays2, self.mask2)
        SUCCESS("Profiles extracted")
        
        # Z-coordinates for both series (use series 1 as reference)
        self.z_positions = metadata1["z_positions"]

        # Differential profiles (dROI/dz)
        self.diff_profile1 = self._compute_differential(self.profile1, self.z_positions)
        self.diff_profile2 = self._compute_differential(self.profile2, self.z_positions)

        # Peak detection (modality-aware) - use differential profiles
        self.series1_modality = self._get_modality(self.datasets1)
        self.series2_modality = self._get_modality(self.datasets2)
        self.expected_peaks1 = self._expected_peak_count(self.series1_modality, fallback=2)
        self.expected_peaks2 = self._expected_peak_count(self.series2_modality, fallback=4)
        self.peaks1 = self._find_profile_peaks(self.diff_profile1, self.expected_peaks1)
        self.peaks2 = self._find_profile_peaks(self.diff_profile2, self.expected_peaks2)
        
        # Compute FWHM for both series
        self.fwhm1 = self._compute_fwhm(self.series1_modality, self.profile1)
        self.fwhm2 = self._compute_fwhm(self.series2_modality, self.profile2)
        
        # Save peak and FWHM summary
        self._save_peak_summary()
    
    def _create_roi_mask(self, rows: int, columns: int) -> np.ndarray:
        """Create ROI mask based on roi_type."""
        if self.roi_type == "circle":
            return create_circular_roi_mask(rows, columns, self.roi_radius)
        elif self.roi_type == "square":
            return create_square_roi_mask(rows, columns, self.roi_size)
        else:
            raise ValueError(f"Unknown roi_type: {self.roi_type}")
    
    def _extract_profile(self, arrays: List[np.ndarray], mask: np.ndarray) -> np.ndarray:
        """Extract statistic values across all slices."""
        profile = []
        for arr in arrays:
            value = extract_roi_statistic(arr, mask, self.statistic)
            profile.append(value)
        return np.array(profile)

    def _compute_differential(self, profile: np.ndarray, z_positions: List[float]) -> np.ndarray:
        """Compute numerical derivative d(profile)/dz with respect to z (mm)."""
        z = np.asarray(z_positions, dtype=np.float64)
        if len(profile) != len(z):
            raise ValueError("Profile length does not match z_positions length")
        return np.gradient(profile, z)
    
    def _get_modality(self, datasets: List[Dataset]) -> str:
        """Return modality from DICOM metadata, if available."""
        if not datasets:
            return "UNKNOWN"
        modality = getattr(datasets[0], "Modality", "UNKNOWN")
        return str(modality).upper()

    def _expected_peak_count(self, modality: str, fallback: int) -> int:
        """Return expected peak count based on modality (CT=4, PET/PT=2)."""
        if modality == "CT":
            return 4
        if modality in {"PT", "PET"}:
            return 2
        return fallback

    def _find_profile_peaks(self, profile: np.ndarray, expected_count: int) -> np.ndarray:
        """Find prominent peaks in differential profile (both positive and negative).
        
        For differential profiles, we want to find both rising edges (positive peaks)
        and falling edges (negative peaks). Returns exactly expected_count peaks.
        """
        if expected_count < 1:
            return np.array([], dtype=int)

        profile = np.asarray(profile, dtype=np.float64)
        data_range = float(np.max(profile) - np.min(profile))
        
        # Start with low prominence to find more candidates
        prominence = data_range * 0.02 if data_range > 0 else 0
        
        # Find positive peaks (rising edges)
        pos_peaks, _ = find_peaks(profile, prominence=prominence)
        
        # Find negative peaks (falling edges) by inverting the signal
        neg_peaks, _ = find_peaks(-profile, prominence=prominence)
        
        # Combine all peaks
        all_peaks = np.concatenate([pos_peaks, neg_peaks]) if pos_peaks.size or neg_peaks.size else np.array([], dtype=int)
        
        if all_peaks.size == 0:
            # Fallback: find points with largest absolute differential values
            abs_profile = np.abs(profile)
            peak_candidates = np.argsort(abs_profile)[-expected_count:]
            return np.sort(peak_candidates)
        
        # Rank by absolute magnitude of differential
        abs_heights = np.abs(profile[all_peaks])
        sort_idx = np.argsort(abs_heights)[::-1]
        
        # Take top expected_count peaks
        n_to_select = min(expected_count, all_peaks.size)
        top_peaks = all_peaks[sort_idx[:n_to_select]]
        
        # If we still don't have enough, add more from absolute maxima
        if n_to_select < expected_count:
            abs_profile = np.abs(profile)
            remaining = expected_count - n_to_select
            # Exclude already selected peaks
            mask = np.ones(len(profile), dtype=bool)
            mask[top_peaks] = False
            candidates = np.where(mask)[0]
            additional = candidates[np.argsort(abs_profile[candidates])[-remaining:]]
            top_peaks = np.concatenate([top_peaks, additional])
        
        return np.sort(top_peaks)

    def _save_peak_summary(self):
        """Save peak indices and values to JSON in output directory."""
        summary = {
            "series1_modality": self.series1_modality,
            "series2_modality": self.series2_modality,
            "series1_expected_peaks": int(self.expected_peaks1),
            "series2_expected_peaks": int(self.expected_peaks2),
            "note": "Peaks detected from differential profiles (dROI/dz)",
            "series1_fwhm": self.fwhm1,
            "series2_fwhm": self.fwhm2,
            "series1_peaks": [
                {
                    "slice_index": int(i),
                    "z_position_mm": float(self.z_positions[i]),
                    "roi_value": float(self.profile1[i]),
                    "differential_value": float(self.diff_profile1[i]),
                }
                for i in self.peaks1
            ],
            "series2_peaks": [
                {
                    "slice_index": int(i),
                    "z_position_mm": float(self.z_positions[i]),
                    "roi_value": float(self.profile2[i]),
                    "differential_value": float(self.diff_profile2[i]),
                }
                for i in self.peaks2
            ],
        }

        peak_file = os.path.join(self.output_dir, "roi_profile_peaks.json")
        with open(peak_file, "w") as f:
            json.dump(summary, f, indent=2)

        SUCCESS(f"Peak summary saved: {peak_file}")
    
    def _compute_fwhm(self, modality: str, profile: np.ndarray) -> Dict[str, float]:
        """Compute FWHM for the given profile based on modality."""
        mode = "pet" if modality in {"PT", "PET"} else "ct"
        
        try:
            fwhm_result = compute_axial_fwhm(
                np.array(self.z_positions),
                profile,
                mode
            )
            INFO(f"{modality} FWHM: {fwhm_result['fwhm_mm']:.2f} mm at z={fwhm_result['z_mid_mm']:.2f} mm")
            return fwhm_result
        except Exception as e:
            WARN(f"Could not compute FWHM for {modality}: {e}")
            return {
                "fwhm_mm": float('nan'),
                "z_left_mm": float('nan'),
                "z_right_mm": float('nan'),
                "z_mid_mm": float('nan'),
            }

    def save_csv(self):
        """Save profile data to CSV."""
        csv_file = os.path.join(self.output_dir, "roi_profile_data.csv")

        INFO(f"Saving profile data to {csv_file}...")

        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "slice_index",
                "z_position_mm",
                "series1_" + self.statistic,
                "series2_" + self.statistic,
                "series1_differential",
                "series2_differential",
            ])

            for i, (z, v1, v2, d1, d2) in enumerate(
                zip(self.z_positions, self.profile1, self.profile2, self.diff_profile1, self.diff_profile2)
            ):
                writer.writerow([i, f"{z:.2f}", f"{v1:.4f}", f"{v2:.4f}", f"{d1:.6f}", f"{d2:.6f}"])

        SUCCESS(f"CSV saved: {csv_file}")

    def plot_profiles(self, figsize: Tuple[int, int] = (12, 6)):
        """
        Create and save comparison plot.
        
        Parameters
        ----------
        figsize : Tuple[int, int]
            Figure size (width, height) in inches.
        """
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(figsize[0], figsize[1] + 4))
        
        # Plot 1: Both series on same axis (normalized)
        ax1.plot(self.z_positions, self.profile1, "o-", label="Series 1", linewidth=2, markersize=4)
        ax1.plot(self.z_positions, self.profile2, "s-", label="Series 2", linewidth=2, markersize=4)
        if self.peaks1.size:
            ax1.plot(
                np.array(self.z_positions)[self.peaks1],
                self.profile1[self.peaks1],
                "^",
                color="black",
                markersize=8,
                label="Series 1 peaks",
            )
        if self.peaks2.size:
            ax1.plot(
                np.array(self.z_positions)[self.peaks2],
                self.profile2[self.peaks2],
                "v",
                color="black",
                markersize=8,
                label="Series 2 peaks",
            )
        ax1.set_xlabel("Z-position (mm)")
        ax1.set_ylabel(f"ROI {self.statistic.capitalize()} Intensity")
        ax1.set_title(f"Axial ROI Profile Comparison ({self.roi_type} ROI, {self.statistic})")
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Plot 2: Normalized profiles (to compare shape independent of scale)
        norm1 = (self.profile1 - np.min(self.profile1)) / (np.max(self.profile1) - np.min(self.profile1) + 1e-8)
        norm2 = (self.profile2 - np.min(self.profile2)) / (np.max(self.profile2) - np.min(self.profile2) + 1e-8)
        
        ax2.plot(self.z_positions, norm1, "o-", label="Series 1 (normalized)", linewidth=2, markersize=4)
        ax2.plot(self.z_positions, norm2, "s-", label="Series 2 (normalized)", linewidth=2, markersize=4)
        ax2.set_xlabel("Z-position (mm)")
        ax2.set_ylabel(f"Normalized {self.statistic.capitalize()}")
        ax2.set_title("Normalized ROI Profiles (0–1 scale)")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        # Plot 3: Differential profiles (dROI/dz) with peak markers
        ax3.plot(self.z_positions, self.diff_profile1, "o-", label="Series 1 dROI/dz", linewidth=2, markersize=4)
        ax3.plot(self.z_positions, self.diff_profile2, "s-", label="Series 2 dROI/dz", linewidth=2, markersize=4)
        if self.peaks1.size:
            ax3.plot(
                np.array(self.z_positions)[self.peaks1],
                self.diff_profile1[self.peaks1],
                "^",
                color="red",
                markersize=8,
                label="Series 1 peaks",
            )
        if self.peaks2.size:
            ax3.plot(
                np.array(self.z_positions)[self.peaks2],
                self.diff_profile2[self.peaks2],
                "v",
                color="red",
                markersize=8,
                label="Series 2 peaks",
            )
        ax3.set_xlabel("Z-position (mm)")
        ax3.set_ylabel(f"d(ROI {self.statistic})/dz")
        ax3.set_title("Differential ROI Profiles (peaks detected here)")
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        plot_file = os.path.join(self.output_dir, "profile_comparison.png")
        fig.savefig(plot_file, dpi=150, bbox_inches="tight")
        SUCCESS(f"Plot saved: {plot_file}")
        plt.close(fig)
    
    def visualize_roi_on_samples(self, num_samples: int = 3):
        """
        Create sample images showing ROI overlay on slices.
        
        Parameters
        ----------
        num_samples : int
            Number of sample slices to visualize (start, middle, end).
        """
        if not self.debug_dir:
            return
        
        diag_dir = os.path.join(self.debug_dir, "roi_visualization")
        os.makedirs(diag_dir, exist_ok=True)
        
        INFO(f"Saving ROI visualization to {diag_dir}...")
        
        # Select sample indices
        if num_samples < 1:
            num_samples = 1
        
        if num_samples == 1:
            indices = [len(self.arrays1) // 2]
        else:
            indices = np.linspace(0, len(self.arrays1) - 1, num_samples, dtype=int)
        
        for idx in indices:
            fig, axes = plt.subplots(1, 2, figsize=(12, 5))
            
            # Series 1
            im1 = axes[0].imshow(self.arrays1[idx], cmap="gray")
            # Overlay ROI contour
            contours1 = np.zeros_like(self.mask1)
            contours1[np.logical_xor(self.mask1, zoom(self.mask1, 0.98, order=0))] = 1
            axes[0].contour(contours1, colors="red", linewidths=2)
            axes[0].set_title(f"Series 1 (slice {idx}, z={self.z_positions[idx]:.2f} mm)")
            axes[0].set_xlabel("Column (pixel)")
            axes[0].set_ylabel("Row (pixel)")
            plt.colorbar(im1, ax=axes[0])
            
            # Series 2
            im2 = axes[1].imshow(self.arrays2[idx], cmap="gray")
            contours2 = np.zeros_like(self.mask2)
            contours2[np.logical_xor(self.mask2, zoom(self.mask2, 0.98, order=0))] = 1
            axes[1].contour(contours2, colors="red", linewidths=2)
            axes[1].set_title(f"Series 2 (slice {idx}, z={self.z_positions[idx]:.2f} mm)")
            axes[1].set_xlabel("Column (pixel)")
            axes[1].set_ylabel("Row (pixel)")
            plt.colorbar(im2, ax=axes[1])
            
            plt.tight_layout()
            
            vis_file = os.path.join(diag_dir, f"roi_visualization_slice_{idx:03d}.png")
            fig.savefig(vis_file, dpi=100, bbox_inches="tight")
            plt.close(fig)
        
        SUCCESS(f"Saved {num_samples} ROI visualizations")


# ============================================================================
# Main
# ============================================================================

def main():
    """
    Main entry point.
    """
    parser = argparse.ArgumentParser(
        description="Extract center ROI and plot axial intensity profiles for two DICOM series.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python roi_axial_profile.py --series1 ./pet_series --series2 ./ct_series
  python roi_axial_profile.py --series1 s1 --series2 s2 --roi-type circle --roi-radius 75
  python roi_axial_profile.py --series1 s1 --series2 s2 --roi-type square --roi-size 150
  python roi_axial_profile.py --series1 s1 --series2 s2 --statistic median --debug ./debug
        """,
    )
    
    parser.add_argument(
        "--series1",
        type=str,
        required=True,
        help="Path to first DICOM series folder.",
    )
    parser.add_argument(
        "--series2",
        type=str,
        required=True,
        help="Path to second DICOM series folder.",
    )
    parser.add_argument(
        "--roi-type",
        type=str,
        choices=["circle", "square"],
        default="circle",
        help="ROI shape: circle (default) or square.",
    )
    parser.add_argument(
        "--roi-radius",
        type=int,
        default=50,
        help="Radius in pixels for circular ROI (default: 50).",
    )
    parser.add_argument(
        "--roi-size",
        type=int,
        default=100,
        help="Width/height in pixels for square ROI (default: 100).",
    )
    parser.add_argument(
        "--statistic",
        type=str,
        choices=["mean", "median", "std"],
        default="mean",
        help="Statistic to extract from ROI (default: mean).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="roi_profiles",
        help="Output directory for CSV and plots (default: roi_profiles).",
    )
    parser.add_argument(
        "--debug",
        type=str,
        default=None,
        help="Directory for debug artifacts (ROI visualizations).",
    )
    
    args = parser.parse_args()
    
    # Validate inputs
    if not os.path.isdir(args.series1):
        ERROR(f"Series 1 directory not found: {args.series1}")
        return 1
    if not os.path.isdir(args.series2):
        ERROR(f"Series 2 directory not found: {args.series2}")
        return 1
    
    try:
        # Load series
        INFO(f"Loading series 1 from {args.series1}...")
        datasets1, metadata1 = load_dicom_series(args.series1, debug=True)
        
        INFO(f"Loading series 2 from {args.series2}...")
        datasets2, metadata2 = load_dicom_series(args.series2, debug=True)
        
        # Analyze profiles
        analyzer = ROIAxisProfileAnalyzer(
            datasets1,
            datasets2,
            metadata1,
            metadata2,
            roi_type=args.roi_type,
            roi_radius=args.roi_radius,
            roi_size=args.roi_size,
            statistic=args.statistic,
            output_dir=args.output,
            debug_dir=args.debug,
        )
        
        # Save outputs
        analyzer.save_csv()
        analyzer.plot_profiles()
        
        # Debug visualizations
        if args.debug:
            analyzer.visualize_roi_on_samples(num_samples=3)
        
        SUCCESS("Done!")
        return 0
    
    except Exception as e:
        ERROR(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
