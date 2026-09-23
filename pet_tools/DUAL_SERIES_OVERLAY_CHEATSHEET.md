# Dual Series Overlay — Quick Reference

## Installation & Setup

```bash
# No special installation needed; ensure dependencies are installed:
pip install numpy matplotlib pydicom pillow
```

## Quick Commands

### Most Basic
```bash
python dual_series_overlay.py --series1 /path/s1 --series2 /path/s2
```
→ Saves overlays to `./overlay_output/`

### Windows Users
Double-click `dual_series_overlay.bat` for an interactive menu.

### Different Colormaps
```bash
python dual_series_overlay.py --series1 s1 --series2 s2 --cmap1 viridis --cmap2 hot
```

### Adjust Transparency
```bash
python dual_series_overlay.py --series1 s1 --series2 s2 --alpha1 0.7 --alpha2 0.3
```
→ Series 1 is 70% opaque, Series 2 is 30%

### Interactive (No Save)
```bash
python dual_series_overlay.py --series1 s1 --series2 s2 --interactive --no-save
```
→ Navigate with arrow keys, no files saved

### Inspect Data
```bash
python dual_series_overlay.py --series1 s1 --series2 s2 --debug ./debug
```
→ Creates diagnostic plots, statistics, and coordinate maps

## Colormap Cheat Sheet

| Category | Colormaps |
|----------|-----------|
| **Warm** | `hot`, `autumn`, `summer`, `OrRd`, `YlOrRd` |
| **Cool** | `cool`, `Blues`, `Greens`, `winter`, `BuPu` |
| **Neutral** | `gray`, `Greys`, `bone`, `copper` |
| **Perceptual** | `viridis`, `plasma`, `inferno`, `magma`, `cividis` |
| **Diverging** | `coolwarm`, `RdBu`, `RdYlGn`, `PiYG` |

## Output Files

```
overlay_output/
  overlay_slice_000_z00.00.png    # First slice
  overlay_slice_001_z03.50.png    # Second slice (3.5mm higher)
  overlay_slice_002_z07.00.png
  ...
```

## Typical Use Cases

### PET/CT Fusion
```bash
python dual_series_overlay.py \
  --series1 pet_series \
  --series2 ct_series \
  --cmap1 hot --cmap2 gray \
  --alpha1 0.7 --alpha2 0.3
```

### Compare Two PET Protocols
```bash
python dual_series_overlay.py \
  --series1 early_pet \
  --series2 late_pet \
  --cmap1 viridis --cmap2 plasma
```

### Check Alignment Quality
```bash
python dual_series_overlay.py \
  --series1 s1 \
  --series2 s2 \
  --debug diagnostics \
  --alpha1 0.5 --alpha2 0.5
```
→ Creates sample diagnostic images in `diagnostics/diagnostic_plots/`

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **"No DICOM files found"** | Check folder path; ensure files end in `.dcm` |
| **Overlay looks dark/blank** | Increase alpha values; try `--alpha1 0.7 --alpha2 0.7` |
| **Series don't align spatially** | Check that both series cover same anatomy; run with `--debug` |
| **Out of memory** | Large series (>500 slices)? Save only the slices you need |
| **Can't see Series 2** | Try swapping `--alpha1` and `--alpha2` values |

## Understanding Output Filenames

```
overlay_slice_042_z123.45.png
           ↓        ↓
      slice index  z-coordinate in mm
```

Use the filename to identify which physical location (z) corresponds to each image.

## Key Parameters Explained

| Parameter | Range | Effect |
|-----------|-------|--------|
| `--alpha1` | 0.0–1.0 | Opacity of Series 1 (0=transparent, 1=opaque) |
| `--alpha2` | 0.0–1.0 | Opacity of Series 2 |
| `--cmap1` | colormap name | Visual style of Series 1 |
| `--cmap2` | colormap name | Visual style of Series 2 |

**Tip**: Keep `alpha1 + alpha2 ≤ 1.0` for best blending; `0.5 + 0.5` is a good default.

## Debug Mode Output

Running with `--debug /path/`:

```
/path/
  coordinate_map.json          ← Z-axis alignment info
  series_stats.json            ← Min/max/mean pixel values
  diagnostic_plots/
    slice_000.png              ← Compare Series 1, 2, and overlay
    slice_128.png
    slice_255.png
    ...
```

Use these to verify that:
1. Both series are loading correctly
2. Spatial alignment looks good
3. Value ranges are reasonable

## Python API (Advanced)

```python
from pet_tools.dual_series_overlay import DualSeriesViewer, load_dicom_series

# Load series
datasets1, meta1 = load_dicom_series("/path/s1")
datasets2, meta2 = load_dicom_series("/path/s2")

# Create viewer
viewer = DualSeriesViewer(
    datasets1, datasets2, meta1, meta2,
    cmap1="viridis", cmap2="hot",
    alpha1=0.6, alpha2=0.4,
)

# Interactive mode
viewer.show_interactive()

# Or save all overlays
viewer.save_all_overlays()
```

## File I/O Notes

- **Input**: DICOM files (`.dcm`) in folders
- **Output**: PNG images (8-bit RGB) + optional debug JSON/plots
- **No modifications** to original DICOM files
- **Coordinates preserved** from DICOM metadata

---

**Need help?** Run:
```bash
python dual_series_overlay.py --help
```
