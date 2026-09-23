# -*- coding: utf-8 -*-
"""
Dual Series Overlay — load and display two DICOM image series with independent color scales.

Purpose
-------
Load two series of medical images (PET, CT, etc.) simultaneously and display them
overlaid in the same spatial coordinates (x, y, z) as specified in the DICOM data.
Each series maintains its own color scale (colormap) for independent visualization.

Features
--------
- Load two DICOM image series from separate folders
- Automatic series sorting by slice position (z-coordinate)
- Independent color scale (colormap) for each series
- Slice navigation via keyboard (↑/↓ arrows or Page Up/Down)
- Interactive ROI selection (crosshair cursor)
- Export overlay images as PNG with metadata
- Optional debug output: coordinate mappings, image statistics, diagnostic plots

Usage
-----
    python dual_series_overlay.py --series1 /path/to/series1 --series2 /path/to/series2
    python dual_series_overlay.py --series1 /path/to/series1 --series2 /path/to/series2 \\
                                  --cmap1 viridis --cmap2 hot --debug debug_output_dir

Inputs
------
series1_dir : str
    Path to first DICOM series folder.
series2_dir : str
    Path to second DICOM series folder.
cmap1 : str, optional
    Matplotlib colormap for series 1 (default: "viridis").
cmap2 : str, optional
    Matplotlib colormap for series 2 (default: "hot").
alpha1, alpha2 : float, optional
    Opacity of each series (default: 0.5 each). Sum should ≤ 1.0 for visibility.
output_dir : str, optional
    Directory to save overlay PNG images (default: "overlay_output").
debug : str, optional
    Enable debug mode; save diagnostic artifacts to this directory.

Outputs
-------
Overlay PNG images : images/
    Files named overlay_slice_NNN.png with both series composited.
Debug artifacts (if --debug): debug_dir/
    - coordinate_map.json: Physical (x,y,z) positions for each slice index.
    - series_stats.json: Min/max/mean pixel values for each series.
    - diagnostic_plots/: Slice-by-slice visualization of both series alone and overlaid.

Assumptions
-----------
1. Each series has uniform geometry (all slices same dimensions and spacing).
2. SliceLocation or ImagePositionPatient in DICOM headers defines z-coordinate.
3. Pixel spacing defines x, y resolution (PixelSpacing in mm).
4. Both series cover the same or similar anatomical region.
5. If slices do not align exactly, linear interpolation is used.

Mathematical Notes
-------------------
**Coordinate Transformation:**
  For each voxel (i, j, k) in image grid:
  - i, j: row and column indices in pixel grid.
  - k: slice index (ordered by z-coordinate).
  
  Physical coordinates are computed as:
    x = ImagePositionPatient[0] + i * PixelSpacing[0]
    y = ImagePositionPatient[1] + j * PixelSpacing[1]
    z = SliceLocation (or ImagePositionPatient[2])
  
  Both series are resampled to a common z-grid (if necessary) to ensure
  alignment at the same anatomical slices.

**Color Blending:**
  For each pixel, the overlay is computed as:
    overlay = alpha1 * normalized(series1) + alpha2 * normalized(series2)
  
  Each series is independently normalized to [0, 1] before blending.

**Interpolation:**
  If series have different slice spacings, images are interpolated to a common
  z-axis grid using linear interpolation in the z-direction.

References
----------
- DICOM standard Part 3, Image Pixel Module: (0028,0030) Pixel Spacing, (0028,0020) Rows/Columns
- DICOM standard Part 3, Image Position/Orientation: (0020,0032) ImagePositionPatient
- DICOM standard Part 3, Slice Location: (0020,1041) SliceLocation

"""

import os
import sys
import argparse
import json
import glob
from pathlib import Path
from typing import Tuple, List, Dict, Optional, Any
from datetime import datetime

