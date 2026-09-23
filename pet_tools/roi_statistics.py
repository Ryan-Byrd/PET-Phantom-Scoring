#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
roi_statistics.py
Analyzes a PET series by drawing a centered 180mm diameter ROI on each slice
and computing SUV statistics (mean, max, min, standard deviation).

Features:
- Loads PET DICOM series from input directory
- Computes SUV for each slice
- Auto-detects phantom center
- Draws 180mm diameter ROI centered on phantom
- Calculates and plots SUV statistics across all slices
- Saves results as CSV and PNG plot
- Supports debug mode with configurable output directory

Usage:
    python roi_statistics.py --input <dicom_folder> --output <output_folder>
    python roi_statistics.py --input <folder> --output <folder> --debug --debug-dir <debug_folder>
    python roi_statistics.py --config config.json
"""

import os
import sys
import argparse
import json
import csv
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

# Import from existing pet_tools module
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from pet_tools import suv_overlay_manual as PET

# Reuse existing utilities
INFO = PET.INFO
WARN = PET.WARN
ERROR = PET.ERROR
ask_folder = PET.ask_folder
ask_output_folder_and_name = PET.ask_output_folder_and_name
load_series = PET.load_series
suv_from_ds = PET.suv_from_ds
find_phantom_center_generalized = PET.find_phantom_center_generalized

# Configuration
ROI_DIAMETER_MM = 180.0  # ROI diameter in mm


def create_circular_mask(shape, center, radius_pixels):
    """
    Create a circular mask for ROI analysis.
    
    Args:
        shape: tuple (rows, cols) of image shape
        center: tuple (cy, cx) center position in pixels
        radius_pixels: radius in pixels
    
    Returns:
        Boolean mask array where True indicates pixels inside the circle
    """
    rows, cols = shape
    cy, cx = center
    y, x = np.ogrid[:rows, :cols]
    mask = (x - cx)**2 + (y - cy)**2 <= radius_pixels**2
    return mask


def compute_roi_statistics(suv_image, center_px, radius_px):
    """
    Compute statistics for ROI defined by center and radius.
    
    Args:
        suv_image: 2D numpy array of SUV values
        center_px: tuple (cy, cx) center in pixels
        radius_px: radius in pixels
    
    Returns:
        Dictionary with keys: mean, max, min, std
    """
    mask = create_circular_mask(suv_image.shape, center_px, radius_px)
    roi_values = suv_image[mask]
    
    # Filter out any NaN or invalid values
    roi_values = roi_values[np.isfinite(roi_values)]
    
    if len(roi_values) == 0:
        WARN("No valid pixels in ROI")
        return {"mean": 0.0, "max": 0.0, "min": 0.0, "std": 0.0}
    
    return {
        "mean": float(np.mean(roi_values)),
        "max": float(np.max(roi_values)),
        "min": float(np.min(roi_values)),
        "std": float(np.std(roi_values))
    }


def plot_statistics(stats_list, output_path, roi_diameter_mm):
    """
    Create a plot showing SUV statistics across all slices.
    
    Args:
        stats_list: list of dicts with statistics for each slice
        output_path: path to save the plot
        roi_diameter_mm: ROI diameter for plot title
    """
    slice_indices = list(range(len(stats_list)))
    means = [s["mean"] for s in stats_list]
    maxs = [s["max"] for s in stats_list]
    mins = [s["min"] for s in stats_list]
    stds = [s["std"] for s in stats_list]
    ratios = [s["max"] / s["mean"] if s["mean"] > 0 else 0 for s in stats_list]
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 12))
    
    # Top plot: SUV statistics
    ax1.plot(slice_indices, means, 'o-', label='Mean', linewidth=2, markersize=6)
    ax1.plot(slice_indices, maxs, 's-', label='Max', linewidth=2, markersize=6)
    ax1.plot(slice_indices, mins, '^-', label='Min', linewidth=2, markersize=6)
    ax1.plot(slice_indices, stds, 'd-', label='Std Dev', linewidth=2, markersize=6)
    
    ax1.set_xlabel('Slice Index', fontsize=12)
    ax1.set_ylabel('SUV', fontsize=12)
    ax1.set_title(f'SUV Statistics - {roi_diameter_mm:.0f}mm Diameter ROI', fontsize=14, weight='bold')
    ax1.legend(loc='best', fontsize=11)
    ax1.grid(True, alpha=0.3)
    
    # Bottom plot: Max/Mean ratio
    ax2.plot(slice_indices, ratios, 'v-', label='Max/Mean Ratio', linewidth=2, markersize=6, color='purple')
    ax2.axhline(y=1.0, color='gray', linestyle='--', linewidth=1, alpha=0.5)
    
    ax2.set_xlabel('Slice Index', fontsize=12)
    ax2.set_ylabel('Max/Mean Ratio', fontsize=12)
    ax2.set_title('Max/Mean Ratio', fontsize=12, weight='bold')
    ax2.legend(loc='best', fontsize=11)
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    INFO(f"Statistics plot saved: {output_path}")


def save_statistics_csv(stats_list, output_path, roi_diameter_mm):
    """
    Save statistics to CSV file.
    
    Args:
        stats_list: list of dicts with statistics for each slice
        output_path: path to save CSV
        roi_diameter_mm: ROI diameter for header
    """
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([f"ROI Statistics - {roi_diameter_mm:.0f}mm Diameter"])
        writer.writerow([])
        writer.writerow(["Slice Index", "Mean SUV", "Max SUV", "Min SUV", "Std Dev SUV", "Max/Mean Ratio"])
        
        for idx, stats in enumerate(stats_list):
            ratio = stats['max'] / stats['mean'] if stats['mean'] > 0 else 0
            writer.writerow([
                idx,
                f"{stats['mean']:.4f}",
                f"{stats['max']:.4f}",
                f"{stats['min']:.4f}",
                f"{stats['std']:.4f}",
                f"{ratio:.4f}"
            ])
        
        writer.writerow([])
        writer.writerow(["Overall Statistics"])
        all_means = [s["mean"] for s in stats_list]
        all_maxs = [s["max"] for s in stats_list]
        all_mins = [s["min"] for s in stats_list]
        all_stds = [s["std"] for s in stats_list]
        all_ratios = [s["max"] / s["mean"] if s["mean"] > 0 else 0 for s in stats_list]
        
        writer.writerow(["", "Mean", "Max", "Min", "Std Dev", "Max/Mean Ratio"])
        writer.writerow(["Average across slices",
                        f"{np.mean(all_means):.4f}",
                        f"{np.mean(all_maxs):.4f}",
                        f"{np.mean(all_mins):.4f}",
                        f"{np.mean(all_stds):.4f}",
                        f"{np.mean(all_ratios):.4f}"])
    
    INFO(f"Statistics CSV saved: {output_path}")


def save_roi_visualization(suv_images, centers_px, radius_px, pixel_mm, output_dir, roi_diameter_mm):
    """
    Save visualization of ROIs on selected slices.
    
    Args:
        suv_images: list of SUV images
        centers_px: list of center coordinates in pixels
        radius_px: ROI radius in pixels
        pixel_mm: tuple (row_mm, col_mm)
        output_dir: output directory
        roi_diameter_mm: ROI diameter for labeling
    """
    # Select a few representative slices
    n_slices = len(suv_images)
    indices = [0, n_slices//4, n_slices//2, 3*n_slices//4, n_slices-1]
    indices = [i for i in indices if i < n_slices]
    
    n_display = len(indices)
    cols = min(3, n_display)
    rows = (n_display + cols - 1) // cols
    
    fig, axes = plt.subplots(rows, cols, figsize=(5*cols, 5*rows))
    if n_display == 1:
        axes = [axes]
    else:
        axes = axes.ravel() if hasattr(axes, 'ravel') else axes
    
    row_mm, col_mm = pixel_mm
    
    for ax_idx, slice_idx in enumerate(indices):
        if ax_idx >= len(axes):
            break
        
        ax = axes[ax_idx]
        suv_img = suv_images[slice_idx]
        cy, cx = centers_px[slice_idx]
        
        # Display SUV image (0-3 SUV range, inverted for white background)
        display_img = np.clip(suv_img, 0, 3) / 3.0
        display_img = 1.0 - display_img  # invert
        
        h, w = suv_img.shape
        extent = [0, w * col_mm, h * row_mm, 0]
        
        ax.imshow(display_img, cmap='gray', extent=extent, origin='upper')
        ax.set_aspect('equal')
        
        # Draw ROI circle
        circle = Circle((cx * col_mm, cy * row_mm), radius_px * col_mm,
                       fill=False, edgecolor='red', linewidth=2)
        ax.add_patch(circle)
        
        # Mark center
        ax.plot([cx * col_mm], [cy * row_mm], 'r+', markersize=15, markeredgewidth=2)
        
        ax.set_title(f'Slice {slice_idx}', fontsize=10)
        ax.axis('off')
    
    # Hide unused subplots
    for ax_idx in range(len(indices), len(axes)):
        axes[ax_idx].axis('off')
    
    fig.suptitle(f'ROI Visualization - {roi_diameter_mm:.0f}mm Diameter', fontsize=14, weight='bold')
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, "roi_visualization.png")
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    INFO(f"ROI visualization saved: {output_path}")


def load_config(path):
    """Load configuration from JSON file."""
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        WARN(f"Failed to load config: {e}")
        return {}


def main(argv=None):
    """Main entry point for ROI statistics analysis."""
    parser = argparse.ArgumentParser(
        description="Analyze PET series with centered 180mm ROI and compute SUV statistics."
    )
    parser.add_argument("--input", "-i", help="Input DICOM folder (optional; else dialog)")
    parser.add_argument("--output", "-o", help="Output folder (optional; else dialog)")
    parser.add_argument("--config", help="Optional JSON config file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--debug-dir", help="Directory for debug artifacts")
    args = parser.parse_args(argv)
    
    cfg = load_config(args.config)
    debug_enabled = args.debug or cfg.get("debug", False)
    debug_dir = args.debug_dir or cfg.get("debug_dir")
    
    if debug_enabled:
        INFO("Debug logging enabled")
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        INFO(f"Debug artifacts directory: {debug_dir}")
    
    # Get input/output directories
    in_dir = args.input or cfg.get("input")
    out_dir = args.output or cfg.get("output")
    
    if not in_dir:
        in_dir = ask_folder("Select PET DICOM Folder (INPUT)")
    if not in_dir:
        INFO("Cancelled: no input folder")
        return 1
    
    if not out_dir:
        out_dir = ask_output_folder_and_name()
    if not out_dir:
        INFO("Cancelled: no output folder")
        return 1
    
    os.makedirs(out_dir, exist_ok=True)
    
    # Load PET series
    INFO("Loading PET DICOM series...")
    try:
        disp_imgs, res_imgs, dsets, pixel_mm = load_series(in_dir)
    except Exception as e:
        ERROR(f"Failed to load series: {e}")
        return 1
    
    row_mm, col_mm = pixel_mm
    INFO(f"Loaded {len(dsets)} slices | Pixel spacing: {row_mm:.3f} x {col_mm:.3f} mm")
    
    # Compute SUV for all slices
    INFO("Computing SUV values...")
    suv_images = []
    for ds, raw in zip(dsets, res_imgs):
        suv, _, _ = suv_from_ds(ds, raw)
        suv_images.append(suv.astype(np.float32))
    
    # Auto-detect phantom center for each slice
    INFO("Detecting phantom centers...")
    centers_px = []
    radius_px = (ROI_DIAMETER_MM / 2.0) / col_mm  # assume square pixels
    
    px_spacing = np.mean([row_mm, col_mm])
    modality = str(getattr(dsets[0], "Modality", "PT"))
    
    for idx, ds in enumerate(dsets):
        px_array = ds.pixel_array.astype(np.float32)
        cy, cx, _r = find_phantom_center_generalized(
            px_array, 
            pixel_size_mm=px_spacing, 
            modality=modality, 
            debug=debug_enabled
        )
        centers_px.append((cy, cx))
        if debug_enabled and idx == len(dsets) // 2:
            INFO(f"Mid-slice center: ({cx:.1f}, {cy:.1f}) pixels")
    
    INFO(f"ROI diameter: {ROI_DIAMETER_MM:.0f} mm ({radius_px*2:.1f} pixels)")
    
    # Compute statistics for each slice
    INFO("Computing ROI statistics...")
    stats_list = []
    for idx, (suv_img, center) in enumerate(zip(suv_images, centers_px)):
        stats = compute_roi_statistics(suv_img, center, radius_px)
        stats_list.append(stats)
        if debug_enabled and idx % 10 == 0:
            INFO(f"Slice {idx}: Mean={stats['mean']:.3f}, Max={stats['max']:.3f}, "
                 f"Min={stats['min']:.3f}, Std={stats['std']:.3f}")
    
    # Save results
    INFO("Saving results...")
    csv_path = os.path.join(out_dir, "roi_statistics.csv")
    save_statistics_csv(stats_list, csv_path, ROI_DIAMETER_MM)
    
    plot_path = os.path.join(out_dir, "roi_statistics_plot.png")
    plot_statistics(stats_list, plot_path, ROI_DIAMETER_MM)
    
    save_roi_visualization(suv_images, centers_px, radius_px, pixel_mm, out_dir, ROI_DIAMETER_MM)
    
    INFO(f"Analysis complete! Results saved to: {out_dir}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        ERROR(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
