import os
import shutil
from collections import defaultdict
from tkinter import Tk, filedialog
import tkinter as tk
from tkinter import ttk

import json
import re
from difflib import SequenceMatcher
import hashlib

import pydicom
from pydicom.multival import MultiValue
from tqdm import tqdm

import pylibjpeg  # ensure plugin registration
from pydicom.data import get_testdata_file

import gdcm  # for GDCM-based conversion


# ------------- UI helpers -----------------
def choose_file(title="Select a file"):
    root = Tk()
    root.withdraw()
    path = filedialog.askopenfilename(title=title)
    root.destroy()
    return path


def choose_folder(title="Select a folder"):
    root = Tk()
    root.withdraw()
    path = filedialog.askdirectory(title=title)
    root.destroy()
    return path


# ------------- Progress window -----------------
class ProgressWindow:
    def __init__(self, title, total_files):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("450x120")
        self.root.resizable(False, False)

        ttk.Label(self.root, text=title, font=("Segoe UI", 12, "bold")).pack(pady=5)

        self.progress = ttk.Progressbar(self.root, length=400, mode="determinate")
        self.progress.pack(pady=5)
        self.progress["maximum"] = max(total_files, 1)

        self.label = ttk.Label(self.root, text="Starting…", font=("Segoe UI", 10))
        self.label.pack()

        self.root.update()

    def update(self, count, filename):
        self.progress["value"] = count
        self.label.config(text=filename)
        self.root.update()

    def close(self):
        self.root.destroy()


# --- series classification + manifest writer ---

# keyword sets (tune these as you encounter real site labels)
KEYWORDS = {
    "uniformity": [
        "uniformity",
        "uniform",
        "uni",
        "uniformity phantom",
        "blanket",
        "flood",
        "phantom_uniform",
        "ucm",
    ],
    "acr": ["acr", "standard", "acredit", "acr phantom", "acrl", "acrp", "normal"],
    "crp": [
        "crp",
        "country performance",
        "countryperformance",
        "cr perf",
        "performance",
        "boost",
        "crp phantom",
    ],
    "transmission": ["transmission", "tx", "empty", "blank"],
    "other": [],
}

try:
    from rapidfuzz.fuzz import partial_ratio as fuzz_partial_ratio

    have_rapidfuzz = True
except Exception:
    have_rapidfuzz = False

