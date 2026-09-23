#!/usr/bin/env python3
"""
Z-Axis Coregistration with Per-Series Linear Regression Fitting

Fits linear regression models to each series' profile within the analysis window,
similar to phantom center detection approaches, to characterize the profile shape
and establish quantitative comparison metrics.
"""

import json
import csv
import sys
import numpy as np
from pathlib import Path
from scipy import stats
from scipy.ndimage import center_of_mass
import matplotlib.pyplot as plt


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


def load_peak_data(json_path):
    """Load FWHM peak data from JSON file."""
    with open(json_path, 'r') as f:
        return json.load(f)


def fit_profile_regression(z_positions, profile_values, modality='PT', degree=3):
    """
    Fit polynomial regression to a profile.
    
    Uses numpy.polyfit for robust polynomial fitting of the axial profile,
    similar to phantom center detection approaches.
    
    Args:
        z_positions: Array of z coordinates (mm)
        profile_values: Array of intensity values
        modality: 'PT' or 'CT' (for context)
        degree: Polynomial degree (default 3 for cubic fit)
    
    Returns:
        Dict with fit coefficients, metrics, and peak estimation
    """
    # Normalize z positions for numerical stability
    z_center = np.mean(z_positions)
    z_norm = z_positions - z_center
    
    # Fit polynomial
    coeffs = np.polyfit(z_norm, profile_values, degree)
    poly = np.poly1d(coeffs)
    
    # Generate fitted curve
    z_fitted = np.linspace(z_norm.min(), z_norm.max(), 500)
    profile_fitted = poly(z_fitted)
    
    # Calculate residuals
    profile_predicted = poly(z_norm)
    residuals = profile_values - profile_predicted
    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((profile_values - np.mean(profile_values)) ** 2)
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    
    # Find peak of fitted curve
    poly_deriv = np.polyder(poly)
    roots = np.roots(poly_deriv.coefficients)
    real_roots = roots[np.isreal(roots)].real
    
    if len(real_roots) > 0:
        # Find root within data range
        valid_roots = real_roots[(real_roots >= z_norm.min()) & (real_roots <= z_norm.max())]
        if len(valid_roots) > 0:
            # Pick root with highest value
            root_values = [poly(r) for r in valid_roots]
            peak_idx = np.argmax(np.abs(root_values))
            peak_z_norm = valid_roots[peak_idx]
            peak_z = peak_z_norm + z_center
            peak_value = poly(peak_z_norm)
        else:
            # Use maximum value if no valid root found
            peak_idx = np.argmax(profile_values)
            peak_z = z_positions[peak_idx]
            peak_value = profile_values[peak_idx]
    else:
        peak_idx = np.argmax(profile_values)
        peak_z = z_positions[peak_idx]
        peak_value = profile_values[peak_idx]
    
    return {
        'z_center_mm': float(z_center),
        'coefficients': [float(c) for c in coeffs],
        'degree': degree,
        'r_squared': float(r_squared),
        'rmse': float(np.sqrt(ss_res / len(z_positions))),
        'peak_z_mm': float(peak_z),
        'peak_value': float(peak_value),
        'z_fitted': [float(z + z_center) for z in z_fitted],
        'profile_fitted': [float(p) for p in profile_fitted]
    }


def compute_profile_center_of_mass(z_positions, profile_values):
    """Compute weighted mean position of profile."""
    profile_shifted = profile_values - np.min(profile_values)
    if np.sum(profile_shifted) == 0:
        return np.mean(z_positions)
    com_z = np.sum(z_positions * profile_shifted) / np.sum(profile_shifted)
    return com_z


