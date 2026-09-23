#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acr_slice_selector.py
Orchestration tool that analyzes an ACR PET series to identify 3 representative slices
(uniformity, rods, hot-cells) and calls image_selection for automated processing.

Features:
- Computes ROI statistics across all slices in the ACR series
- Identifies contiguous regions based on hot-signal concentration and min/mean ratios
- Selects center slices from uniformity, rods, and hot-cell regions
- Calls image_selection CLI with identified slices in headless mode
- Saves selection metadata as JSON sidecar

Usage:
    python acr_slice_selector.py --input <acr_series_dir> --output <output_dir>
    python acr_slice_selector.py --config config.json
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict
import numpy as np

# Import from existing pet_tools module
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pet_tools import suv_overlay_manual as PET

# Reuse existing utilities
INFO = PET.INFO
WARN = PET.WARN
ERROR = PET.ERROR
load_series = PET.load_series
suv_from_ds = PET.suv_from_ds
find_phantom_center_generalized = PET.find_phantom_center_generalized

# Configuration
ROI_DIAMETER_MM = 180.0  # ROI diameter for analysis
DEFAULT_MAX_PERCENTILE = 85  # Top percentile for hot-cell region
DEFAULT_MIN_PERCENTILE = 85  # Top percentile for uniformity region (high min/mean ratio)
DEFAULT_HOT_INTENSITY_PERCENTILE = 98  # Global ROI percentile used to define concentrated hot signal


def create_circular_mask(shape: Tuple[int, int], center: Tuple[float, float], radius_pixels: float) -> np.ndarray:
    """
    Create a circular mask for ROI analysis.
    
    Args:
        shape: (rows, cols) of image shape
        center: (cy, cx) center position in pixels
        radius_pixels: radius in pixels
    
    Returns:
        Boolean mask array where True indicates pixels inside the circle
    """
    rows, cols = shape
    cy, cx = center
    y, x = np.ogrid[:rows, :cols]
    mask = (x - cx)**2 + (y - cy)**2 <= radius_pixels**2
    return mask


def compute_slice_roi_stats(suv_images: List[np.ndarray], 
                            dsets: List,
                            pixel_mm: Tuple[float, float]) -> Dict[str, np.ndarray]:
    """
    Compute ROI statistics for all slices.
    
    Args:
        suv_images: List of SUV images
        dsets: List of DICOM datasets
        pixel_mm: (row_mm, col_mm) pixel spacing
    
    Returns:
        Dictionary with arrays/lists: roi_mean, roi_max, roi_min, centers_px, roi_values
    """
    row_mm, col_mm = pixel_mm
    radius_px = (ROI_DIAMETER_MM / 2.0) / col_mm
    px_spacing = np.mean([row_mm, col_mm])
    modality_raw = str(getattr(dsets[0], "Modality", "PT")).upper()
    # The generalized center detector uses PET-specific preprocessing for the
    # descriptive modality name "PET", while DICOM encodes PET as "PT".
    modality = "PET" if modality_raw == "PT" else modality_raw
    
    roi_means = []
    roi_maxs = []
    roi_mins = []
    centers_px = []
    roi_values_by_slice = []
    
    for idx, (suv_img, ds) in enumerate(zip(suv_images, dsets)):
        # Find phantom center
        px_array = ds.pixel_array.astype(np.float32)
        cy, cx, _r = find_phantom_center_generalized(
            px_array, 
            pixel_size_mm=px_spacing, 
            modality=modality, 
            debug=False
        )
        centers_px.append((cy, cx))
        
        # Create mask and compute stats
        mask = create_circular_mask(suv_img.shape, (cy, cx), radius_px)
        roi_values = suv_img[mask]
        roi_values = roi_values[np.isfinite(roi_values)]
        roi_values_by_slice.append(roi_values.astype(np.float32, copy=False))
        
        if len(roi_values) > 0:
            roi_means.append(float(np.mean(roi_values)))
            roi_maxs.append(float(np.max(roi_values)))
            roi_mins.append(float(np.min(roi_values)))
        else:
            roi_means.append(0.0)
            roi_maxs.append(0.0)
            roi_mins.append(0.0)
    
    return {
        "roi_mean": np.array(roi_means),
        "roi_max": np.array(roi_maxs),
        "roi_min": np.array(roi_mins),
        "centers_px": centers_px,
        "roi_values": roi_values_by_slice,
    }