import numpy as np
from scipy.ndimage import zoom
import pydicom
from pydicom.dataset import Dataset
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.widgets import Cursor


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
# DICOM Utilities
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
        List of DICOM datasets sorted by z-coordinate (slice position).
    metadata : Dict[str, Any]
        Series metadata: rows, columns, pixel spacing, slice positions.
    
    Raises
    ------
    ValueError
        If no DICOM files found or series is not valid.
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
    pixel_spacing = [float(x) for x in ds0.PixelSpacing]  # [row_spacing, col_spacing] in mm
    
    metadata = {
        "rows": rows,
        "columns": columns,
        "pixel_spacing": pixel_spacing,  # [row_mm, col_mm]
        "z_positions": z_positions,
        "num_slices": len(datasets),
    }
    
    if debug:
        INFO(f"Loaded {len(datasets)} slices from {series_dir}")
        INFO(f"  Dimensions: {rows} × {columns} pixels")
        INFO(f"  Pixel spacing: {pixel_spacing[0]:.3f} × {pixel_spacing[1]:.3f} mm")
        INFO(f"  Z range: {z_positions[0]:.2f} to {z_positions[-1]:.2f} mm")
        INFO(f"  Slice spacing: {np.mean(np.diff(z_positions)):.2f} mm")
    
    return datasets, metadata


def extract_pixel_array(ds: Dataset, debug: bool = False) -> np.ndarray:
    """
    Extract and scale pixel array from DICOM dataset.
    
    Applies RescaleSlope and RescaleIntercept if present (typical for PET/CT).
    
    Parameters
    ----------
    ds : pydicom.dataset.Dataset
        DICOM dataset.
    debug : bool
        If True, print diagnostic info.
    
    Returns
    -------
    pixel_array : np.ndarray
        2D array of pixel values (typically HU or SUV units).
    """
    arr = ds.pixel_array.astype(np.float32)
    
    # Apply rescale slope/intercept (common for PET/CT)
    if hasattr(ds, "RescaleSlope") and hasattr(ds, "RescaleIntercept"):
        slope = float(ds.RescaleSlope)
        intercept = float(ds.RescaleIntercept)
        arr = arr * slope + intercept
        if debug:
            INFO(f"Applied rescale: slope={slope}, intercept={intercept}")
    
    return arr


def get_image_position(ds: Dataset) -> Tuple[float, float, float]:
    """
    Extract image position (x, y, z) from DICOM dataset.
    
    Returns
    -------
    x, y, z : float
        Physical position in mm.
    """
    if hasattr(ds, "ImagePositionPatient"):
        return tuple(float(x) for x in ds.ImagePositionPatient)
    else:
        return (0.0, 0.0, 0.0)


# ============================================================================
# Image Processing & Overlay
# ============================================================================

def normalize_image(image: np.ndarray, percentile_range: Tuple[float, float] = (2, 98)) -> np.ndarray:
    """
    Normalize image to [0, 1] using percentile clipping.
    
    Parameters
    ----------
    image : np.ndarray
        2D or 3D image array.
    percentile_range : Tuple[float, float]
        Percentiles for clipping (default: 2–98%).
    
    Returns
    -------
    normalized : np.ndarray
        Image scaled to [0, 1].
    """
    vmin, vmax = np.percentile(image, percentile_range)
    normalized = np.clip((image - vmin) / (vmax - vmin + 1e-8), 0, 1)
    return normalized


