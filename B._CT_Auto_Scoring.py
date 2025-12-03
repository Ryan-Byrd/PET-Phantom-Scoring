import os
import numpy as np
import pydicom
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

# ---------------------------------------------------------------------
# Hardcoded DICOM directory
# ---------------------------------------------------------------------
study_dir = r"C:\Users\RyanByrd\OneDrive - ONE Physics\Desktop\2_ACR ABDOMEN 300 Br40 S3 ax"

# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------
def find_dicom_files(folder):
    dcm_files = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".dcm"):
                dcm_files.append(os.path.join(root, f))
    return dcm_files

def load_dicom_sorted_by_z(dcm_files):
    slices = []
    for fp in dcm_files:
        try:
            ds = pydicom.dcmread(fp, force=True)
            ipp = getattr(ds, "ImagePositionPatient", None)
            if ipp is not None and len(ipp) >= 3:
                z = float(ipp[2])
            else:
                z = float(getattr(ds, "SliceLocation", 0.0))
            slices.append((z, fp, ds))
        except Exception:
            continue
    slices.sort(key=lambda t: t[0])
    return slices

def load_pixels(ds):
    arr = ds.pixel_array.astype(np.float32)
    slope = float(getattr(ds, "RescaleSlope", 1))
    inter = float(getattr(ds, "RescaleIntercept", 0))
    return arr * slope + inter

def window_image(arr, wc, ww):
    arr = arr.astype(np.float32)
    ww = max(float(ww), 1.0)
    wc = float(wc)
    vmin, vmax = wc - ww / 2.0, wc + ww / 2.0
    arr = np.clip(arr, vmin, vmax)
    return (arr - vmin) / (vmax - vmin)

# ---------------------------------------------------------------------
# Load and prepare slices
# ---------------------------------------------------------------------
dcm_files = find_dicom_files(study_dir)
slices = load_dicom_sorted_by_z(dcm_files)
if not slices:
    raise FileNotFoundError("No DICOM files found in the directory!")

