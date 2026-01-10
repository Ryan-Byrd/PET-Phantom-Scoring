#!/usr/bin/env python3
"""
Stage 0: Flatten raw PET/CT export into a single folder.

This script does NOT attempt to detect DICOM or filter files.
It just collects *every file* from the input (directory or ZIP)
and writes it into a single output folder called 'Flattened_Input'
with safe, unique filenames.

Usage examples:
  python flatten_input.py --input "D:\\PET_DVD"
  python flatten_input.py --input "D:\\ClientUpload.zip"
  python flatten_input.py --input "D:\\ClientUpload.zip" --output-root "D:\\Work"

If --output-root is omitted, 'Flattened_Input' will be created
in the *same directory* as the input path's parent.
"""

import argparse
import os
import zipfile
import shutil


def _win_extended_path(path: str) -> str:
    """
    On Windows, convert a path to an extended-length path (\\?\\...) to avoid MAX_PATH issues.
    Leaves paths unchanged on non-Windows.
    """
    if os.name != "nt":
        return path

    p = os.path.abspath(path)

    # Already extended-length
    if p.startswith("\\\\?\\"):
        return p

    # UNC path
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p.lstrip("\\")
    return "\\\\?\\" + p


def _copy2_robust(src_path: str, dst_path: str) -> bool:
    """
    Copy with Windows long-path support and friendly warnings.
    Returns True if copied; False if skipped.
    """
    try:
        shutil.copy2(_win_extended_path(src_path), _win_extended_path(dst_path))
        return True
    except FileNotFoundError as e:
        # WinError 3 can be long-path related or a transient/vanished source.
        print(f"⚠️ Skipping missing/unreachable file:\n   {src_path}\n   ({e})")
        return False
    except OSError as e:
        print(f"⚠️ Skipping file due to OS error:\n   {src_path}\n   ({e})")
        return False


def make_output_folder(input_path, output_root=None):
    """
    Determine and create the Flattened_Input output folder.
    If output_root is provided, use that as the parent.
    Otherwise, use the parent of input_path.
    """
    if output_root:
        parent = os.path.abspath(output_root)
    else:
        parent = os.path.dirname(os.path.abspath(input_path))

    out_dir = os.path.join(parent, "Flattened_Input")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def generate_flat_name(counter, original_name):
    """
    Generate a unique flat filename like FILE_000001.ext
    preserving the original extension (if any).
    """
    base, ext = os.path.splitext(original_name)
    # Normalize extension to something sane; leave as-is otherwise
    return f"FILE_{counter:06d}{ext}"


def flatten_from_directory(src_root, out_dir):
    """
    Recursively walk src_root and copy every file into out_dir
    with unique flat names.
    """
    counter = 1
    copied = 0
    skipped = 0
    src_root = os.path.abspath(src_root)
    out_dir = os.path.abspath(out_dir)

    os.makedirs(out_dir, exist_ok=True)

    print(f"📁 Flattening directory:\n   {src_root}")
    print(f"📂 Output folder:\n   {out_dir}\n")

    for dirpath, dirnames, filenames in os.walk(src_root, topdown=True):
        # Avoid descending into the output folder if it’s inside src_root
        dirnames[:] = [
            d for d in dirnames
            if os.path.abspath(os.path.join(dirpath, d)) != out_dir
        ]

        for fn in filenames:
            src_path = os.path.join(dirpath, fn)

            # Skip if the source file is actually inside the out_dir
            if os.path.abspath(src_path).startswith(out_dir):
                continue

            new_name = generate_flat_name(counter, fn)
            dst_path = os.path.join(out_dir, new_name)

            if _copy2_robust(src_path, dst_path):
                copied += 1
                counter += 1
            else:
                skipped += 1

    print(f"✅ Done. Flattened {copied} files from directory. Skipped {skipped}.\n")


def flatten_from_zip(zip_path, out_dir):
    """
    Read all files from a ZIP and write them directly into out_dir
    with unique flat names. Internal folder structure is NOT preserved.
    """
    counter = 1
    zip_path = os.path.abspath(zip_path)
    out_dir = os.path.abspath(out_dir)

    print(f"📦 Flattening ZIP:\n   {zip_path}")
    print(f"📂 Output folder:\n   {out_dir}\n")

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            # Skip directories inside the ZIP
            if info.is_dir():
                continue

            # Use the filename part to get an extension, ignore internal dirs
            _, fn = os.path.split(info.filename)
            if not fn:
                # Some weird entries can have empty names; skip them
                continue

            new_name = generate_flat_name(counter, fn)
            dst_path = os.path.join(out_dir, new_name)

            # Read bytes from the ZIP and write to output
            with zf.open(info, "r") as src_f, open(dst_path, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)

            counter += 1

    print(f"✅ Done. Flattened {counter - 1} files from ZIP.\n")


def main():
    parser = argparse.ArgumentParser(
        description="Stage 0: Flatten raw PET/CT export into 'Flattened_Input' with no filtering."
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to input directory OR .zip file."
    )
    parser.add_argument(
        "--output-root", "-o",
        help="Optional parent folder in which to create 'Flattened_Input'. "
             "If omitted, the parent directory of --input is used."
    )

    args = parser.parse_args()

    input_path = os.path.abspath(args.input)

    if not os.path.exists(input_path):
        print(f"❌ Input path does not exist:\n   {input_path}")
        return

    out_dir = make_output_folder(input_path, args.output_root)

    if os.path.isdir(input_path):
        flatten_from_directory(input_path, out_dir)
    elif zipfile.is_zipfile(input_path):
        flatten_from_zip(input_path, out_dir)
    else:
        print("❌ Input must be either a directory or a .zip file.")
        print(f"   Got: {input_path}")


if __name__ == "__main__":
    main()