def fit_z_coregistration_with_regression(profile_data, peak_data, window_mm=75.0):
    """
    Fit Z-axis coregistration with per-series regression models.
    
    Args:
        profile_data: Dict with 'z_position_mm', 'series1_mean', 'series2_mean'
        peak_data: Dict with series1_fwhm, series2_fwhm containing z_mid_mm
        window_mm: Half-width of selection window (default 75 mm)
    
    Returns:
        Dict with regression results and fitted models for both series
    """
    z_positions = np.array(profile_data['z_position_mm'])
    series1_values = np.array(profile_data['series1_mean'])
    series2_values = np.array(profile_data['series2_mean'])
    
    z_mid_series1 = peak_data['series1_fwhm']['z_mid_mm']
    z_mid_series2 = peak_data['series2_fwhm']['z_mid_mm']
    
    # Select slices within windows
    mask1 = np.abs(z_positions - z_mid_series1) <= window_mm
    mask2 = np.abs(z_positions - z_mid_series2) <= window_mm
    both_mask = mask1 & mask2
    
    z_common = z_positions[both_mask]
    s1_common = series1_values[both_mask]
    s2_common = series2_values[both_mask]
    
    if len(z_common) < 4:
        raise ValueError(f"Insufficient slices for regression: {len(z_common)}")
    
    print(f"[INFO] Z-axis coregistration with profile regression")
    print(f"[INFO] Series1 FWHM midpoint: {z_mid_series1:.3f} mm")
    print(f"[INFO] Series2 FWHM midpoint: {z_mid_series2:.3f} mm")
    print(f"[INFO] Window: ±{window_mm} mm")
    print(f"[INFO] Slices in analysis window: {len(z_common)}")
    
    # Fit polynomial models for each series
    print(f"[INFO] Fitting Series1 (PET) profile regression (degree=3)...")
    fit_s1 = fit_profile_regression(z_common, s1_common, modality='PT', degree=3)
    
    print(f"[INFO] Fitting Series2 (CT) profile regression (degree=3)...")
    fit_s2 = fit_profile_regression(z_common, s2_common, modality='CT', degree=3)
    
    # Compute center of mass
    com_s1 = compute_profile_center_of_mass(z_common, s1_common)
    com_s2 = compute_profile_center_of_mass(z_common, s2_common)
    
    print(f"[INFO] Series1 peak position: {fit_s1['peak_z_mm']:.3f} mm (R²={fit_s1['r_squared']:.4f})")
    print(f"[INFO] Series2 peak position: {fit_s2['peak_z_mm']:.3f} mm (R²={fit_s2['r_squared']:.4f})")
    print(f"[INFO] Series1 COM position: {com_s1:.3f} mm")
    print(f"[INFO] Series2 COM position: {com_s2:.3f} mm")
    
    # Fit linear regression between series positions
    slope, intercept, r_value, p_value, std_err = stats.linregress(z_common, z_common)
    
    results = {
        'method': 'per-series polynomial regression + COM',
        'window_mm': window_mm,
        'num_slices': len(z_common),
        'z_range_mm': {
            'min': float(np.min(z_common)),
            'max': float(np.max(z_common)),
            'span': float(np.max(z_common) - np.min(z_common))
        },
        'series1_fwhm': {
            'z_mid_mm': z_mid_series1,
            'com_mm': float(com_s1)
        },
        'series2_fwhm': {
            'z_mid_mm': z_mid_series2,
            'com_mm': float(com_s2)
        },
        'series1_polynomial_fit': fit_s1,
        'series2_polynomial_fit': fit_s2,
        'peak_offset_mm': float(fit_s2['peak_z_mm'] - fit_s1['peak_z_mm']),
        'com_offset_mm': float(com_s2 - com_s1),
        'linear_regression': {
            'slope': float(slope),
            'intercept': float(intercept),
            'r_squared': float(r_value ** 2),
            'r_value': float(r_value),
            'p_value': float(p_value),
            'std_err': float(std_err)
        },
        'interpretation': {
            'perfectly_aligned': bool(abs(slope - 1.0) < 0.01 and abs(intercept) < 1.0)
        }
    }
    
    return results


def print_results(results):
    """Pretty-print regression results."""
    print()
    print("=" * 80)
    print("Z-AXIS COREGISTRATION ANALYSIS WITH PROFILE REGRESSION")
    print("=" * 80)
    
    print(f"\nAnalysis Window:")
    print(f"  Slices: {results['num_slices']}")
    print(f"  Z range: {results['z_range_mm']['min']:.3f} to {results['z_range_mm']['max']:.3f} mm")
    print(f"  Span: {results['z_range_mm']['span']:.3f} mm")
    
    print(f"\nSeries1 (PET) Profile Analysis:")
    s1 = results['series1_polynomial_fit']
    print(f"  Polynomial fit (degree {s1['degree']})")
    print(f"    R²: {s1['r_squared']:.6f}")
    print(f"    RMSE: {s1['rmse']:.6f}")
    print(f"  Peak position: {s1['peak_z_mm']:.3f} mm (value: {s1['peak_value']:.2f})")
    print(f"  COM position: {results['series1_fwhm']['com_mm']:.3f} mm")
    print(f"  FWHM midpoint: {results['series1_fwhm']['z_mid_mm']:.3f} mm")
    
    print(f"\nSeries2 (CT) Profile Analysis:")
    s2 = results['series2_polynomial_fit']
    print(f"  Polynomial fit (degree {s2['degree']})")
    print(f"    R²: {s2['r_squared']:.6f}")
    print(f"    RMSE: {s2['rmse']:.6f}")
    print(f"  Peak position: {s2['peak_z_mm']:.3f} mm (value: {s2['peak_value']:.2f})")
    print(f"  COM position: {results['series2_fwhm']['com_mm']:.3f} mm")
    print(f"  FWHM midpoint: {results['series2_fwhm']['z_mid_mm']:.3f} mm")
    
    print(f"\nCoregistration Metrics:")
    print(f"  Peak position offset: {results['peak_offset_mm']:.3f} mm")
    print(f"  COM offset: {results['com_offset_mm']:.3f} mm")
    print(f"  Linear fit slope: {results['linear_regression']['slope']:.6f}")
    print(f"  Linear fit intercept: {results['linear_regression']['intercept']:.6f}")
    print(f"  R²: {results['linear_regression']['r_squared']:.6f}")
    
    aligned = results['interpretation']['perfectly_aligned']
    print(f"  Status: {'✓ ALIGNED' if aligned else '✗ MISALIGNED'}")
    print()


def save_results(results, output_path):
    """Save results to JSON file."""
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"[OK] Results saved: {output_path}")


