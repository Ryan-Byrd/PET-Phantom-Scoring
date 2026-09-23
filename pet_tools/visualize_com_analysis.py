#!/usr/bin/env python3
"""
Visualize Center-of-Mass Analysis for Z-Axis Coregistration

Creates overlay plots showing:
1. Axial profiles from both series within the analysis window
2. COM positions marked on each profile
3. Weighted intensity distribution used for COM calculation
"""

import json
import csv
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from pathlib import Path


def load_profile_data(csv_path):
    """Load ROI profile data from CSV file."""
    data = {
        'slice_index': [],
        'z_position_mm': [],
        'series1_mean': [],
        'series2_mean': []
    }
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data['slice_index'].append(int(row['slice_index']))
            data['z_position_mm'].append(float(row['z_position_mm']))
            data['series1_mean'].append(float(row['series1_mean']))
            data['series2_mean'].append(float(row['series2_mean']))
    
    return data


def load_coregistration_data(json_path):
    """Load coregistration analysis results."""
    with open(json_path, 'r') as f:
        return json.load(f)


def compute_profile_center_of_mass(z_positions, profile_values):
    """Compute weighted mean position of profile."""
    profile_shifted = profile_values - np.min(profile_values)
    if np.sum(profile_shifted) == 0:
        return np.mean(z_positions)
    com_z = np.sum(z_positions * profile_shifted) / np.sum(profile_shifted)
    return com_z


