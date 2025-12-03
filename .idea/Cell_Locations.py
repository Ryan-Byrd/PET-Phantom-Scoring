import os
import tkinter as tk
from tkinter import filedialog, messagebox
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import pydicom
import numpy as np
import csv
import matplotlib
matplotlib.use("Qt5Agg")  # use Qt backend, handles mouse events cleanly on Windows


LABELS = ["25", "16", "12", "8", "Bone", "Air", "Water"]
FOV_MM = 250.0  # zoomed field of view (square), in millimetres

# ------------------ Final working Windows-friendly crosshair ------------------
class SimpleCrosshair:
    """Crosshair that reliably follows the mouse on all backends (Windows included)."""
    def __init__(self, ax, color='yellow', lw=1.2, ls='--'):
        self.ax = ax
        self.color = color

        # start in the middle of current view
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        cx = (xlim[0] + xlim[1]) / 2
        cy = (ylim[0] + ylim[1]) / 2

        # draw initial lines/text
        self.hline = ax.axhline(y=cy, color=color, lw=lw, ls=ls, zorder=999)
        self.vline = ax.axvline(x=cx, color=color, lw=lw, ls=ls, zorder=999)
        self.text = ax.text(
            0.72, 0.9, f"x={cx:.1f}, y={cy:.1f}",
            transform=ax.transAxes, color=color, fontsize=8,
            backgroundcolor='black', zorder=999
        )

        # explicitly connect to the figure canvas, not just the axes
        cid = ax.figure.canvas.mpl_connect('motion_notify_event', self.on_move)
        print(f"[DEBUG] Crosshair connected with id={cid}")
        ax.figure.canvas.draw_idle()

    def on_move(self, event):
        """Update crosshair when the mouse moves."""
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        x, y = event.xdata, event.ydata
        # update positions
        self.hline.set_ydata([y])
        self.vline.set_xdata([x])
        self.text.set_text(f"x={x:.1f}, y={y:.1f}")
        # redraw only these three artists for speed
        self.ax.draw_artist(self.hline)
        self.ax.draw_artist(self.vline)
        self.ax.draw_artist(self.text)
        self.ax.figure.canvas.flush_events()

def attach_crosshair(ax, color='yellow'):
    """Attach a crosshair that always follows the cursor."""
    import matplotlib
    print(f"[INFO] Matplotlib backend → {matplotlib.get_backend()}")
    ch = SimpleCrosshair(ax, color=color)
    print("[INFO] Crosshair ready and following cursor.")
    return ch

# ------------------ UI helpers ------------------
def select_dicom_file():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Select a DICOM file",
        filetypes=[("DICOM files", "*.dcm")]
    )
    return file_path

def set_fov_mm(ax, center_mm, fov_mm=FOV_MM):
    """Zoom the axes to a square FOV (fov_mm × fov_mm) centered at center_mm (in mm)."""
    half = fov_mm / 2.0
    cx, cy = center_mm
    ax.set_xlim(cx - half, cx + half)
    # origin='upper' => invert y-limits to preserve visual orientation
    ax.set_ylim(cy + half, cy - half)

# ------------------ DICOM load ------------------
def load_dicom(file_path):
    ds = pydicom.dcmread(file_path)
    img = ds.pixel_array.astype(float)
    # Rescale (if present)
    slope = float(getattr(ds, "RescaleSlope", 1.0))
    inter = float(getattr(ds, "RescaleIntercept", 0.0))
    img = img * slope + inter
    # Normalize only for display
    disp = img / (np.max(img) if np.max(img) else 1.0)

    # Pixel spacing (mm)
    px = getattr(ds, "PixelSpacing", [1.0, 1.0])
    row_mm, col_mm = float(px[0]), float(px[1])  # (dy, dx)
    return disp, ds, (row_mm, col_mm)