ds0 = slices[len(slices)//2][2]
slice_thickness = float(getattr(ds0, "SliceThickness", 1.0))

# ---------------------------------------------------------------------
# Module definitions
# ---------------------------------------------------------------------
modules = [
    ("CT Numbers", 0, 400),
    ("Low Contrast Resolution", 100, 100),
    ("Uniformity", 0, 400),
    ("Spatial Resolution", 0, 1100)
]

# ---------------------------------------------------------------------
# Interactive 3×3 selector class
# ---------------------------------------------------------------------
class GridSelector:
    def __init__(self, slices, modules, slice_thickness):
        self.slices = slices
        self.modules = modules
        self.thickness = slice_thickness
        self.pick_index = None
        self.ref_index = None
        self.results = []
        self.mod_idx = 0
        self.page = 0
        self.display_grid()

    def display_grid(self):
        plt.close("all")
        n_slices = len(self.slices)
        start = self.page * 9
        end = min(start + 9, n_slices)
        subset = self.slices[start:end]

        mod_name, wc, ww = self.modules[self.mod_idx]
        fig, axes = plt.subplots(3, 3, figsize=(9, 9))
        fig.suptitle(
            f"{mod_name} — WL={wc}, WW={ww}\n"
            f"Page {self.page + 1}/{(n_slices + 8)//9} | "
            "Click to select | ←/→ to change page | Backspace to go back",
            fontsize=12
        )

        for ax, (z_abs, path, ds) in zip(axes.flat, subset):
            arr = load_pixels(ds)
            disp = window_image(arr, wc, ww)
            ax.imshow(disp, cmap="gray", origin="upper")

            # Show relative z if ref_index is defined
            if self.ref_index is not None:
                idx = next(i for i, (_, p, _) in enumerate(self.slices) if p == path)
                z_rel = (idx - self.ref_index) * self.thickness
                title_z = f"Δz = {z_rel:.1f} mm"
            else:
                title_z = f"z = {z_abs:.1f} mm"

            ax.set_title(title_z)
            ax.axis("off")
            ax.path = path
            ax.z_val = z_abs
            ax.ds = ds

        for ax in axes.flat[len(subset):]:
            ax.axis("off")

        fig.canvas.mpl_connect("button_press_event", self.onclick)
        fig.canvas.mpl_connect("key_press_event", self.onkey)
        plt.tight_layout(rect=[0, 0, 1, 0.93])
        plt.show(block=True)

    def onclick(self, event):
        if not hasattr(event, "inaxes") or event.inaxes is None:
            return
        ax = event.inaxes
        path = getattr(ax, "path", None)
        z = getattr(ax, "z_val", None)
        if path is None:
            return

        index = next(i for i, (_, p, _) in enumerate(self.slices) if p == path)
        if self.ref_index is None:
            self.ref_index = index
            print(f"📍 Defined zero point at slice index {index} (z = {z:.2f} mm)")

        z_rel = (index - self.ref_index) * self.thickness
        mod_name, _, _ = self.modules[self.mod_idx]
        self.results.append({
            "module": mod_name,
            "index": index,
            "z_rel_mm": z_rel,
            "path": path
        })

        print(f"✅ Selected {mod_name}: slice index {index}, Δz = {z_rel:.2f} mm")

        self.mod_idx += 1
        if self.mod_idx < len(self.modules):
            self.pick_index = index
            self.page = index // 9
            self.display_grid()
        else:
            print("\n✅ Selection complete!")
            for r in self.results:
                print(r)
            plt.close("all")
            self.run_hu_module()

    def onkey(self, event):
        n_pages = (len(self.slices) + 8) // 9
        if event.key == "right":
            if self.page < n_pages - 1:
                self.page += 1
                self.display_grid()
        elif event.key == "left":
            if self.page > 0:
                self.page -= 1
                self.display_grid()
        elif event.key == "backspace" and self.mod_idx > 0:
            print("↩️ Going back one module...")
            self.mod_idx -= 1
            self.results.pop()
            self.display_grid()

    # -----------------------------------------------------------------
    # HU module overlay and CSV export
    # -----------------------------------------------------------------
    def run_hu_module(self):
        hu_entry = next((r for r in self.results if r["module"] == "CT Numbers"), None)
        if not hu_entry:
            print("⚠️ No CT Numbers module found — skipping HU analysis.")
            return

        path = hu_entry["path"]
        ds = pydicom.dcmread(path)
        px = ds.pixel_array.astype(np.float32) * ds.RescaleSlope + ds.RescaleIntercept

        pixel_spacing = np.array(ds.PixelSpacing, dtype=float)
        px_size = pixel_spacing.mean()

        roi_radius_mm = 7.9788
        roi_offset_mm = 63
        angles_deg = [180, 225, 316, 47, 135]
        materials = ["Water", "Acrylic", "Air", "Bone", "Polyethylene"]

        rows, cols = px.shape
        center = np.array([rows / 2, cols / 2])
        roi_radius_px = roi_radius_mm / px_size
        roi_offset_px = roi_offset_mm / px_size

        roi_results = []
        for material, angle in zip(materials, angles_deg):
            theta = np.deg2rad(angle)
            y = center[0] - roi_offset_px * np.sin(theta)
            x = center[1] + roi_offset_px * np.cos(theta)

            Y, X = np.ogrid[:rows, :cols]
            mask = (X - x)**2 + (Y - y)**2 <= roi_radius_px**2
            roi_values = px[mask]

            mean_hu = np.mean(roi_values)
            std_hu = np.std(roi_values)
            roi_results.append((material, mean_hu, std_hu, (x, y)))

        # Overlay plot
        fig, ax = plt.subplots(figsize=(7, 7))
        ax.imshow(px, cmap="gray", vmin=-1000, vmax=1000)
        ax.set_title("CT Number Module — HU Overlay", fontsize=14)
        for (material, mean_hu, std_hu, (x, y)) in roi_results:
            circ = Circle((x, y), roi_radius_px, edgecolor="coral", facecolor="none", lw=2)
            ax.add_patch(circ)
            ax.text(x, y, f"{material}\n{mean_hu:.2f} HU", color="maroon",
                    ha="center", va="center", fontsize=12, fontname="Verdana")
        ax.axis("off")
        plt.tight_layout()
        plt.show()

        # Print and export to CSV
        print("\n=== HU Results (Clockwise from Water) ===")
        for mat, hu, std, _ in roi_results:
            print(f"{mat:15s}: {hu:8.2f} ± {std:6.2f} HU")

        import csv
        output_name = "HU_Module_Results.csv"
        output_path = os.path.join(os.path.expanduser("~"), "Desktop", output_name)
        with open(output_path, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Material", "Mean HU", "Std HU"])
            for mat, hu, std, _ in roi_results:
                writer.writerow([mat, f"{hu:.2f}", f"{std:.2f}"])
        print(f"\n✅ HU results saved to: {output_path}")

# ---------------------------------------------------------------------
# Run interactive interface
# ---------------------------------------------------------------------
GridSelector(slices, modules, slice_thickness)
