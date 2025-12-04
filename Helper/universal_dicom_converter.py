#!/usr/bin/env python3

import os
import argparse
import subprocess
import tempfile
import shutil
import pydicom
from multiprocessing import Pool, cpu_count
from tqdm import tqdm   # ← NEW: progress bar

# Only used if --output is not provided
try:
    from tkinter import Tk, filedialog
    TK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False


import subprocess
import os
import pydicom


def find_gdcmconv():
    here = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(here, "bin", "gdcmconv.exe")

    # Prefer bundled converter
    if os.path.exists(bundled):
        return bundled

    # Fallback to system PATH
    import shutil
    system_path = shutil.which("gdcmconv")
    if system_path:
        return system_path

    return "gdcmconv"   # Will error later if truly missing


def is_valid_dicom(path):
    """Validate that the file is a real DICOM with image data."""
    if not os.path.exists(path):
        return False

    try:
        ds = pydicom.dcmread(path, force=False)
    except Exception:
        return False

    if not hasattr(ds, "PixelData"):
        return False

    return True


def convert_with_gdcm(input_file, output_file):
    """Attempt conversion using gdcmconv. Returns True if output_file is valid DICOM."""

    gdcm = find_gdcmconv()

    # Remove stale output file
    if os.path.exists(output_file):
        os.remove(output_file)

    cmd = [gdcm, "--raw", input_file, output_file]

    try:
        subprocess.run(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            check=False
        )
    except Exception:
        return False

    # Validate
    if is_valid_dicom(output_file):
        return True

    # Clean up invalid output
    if os.path.exists(output_file):
        os.remove(output_file)

    return False


def build_jobs(input_dir, output_dir):
    """
    Walk the input directory and build a list of (src, out) jobs.
    Ensures unique output paths by fixing filename collisions.
    """
    jobs = []
    used_bases = {}

    for root, dirs, files in os.walk(input_dir):
        for fn in files:
            src = os.path.join(root, fn)
            base, _ = os.path.splitext(fn)

            # avoid filename collisions
            count = used_bases.get(base, 0)
            out_base = base if count == 0 else f"{base}_{count}"
            used_bases[base] = count + 1

            out_path = os.path.join(output_dir, out_base + ".dcm")
            jobs.append((src, out_path))

    return jobs


def _convert_job(job):
    """Worker function for (src, out). Returns tuple: (converted_count, failed_count)."""
    src, out = job
    tmp = out + ".tmp"

    if convert_with_gdcm(src, tmp):
        try:
            shutil.move(tmp, out)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            return (0, 1)
        return (1, 0)

    if os.path.exists(tmp):
        os.remove(tmp)

    return (0, 1)


def convert_all(input_dir, output_dir, workers=1):
    """
    Convert every file in input_dir using gdcmconv.
    Now includes a real tqdm progress bar.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    jobs = build_jobs(input_dir, output_dir)
    total = len(jobs)

    if total == 0:
        print("⚠️  No files found to convert.")
        return

    print(f"\n📄 Files to process: {total}")
    print(f"🧵 Using workers: {workers}\n")

    converted = 0
    failed = 0

    # Sequential mode
    if workers <= 1:
        with tqdm(total=total, desc="Converting files") as pbar:
            for job in jobs:
                ok, bad = _convert_job(job)
                converted += ok
                failed += bad
                pbar.update(1)

    # Multiprocessing mode
    else:
        if workers < 1:
            workers = cpu_count()
        else:
            workers = min(workers, cpu_count())

        with Pool(processes=workers) as pool:
            with tqdm(total=total, desc="Converting files") as pbar:
                for ok, bad in pool.imap_unordered(_convert_job, jobs):
                    converted += ok
                    failed += bad
                    pbar.update(1)

    print("\n==========================================")
    print("Conversion Complete")
    print(f"✔ Valid DICOM files created: {converted}")
    print(f"✘ Failed / non-DICOM:        {failed}")
    print("==========================================\n")


def pick_output_folder():
    """Open a folder picker if --output was not passed."""
    if not TK_AVAILABLE:
        return None

    Tk().withdraw()
    out_dir = filedialog.askdirectory(title="Select Output Folder for Converted DICOMs")
    if not out_dir:
        return None
    return os.path.abspath(out_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Universal PET/CT DICOM converter using GDCM (with optional multiprocessing)."
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Path to input folder containing raw files")
    parser.add_argument("--output", "-o", required=False,
                        help="Folder to store converted DICOMs. "
                             "If omitted, GUI picker will appear.")
    parser.add_argument("--workers", "-w", type=int, default=1,
                        help="Number of worker processes (default 1).")

    args = parser.parse_args()

    input_dir = os.path.abspath(args.input)

    if args.output:
        output_dir = os.path.abspath(args.output)
    else:
        output_dir = pick_output_folder()
        if not output_dir:
            print("❌ No output folder provided. Exiting.")
            return

    print(f"📁 Input folder:  {input_dir}")
    print(f"📂 Output folder: {output_dir}")

    convert_all(input_dir, output_dir, workers=args.workers)


if __name__ == "__main__":
    main()