# ------------------ Main annotate ------------------
def annotate_points_zoomed(image_disp, ds, pixel_mm, out_dir=None):
    """
    Click 1: CENTER (red)
    Then: labeled points in order LABELS (blue) with crosshair.
    View is zoomed to 250x250 mm (mm coordinates). Backspace = undo.
    Saves relative_coordinates.csv (mm).
    """
    row_mm, col_mm = pixel_mm
    h, w = image_disp.shape
    extent = [0, w*col_mm, h*row_mm, 0]  # show data in mm

    fig, ax = plt.subplots()
    ax.imshow(image_disp, cmap="gray", extent=extent, origin="upper")
    ax.set_aspect("equal")
    ax.set_title("Click CENTER, then: " + " → ".join(LABELS) + "  (Backspace = undo)")
    # Initial zoom around geometric center
    init_center = (w*col_mm/2.0, h*row_mm/2.0)
    set_fov_mm(ax, init_center, FOV_MM)

    # Attach blitted crosshair
    attach_crosshair(ax, color='yellow')

    center = [None]      # (x_mm, y_mm)
    points = []          # list of (label, x_mm, y_mm)
    artists = []         # for undo: pairs of (plot_artist, text_artist)

    def redraw_title():
        if center[0] is None:
            ax.set_title("Click CENTER, then: " + " → ".join(LABELS) + "  (Backspace = undo)")
        else:
            next_lab = LABELS[len(points)] if len(points) < len(LABELS) else "Done"
            ax.set_title(f"Center set. Next: {next_lab}  (Backspace = undo)")

    def on_click(event):
        if event.inaxes != ax:
            return
        x, y = event.xdata, event.ydata

        if center[0] is None:
            # First click = center
            center[0] = (x, y)
            p, = ax.plot(x, y, 'ro')
            t = ax.text(x + 4, y, "Center", color='red', fontsize=9)
            artists.append((p, t))
            # Recenter FOV to this center
            set_fov_mm(ax, center[0], FOV_MM)
            redraw_title()
            fig.canvas.draw_idle()
            return

        # Subsequent clicks = labeled points
        if len(points) < len(LABELS):
            label = LABELS[len(points)]
            p, = ax.plot(x, y, 'bx')
            t = ax.text(x + 4, y, label, color='cyan', fontsize=9)
            artists.append((p, t))
            points.append((label, x, y))
            redraw_title()
            # keep same zoom (centered on center[0])
            set_fov_mm(ax, center[0], FOV_MM)
            fig.canvas.draw_idle()

        # Close figure when finished
        if len(points) == len(LABELS):
            plt.close(fig)

    def on_key(event):
        if event.key == 'backspace':
            # Undo last ROI point, else undo center
            if points:
                points.pop()
                art = artists.pop()
                for a in (art if isinstance(art, tuple) else [art]):
                    try:
                        a.remove()
                    except Exception:
                        pass
                redraw_title()
                set_fov_mm(ax, center[0] if center[0] else init_center, FOV_MM)
                fig.canvas.draw_idle()
            elif center[0] is not None:
                # Remove center
                center[0] = None
                art = artists.pop()
                for a in (art if isinstance(art, tuple) else [art]):
                    try:
                        a.remove()
                    except Exception:
                        pass
                redraw_title()
                set_fov_mm(ax, init_center, FOV_MM)
                fig.canvas.draw_idle()

    fig.canvas.mpl_connect('button_press_event', on_click)
    fig.canvas.mpl_connect('key_press_event', on_key)
    plt.show()

    if center[0] is None:
        print("No center defined. Exiting.")
        return

    # Save relative coordinates (mm) w.r.t. center
    cx, cy = center[0]
    rel = [(lab, x - cx, y - cy) for (lab, x, y) in points]

    if out_dir is None:
        out_dir = os.path.dirname(getattr(ds, 'filename', '') or '.')

    out_csv = os.path.join(out_dir, "relative_coordinates.csv")
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Label", "X_rel_mm", "Y_rel_mm"])
        w.writerows(rel)

    print(f"Center (mm): ({cx:.2f}, {cy:.2f})")
    print(f"Saved {len(rel)} labeled points (relative mm) to:\n{out_csv}")

# ------------------ Runner ------------------
if __name__ == "__main__":
    file_path = select_dicom_file()
    if not file_path:
        print("No file selected.")
    else:
        img_disp, ds, pixel_mm = load_dicom(file_path)
        out_dir = os.path.dirname(file_path)
        annotate_points_zoomed(img_disp, ds, pixel_mm, out_dir=out_dir)
