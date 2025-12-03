import os
import sys
import math
from PIL import Image, ImageDraw, ImageFont
import pydicom

def get_metadata(folder):
    """Extract Manufacturer and ModelName from first DICOM file in folder."""
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".dcm"):
                try:
                    ds = pydicom.dcmread(os.path.join(root, f), stop_before_pixels=True)
                    man = getattr(ds, "Manufacturer", "Unknown").strip()
                    model = getattr(ds, "ManufacturerModelName", "").strip()

                    # normalize capitalization
                    man = man.title().replace("_", " ")
                    model = model.title().replace("_", " ")

                    return man, model
                except Exception:
                    continue
    return "Unknown", "Unknown"

def make_master_splash(base_dir):
    """Create one splash view of all SUV_overlay.png images across subfolders."""
    overlays = []
    labels = []

    # find all overlays and collect labels
    for root, dirs, files in os.walk(base_dir):
        for f in files:
            if f.lower() == "suv_overlay.png":
                folder = os.path.dirname(os.path.join(root, f))
                overlays.append(os.path.join(root, f))
                man, model = get_metadata(folder)
                labels.append(f"{man} {model}".strip())
                break  # one per folder

    if not overlays:
        print("[WARN] No SUV_overlay.png images found.")
        return

    images = [Image.open(path).convert("RGB") for path in overlays]
    n = len(images)
    grid_size = math.ceil(math.sqrt(n))
    w, h = images[0].size
    grid_w, grid_h = grid_size * w, grid_size * h

    splash = Image.new("RGB", (grid_w, grid_h), "white")

    draw = ImageDraw.Draw(splash)
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except:
        font = ImageFont.load_default()

    for idx, img in enumerate(images):
        x = (idx % grid_size) * w
        y = (idx // grid_size) * h
        splash.paste(img, (x, y))

        label = labels[idx]
        # Compute text size safely across Pillow versions
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except AttributeError:
            # Fallback for older Pillow
            tw, th = draw.textsize(label, font=font)

        # Draw label box and text
        draw.rectangle([(x + 10, y + 10), (x + tw + 20, y + th + 20)], fill=(255, 255, 255, 200))
        draw.text((x + 20, y + 15), label, fill="black", font=font)

    out_path = os.path.join(base_dir, "MASTER_SPLASH.png")
    splash.save(out_path)
    print(f"[INFO] Saved master splash view → {out_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: make_master_splash.py <directory>")
        sys.exit(1)

    base_dir = sys.argv[1]
    make_master_splash(base_dir)