def align_z_axes(z1: List[float], z2: List[float]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Create a common z-axis for two series with potentially different slice positions.
    
    Uses linear interpolation to resample both series to a common grid.
    
    Parameters
    ----------
    z1, z2 : List[float]
        Slice positions (z-coordinates) for each series.
    
    Returns
    -------
    common_z : np.ndarray
        Common z-axis.
    indices1, indices2 : np.ndarray
        Interpolation indices for series 1 and 2 on common axis.
    """
    z_min = max(min(z1), min(z2))
    z_max = min(max(z1), max(z2))
    
    # Create common grid with average spacing
    spacing1 = np.mean(np.diff(z1))
    spacing2 = np.mean(np.diff(z2))
    avg_spacing = (spacing1 + spacing2) / 2
    
    num_slices = int((z_max - z_min) / avg_spacing) + 1
    common_z = np.linspace(z_min, z_max, num_slices)
    
    # Compute interpolation indices
    indices1 = np.interp(common_z, z1, np.arange(len(z1)))
    indices2 = np.interp(common_z, z2, np.arange(len(z2)))
    
    return common_z, indices1, indices2


def create_coordinate_map(
    metadata1: Dict[str, Any],
    metadata2: Dict[str, Any],
    common_z: np.ndarray,
) -> Dict[str, Any]:
    """
    Create a map of physical coordinates for each slice index.
    
    Returns
    -------
    coord_map : Dict[str, Any]
        Maps slice index → (x_origin, y_origin, z) for both series.
    """
    z1 = metadata1["z_positions"]
    z2 = metadata2["z_positions"]
    
    coord_map = {
        "common_z_axis": common_z.tolist(),
        "series1_z": z1,
        "series2_z": z2,
    }
    
    return coord_map


# ============================================================================
# Visualization & Interaction
# ============================================================================

class DualSeriesViewer:
    """
    Interactive viewer for dual DICOM series overlay.
    
    Allows navigation through slices with ↑/↓ arrow keys or Page Up/Down.
    """
    
    def __init__(
        self,
        datasets1: List[Dataset],
        datasets2: List[Dataset],
        metadata1: Dict[str, Any],
        metadata2: Dict[str, Any],
        cmap1: str = "viridis",
        cmap2: str = "hot",
        alpha1: float = 0.5,
        alpha2: float = 0.5,
        output_dir: str = "overlay_output",
        debug_dir: Optional[str] = None,
    ):
        """
        Initialize viewer.
        
        Parameters
        ----------
        datasets1, datasets2 : List[pydicom.dataset.Dataset]
            Lists of DICOM datasets for each series.
        metadata1, metadata2 : Dict[str, Any]
            Metadata (rows, columns, pixel spacing, z positions).
        cmap1, cmap2 : str
            Matplotlib colormaps for each series.
        alpha1, alpha2 : float
            Opacity of each series (should sum to ≤ 1.0).
        output_dir : str
            Directory to save overlay images.
        debug_dir : str, optional
            Directory for debug output.
        """
        self.datasets1 = datasets1
        self.datasets2 = datasets2
        self.metadata1 = metadata1
        self.metadata2 = metadata2
        # Use pyplot.get_cmap() to avoid deprecation warning (matplotlib 3.7+)
        self.cmap1 = plt.get_cmap(cmap1)
        self.cmap2 = plt.get_cmap(cmap2)
        self.alpha1 = alpha1
        self.alpha2 = alpha2
        self.output_dir = output_dir
        self.debug_dir = debug_dir
        
        os.makedirs(output_dir, exist_ok=True)
        if debug_dir:
            os.makedirs(debug_dir, exist_ok=True)
        
        # Align z-axes
        common_z, idx1, idx2 = align_z_axes(
            metadata1["z_positions"],
            metadata2["z_positions"],
        )
        self.common_z = common_z
        self.interp_idx1 = idx1
        self.interp_idx2 = idx2
        
        # Load all pixel arrays
        INFO("Loading pixel arrays...")
        self.arrays1 = [extract_pixel_array(ds) for ds in datasets1]
        self.arrays2 = [extract_pixel_array(ds) for ds in datasets2]
        SUCCESS("Pixel arrays loaded")
        
        # Check if dimensions match; if not, resample series 2 to match series 1
        shape1 = self.arrays1[0].shape
        shape2 = self.arrays2[0].shape
        if shape1 != shape2:
            INFO(f"Dimension mismatch: Series 1 {shape1} vs Series 2 {shape2}")
            INFO(f"Resampling Series 2 to match Series 1 dimensions...")
            # Compute zoom factors for bilinear interpolation
            zoom_factors = (shape1[0] / shape2[0], shape1[1] / shape2[1])
            self.arrays2 = [zoom(arr, zoom_factors, order=1) for arr in self.arrays2]
            INFO(f"Resampling complete")
        
        # Normalize
        self.norm_arrays1 = [normalize_image(arr) for arr in self.arrays1]
        self.norm_arrays2 = [normalize_image(arr) for arr in self.arrays2]
        
        # Current slice index
        self.current_slice = 0
        
        # Stats for debug output
        self.series_stats = {
            "series1": {
                "min": float(np.min([arr.min() for arr in self.arrays1])),
                "max": float(np.max([arr.max() for arr in self.arrays1])),
                "mean": float(np.mean([arr.mean() for arr in self.arrays1])),
            },
            "series2": {
                "min": float(np.min([arr.min() for arr in self.arrays2])),
                "max": float(np.max([arr.max() for arr in self.arrays2])),
                "mean": float(np.mean([arr.mean() for arr in self.arrays2])),
            },
        }
        
        # Save stats if debug enabled
        if debug_dir:
            self._save_debug_artifacts()
    
    def get_slice_overlay(self, slice_idx: int) -> np.ndarray:
        """
        Generate RGB overlay image for a given slice index.
        
        Parameters
        ----------
        slice_idx : int
            Index into common_z axis.
        
        Returns
        -------
        overlay_rgb : np.ndarray
            RGB image (H × W × 3) with both series overlaid.
        """
        # Interpolate indices
        idx1_float = self.interp_idx1[slice_idx]
        idx2_float = self.interp_idx2[slice_idx]
        
        # Get indices and weights for interpolation
        idx1_low = int(np.floor(idx1_float))
        idx1_high = int(np.ceil(idx1_float))
        weight1_high = idx1_float - idx1_low
        weight1_low = 1.0 - weight1_high
        
        idx2_low = int(np.floor(idx2_float))
        idx2_high = int(np.ceil(idx2_float))
        weight2_high = idx2_float - idx2_low
        weight2_low = 1.0 - weight2_high
        
        # Clamp indices
        idx1_low = np.clip(idx1_low, 0, len(self.norm_arrays1) - 1)
        idx1_high = np.clip(idx1_high, 0, len(self.norm_arrays1) - 1)
        idx2_low = np.clip(idx2_low, 0, len(self.norm_arrays2) - 1)
        idx2_high = np.clip(idx2_high, 0, len(self.norm_arrays2) - 1)
        
        # Interpolate series 1
        arr1 = (weight1_low * self.norm_arrays1[idx1_low] +
                weight1_high * self.norm_arrays1[idx1_high])
        
        # Interpolate series 2
        arr2 = (weight2_low * self.norm_arrays2[idx2_low] +
                weight2_high * self.norm_arrays2[idx2_high])
        
        # Apply colormaps
        rgb1 = self.cmap1(arr1)[:, :, :3]  # Drop alpha channel
        rgb2 = self.cmap2(arr2)[:, :, :3]
        
        # Blend
        overlay = self.alpha1 * rgb1 + self.alpha2 * rgb2
        overlay = np.clip(overlay, 0, 1)
        
        return overlay
    
    def show_interactive(self):
        """
        Display interactive viewer with slice navigation.
        """
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(f"Dual Series Overlay: slice index {self.current_slice}/{len(self.common_z)-1}")
        
        # Series 1 only
        im1 = axes[0].imshow(self.norm_arrays1[0], cmap=self.cmap1)
        axes[0].set_title("Series 1 (alone)")
        axes[0].set_xlabel("Column (pixel)")
        axes[0].set_ylabel("Row (pixel)")
        
        # Overlay
        overlay = self.get_slice_overlay(self.current_slice)
        im_overlay = axes[1].imshow(overlay)
        axes[1].set_title(f"Overlay (z={self.common_z[self.current_slice]:.2f} mm)")
        axes[1].set_xlabel("Column (pixel)")
        axes[1].set_ylabel("Row (pixel)")
        
        def update_slices(direction: int):
            """Update slice index and redraw."""
            self.current_slice = np.clip(
                self.current_slice + direction,
                0,
                len(self.common_z) - 1
            )
            
            idx1_float = self.interp_idx1[self.current_slice]
            idx1_low = int(np.floor(idx1_float))
            idx1_low = np.clip(idx1_low, 0, len(self.norm_arrays1) - 1)
            
            im1.set_data(self.norm_arrays1[idx1_low])
            overlay = self.get_slice_overlay(self.current_slice)
            im_overlay.set_data(overlay)
            
            fig.suptitle(f"Dual Series Overlay: slice index {self.current_slice}/{len(self.common_z)-1}")
            axes[1].set_title(f"Overlay (z={self.common_z[self.current_slice]:.2f} mm)")
            
            fig.canvas.draw_idle()
        
        def on_key(event):
            """Keyboard navigation: arrow keys or Page Up/Down."""
            if event.key in ("up", "pageup"):
                update_slices(1)
            elif event.key in ("down", "pagedown"):
                update_slices(-1)
        
        fig.canvas.mpl_connect("key_press_event", on_key)
        
        plt.tight_layout()
        plt.show()
    
    def save_all_overlays(self):
        """
        Save all overlay images to output directory.
        """
        INFO(f"Saving {len(self.common_z)} overlay images to {self.output_dir}...")
        for i, z_pos in enumerate(self.common_z):
            overlay = self.get_slice_overlay(i)
            # Convert to 0–255 uint8
            overlay_uint8 = (overlay * 255).astype(np.uint8)
            
            # Save using PIL
            try:
                from PIL import Image
                img = Image.fromarray(overlay_uint8)
                output_file = os.path.join(
                    self.output_dir,
                    f"overlay_slice_{i:03d}_z{z_pos:07.2f}.png"
                )
                img.save(output_file)
            except ImportError:
                # Fallback: use matplotlib
                import matplotlib.image as mimg
                output_file = os.path.join(
                    self.output_dir,
                    f"overlay_slice_{i:03d}_z{z_pos:07.2f}.png"
                )
                mimg.imsave(output_file, overlay)
        
        SUCCESS(f"Saved {len(self.common_z)} overlay images")
    
    def _save_debug_artifacts(self):
        """
        Save debug diagnostic artifacts.
        """
        if not self.debug_dir:
            return
        
        INFO(f"Saving debug artifacts to {self.debug_dir}...")
        
        # Coordinate map
        coord_map = create_coordinate_map(
            self.metadata1,
            self.metadata2,
            self.common_z,
        )
        coord_file = os.path.join(self.debug_dir, "coordinate_map.json")
        with open(coord_file, "w") as f:
            json.dump(coord_map, f, indent=2)
        
        # Series stats
        stats_file = os.path.join(self.debug_dir, "series_stats.json")
        with open(stats_file, "w") as f:
            json.dump(self.series_stats, f, indent=2)
        
        # Diagnostic plots
        diag_dir = os.path.join(self.debug_dir, "diagnostic_plots")
        os.makedirs(diag_dir, exist_ok=True)
        
        # Sample a few slices
        sample_indices = [0, len(self.common_z) // 2, -1]
        for i in sample_indices:
            slice_idx = i if i >= 0 else len(self.common_z) + i
            
            idx1_float = self.interp_idx1[slice_idx]
            idx1 = int(np.round(idx1_float))
            idx1 = np.clip(idx1, 0, len(self.norm_arrays1) - 1)
            
            idx2_float = self.interp_idx2[slice_idx]
            idx2 = int(np.round(idx2_float))
            idx2 = np.clip(idx2, 0, len(self.norm_arrays2) - 1)
            
            overlay = self.get_slice_overlay(slice_idx)
            
            fig, axes = plt.subplots(1, 3, figsize=(15, 4))
            axes[0].imshow(self.norm_arrays1[idx1], cmap=self.cmap1)
            axes[0].set_title(f"Series 1 (slice {idx1})")
            axes[1].imshow(self.norm_arrays2[idx2], cmap=self.cmap2)
            axes[1].set_title(f"Series 2 (slice {idx2})")
            axes[2].imshow(overlay)
            axes[2].set_title(f"Overlay (z={self.common_z[slice_idx]:.2f})")
            
            for ax in axes:
                ax.set_xlabel("Column (pixel)")
                ax.set_ylabel("Row (pixel)")
            
            plot_file = os.path.join(diag_dir, f"slice_{slice_idx:03d}.png")
            fig.savefig(plot_file, dpi=100, bbox_inches="tight")
            plt.close(fig)
        
        SUCCESS(f"Debug artifacts saved to {self.debug_dir}")


# ============================================================================
# Main
# ============================================================================

def main():
    """
    Main entry point.
    """
    parser = argparse.ArgumentParser(
        description="Load and overlay two DICOM image series with independent color scales.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dual_series_overlay.py --series1 ./pet_series --series2 ./ct_series
  python dual_series_overlay.py --series1 ./series1 --series2 ./series2 \\
                                --cmap1 viridis --cmap2 hot --output overlays
  python dual_series_overlay.py --series1 ./s1 --series2 ./s2 --debug ./debug_output
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
        "--cmap1",
        type=str,
        default="viridis",
        help="Colormap for series 1 (default: viridis). Options: viridis, plasma, hot, cool, etc.",
    )
    parser.add_argument(
        "--cmap2",
        type=str,
        default="hot",
        help="Colormap for series 2 (default: hot).",
    )
    parser.add_argument(
        "--alpha1",
        type=float,
        default=0.5,
        help="Opacity of series 1 (default: 0.5, range: 0–1).",
    )
    parser.add_argument(
        "--alpha2",
        type=float,
        default=0.5,
        help="Opacity of series 2 (default: 0.5, range: 0–1).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="overlay_output",
        help="Output directory for overlay images (default: overlay_output).",
    )
    parser.add_argument(
        "--debug",
        type=str,
        default=None,
        help="Enable debug mode; save diagnostic artifacts to this directory.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Show interactive viewer (default: False, just save overlays).",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save overlay images (useful with --interactive).",
    )
    
    args = parser.parse_args()
    
    # Validate inputs
    if not os.path.isdir(args.series1):
        ERROR(f"Series 1 directory not found: {args.series1}")
        return 1
    if not os.path.isdir(args.series2):
        ERROR(f"Series 2 directory not found: {args.series2}")
        return 1
    
    if args.alpha1 + args.alpha2 > 1.0:
        WARN(f"Sum of alphas ({args.alpha1 + args.alpha2}) exceeds 1.0; will clip to 1.0")
    
    try:
        # Load series
        INFO(f"Loading series 1 from {args.series1}...")
        datasets1, metadata1 = load_dicom_series(args.series1, debug=True)
        
        INFO(f"Loading series 2 from {args.series2}...")
        datasets2, metadata2 = load_dicom_series(args.series2, debug=True)
        
        # Create viewer
        viewer = DualSeriesViewer(
            datasets1,
            datasets2,
            metadata1,
            metadata2,
            cmap1=args.cmap1,
            cmap2=args.cmap2,
            alpha1=args.alpha1,
            alpha2=args.alpha2,
            output_dir=args.output,
            debug_dir=args.debug,
        )
        
        # Interactive viewer
        if args.interactive:
            INFO("Opening interactive viewer (use ↑/↓ arrow keys to navigate slices)...")
            viewer.show_interactive()
        
        # Save overlays
        if not args.no_save:
            viewer.save_all_overlays()
        
        SUCCESS("Done!")
        return 0
    
    except Exception as e:
        ERROR(f"Fatal error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