def create_com_visualization(profile_data, coreg_data, output_path):
    """
    Create a comprehensive visualization of COM analysis.
    
    Shows:
    - Top: Axial profiles with COM markers
    - Bottom: Normalized intensity distributions used for COM weighting
    """
    z_positions = np.array(profile_data['z_position_mm'])
    series1_values = np.array(profile_data['series1_mean'])
    series2_values = np.array(profile_data['series2_mean'])
    
    z_mid_s1 = coreg_data['z_mid_series1_mm']
    z_mid_s2 = coreg_data['z_mid_series2_mm']
    window_mm = coreg_data['window_mm']
    com_s1 = coreg_data['com_series1_mm']
    com_s2 = coreg_data['com_series2_mm']
    
    # Select data within windows
    mask1 = np.abs(z_positions - z_mid_s1) <= window_mm
    mask2 = np.abs(z_positions - z_mid_s2) <= window_mm
    both_mask = mask1 & mask2
    
    z_common = z_positions[both_mask]
    s1_common = series1_values[both_mask]
    s2_common = series2_values[both_mask]
    
    # Normalize for weighting visualization
    s1_norm = s1_common - np.min(s1_common)
    s2_norm = s2_common - np.min(s2_common)
    
    if np.max(s1_norm) > 0:
        s1_norm = s1_norm / np.max(s1_norm)
    if np.max(s2_norm) > 0:
        s2_norm = s2_norm / np.max(s2_norm)
    
    # Create figure with subplots
    fig = plt.figure(figsize=(14, 10))
    
    # ========== TOP: Raw Profiles ==========
    ax1 = plt.subplot(2, 2, (1, 2))
    
    ax1.plot(z_common, s1_common, 'b-', linewidth=2.5, label='Series1 (PET)', alpha=0.8)
    ax1.plot(z_common, s2_common, 'r-', linewidth=2.5, label='Series2 (CT)', alpha=0.8)
    
    # Mark FWHM midpoints
    ax1.axvline(z_mid_s1, color='blue', linestyle='--', linewidth=1.5, alpha=0.6, label=f'Series1 FWHM center ({z_mid_s1:.1f} mm)')
    ax1.axvline(z_mid_s2, color='red', linestyle='--', linewidth=1.5, alpha=0.6, label=f'Series2 FWHM center ({z_mid_s2:.1f} mm)')
    
    # Mark COM positions
    ax1.axvline(com_s1, color='blue', linestyle=':', linewidth=3, alpha=0.9, label=f'Series1 COM ({com_s1:.1f} mm)')
    ax1.axvline(com_s2, color='red', linestyle=':', linewidth=3, alpha=0.9, label=f'Series2 COM ({com_s2:.1f} mm)')
    
    ax1.scatter([com_s1], [np.interp(com_s1, z_common, s1_common)], 
               color='blue', s=150, marker='v', edgecolors='darkblue', linewidths=2, zorder=5)
    ax1.scatter([com_s2], [np.interp(com_s2, z_common, s2_common)], 
               color='red', s=150, marker='v', edgecolors='darkred', linewidths=2, zorder=5)
    
    # Shade the analysis window
    window_rect = Rectangle((z_common[0], ax1.get_ylim()[0]), 
                           z_common[-1] - z_common[0], 
                           ax1.get_ylim()[1] - ax1.get_ylim()[0],
                           alpha=0.05, color='green', label='Analysis window')
    ax1.add_patch(window_rect)
    
    ax1.set_xlabel('Z Position (mm)', fontsize=11, fontweight='bold')
    ax1.set_ylabel('ROI Mean Intensity', fontsize=11, fontweight='bold')
    ax1.set_title('Axial ROI Profiles with Center-of-Mass (COM) Markers', fontsize=13, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='best', fontsize=9)
    
    # ========== BOTTOM LEFT: Normalized Weights (Series1) ==========
    ax2 = plt.subplot(2, 2, 3)
    
    ax2.fill_between(z_common, 0, s1_norm, color='blue', alpha=0.4, label='Weighting')
    ax2.plot(z_common, s1_norm, 'b-', linewidth=2)
    ax2.axvline(com_s1, color='blue', linestyle=':', linewidth=3, alpha=0.9)
    ax2.scatter([com_s1], [np.interp(com_s1, z_common, s1_norm)], 
               color='blue', s=120, marker='v', edgecolors='darkblue', linewidths=2, zorder=5)
    
    # Add COM calculation text
    com_calc = f"COM = Σ(z × w) / Σ(w)\n= {com_s1:.2f} mm"
    ax2.text(0.05, 0.95, com_calc, transform=ax2.transAxes, 
            fontsize=10, verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.7))
    
    ax2.set_xlabel('Z Position (mm)', fontsize=11, fontweight='bold')
    ax2.set_ylabel('Normalized Weight', fontsize=11, fontweight='bold')
    ax2.set_title('Series1 (PET) - COM Calculation', fontsize=12, fontweight='bold')
    ax2.set_ylim([0, 1.1])
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='best', fontsize=9)
    
    # ========== BOTTOM RIGHT: Normalized Weights (Series2) ==========
    ax3 = plt.subplot(2, 2, 4)
    
    ax3.fill_between(z_common, 0, s2_norm, color='red', alpha=0.4, label='Weighting')
    ax3.plot(z_common, s2_norm, 'r-', linewidth=2)
    ax3.axvline(com_s2, color='red', linestyle=':', linewidth=3, alpha=0.9)
    ax3.scatter([com_s2], [np.interp(com_s2, z_common, s2_norm)], 
               color='red', s=120, marker='v', edgecolors='darkred', linewidths=2, zorder=5)
    
    # Add COM calculation text
    com_calc = f"COM = Σ(z × w) / Σ(w)\n= {com_s2:.2f} mm"
    ax3.text(0.05, 0.95, com_calc, transform=ax3.transAxes, 
            fontsize=10, verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.7))
    
    ax3.set_xlabel('Z Position (mm)', fontsize=11, fontweight='bold')
    ax3.set_ylabel('Normalized Weight', fontsize=11, fontweight='bold')
    ax3.set_title('Series2 (CT) - COM Calculation', fontsize=12, fontweight='bold')
    ax3.set_ylim([0, 1.1])
    ax3.grid(True, alpha=0.3)
    ax3.legend(loc='best', fontsize=9)
    
    # Overall title with statistics
    offset_mm = com_s2 - com_s1
    fig.suptitle(
        f'Z-Axis Coregistration Analysis: Center-of-Mass Method\n'
        f'COM Offset: {offset_mm:.2f} mm | Window: ±{window_mm} mm | Slices: {len(z_common)}',
        fontsize=14, fontweight='bold', y=0.995
    )
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"[OK] Visualization saved: {output_path}")
    
    return fig


