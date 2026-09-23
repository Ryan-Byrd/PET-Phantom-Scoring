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
import runpy

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

import importlib
import sys

def run_step_module(module_name: str, argv: list[str], desc: str):
    """Run a helper module by importing it (multiprocessing-safe) and calling main()."""
    print(f"\n{'='*72}\n{desc}\n{'='*72}")

    old_argv = sys.argv[:]
    try:
        # Make argparse inside the helper see the right CLI args
        sys.argv = [module_name] + list(argv)

        mod = importlib.import_module(module_name)

        # Optional: if you're iterating quickly in dev, you can force reload
        # importlib.reload(mod)

        if not hasattr(mod, "main"):
            raise RuntimeError(f"{module_name} has no main() function")

        mod.main()

    except SystemExit as e:
        # argparse exits with SystemExit(0) on success
        code = getattr(e, "code", 0)
        if isinstance(code, int) and code != 0:
            raise
    finally:
        sys.argv = old_argv



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

def _mp_handoff_if_needed():
    # When frozen + multiprocessing spawns workers, it relaunches the exe with
    # internal flags like --multiprocessing-fork. We must let multiprocessing
    # handle those and exit, otherwise argparse will reject them.
    if any(a.startswith("--multiprocessing-") for a in sys.argv[1:]):
        import multiprocessing as mp
        mp.freeze_support()
        # If it was a multiprocessing child invocation, freeze_support will do the setup
        # and we should just return control to multiprocessing / exit cleanly.
        return True
    return False

if _mp_handoff_if_needed():
    raise SystemExit(0)


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
    import runpy

    FLATTEN_MOD = "pet_tools.helper.flatten_input"
    CONVERT_MOD = "pet_tools.helper.universal_dicom_converter"
    ORGANIZE_MOD = "pet_tools.helper.universal_dicom_organizer"
    MANIFEST_MOD = "pet_tools.helper.manifest_builder"

    # ----------------------------------------------------------------------
    # Derived output directories
    # ----------------------------------------------------------------------
    flattened_dir = os.path.join(work_root, "Flattened_Input")
    converted_dir = os.path.join(work_root, "Converted_DICOMs")

    organized_root = os.path.join(work_root, "organized")
    manifest_path = os.path.join(work_root, "series_manifest.json")

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
    run_step_module(
        FLATTEN_MOD,
        ["--input", input_path, "--output", flattened_dir],
        "Step 1/4: Flattening input files"
    )

    # ----------------------------
    # Step 2 — Convert → DICOM
    # ----------------------------
    print("🚀 Step 2/4: Converting flattened files → DICOM")

    run_step_module(
        CONVERT_MOD,
        ["--input", flattened_dir, "--output", converted_dir, "--workers", "10"],
        "Step 2/4: Converting flattened files → DICOM"
    )

    # ----------------------------------------------------------------------
    # 3) Organize
    # ----------------------------------------------------------------------
    run_step_module(
        ORGANIZE_MOD,
        ["--input", converted_dir, "--output", organized_root],
        "Step 3/4: Organizing by site/patient/series"
    )

    # ----------------------------------------------------------------------
    # 4) Manifest (per-site)
    # ----------------------------------------------------------------------
    def find_site_dirs(root):
        if not os.path.exists(root):
            return []
        return [
            os.path.join(root, d)
            for d in os.listdir(root)
            if os.path.isdir(os.path.join(root, d))
        ]

    print(f"[DEBUG] About to write manifests under: {organized_root}")

    site_dirs = find_site_dirs(organized_root)
    if not site_dirs:
        print("⚠️ No site directories found in organized output.")
        print("   This may indicate no valid DICOM files were created during conversion.")
        print("   Skipping manifest generation and cleanup.")
        sys.exit(0)

    for site_dir in site_dirs:
        print(f"[DEBUG] Writing manifest for site: {site_dir}")

        run_step_module(
            MANIFEST_MOD,
            ["--site", site_dir],
            f"Step 4/4: Writing series manifest for {os.path.basename(site_dir)}"
        )

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
    import multiprocessing as mp
    mp.freeze_support()
    main()