def compute_hot_intensity_concentration(roi_stats: Dict[str, np.ndarray],
                                        intensity_percentile: int = DEFAULT_HOT_INTENSITY_PERCENTILE) -> Tuple[np.ndarray, float]:
    """
    Compute a per-slice hot-signal concentration score.

    The score measures how much SUV signal sits above a global high-intensity
    threshold across the full series ROI population. This favors slices with a
    spatially concentrated hot region rather than slices that contain a single
    bright voxel on top of a depressed slice mean.

    Args:
        roi_stats: Dictionary returned by compute_slice_roi_stats
        intensity_percentile: Global percentile used to define the bright tail

    Returns:
        (hot_score, threshold) where hot_score is indexed by slice and threshold
        is the global SUV threshold used for the bright-tail excess calculation.
    """
    roi_values_by_slice = roi_stats["roi_values"]
    positive_roi_values = [values[values > 0] for values in roi_values_by_slice if len(values) > 0]

    if not positive_roi_values:
        return np.zeros(len(roi_values_by_slice), dtype=np.float32), 0.0

    global_values = np.concatenate(positive_roi_values)
    if len(global_values) == 0:
        return np.zeros(len(roi_values_by_slice), dtype=np.float32), 0.0

    intensity_threshold = float(np.percentile(global_values, intensity_percentile))
    hot_score = np.zeros(len(roi_values_by_slice), dtype=np.float32)

    for idx, roi_values in enumerate(roi_values_by_slice):
        positive_values = roi_values[roi_values > 0]
        if len(positive_values) == 0:
            continue

        bright_values = positive_values[positive_values >= intensity_threshold]
        if len(bright_values) == 0:
            continue

        hot_score[idx] = float(np.sum(bright_values - intensity_threshold))

    return hot_score, intensity_threshold


