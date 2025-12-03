import re
import pydicom
pydicom.config.convert_wrong_length_to_UN = True

import tkinter as tk
from tkinter import filedialog, messagebox
import os
from datetime import datetime

def select_dicom_file():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Select a DICOM file",
        filetypes=[("DICOM files", "*.dcm"), ("All files", "*.*")]
    )
    return file_path

def select_output_directory():
    root = tk.Tk()
    root.withdraw()
    output_dir = filedialog.askdirectory(
        title="Select a folder to save DICOM metadata"
    )
    return output_dir

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

def save_to_txt(text, original_file_path, output_dir):
    base_name = os.path.splitext(os.path.basename(original_file_path))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"{base_name}_metadata_{timestamp}.txt"
    output_path = os.path.join(output_dir, output_name)

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

def main():
    file_path = select_dicom_file()
    if not file_path:
        messagebox.showinfo("Cancelled", "No DICOM file was selected.")
        return

    output_dir = select_output_directory()
    if not output_dir:
        messagebox.showinfo("Cancelled", "No output directory selected.")
        return

    metadata_text = extract_dicom_metadata(file_path)
    save_to_txt(metadata_text, file_path, output_dir)

if __name__ == "__main__":
    main()