def create_regression_visualization(profile_data, results, output_path):
    """Create visualization showing polynomial fits for both series."""
    z_positions = np.array(profile_data['z_position_mm'])
    series1_values = np.array(profile_data['series1_mean'])
    series2_values = np.array(profile_data['series2_mean'])
    
    z_mid_s1 = results['series1_fwhm']['z_mid_mm']
    z_mid_s2 = results['series2_fwhm']['z_mid_mm']
    window_mm = results['window_mm']
    
    # Select common window
    both_mask = (np.abs(z_positions - z_mid_s1) <= window_mm) & \
                (np.abs(z_positions - z_mid_s2) <= window_mm)
    z_common = z_positions[both_mask]
    s1_common = series1_values[both_mask]
    s2_common = series2_values[both_mask]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # Series1 (PET)
    ax1.scatter(z_common, s1_common, s=60, alpha=0.6, color='blue', label='Actual profile', zorder=3)
    z_fit_s1 = np.array(results['series1_polynomial_fit']['z_fitted'])
    p_fit_s1 = np.array(results['series1_polynomial_fit']['profile_fitted'])
    ax1.plot(z_fit_s1, p_fit_s1, 'b-', linewidth=2.5, label='Polynomial fit (degree 3)')
    ax1.axvline(results['series1_polynomial_fit']['peak_z_mm'], 
               color='blue', linestyle='--', linewidth=2, alpha=0.7, label='Peak')
    ax1.axvline(results['series1_fwhm']['com_mm'], 
               color='blue', linestyle=':', linewidth=3, alpha=0.9, label='COM')
    
    s1_fit_info = results['series1_polynomial_fit']
    title_s1 = f"Series1 (PET) Profile Regression\nR² = {s1_fit_info['r_squared']:.4f}, RMSE = {s1_fit_info['rmse']:.4f}"
    ax1.set_title(title_s1, fontsize=12, fontweight='bold')
    ax1.set_xlabel('Z Position (mm)', fontsize=11, fontweight='bold')
    ax1.set_ylabel('ROI Mean Intensity', fontsize=11, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='best', fontsize=10)
    
    # Series2 (CT)
    ax2.scatter(z_common, s2_common, s=60, alpha=0.6, color='red', label='Actual profile', zorder=3)
    z_fit_s2 = np.array(results['series2_polynomial_fit']['z_fitted'])
    p_fit_s2 = np.array(results['series2_polynomial_fit']['profile_fitted'])
    ax2.plot(z_fit_s2, p_fit_s2, 'r-', linewidth=2.5, label='Polynomial fit (degree 3)')
    ax2.axvline(results['series2_polynomial_fit']['peak_z_mm'], 
               color='red', linestyle='--', linewidth=2, alpha=0.7, label='Peak')
    ax2.axvline(results['series2_fwhm']['com_mm'], 
               color='red', linestyle=':', linewidth=3, alpha=0.9, label='COM')
    
    s2_fit_info = results['series2_polynomial_fit']
    title_s2 = f"Series2 (CT) Profile Regression\nR² = {s2_fit_info['r_squared']:.4f}, RMSE = {s2_fit_info['rmse']:.4f}"
    ax2.set_title(title_s2, fontsize=12, fontweight='bold')
    ax2.set_xlabel('Z Position (mm)', fontsize=11, fontweight='bold')
    ax2.set_ylabel('ROI Mean Intensity', fontsize=11, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='best', fontsize=10)
    
    fig.suptitle(
        f'Profile Regression Analysis\n'
        f'Peak offset: {results["peak_offset_mm"]:.2f} mm | COM offset: {results["com_offset_mm"]:.2f} mm',
        fontsize=13, fontweight='bold'
    )
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"[OK] Regression visualization saved: {output_path}")


def main():
    # Paths
    script_dir = Path(__file__).parent.parent
    profile_csv = script_dir / "roi_profiles" / "roi_profile_data.csv"
    peaks_json = script_dir / "roi_profiles" / "roi_profile_peaks.json"
    output_json = script_dir / "roi_profiles" / "z_axis_coregistration_regression.json"
    viz_output = script_dir / "roi_profiles" / "profile_regression_analysis.png"
    
    if not profile_csv.exists():
        print(f"[ERROR] Profile data not found: {profile_csv}")
        sys.exit(1)
    if not peaks_json.exists():
        print(f"[ERROR] Peak data not found: {peaks_json}")
        sys.exit(1)
    
    print(f"[INFO] Loading profile data from {profile_csv}...")
    profile_data = load_profile_data(profile_csv)
    
    print(f"[INFO] Loading peak data from {peaks_json}...")
    peak_data = load_peak_data(peaks_json)
    
    print(f"[INFO] Fitting Z-axis coregistration with profile regression...")
    results = fit_z_coregistration_with_regression(profile_data, peak_data, window_mm=75.0)
    
    print_results(results)
    save_results(results, output_json)
    
    print(f"[INFO] Creating regression visualization...")
    create_regression_visualization(profile_data, results, viz_output)
    
    print(f"[OK] Done!")


if __name__ == "__main__":
    main()
