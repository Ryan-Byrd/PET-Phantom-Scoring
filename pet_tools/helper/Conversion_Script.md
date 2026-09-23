# Task: GDCM-Based Flat-Directory DICOM Normalization Helper (Python Callable)

## Objective
Write a small native helper using **GDCM (Grassroots DICOM)** to convert a flat directory of **mixed files**—some of which may be valid DICOM objects and some of which may not—into **standard Explicit VR Little Endian DICOM** files.

Input files:
- May have **no file extension**
- May use extensions such as `.ima`, `.dcm`, or vendor-specific names
- Must be detected as DICOM based on **file content**, not filename or extension

This helper will be called from Python as part of a medical imaging QA pipeline.

---

## Functional Requirements

1. Use **GDCM (C++ preferred)** for all DICOM detection and conversion.
2. Accept:
   - An **input directory** containing a flat list of files
   - An **output directory** where converted DICOM files will be written
3. Do **not** recurse into subdirectories.
4. For each file in the input directory:
   - Attempt to identify it as DICOM using GDCM (not file extension)
   - If the file is not a valid DICOM object, skip it silently or log (based on verbosity)
5. For each valid DICOM file:
   - Load it using GDCM
   - Rewrite it as **Explicit VR Little Endian**
   - Preserve:
     - Patient / Study / Series / SOP Instance UIDs
     - Pixel data exactly as-is
   - Write the converted file to the output directory
     - Use the original filename
     - Append `.dcm` only if required to avoid collisions
6. Continue processing even if individual files fail.

---

## Interface Requirements (C ABI)

Expose a **C-compatible function** callable from Python `ctypes`:

```c
int convert_dicom_directory(
    const char* input_dir,
    const char* output_dir,
    int verbose
);
