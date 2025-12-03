#!/usr/bin/env python3
"""
PET_Pipeline.py

High-level driver that runs the full PET phantom pipeline:

1) Flatten_Input.py
   - Flattens raw input (folder or ZIP) into a single folder: Flattened_Input

2) universal_dicom_converter.py  (in Helper/)
   - Converts everything in Flattened_Input to DICOM into: Converted_DICOMs
   - Uses 4 workers (built-in converter parallelism)

3) universal_dicom_organizer.py
   - Organizes Converted_DICOMs into site-level folders:
         <SiteName> DICOM Images/

4) manifest_builder.py
   - For each "<SiteName> DICOM Images" folder, builds:
         series_manifest.json

Usage:
  python PET_Pipeline.py --input "D:\\ClientUpload.zip" --work-root "D:\\Work"

If --work-root is omitted, the parent directory of --input is used.
"""

import argparse
import os
import subprocess
import sys
import ctypes
from ctypes import wintypes

from tkinter import Tk, filedialog
import os

def pick_file_or_folder():
    """
    Single Tk dialog that allows selecting EITHER a file OR a folder.
    Works across all versions of Windows.
    """

    Tk().withdraw()

    # This is the key: allow choosing folders inside file dialog
    path = filedialog.askopenfilename(
        title="Select ZIP File or Folder",
        filetypes=[
            ("ZIP Files", "*.zip"),
            ("All Files", "*.*")
        ]
    )

    # If user selected a folder instead of a file:
    # askopenfilename returns an empty string for a folder
    if not path:
        path = filedialog.askdirectory(title="Select Folder")

    if not path:
        return None

    return os.path.abspath(path)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def run_step(cmd, cwd=None, description=""):
    """Run a subprocess step with nice printing and error checking."""
    if description:
        print(f"\n🚀 {description}")
    print("   Command:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise RuntimeError(f"Step failed ({description}): return code {result.returncode}")


def find_site_folders(work_root):
    """
    Find site folders created by the organizer, which should end with ' DICOM Images'.
    Returns a list of absolute paths.
    """
    site_dirs = []
    for name in os.listdir(work_root):
        full = os.path.join(work_root, name)
        if os.path.isdir(full) and name.endswith(" DICOM Images"):
            site_dirs.append(full)
    return site_dirs


# -------------------------------------------------------------------
# Main Pipeline
# -------------------------------------------------------------------

def main():
    import argparse
    import os
    import sys
    import subprocess
    from tkinter import Tk, filedialog

    parser = argparse.ArgumentParser(
        description="Run full PET phantom pipeline: flatten → convert → organize → manifest."
    )
    parser.add_argument(
        "--input", "-i",
        help="Path to raw input (folder or .zip). If omitted, opens File Explorer."
    )
    parser.add_argument(
        "--work-root", "-w",
        help="Optional working directory. If omitted, parent of input is used."
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # INPUT SELECTION — one dialog only
    # --------------------------------------------------------
    if args.input:
        input_path = os.path.abspath(args.input)
    else:
        print("📁 No input passed. Opening single Explorer dialog…")
        input_path = pick_file_or_folder()

        if not input_path:
            print("❌ No input selected. Exiting.")
            sys.exit(1)

        input_path = os.path.abspath(input_path)

    print("📥 Selected input:", input_path)

    if not os.path.exists(input_path):
        print(f"❌ Input does not exist:\n   {input_path}")
        sys.exit(1)

    # ----------------------------------------------------------------------
    # VALIDATION
    # ----------------------------------------------------------------------
    if not os.path.exists(input_path):
        print(f"❌ Input path does not exist:\n   {input_path}")
        sys.exit(1)

    # --------------------------------------------------------
    # OUTPUT ROOT SELECTION
    # --------------------------------------------------------
    if args.work_root:
        work_root = os.path.abspath(args.work_root)

    else:
        print("📁 No output root passed. Opening File Explorer…")

        # One dialog to pick an **output directory**
        try:
            from tkinter import Tk, filedialog
            Tk().withdraw()
            selected_out = filedialog.askdirectory(title="Select Output Folder for Pipeline Results")
        except Exception:
            selected_out = None

        if not selected_out:
            print("❌ No output folder selected. Exiting.")
            sys.exit(1)

        work_root = os.path.abspath(selected_out)

    print(f"📂 Output root selected:\n   {work_root}")

    # Ensure directory exists
    os.makedirs(work_root, exist_ok=True)

    # ----------------------------------------------------------------------
    # Script locations
    # ----------------------------------------------------------------------
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    HELPER_DIR = os.path.join(BASE_DIR, "Helper")

    flatten_script = os.path.join(HELPER_DIR, "Flatten_Input.py")
    converter_script = os.path.join(HELPER_DIR, "universal_dicom_converter.py")
    organizer_script = os.path.join(HELPER_DIR, "universal_dicom_organizer.py")
    manifest_script = os.path.join(HELPER_DIR, "manifest_builder.py")

    # ----------------------------------------------------------------------
    # Derived output directories
    # ----------------------------------------------------------------------
    flattened_dir = os.path.join(work_root, "Flattened_Input")
    converted_dir = os.path.join(work_root, "Converted_DICOMs")

    # ----------------------------------------------------------------------
    # Helper: run subprocess
    # ----------------------------------------------------------------------
    def run_step(cmd, cwd=None, desc=""):
        if desc:
            print(f"\n🚀 {desc}")
        print("   Command:", " ".join(cmd))

        result = subprocess.run(cmd, cwd=cwd)
        if result.returncode != 0:
            print(f"❌ Step failed ({desc})")
            sys.exit(result.returncode)

    py = sys.executable

    # ----------------------------------------------------------------------
    # 1) Flatten
    # ----------------------------------------------------------------------
    run_step(
        [py, flatten_script, "--input", input_path, "--output-root", work_root],
        desc="Step 1/4: Flattening raw input"
    )

    # ----------------------------
    # Step 2 — Convert → DICOM
    # ----------------------------
    print("🚀 Step 2/4: Converting flattened files → DICOM")

    cmd = [
        py,
        converter_script,
        "--input", flattened_dir,
        "--output", converted_dir,
        "--workers", "10"
    ]

    run_step(cmd, desc="Step 2/4: Converting flattened files → DICOM")

    # ----------------------------------------------------------------------
    # 3) Organize
    # ----------------------------------------------------------------------
    run_step(
        [py, organizer_script, "--input", converted_dir, "--output", work_root],
        cwd=BASE_DIR,
        desc="Step 3/4: Organizing by site/patient/series"
    )

    # ----------------------------------------------------------------------
    # 4) Manifest
    # ----------------------------------------------------------------------
    def find_site_dirs(root):
        return [
            os.path.join(root, x)
            for x in os.listdir(root)
            if x.endswith(" DICOM Images")
            and os.path.isdir(os.path.join(root, x))
        ]

    for site_dir in find_site_dirs(work_root):
        run_step(
            [py, manifest_script, "--site", site_dir],
            cwd=BASE_DIR,
            desc=f"Step 4/4: Building manifest for {os.path.basename(site_dir)}"
        )

    print("\n🎉 Pipeline complete!\n")
    print("Working directory:", work_root)
    print("Flattened:", flattened_dir)
    print("Converted:", converted_dir)
    for sd in find_site_dirs(work_root):
        print("Site folder:", sd)

    # --------------------------------------------------------
    # Cleanup step: remove temporary directories
    # --------------------------------------------------------
    import shutil

    def safe_rmdir(path):
        """Delete a directory if it exists and is safe to remove."""
        if os.path.exists(path) and os.path.isdir(path):
            try:
                shutil.rmtree(path)
                print(f"🧹 Removed temporary directory: {path}")
            except Exception as e:
                print(f"⚠️ Could not remove {path}: {e}")

    print("\n🧹 Step 5/5: Cleaning up temporary folders...")

    safe_rmdir(flattened_dir)
    safe_rmdir(converted_dir)

    print("\n✨ Cleanup complete. Only organized site folders remain.\n")


if __name__ == "__main__":
    main()
