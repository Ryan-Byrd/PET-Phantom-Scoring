"""
Extract DICOM Info
==================

Purpose
-------
Read a single DICOM file and dump every metadata element (tag, name, value)
into a plain-text file for quick inspection and archiving.

Inputs
------
- One DICOM file (any SOP class; read with ``force=True``).

Outputs
-------
- A ``.txt`` metadata dump named ``<base>_metadata_<timestamp>.txt``.

Assumptions
-----------
- Input is a single file, not a folder. If a folder is passed via ``--input``
  (for example when the launcher tree has a folder selected), a file dialog
  opens rooted at that folder so the user can pick the file.
- ``--output`` may be either a folder (the file name is auto-generated inside
  it) or a full ``.txt`` file path. If ``--output`` is omitted, a save dialog
  is shown.

CLI
---
    python -m pet_tools.extract_dicom_info [--input FILE] [--output PATH] [--debug]

Any value not supplied on the command line is requested with a file-explorer
dialog. ``--debug`` echoes the resolved parameters to the console.
"""

import argparse
import os
import re
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox

import pydicom
# Tolerate malformed element lengths seen in some clinical exports.
pydicom.config.convert_wrong_length_to_UN = True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Dump all DICOM metadata elements from one file to a .txt report."
    )
    parser.add_argument(
        "--input", default="",
        help="DICOM file to read. If omitted (or a folder is given), a file dialog opens.",
    )
    parser.add_argument(
        "--output", default="",
        help="Output folder OR full .txt file path. If omitted, a save dialog opens.",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Echo resolved parameters to the console.",
    )
    return parser.parse_args(argv)


def default_output_name(original_file_path):
    base_name = os.path.splitext(os.path.basename(original_file_path))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base_name}_metadata_{timestamp}.txt"


def select_dicom_file(initial_dir=""):
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Select a DICOM file",
        initialdir=initial_dir if initial_dir and os.path.isdir(initial_dir) else "",
        filetypes=[("DICOM files", "*.dcm"), ("All files", "*.*")]
    )
    root.destroy()
    return file_path


def select_output_file(default_name="dicom_metadata.txt"):
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.asksaveasfilename(
        title="Save DICOM metadata as",
        initialfile=default_name,
        defaultextension=".txt",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
    )
    root.destroy()
    return file_path


def resolve_input_path(input_arg):
    """Return a DICOM file path, asking via file dialog when needed."""
    if input_arg and os.path.isfile(input_arg):
        return input_arg

    # A folder (or nothing) was supplied: open the explorer so the user can
    # pick the actual file, rooted at the folder when it exists.
    return select_dicom_file(initial_dir=input_arg)


def resolve_output_path(output_arg, input_path):
    """Return the full .txt output path, asking via save dialog when needed."""
    name = default_output_name(input_path)

    if not output_arg:
        return select_output_file(default_name=name)

    if os.path.isdir(output_arg):
        return os.path.join(output_arg, name)

    # Treat a non-directory value as the explicit output file path.
    parent = os.path.dirname(os.path.abspath(output_arg))
    os.makedirs(parent, exist_ok=True)
    return output_arg


def extract_dicom_metadata(file_path):
    ds = pydicom.dcmread(file_path, force=True)
    metadata_lines = ["Tag | Name | Value"]

    for elem in ds.iterall():
        raw_tag = f"({elem.tag.group:04X},{elem.tag.element:04X})"
        clean_tag = re.sub(r"[^\w]", "", raw_tag).strip()

        if isinstance(elem.value, (list, pydicom.multival.MultiValue)):
            value = ", ".join(str(v) for v in elem.value)
        else:
            value = str(elem.value)

        # Clean formatting
        value = value.replace("\n", " ").replace("\t", " ").replace("\r", "").strip()
        name = elem.name.strip()

        if len(value) > 100:
            value = value[:97] + "..."

        metadata_lines.append(f"{clean_tag} | {name} | {value}")

    return "\n".join(metadata_lines)


def save_to_txt(text, output_path):
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        messagebox.showinfo("Success", f"Metadata saved to:\n{output_path}")

        try:
            os.startfile(output_path)
        except Exception:
            pass

    except Exception as e:
        messagebox.showerror("Error", f"Could not save metadata:\n{e}")


def main(argv=None):
    args = parse_args(argv)

    file_path = resolve_input_path(args.input)
    if not file_path:
        messagebox.showinfo("Cancelled", "No DICOM file was selected.")
        return

    output_path = resolve_output_path(args.output, file_path)
    if not output_path:
        messagebox.showinfo("Cancelled", "No output location was selected.")
        return

    if args.debug:
        print(f"[debug] input  : {os.path.abspath(file_path)}")
        print(f"[debug] output : {os.path.abspath(output_path)}")

    metadata_text = extract_dicom_metadata(file_path)

    if args.debug:
        print(f"[debug] elements written: {len(metadata_text.splitlines()) - 1}")

    save_to_txt(metadata_text, output_path)


if __name__ == "__main__":
    main()