def compute_ratios(roi_stats: Dict[str, np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute max/mean and min/mean ratios with division-by-zero protection.
    
    Args:
        roi_stats: Dictionary containing roi_mean, roi_max, roi_min arrays
    
    Returns:
        (max_ratio, min_ratio) arrays
    """
    means = roi_stats["roi_mean"]
    maxs = roi_stats["roi_max"]
    mins = roi_stats["roi_min"]
    
    # Guard against division by zero
    max_ratio = np.divide(maxs, means, out=np.ones_like(maxs), where=means > 0)
    min_ratio = np.divide(mins, means, out=np.ones_like(mins), where=means > 0)
    
    return max_ratio, min_ratio


def find_contiguous_segments(indices: List[int]) -> List[Tuple[int, int]]:
    """
    Find contiguous segments from a list of indices.
    
    Args:
        indices: List of slice indices (may not be contiguous)
    
    Returns:
        List of (start, end) tuples representing contiguous segments (inclusive)
    """
    if not indices:
        return []
    
    indices = sorted(indices)
    segments = []
    start = indices[0]
    prev = indices[0]
    
    for idx in indices[1:]:
        if idx != prev + 1:
            # New segment
            segments.append((start, prev))
            start = idx
        prev = idx
    
    # Add final segment
    segments.append((start, prev))
    return segments


def select_best_segment(segments: List[Tuple[int, int]], 
                       values: np.ndarray, 
                       prefer_high: bool = True) -> Tuple[int, int]:
    """
    Select the best segment from candidates.
    
    Args:
        segments: List of (start, end) segment tuples
        values: Array of values indexed by slice
        prefer_high: If True, prefer higher mean values; else prefer lower
    
    Returns:
        (start, end) of the best segment
    """
    if not segments:
        return (0, 0)
    
    # Rank by length first, then by mean value
    scored_segments = []
    for start, end in segments:
        length = end - start + 1
        segment_values = values[start:end+1]
        mean_val = np.mean(segment_values) if len(segment_values) > 0 else 0.0
        scored_segments.append((length, mean_val if prefer_high else -mean_val, start, end))
    
    # Sort by length (descending), then by mean value
    scored_segments.sort(reverse=True)
    _, _, start, end = scored_segments[0]
    return (start, end)


def identify_regions(hot_score: np.ndarray,
                    min_ratio: np.ndarray,
                    max_percentile: int = DEFAULT_MAX_PERCENTILE,
                    min_percentile: int = DEFAULT_MIN_PERCENTILE) -> Dict[str, Tuple[int, int]]:
    """
    Identify uniformity, hot-cell, and rods regions as contiguous segments.
    
    Args:
        hot_score: Array of hot-signal concentration scores
        min_ratio: Array of min/mean ratios
        max_percentile: Percentile threshold for hot-cell region (high concentration)
        min_percentile: Percentile threshold for uniformity region (high min/mean)
    
    Returns:
        Dictionary with keys: 'max_region', 'min_region', 'rods_region'
        Each value is a (start, end) tuple
    """
    n_slices = len(hot_score)
    
    # Identify candidate slices
    # Hot-cells: high concentration of bright SUV signal (top percentile)
    max_threshold = np.percentile(hot_score, max_percentile)
    max_candidates = [i for i in range(n_slices) if hot_score[i] >= max_threshold and hot_score[i] > 0]
    
    # Uniformity: high min/mean ratio (top percentile) - minimum is close to mean
    min_threshold = np.percentile(min_ratio, min_percentile)
    min_candidates = [i for i in range(n_slices) if min_ratio[i] >= min_threshold]
    
    # Resolve overlaps: max-region takes priority
    min_candidates = [i for i in min_candidates if i not in max_candidates]
    
    # Find contiguous segments
    max_segments = find_contiguous_segments(max_candidates)
    min_segments = find_contiguous_segments(min_candidates)
    
    # Select best segments
    if max_segments:
        max_region = select_best_segment(max_segments, hot_score, prefer_high=True)
    else:
        # Fallback: single slice with highest concentration score
        idx = int(np.argmax(hot_score))
        max_region = (idx, idx)
        WARN(f"No max region found; using fallback slice {idx}")
    
    if min_segments:
        min_region = select_best_segment(min_segments, min_ratio, prefer_high=True)
    else:
        # Fallback: single slice with highest min_ratio
        idx = int(np.argmax(min_ratio))
        min_region = (idx, idx)
        WARN(f"No min region found; using fallback slice {idx}")
    
    # Rods region: remaining slices
    used_indices = set(range(max_region[0], max_region[1] + 1))
    used_indices.update(range(min_region[0], min_region[1] + 1))
    rods_candidates = [i for i in range(n_slices) if i not in used_indices]
    
    if rods_candidates:
        rods_segments = find_contiguous_segments(rods_candidates)
        # For rods, just pick the longest segment
        rods_region = select_best_segment(rods_segments, np.ones(n_slices), prefer_high=True)
    else:
        # Fallback: median slice
        idx = n_slices // 2
        rods_region = (idx, idx)
        WARN(f"No rods region found; using fallback slice {idx}")
    
    INFO(f"Identified regions:")
    INFO(f"  Max region (hot-cells concentration): slices {max_region[0]}-{max_region[1]}")
    INFO(f"  Min region (uniformity): slices {min_region[0]}-{min_region[1]}")
    INFO(f"  Rods region: slices {rods_region[0]}-{rods_region[1]}")
    
    return {
        "max_region": max_region,
        "min_region": min_region,
        "rods_region": rods_region
    }


def compute_center_slices(regions: Dict[str, Tuple[int, int]], n_slices: int) -> Dict[str, int]:
    """
    Compute center slice index for each region.
    
    Args:
        regions: Dictionary with region (start, end) tuples
        n_slices: Total number of slices for bounds checking
    
    Returns:
        Dictionary with keys: 'uniformity_slice', 'hot_slice', 'rods_slice'
    """
    def center_of_region(start: int, end: int) -> int:
        center = (start + end) // 2
        return max(0, min(center, n_slices - 1))
    
    min_region = regions["min_region"]
    max_region = regions["max_region"]
    rods_region = regions["rods_region"]
    
    result = {
        "uniformity_slice": center_of_region(*min_region),
        "hot_slice": center_of_region(*max_region),
        "rods_slice": center_of_region(*rods_region)
    }
    
    INFO(f"Selected representative slices:")
    INFO(f"  Uniformity: slice {result['uniformity_slice']}")
    INFO(f"  Hot-cells: slice {result['hot_slice']}")
    INFO(f"  Rods: slice {result['rods_slice']}")
    
    return result


def call_image_selection(series_dir: Path, 
                        output_dir: Path,
                        uniformity_slice: int,
                        hot_slice: int,
                        rods_slice: int,
                        debug_enabled: bool = False):
    """
    Call image_selection CLI tool with identified slice indices.
    
    Args:
        series_dir: Input DICOM series directory
        output_dir: Output directory for results
        uniformity_slice: Uniformity slice index
        hot_slice: Hot-cell slice index
        rods_slice: Rods slice index
        debug_enabled: If True, save subprocess output to log file
    
    Raises:
        RuntimeError: If image_selection returns non-zero exit code
    """
    python_exe = Path(sys.executable)
    
    # Sort indices in ascending order as required by image_selection
    sorted_indices = sorted([uniformity_slice, rods_slice, hot_slice])
    indices_str = ','.join(str(idx) for idx in sorted_indices)
    
    tool_args = [
        "--input", str(series_dir),
        "--output", str(output_dir),
        "--indices", indices_str,
        "--fov", "220",
        "--save"
    ]

    if getattr(sys, "frozen", False):
        cmd = [
            str(python_exe),
            "--run-tool", "imgsel", "--",
            *tool_args,
        ]
    else:
        image_selection_script = HERE / "image_selection.py"
        cmd = [
            str(python_exe),
            str(image_selection_script),
            *tool_args,
        ]
    
    # Create a properly quoted version for display
    def quote_if_needed(s):
        return f'"{s}"' if ' ' in s else s
    
    display_cmd = ' '.join(quote_if_needed(str(c)) for c in cmd)
    
    INFO(f"Calling image_selection with command:")
    INFO(f"  {display_cmd}")
    INFO(f"  Indices (sorted): {indices_str}")
    INFO(f"  (uniformity={uniformity_slice}, rods={rods_slice}, hot={hot_slice})")
    
    try:
        result = subprocess.run(
            cmd,
            check=False,
            encoding='utf-8',
            errors='replace'
        )
        
        # Write output to log file if debug is enabled (not captured, so minimal info)
        if debug_enabled:
            log_file = output_dir / "image_selection_log.txt"
            with open(log_file, 'w', encoding='utf-8', errors='replace') as f:
                f.write(f"=== Command ===\n")
                f.write(' '.join(cmd) + "\n")
                f.write(f"\n=== EXIT CODE: {result.returncode} ===\n")
            
            INFO(f"image_selection output written to: {log_file}")
        
        if result.returncode != 0:
            ERROR(f"image_selection failed with exit code {result.returncode}")
            if debug_enabled:
                log_file = output_dir / "image_selection_log.txt"
                ERROR(f"Check log file for details: {log_file}")
            raise RuntimeError(f"image_selection failed with exit code {result.returncode}")
        
        INFO("image_selection completed successfully")
        
    except Exception as e:
        ERROR(f"Failed to call image_selection: {e}")
        raise


def save_selection_metadata(output_dir: Path,
                           series_dir: Path,
                           selected_slices: Dict[str, int],
                           regions: Dict[str, Tuple[int, int]],
                           max_percentile: int,
                           min_percentile: int,
                           hot_intensity_percentile: int,
                           diagnostics: Dict[str, List[float]],
                           debug_enabled: bool = False):
    """
    Save selection metadata as JSON sidecar (only if debug enabled).
    
    Args:
        output_dir: Output directory
        series_dir: Input series directory
        selected_slices: Dictionary with slice indices
        regions: Dictionary with region boundaries
        max_percentile: Max percentile threshold used
        min_percentile: Min percentile threshold used
        debug_enabled: If True, save metadata file
    """
    if not debug_enabled:
        return
    
    metadata = {
        "series_dir": str(series_dir),
        "uniformity_slice": selected_slices["uniformity_slice"],
        "hot_slice": selected_slices["hot_slice"],
        "rods_slice": selected_slices["rods_slice"],
        "regions": {
            "uniformity_region": list(regions["min_region"]),
            "hot_cells_region": list(regions["max_region"]),
            "rods_region": list(regions["rods_region"])
        },
        "thresholds": {
            "max_percentile": max_percentile,
            "min_percentile": min_percentile,
            "hot_intensity_percentile": hot_intensity_percentile,
        },
        "hot_region_method": "global bright-tail excess concentration",
        "diagnostics": diagnostics,
        "roi_diameter_mm": ROI_DIAMETER_MM
    }
    
    output_file = output_dir / "slice_selection_metadata.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    
    INFO(f"Metadata saved: {output_file}")


def load_config(path: str) -> dict:
    """Load configuration from JSON file."""
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        WARN(f"Failed to load config: {e}")
        return {}


def main(argv=None) -> int:
    """Main entry point for ACR slice selector."""
    parser = argparse.ArgumentParser(
        description="Analyze ACR PET series and call image_selection with representative slices."
    )
    parser.add_argument("--input", "-i", help="Input ACR DICOM series folder")
    parser.add_argument("--output", "-o", help="Output folder")
    parser.add_argument("--max-percentile", type=int, default=DEFAULT_MAX_PERCENTILE,
                       help=f"Percentile threshold for hot-cell concentration region (default: {DEFAULT_MAX_PERCENTILE})")
    parser.add_argument("--min-percentile", type=int, default=DEFAULT_MIN_PERCENTILE,
                       help=f"Percentile threshold for uniformity region - high min/mean ratio (default: {DEFAULT_MIN_PERCENTILE})")
    parser.add_argument("--hot-intensity-percentile", type=int, default=DEFAULT_HOT_INTENSITY_PERCENTILE,
                       help=f"Global ROI percentile used for hot-signal concentration scoring (default: {DEFAULT_HOT_INTENSITY_PERCENTILE})")
    parser.add_argument("--config", help="Optional JSON config file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)
    
    cfg = load_config(args.config)
    debug_enabled = args.debug or cfg.get("debug", False)
    
    # Get parameters
    series_dir = Path(args.input or cfg.get("input", ""))
    output_dir = Path(args.output or cfg.get("output", ""))
    max_percentile = args.max_percentile or cfg.get("max_percentile", DEFAULT_MAX_PERCENTILE)
    min_percentile = args.min_percentile or cfg.get("min_percentile", DEFAULT_MIN_PERCENTILE)
    hot_intensity_percentile = args.hot_intensity_percentile or cfg.get("hot_intensity_percentile", DEFAULT_HOT_INTENSITY_PERCENTILE)
    
    # Validate inputs
    if not series_dir or not series_dir.exists():
        ERROR(f"Invalid input directory: {series_dir}")
        return 1
    
    if not output_dir:
        ERROR("Output directory required")
        return 1
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    INFO("="*60)
    INFO("ACR Slice Selector - Automated Representative Slice Detection")
    INFO("="*60)
    INFO(f"Input series: {series_dir}")
    INFO(f"Output directory: {output_dir}")
    INFO(f"Thresholds: hot region {max_percentile}th percentile, min {min_percentile}th percentile")
    INFO(f"Hot concentration uses global ROI intensity percentile: {hot_intensity_percentile}")
    
    # Load PET series
    INFO("Loading PET DICOM series...")
    try:
        disp_imgs, res_imgs, dsets, pixel_mm = load_series(str(series_dir))
    except Exception as e:
        ERROR(f"Failed to load series: {e}")
        return 1
    
    n_slices = len(dsets)
    INFO(f"Loaded {n_slices} slices | Pixel spacing: {pixel_mm[0]:.3f} x {pixel_mm[1]:.3f} mm")
    
    # Compute SUV for all slices
    INFO("Computing SUV values...")
    suv_images = []
    for ds, raw in zip(dsets, res_imgs):
        suv, _, _ = suv_from_ds(ds, raw)
        suv_images.append(suv.astype(np.float32))
    
    # Compute ROI statistics
    INFO("Computing ROI statistics for all slices...")
    roi_stats = compute_slice_roi_stats(suv_images, dsets, pixel_mm)
    
    # Compute ratios
    INFO("Computing max/mean and min/mean ratios...")
    max_ratio, min_ratio = compute_ratios(roi_stats)

    # Compute hot-signal concentration score
    INFO("Computing hot-signal concentration across slices...")
    hot_score, hot_intensity_threshold = compute_hot_intensity_concentration(
        roi_stats,
        intensity_percentile=hot_intensity_percentile,
    )
    
    # Identify regions
    INFO("Identifying contiguous regions...")
    regions = identify_regions(hot_score, min_ratio, max_percentile, min_percentile)
    
    # Compute center slices
    selected_slices = compute_center_slices(regions, n_slices)
    
    # Call image_selection
    INFO("Calling image_selection...")
    try:
        call_image_selection(
            series_dir,
            output_dir,
            selected_slices["uniformity_slice"],
            selected_slices["hot_slice"],
            selected_slices["rods_slice"],
            debug_enabled=debug_enabled
        )
    except Exception as e:
        ERROR(f"Failed to execute image_selection: {e}")
        return 1
    
    # Save metadata (only if debug enabled)
    save_selection_metadata(
        output_dir,
        series_dir,
        selected_slices,
        regions,
        max_percentile,
        min_percentile,
        hot_intensity_percentile,
        diagnostics={
            "hot_score": [float(v) for v in hot_score],
            "max_ratio": [float(v) for v in max_ratio],
            "min_ratio": [float(v) for v in min_ratio],
            "hot_intensity_threshold": [float(hot_intensity_threshold)],
        },
        debug_enabled=debug_enabled
    )
    
    INFO("="*60)
    INFO("ACR slice selection and image processing complete!")
    INFO(f"Results saved to: {output_dir}")
    INFO("="*60)
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        ERROR(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