def norm_text(s):
    if not s:
        return ""
    s = str(s).lower()
    # remove punctuation but keep spaces & underscores
    s = re.sub(r"[^\w\s_-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def fuzzy_score(a, b):
    if not a or not b:
        return 0
    if have_rapidfuzz:
        return fuzz_partial_ratio(a, b)  # 0-100
    # fallback to difflib ratio scaled to 0-100
    return int(SequenceMatcher(None, a, b).ratio() * 100)

def classify_text(text):
    t = norm_text(text)
    # quick substring check first (fast and deterministic)
    for label, kws in KEYWORDS.items():
        for kw in kws:
            if kw in t:
                return label
    # fuzzy fallback across keywords
    best_label = "other"
    best_score = 0
    for label, kws in KEYWORDS.items():
        for kw in kws:
            score = fuzzy_score(t, kw)
            if score > best_score:
                best_score = score
                best_label = label
    # require a threshold for fuzzy match (tune as needed)
    if best_score >= 70:
        return best_label
    return "other"

def classify_series_from_metadata(ds):
    """
    ds: pydicom Dataset for a representative file in the series
    Returns: classification label string
    """
    # check several fields in order of trustworthiness
    candidates = []
    for tag in (
        "SeriesDescription",
        "ProtocolName",
        "StudyDescription",
        "ImageType",
        "SeriesNumber",
        "PatientName",
    ):
        val = ds.get(tag, "")
        if isinstance(val, (list, tuple)):
            val = " ".join(map(str, val))
        candidates.append(str(val))
    # make one combined string for matching
    combined = " ".join([c for c in candidates if c])
    label = classify_text(combined)
    return label

def refine_label_by_stats(label, ds, file_count):
    """Adjust classification based on series stats and DICOM metadata."""
    # If thickness tag exists, read it
    try:
        thick = float(ds.get("SliceThickness", 0))
    except Exception:
        thick = 0

    # --- ACR / CRP: always 10mm and ~20 slices ---
    if 8.5 <= thick <= 11.5 or 15 <= file_count <= 25:
        # if original label looked like acr or crp, keep it
        if label in ("acr", "crp"):
            return label
        # if text hints of performance, treat as CRP
        desc = str(ds.get("SeriesDescription", "")).lower()
        if "crp" in desc or "performance" in desc or "boost" in desc:
            return "crp"
        # else treat as ACR phantom
        if "acr" in desc or "standard" in desc or "normal" in desc:
            return "acr"

    # --- Uniformity: attenuation-corrected PET, usually one series ---
    # look for attenuation correction in DICOM metadata
    corr = str(ds.get("CorrectedImage", "")).lower()
    if "attenuation" in corr or "ac" in corr or "attn" in corr:
        if label not in ("acr", "crp"):
            return "uniformity"

    # --- Fallback ---
    return label

def build_series_manifest_from_index(image_root, idx_leaf, idx_rel, out_manifest_path):
    """
    Walk the indexed files (idx_leaf) and group by SeriesInstanceUID if possible.
    Write a JSON manifest of { label: [paths...] } and also a simple TXT summary.
    """
    # map series_uid -> representative file
    series_map = {}  # key -> dict {uid, series_num, series_desc, file_path}
    # try to find SeriesInstanceUID by reading minimal tags from file leaves
    for leaf, paths in idx_leaf.items():
        # choose first path as representative to avoid heavy ops
        rep = paths[0]
        try:
            ds = pydicom.dcmread(rep, stop_before_pixels=True, force=True)
        except Exception:
            continue
        uid = ds.get("SeriesInstanceUID", None) or f"SERIES_{ds.get('SeriesNumber','')}_{leaf}"
        if uid not in series_map:
            series_map[uid] = {
                "uid": uid,
                "series_num": ds.get("SeriesNumber", ""),
                "series_desc": ds.get("SeriesDescription", "") or ds.get("ProtocolName", ""),
                "patient": f"{ds.get('PatientName','')}_{ds.get('PatientID','')}",
                "files": [],
            }
        series_map[uid]["files"].append(rep)

    # classify each series and produce manifest
    manifest = {}  # label -> list of folders or sample file paths
    for uid, info in series_map.items():
        # open a representative file for metadata classification (use first file)
        rep_file = info["files"][0]
        try:
            ds = pydicom.dcmread(rep_file, stop_before_pixels=True, force=True)
        except Exception:
            ds = None
        label = classify_series_from_metadata(ds) if ds else "other"
        label = refine_label_by_stats(label, ds, len(info["files"]))
        # choose series folder (common parent of all files in that series)
        folders = sorted({os.path.abspath(os.path.dirname(f)) for f in info["files"]})
        # prefer the shallowest folder (shortest path) as representative
        rep_folder = min(folders, key=lambda p: len(p)) if folders else os.path.abspath(
            os.path.dirname(rep_file)
        )
        manifest.setdefault(label, []).append(
            {
                "uid": uid,
                "series_num": info.get("series_num"),
                "series_desc": info.get("series_desc"),
                "patient": info.get("patient"),
                "rep_folder": rep_folder,
                "rep_file": os.path.abspath(rep_file),
                "file_count": len(info["files"]),
            }
        )

    # write JSON manifest
    with open(out_manifest_path + ".json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    # write a simple human-readable summary
    with open(out_manifest_path + ".txt", "w", encoding="utf-8") as fh:
        fh.write("Series classification manifest\n\n")
        for label, items in manifest.items():
            fh.write(f"== {label.upper()} ({len(items)} series) ==\n")
            for it in items:
                fh.write(
                    f"- UID: {it['uid']} | Series#: {it['series_num']} | Desc: {it['series_desc']}\n"
                )
                fh.write(f"  Patient: {it['patient']}\n")
                fh.write(
                    f"  Folder: {it['rep_folder']}  (files: {it['file_count']})\n"
                )
            fh.write("\n")
    return manifest

# ------------- path & DICOM utils -----------------
def safe_name(s):
    return "".join(c for c in str(s) if c.isalnum() or c in " _-").strip()

def flatten_ref(ref):
    if isinstance(ref, (MultiValue, list, tuple)):
        return os.path.join(*[str(x) for x in ref])
    return str(ref)

def is_probably_dicom(path):
    # Prefer robust check: some valid DICOMs lack the DICM preamble.
    try:
        pydicom.dcmread(path, stop_before_pixels=True, force=True)
        return True
    except Exception:
        return False

def convert_with_gdcm(src_path, dst_path):
    reader = gdcm.ImageReader()
    reader.SetFileName(src_path)
    if not reader.Read():
        return False
    writer = gdcm.ImageWriter()
    writer.SetFile(reader.GetFile())
    writer.SetImage(reader.GetImage())
    writer.SetFileName(dst_path)
    return bool(writer.Write())

def build_recursive_index(root):
    """
    Return two indices:
      - by_leaf: {'18507241': [fullpath1, fullpath2, ...]}
      - by_rel:  {'DICOM\\20250616\\18500000\\50140002\\18507241': fullpath}
    """
    by_leaf = defaultdict(list)
    by_rel = {}
    root_abs = os.path.abspath(root)
    for dirpath, _, filenames in os.walk(root_abs):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            leaf = os.path.splitext(os.path.basename(full))[0]  # ignore extension if present
            by_leaf[leaf].append(full)
            rel = os.path.relpath(full, root_abs)
            by_rel[rel.replace("/", "\\")] = full
            # also map without extension for relative lookups
            rel_noext = os.path.splitext(rel)[0].replace("/", "\\")
            by_rel[rel_noext] = full
    return by_leaf, by_rel

def resolve_ref_to_path(ref_id, image_root, idx_leaf, idx_rel):
    """
    Try (in order):
      1) direct join image_root + ref_id (as-is and without extension)
      2) lookup by relative path in index (with/without extension)
      3) lookup by leaf name (last component), choose shortest path
    """
    # normalize slashes
    norm_ref = ref_id.replace("/", "\\")
    # 1) direct join
    direct = os.path.join(image_root, norm_ref)
    candidates = [direct, os.path.splitext(direct)[0]]
    # try case variants with common extensions
    exts = ("", ".ima", ".IMA", ".dcm", ".DCM")
    for c in candidates:
        for ext in exts:
            p = c + ext
            if os.path.exists(p):
                return p

    # 2) index by relative
    if norm_ref in idx_rel and os.path.exists(idx_rel[norm_ref]):
        return idx_rel[norm_ref]
    # also try without extension
    ref_noext = os.path.splitext(norm_ref)[0]
    if ref_noext in idx_rel and os.path.exists(idx_rel[ref_noext]):
        return idx_rel[ref_noext]

    # 3) index by leaf
    leaf = os.path.splitext(os.path.basename(norm_ref))[0]
    if leaf in idx_leaf:
        # choose the shortest relative path (closest match)
        paths = idx_leaf[leaf]
        if len(paths) == 1:
            return paths[0]
        # tie-breaker: prefer a path that contains the parent directories of ref_noext
        parts = ref_noext.split("\\")
        best = None
        best_score = -1
        for p in paths:
            score = sum(1 for part in parts if part and part.lower() in p.lower())
            if score > best_score:
                best = p
                best_score = score
        return best

    return None

# ------------- organization -----------------
def organize_from_folder(src_folder, out_root):
    organized_dir = os.path.join(out_root, "Organized_DICOMs")
    os.makedirs(organized_dir, exist_ok=True)

    # collect all potential dicom files
    candidates = []
    for dirpath, _, filenames in os.walk(src_folder):
        for fn in filenames:
            if fn.lower().endswith((".dcm",)):
                candidates.append(os.path.join(dirpath, fn))

    print(f"\n📦 Organizing {len(candidates)} files...")
    for fpath in tqdm(candidates, unit="file"):
        try:
            ds = pydicom.dcmread(fpath, stop_before_pixels=True, force=True)
        except Exception:
            continue
        patient = safe_name(f"{ds.get('PatientName', 'Unknown')}_{ds.get('PatientID', '')}")
        study = safe_name(f"{ds.get('StudyDate', 'NoDate')}_{ds.get('StudyDescription', '')}")
        series = safe_name(f"{ds.get('SeriesNumber', '')}_{ds.get('SeriesDescription', '')}")
        outdir = os.path.join(organized_dir, patient, study, series)
        os.makedirs(outdir, exist_ok=True)
        shutil.copy2(fpath, os.path.join(outdir, os.path.basename(fpath)))

    print(f"✅ Organization complete.\n📁 {organized_dir}")

    # Now that all files are organized, build manifest ONCE
    idx_leaf, idx_rel = build_recursive_index(organized_dir)
    manifest = build_series_manifest_from_index(
        image_root=organized_dir,
        idx_leaf=idx_leaf,
        idx_rel=idx_rel,
        out_manifest_path=os.path.join(out_root, "series_manifest"),
    )
    print("Manifest written to:", os.path.join(out_root, "series_manifest.json"))

# ------------- universal IMA → DICOM converter -----------------
def convert_siemens_ima_universal(src_path, dst_path):
    """
    First tries reading as DICOM (many Siemens IMAs are DICOM).
    If that fails, tries GDCM (needed for some proprietary IMA).
    Returns True if success, False if failed.
    """
    # 1) Try pydicom
    try:
        ds = pydicom.dcmread(src_path, force=True)
        if "PixelData" in ds:
            # ensure parent exists
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            ds.save_as(dst_path, write_like_original=False)
            return True
    except Exception:
        pass

    # 2) Try GDCM
    try:
        if convert_with_gdcm(src_path, dst_path):
            return True
    except Exception:
        pass

    print(f"⚠️ Could not convert IMA as DICOM: {src_path}")
    return False

# ------------- DICOMDIR-driven mode (Case 1) -----------------
def run_dicomdir_mode(dicomdir_path, image_root, converted_dir):
    print(f"\n📖 Reading DICOMDIR: {dicomdir_path}")
    try:
        dicomdir = pydicom.dcmread(dicomdir_path, force=True)
    except Exception as e:
        print(f"❌ Failed to read DICOMDIR: {e}")
        return

    if "DirectoryRecordSequence" not in dicomdir:
        print("❌ Invalid DICOMDIR — missing DirectoryRecordSequence.")
        return

    idx_leaf, idx_rel = build_recursive_index(image_root)

    image_records = [
        rec
        for rec in dicomdir.DirectoryRecordSequence
        if getattr(rec, "DirectoryRecordType", "").upper() == "IMAGE"
    ]
    print(f"🧩 Found {len(image_records)} IMAGE records in DICOMDIR.")

    copied_ok = 0
    converted_ok = 0
    missing = 0

    print("\n🔄 Resolving & converting as needed (DICOMDIR mode)...")
    for rec in tqdm(image_records, unit="ref"):
        ref = getattr(rec, "ReferencedFileID", None)
        if not ref:
            missing += 1
            continue
        ref_path = flatten_ref(ref)
        src = resolve_ref_to_path(ref_path, image_root, idx_leaf, idx_rel)

        if not src or not os.path.exists(src):
            # Not found via ref — try leaf-only fallback
            leaf = os.path.splitext(os.path.basename(ref_path.replace("/", "\\")))[0]
            candidates = idx_leaf.get(leaf, [])
            src = candidates[0] if candidates else None

        if not src or not os.path.exists(src):
            print(f"⚠️ Missing: {ref_path}")
            missing += 1
            continue

        base_name = os.path.splitext(os.path.basename(src))[0]
        out_path = os.path.join(converted_dir, base_name + ".dcm")

        if is_probably_dicom(src):
            try:
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                shutil.copy2(src, out_path)
                copied_ok += 1
            except Exception as e:
                print(f"⚠️ Copy failed: {src} -> {e}")
                missing += 1
        elif src.lower().endswith(".ima"):
            if convert_siemens_ima_universal(src, out_path):
                converted_ok += 1
            else:
                missing += 1
        else:
            if convert_with_gdcm(src, out_path):
                converted_ok += 1
            else:
                print(f"⚠️ GDCM failed to decode: {src}")
                missing += 1

    print("\n📊 DICOMDIR Mode Summary")
    print(f"   ✅ Copied clean DICOMs : {copied_ok}")
    print(f"   🔁 Converted via GDCM/IMA: {converted_ok}")
    print(f"   ⚠️ Missing/failed      : {missing}")
    print(f"   📦 Converted output    : {converted_dir}")

# ------------- Generic IMA mode (Case 3) -----------------
def run_case3_preserve_structure(root, converted_dir):
    """
    Case 3: root contains nested folders of true DICOM .IMA files.
    We preserve the entire directory structure and convert each IMA to DICOM
    in the same relative folder, using short/safe filenames.
    """
    # Gather all IMA files
    ima_files = []
    for dirpath, _, filenames in os.walk(root, topdown=True):

        # Ignore GE viewer installers, language packs, misc junk
        if any(skip in dirpath.upper() for skip in ("DV31", "MISC")):
            continue

        for fn in filenames:
            lower = fn.lower()

            # GE DVD files have *no extension* (Z00, Z01…)
            is_extensionless = "." not in fn

            # Accept:
            #  - .ima
            #  - .dcm
            #  - extensionless DICOM slices (GE Zxx)
            if lower.endswith(".ima") or lower.endswith(".dcm") or is_extensionless:
                ima_files.append(os.path.join(dirpath, fn))

    if not ima_files:
        print("❌ No .IMA files found under the selected root.")
        return

    prog = ProgressWindow("Converting IMA Files…", len(ima_files))
    count = 0

    for dirpath, fn in ima_files:
        prog.update(count, f"Converting: {fn}")
        count += 1

        src = os.path.join(dirpath, fn)

        # Mirror directory structure under converted_dir
        rel_path = os.path.relpath(dirpath, root)
        out_dir = os.path.join(converted_dir, rel_path)
        os.makedirs(out_dir, exist_ok=True)

        base = os.path.splitext(fn)[0]
        # To avoid extremely long filenames, keep last 6 chars of base
        safe_base = base[-6:] if len(base) > 6 else base

        dst = os.path.join(out_dir, safe_base + ".dcm")

        if not convert_siemens_ima_universal(src, dst):
            print(f"⚠️ Failed to convert: {src}")

    prog.close()
    print(f"✅ Case 3 conversion complete — {count} slices processed.")
    print(f"📦 Converted output (structure preserved): {converted_dir}")

def run_case3_flatten(root, converted_dir):
    """
    Case 3 (Universal Flatten Mode):
    - Recursively scan GE/Siemens PET/CT discs
    - GE: handles extensionless files (Z00, Z01, ...)
    - Siemens: handles .IMA conversion
    - Copies valid DICOM files
    - Flattens everything into converted_dir
    """

    import pydicom
    import shutil
    import os

    print("\n🔎 Scanning for DICOM/IMA files (GE + Siemens compatible)...")

    file_list = []

    # --------- RECURSIVE DEEP SCAN ----------
    for dirpath, dirs, filenames in os.walk(root, topdown=True):

        # Skip viewer installers, language packs, misc GE junk
        skip_folders = ("DV31", "MISC", "ZIP", "INSTALL", "__MACOSX")
        if any(x in dirpath.upper() for x in skip_folders):
            continue

        for fn in filenames:

            # GE DVDs: extensionless slices "Z00", "Z01", etc.
            is_extensionless = ("." not in fn)

            # Siemens IMA
            is_ima = fn.lower().endswith(".ima")

            # DICOM with extension
            is_dcm = fn.lower().endswith(".dcm")

            # Accept ANY of these
            if is_extensionless or is_ima or is_dcm:
                file_list.append((dirpath, fn))

    print(f"📄 Found {len(file_list)} candidate files\n")

    if not file_list:
        print("❌ No GE Zxx or DICOM/IMA files found in Case 3 flatten mode.")
        return

    # --------- CONVERT / COPY ----------
    from tkinter import Tk
    Tk().withdraw()
    prog = ProgressWindow("Flattening + Converting Files (Case 3)", len(file_list))

    converted_ok = 0
    missing = []

    for idx, (dirpath, fn) in enumerate(file_list):
        src = os.path.join(dirpath, fn)

        # Build output path using short suffix to avoid long paths
        base = os.path.splitext(fn)[0]
        safe = base[-16:] if len(base) > 16 else base
        dst = os.path.join(converted_dir, safe + ".dcm")

        prog.update(idx, fn)

        # --- FIRST: Try reading as GE/standard DICOM ---
        try:
            ds = pydicom.dcmread(src, stop_before_pixels=False, force=True)
            shutil.copy(src, dst)
            converted_ok += 1
            continue
        except:
            pass

        # --- SECOND: Try Siemens IMA conversion ---
        if fn.lower().endswith(".ima"):
            try:
                convert_siemens_ima_universal(src, dst)
                converted_ok += 1
                continue
            except:
                missing.append(src)
                print(f"⚠️ Failed IMA conversion: {src}")
                continue

        # --- OTHERWISE: skip ---
        missing.append(src)
        print(f"⚠️ Skipping non-DICOM file: {src}")

    prog.close()

    print(f"\n✅ Flatten/convert complete")
    print(f"   ✔ Copied/converted: {converted_ok}")
    print(f"   ⚠ Missing/failed:  {len(missing)}")
    if missing:
        print("   These files failed:")
        for m in missing[:10]:
            print("     -", m)
        if len(missing) > 10:
            print("     ... (more omitted)")

    print("--------------------------------------------------")

def handle_case3_flatten(input_root, out_root):
    """
    Case 3: GE-style deeply nested structure with extension-less Z00..Z25 files.
    Fully recursive flatten → detect DICOM → copy with .dcm extension.
    """

    print("\n📂 Case 3: GE recursive flatten + extensionless DICOM detection")

    flat_tmp = os.path.join(out_root, "Converted_DICOMs")
    os.makedirs(flat_tmp, exist_ok=True)

    copied = 0
    skipped = 0
    errors = 0

    # Walk EVERY directory, no depth limit
    for root, dirs, files in os.walk(input_root):
        for f in files:
            src = os.path.join(root, f)

            # GE Z-files (no ext)
            if f.upper().startswith("Z") and len(f) in (2, 3):
                dest = os.path.join(flat_tmp, f"{f}.dcm")
                try:
                    shutil.copy2(src, dest)
                    copied += 1
                except Exception as e:
                    print("❌ Error copying", src, "→", e)
                    errors += 1
                continue

            # .IMA (Siemens)
            if f.lower().endswith(".ima"):
                dest = os.path.join(flat_tmp, f.replace(".ima", ".dcm"))
                try:
                    shutil.copy2(src, dest)
                    copied += 1
                except Exception as e:
                    print("❌ Error copying IMA", src, "→", e)
                    errors += 1
                continue

            # .DCM
            if f.lower().endswith(".dcm"):
                dest = os.path.join(flat_tmp, f)
                try:
                    shutil.copy2(src, dest)
                    copied += 1
                except Exception as e:
                    print("❌ Error copying DCM", src, "→", e)
                    errors += 1
                continue

            # Try reading as DICOM with pydicom
            try:
                import pydicom
                ds = pydicom.dcmread(src, stop_before_pixels=True)
                dest = os.path.join(flat_tmp, f"{f}.dcm")
                shutil.copy2(src, dest)
                copied += 1
            except:
                skipped += 1

    print("\n📊 Flatten Summary:")
    print("   Copied:", copied)
    print("   Skipped (non-dicom):", skipped)
    print("   Errors:", errors)

    # Organize all converted DICOMs
    organize_from_folder(flat_tmp, out_root)

    # Clean up
    try:
        shutil.rmtree(flat_tmp)
    except:
        pass

    print("\n✅ Case 3 completed.")



# ------------- main -----------------
def main():
    import os, shutil, sys, time
    from datetime import datetime
    import argparse

    def choose_or_cli_path(prompt_title: str, cli_value: str | None, must_exist: bool = True):
        """If a CLI value is provided, use it; otherwise open the folder picker."""
        if cli_value:
            p = os.path.abspath(cli_value)
            if must_exist and not os.path.isdir(p):
                print(f"❌ {prompt_title}: '{p}' does not exist or is not a directory.")
                sys.exit(1)
            return p
        # Fallback to GUI picker
        p = choose_folder(prompt_title)
        if not p:
            print(f"❌ No selection made for: {prompt_title}.")
            sys.exit(1)
        return p

    def count_files(folder: str) -> int:
        n = 0
        for _, _, files in os.walk(folder):
            n += len(files)
        return n

    # ---------------- CLI ----------------
    parser = argparse.ArgumentParser(description="PET DVD/Folder organizer (GE Zxx + Siemens IMA aware).")
    parser.add_argument("-i", "--input",  help="Input root (DVD or copied DVD folder). If omitted, a picker opens.")
    parser.add_argument("-o", "--output", help="Output root folder. If omitted, a picker opens.")
    args, _ = parser.parse_known_args()

    # ---------------- Paths ----------------
    print("📁 Select the root folder (DVD, copied DVD folder, or IMA source folder)...")
    root = choose_or_cli_path("Select root folder", args.input, must_exist=True)

    print("📁 Select output folder...")
    out_root = choose_or_cli_path("Select output folder for processed files", args.output, must_exist=True)

    # Use a timestamped temp to avoid conflicts if you run multiple times
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    converted_dir = os.path.join(out_root, f"Converted_DICOMs_{stamp}")
    os.makedirs(converted_dir, exist_ok=True)

    t0 = time.time()
    print("\n📂 Using Case 3 (flatten + convert) — ignoring vendor folder names (GE Zxx / Siemens IMA supported).")
    run_case3_flatten(root, converted_dir)

    # Quick sanity check before organizing
    produced = count_files(converted_dir)
    print(f"\n🔎 Converted/collected files in temp: {produced}")
    if produced == 0:
        print("⚠️ No files were produced in the converted folder; skipping organization.")
        try:
            shutil.rmtree(converted_dir)
        except Exception as e:
            print(f"⚠️ Could not remove empty temp: {e}")
        print("\n✅ Done (nothing to organize).")
        return

    # ---------------- Organize & Manifest ----------------
    print("\n📦 Organizing converted DICOMs by metadata...")
    try:
        organize_from_folder(converted_dir, out_root)
    except Exception as e:
        print(f"❌ organize_from_folder failed: {e}")
    else:
        print("✅ Organization step finished.")

    # ---------------- Cleanup ----------------
    print("\n🧹 Cleaning up temporary converted files...")
    try:
        shutil.rmtree(converted_dir)
        print(f"✅ Removed temporary folder: {converted_dir}")
    except Exception as e:
        print(f"⚠️ Could not remove {converted_dir}: {e}")

    dt = time.time() - t0
    print(f"\n✅ All done in {dt:.1f} s.")




if __name__ == "__main__":
    main()
