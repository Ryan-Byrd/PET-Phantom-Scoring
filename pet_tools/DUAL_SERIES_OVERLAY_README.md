# Dual Series Overlay — Usage Guide

## Overview

The **Dual Series Overlay** tool loads two DICOM medical image series (e.g., PET + CT, or two different imaging protocols) and displays them simultaneously in the same spatial coordinates. Each series can have its own independent color scale and opacity setting.

## Key Features

✓ **Simultaneous Multi-Series Display** — Load any two DICOM series at once  
✓ **Independent Color Scales** — Use different colormaps (viridis, hot, plasma, etc.) for each series  
✓ **Automatic Spatial Alignment** — DICOM coordinates (x, y, z) are preserved and aligned  
✓ **Interactive Navigation** — Scroll through slices with arrow keys or Page Up/Down  
✓ **Batch Export** — Save all overlay images as PNG files  
✓ **Debug Diagnostics** — Optional output: coordinate maps, statistics, and diagnostic plots  

## Quick Start

### Basic Usage

```bash
python dual_series_overlay.py --series1 /path/to/series1 --series2 /path/to/series2
```

This will save all overlay images to `./overlay_output/`.

### With Custom Colormaps and Opacity

```bash
python dual_series_overlay.py \
  --series1 ./pet_folder \
  --series2 ./ct_folder \
  --cmap1 plasma \
  --cmap2 gray \
  --alpha1 0.6 \
  --alpha2 0.4 \
  --output ./my_overlays
```

### Interactive Viewer (No Save)

```bash
python dual_series_overlay.py \
  --series1 ./series1 \
  --series2 ./series2 \
  --interactive \
  --no-save
```

Use **↑** or **Page Up** to move forward through slices; **↓** or **Page Down** to move backward.

### With Debug Output

```bash
python dual_series_overlay.py \
  --series1 ./s1 \
  --series2 ./s2 \
  --debug ./debug_artifacts
```

This creates:
- `coordinate_map.json` — Physical (x, y, z) positions and slice mappings
- `series_stats.json` — Min/max/mean pixel values for each series
- `diagnostic_plots/` — Sample slice visualizations (both series alone and overlaid)

## Command-Line Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--series1` | path | **required** | First DICOM series folder |
| `--series2` | path | **required** | Second DICOM series folder |
| `--cmap1` | str | `viridis` | Colormap for series 1 |
| `--cmap2` | str | `hot` | Colormap for series 2 |
| `--alpha1` | float | `0.5` | Opacity of series 1 (0–1) |
| `--alpha2` | float | `0.5` | Opacity of series 2 (0–1) |
| `--output` | path | `overlay_output` | Directory to save images |
| `--debug` | path | — | Directory for debug artifacts |
| `--interactive` | flag | False | Show interactive viewer |
| `--no-save` | flag | False | Skip saving overlay images |

## Available Colormaps

Popular choices:
- **Perceptual**: `viridis`, `plasma`, `inferno`, `magma`, `cividis`
- **Sequential**: `gray`, `Greys`, `Blues`, `Greens`, `Reds`, `Purples`
- **Diverging**: `coolwarm`, `RdBu`, `PiYG`, `Spectral`
- **Cyclic**: `hsv`, `twilight`