def create_overlay_comparison(profile_data, coreg_data, output_path):
    """
    Create an overlay comparison showing both series on the same plot.
    """
    z_positions = np.array(profile_data['z_position_mm'])
    series1_values = np.array(profile_data['series1_mean'])
    series2_values = np.array(profile_data['series2_mean'])
    
    z_mid_s1 = coreg_data['z_mid_series1_mm']
    z_mid_s2 = coreg_data['z_mid_series2_mm']
    window_mm = coreg_data['window_mm']
    com_s1 = coreg_data['com_series1_mm']
    com_s2 = coreg_data['com_series2_mm']
    
    # Select data within windows
    both_mask = (np.abs(z_positions - z_mid_s1) <= window_mm) & \
                (np.abs(z_positions - z_mid_s2) <= window_mm)
    
    z_common = z_positions[both_mask]
    s1_common = series1_values[both_mask]
    s2_common = series2_values[both_mask]
    
    # Normalize both for better comparison
    s1_norm = (s1_common - np.min(s1_common)) / (np.max(s1_common) - np.min(s1_common) + 1e-6)
    s2_norm = (s2_common - np.min(s2_common)) / (np.max(s2_common) - np.min(s2_common) + 1e-6)
    
    fig, ax = plt.subplots(figsize=(12, 7))
    
    # Plot normalized profiles
    ax.fill_between(z_common, 0, s1_norm, color='blue', alpha=0.3, label='Series1 (PET)')
    ax.plot(z_common, s1_norm, 'b-', linewidth=2.5)
    
    ax.fill_between(z_common, 0, s2_norm, color='red', alpha=0.3, label='Series2 (CT)')
    ax.plot(z_common, s2_norm, 'r-', linewidth=2.5)
    
    # Mark COMs
    ax.axvline(com_s1, color='blue', linestyle=':', linewidth=3, alpha=0.8, 
              label=f'Series1 COM: {com_s1:.2f} mm')
    ax.axvline(com_s2, color='red', linestyle=':', linewidth=3, alpha=0.8,
              label=f'Series2 COM: {com_s2:.2f} mm')
    
    # Markers
    ax.scatter([com_s1], [np.interp(com_s1, z_common, s1_norm)], 
              color='blue', s=200, marker='*', edgecolors='darkblue', linewidths=2, zorder=5)
    ax.scatter([com_s2], [np.interp(com_s2, z_common, s2_norm)], 
              color='red', s=200, marker='*', edgecolors='darkred', linewidths=2, zorder=5)
    
    # Vertical line showing offset
    ax.plot([com_s1, com_s2], [0.5, 0.5], 'k-', linewidth=2, alpha=0.5)
    ax.annotate('', xy=(com_s2, 0.5), xytext=(com_s1, 0.5),
               arrowprops=dict(arrowstyle='<->', color='black', lw=2))
    offset_mm = com_s2 - com_s1
    ax.text((com_s1 + com_s2) / 2, 0.55, f'Offset: {offset_mm:.2f} mm', 
           ha='center', fontsize=11, fontweight='bold',
           bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))
    
    ax.set_xlabel('Z Position (mm)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Normalized Intensity', fontsize=12, fontweight='bold')
    ax.set_title('COM Overlay Comparison: Series1 (PET) vs Series2 (CT)', 
                fontsize=13, fontweight='bold')
    ax.set_ylim([0, 1.1])
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right', fontsize=11)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"[OK] Overlay comparison saved: {output_path}")
    
    return fig


def main():
    # Paths
    script_dir = Path(__file__).parent.parent
    profile_csv = script_dir / "roi_profiles" / "roi_profile_data.csv"
    coreg_json = script_dir / "roi_profiles" / "z_axis_coregistration.json"
    viz_output = script_dir / "roi_profiles" / "com_analysis_detailed.png"
    overlay_output = script_dir / "roi_profiles" / "com_analysis_overlay.png"
    
    if not profile_csv.exists() or not coreg_json.exists():
        print(f"[ERROR] Required files not found")
        return
    
    print(f"[INFO] Loading profile data...")
    profile_data = load_profile_data(profile_csv)
    
    print(f"[INFO] Loading coregistration results...")
    coreg_data = load_coregistration_data(coreg_json)
    
    print(f"[INFO] Creating detailed COM visualization...")
    create_com_visualization(profile_data, coreg_data, viz_output)
    
    print(f"[INFO] Creating overlay comparison...")
    create_overlay_comparison(profile_data, coreg_data, overlay_output)
    
    print(f"[OK] Done! Check roi_profiles/ directory for visualizations")


if __name__ == "__main__":
    main()
