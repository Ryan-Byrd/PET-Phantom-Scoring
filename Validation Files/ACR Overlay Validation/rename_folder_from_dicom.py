import os
import pydicom
import re

def pretty_name(text: str) -> str:
    """Format manufacturer/model/site text with proper capitalization and safe characters."""
    if not text:
        return "Unknown"

    # Remove any non-printable or dangerous characters
    text = re.sub(r"[^A-Za-z0-9\s\-]", "", text.strip())

    # If text is ALL CAPS, convert to title case but keep known abbreviations uppercase
    if text.isupper():
        parts = text.split()
        formatted = []
        for p in parts:
            if p in {"GE", "CT", "PET", "MRI", "NM"}:
                formatted.append(p)
            else:
                formatted.append(p.capitalize())
        text = " ".join(formatted)

    return text


def get_dicom_metadata(folder):
    """Find the first readable DICOM and extract manufacturer, model, and site."""
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".dcm"):
                path = os.path.join(root, f)
                try:
                    ds = pydicom.dcmread(path, stop_before_pixels=True)
                    manufacturer = pretty_name(getattr(ds, "Manufacturer", "Unknown"))
                    model = pretty_name(getattr(ds, "ManufacturerModelName", "Unknown"))
                    site = pretty_name(
                        getattr(ds, "InstitutionName", "")
                        or getattr(ds, "InstitutionAddress", "")
                        or "Unknown Site"
                    )
                    return manufacturer, model, site
                except Exception:
                    continue
    return None, None, None


def rename_subfolders(base_dir):
    """Iterate over subfolders in the current directory and rename them based on DICOM metadata."""
    for entry in os.listdir(base_dir):
        folder = os.path.join(base_dir, entry)
        if not os.path.isdir(folder):
            continue

        mfr, model, site = get_dicom_metadata(folder)
        if not all([mfr, model, site]):
            print(f"[WARN] Metadata incomplete for '{entry}'")
            continue

        new_name = f"{mfr} {model} {site}".strip()
        new_name = re.sub(r"\s+", " ", new_name)  # collapse extra spaces
        new_path = os.path.join(base_dir, new_name)

        if folder != new_path:
            try:
                os.rename(folder, new_path)
                print(f"[OK] Renamed '{entry}' → '{new_name}'")
            except Exception as e:
                print(f"[ERROR] Failed to rename '{entry}': {e}")
        else:
            print(f"[INFO] '{entry}' already correctly named.")


if __name__ == "__main__":
    current_dir = os.getcwd()
    print(f"[INFO] Running rename_folder_from_dicom.py in: {current_dir}")
    rename_subfolders(current_dir)
    print("[DONE] All subfolders processed.")