For a complete list, see [Matplotlib Colormaps](https://matplotlib.org/stable/tutorials/colors/colormaps.html).

## Understanding the Output

### Overlay PNG Images

- **File naming**: `overlay_slice_NNN_zXXXX.XX.png`
  - `NNN` — slice index (0-based)
  - `XXXX.XX` — z-coordinate in mm (from DICOM ImagePositionPatient or SliceLocation)
- **Format**: RGB PNG, 8-bit per channel
- **Dimensions**: Same as input DICOM images (e.g., 512×512 pixels)

### Debug Artifacts

#### `coordinate_map.json`
Maps each slice index to physical coordinates:
```json
{
  "common_z_axis": [0.0, 3.5, 7.0, ...],
  "series1_z": [0.0, 3.5, 7.0, ...],
  "series2_z": [0.1, 3.6, 7.1, ...]
}
```

#### `series_stats.json`
Image value statistics (useful for choosing opacity and normalization):
```json
{
  "series1": {
    "min": -1024.5,
    "max": 3071.2,
    "mean": 45.3
  },
  "series2": {
    "min": 0.0,
    "max": 15.5,
    "mean": 2.1
  }
}
```

#### `diagnostic_plots/`
Sample images comparing:
- Series 1 alone (with cmap1)
- Series 2 alone (with cmap2)
- Blended overlay (both series combined)

## Mathematical Details

### Coordinate Alignment

Both series are automatically aligned to a **common z-axis** (slice position grid). If the two series have different slice spacings, linear interpolation is used to create a unified view.

**Physical coordinates** are computed as:
```
x = ImagePositionPatient[0] + row_index × PixelSpacing[0]
y = ImagePositionPatient[1] + col_index × PixelSpacing[1]
z = SliceLocation (or ImagePositionPatient[2])
```

### Color Blending

Each series is independently normalized to [0, 1] using robust percentile clipping (2nd–98th percentiles). The overlay is then computed per-pixel as:

```
overlay(x, y) = α₁ × normalized(series1) × cmap1 +
                α₂ × normalized(series2) × cmap2
```

where `α₁` and `α₂` are the opacity parameters.

### Interpolation

If slices do not align exactly, bilinear interpolation is used:
```
interpolated_value = w₁ × value[k] + w₂ × value[k+1]
```
where `w₁ + w₂ = 1` and the weights are computed from the fractional slice index.

## Requirements

### Python Packages
- `numpy` — Array operations
- `matplotlib` — Visualization and colormaps
- `pydicom` — DICOM file reading
- `pillow` (optional) — PNG export (fallback to matplotlib if not installed)

### DICOM Files
Both series should be standard medical images with:
- PixelData (8, 16, or 32-bit)
- Rows, Columns (image dimensions)
- PixelSpacing (mm per pixel)
- SliceLocation or ImagePositionPatient (z-coordinate)

## Troubleshooting

### "No DICOM files found"
- Ensure the folder path is correct
- Check that files have `.dcm` extension or are readable by pydicom

### "No SliceLocation or ImagePositionPatient"
- Some DICOM files may lack proper slice position metadata
- Verify the series is valid using a DICOM viewer

### Black or blank overlay
- Check opacity settings; if both alphas are very small, the image will be dark
- Try `--debug` to inspect individual series statistics and sample images

### Memory issues with large series
- Reduce the number of slices (save only a subset)
- Consider processing series separately if >500 slices

## Examples

### PET + CT Fusion
```bash
python dual_series_overlay.py \
  --series1 ./pet_ac_series \
  --series2 ./ct_series \
  --cmap1 hot \
  --cmap2 gray \
  --alpha1 0.7 \
  --alpha2 0.3 \
  --output ./pet_ct_fusion
```

### Two PET Protocols (Early vs Delayed)
```bash
python dual_series_overlay.py \
  --series1 ./pet_early_imaging \
  --series2 ./pet_delayed_imaging \
  --cmap1 viridis \
  --cmap2 plasma \
  --output ./early_vs_delayed
```

### Debug Run with Diagnostics
```bash
python dual_series_overlay.py \
  --series1 ./series1 \
  --series2 ./series2 \
  --debug ./diagnostic_output \
  --interactive
```

## Regulatory / Standards Notes

This tool follows DICOM Part 3 standards for:
- **Image Pixel Module** — Rows (0028,0008), Columns (0028,0009), PixelSpacing (0028,0030)
- **Image Position/Orientation** — ImagePositionPatient (0020,0032), SliceLocation (0020,1041)
- **Pixel Data** — Rescale Slope/Intercept (0028,1052/1053) applied when present

No modifications are made to the original DICOM files; output is PNG overlay images only.

## Questions or Issues?

If you encounter problems or have suggestions, check:
1. That both series are from the same anatomical region (overlapping z-range)
2. That DICOM files are not corrupted (validate with a DICOM viewer first)
3. Run with `--debug` to inspect intermediate outputs
4. Check console output for specific error messages

---

**Version**: 1.0  
**Last Updated**: 2026-01-31
