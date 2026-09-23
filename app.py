import os
import json
import time
import uuid
import shutil
import zipfile
import subprocess
import sys
from pathlib import Path

from flask import Flask, request, jsonify, send_file

app = Flask(__name__)

@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp

@app.route("/convert", methods=["OPTIONS"])
@app.route("/run/<script_key>", methods=["OPTIONS"])
def preflight(script_key=None):
    return ("", 204)


# =====================================================================
# CONFIGURATION
# =====================================================================

REPO_ROOT = Path(__file__).resolve().parent

# If you ever move the scripts into a subfolder, set this env var on Render:
#   PET_SCRIPT_ROOT=/opt/render/project/src/SomeFolder
SCRIPT_ROOT = Path(os.environ.get("PET_SCRIPT_ROOT", REPO_ROOT))

# Where session folders live on the server
SESSION_ROOT = Path(os.environ.get("PET_SESSION_ROOT", "/tmp/pet_sessions"))
SESSION_ROOT.mkdir(parents=True, exist_ok=True)

SESSION_LIFETIME = 60 * 60  # 1 hour (in seconds)

# Converter script filename
CONVERTER_SCRIPT = "1._Convert_to_DICOM.py"

# Automatic PET scripts (non-converter)
SCRIPT_MAP = {
    "auto_suv": "3b._Auto_SUV_Overlay.py",
    "auto_uniformity": "4b._Auto_Uniformity_Scoring.py",
    "count_rate": "5._Count_Rate_Performance.py",
    "image_selection": "A.__Image_Selection.py",
    "manifest": "Run_From_Manifest.py",
}

@app.get("/workbench")
def workbench():
    """Return the PET QA Workbench HTML page."""
    return send_file(REPO_ROOT / "PET_QA_Workbench.html")

# =====================================================================
# HELPERS: FILE / SESSION MANAGEMENT
# =====================================================================

def _now() -> float:
    return time.time()


def ensure_script_path(filename: str) -> Path:
    """Return absolute script path and check that it exists."""
    path = SCRIPT_ROOT / filename
    if not path.exists():
        raise FileNotFoundError(f"Script not found: {path}")
    return path


def _new_session_id() -> str:
    return uuid.uuid4().hex


def _session_dir(session_id: str) -> Path:
    return SESSION_ROOT / session_id


def _session_meta_path(session_id: str) -> Path:
    return _session_dir(session_id) / "meta.json"


def build_dir_tree(base: Path, rel: str = ""):
    """
    Build a directory-only tree (no individual files), for UI display.
    Each node is { name, path, file_count, children }.
    """
    nodes = []
    for entry in sorted(os.listdir(base)):
        full = base / entry
        if full.is_dir():
            rel_path = f"{rel}/{entry}" if rel else entry
            # Count files under this directory (for info only)
            file_count = 0
            for _, _, files in os.walk(full):
                file_count += len(files)
            nodes.append({
                "name": entry,
                "path": rel_path.replace(os.sep, "/"),
                "file_count": file_count,
                "children": build_dir_tree(full, rel_path)
            })
    return nodes


def create_session() -> str:
    """Create a new session folder and return its ID."""
    sid = _new_session_id()
    sdir = _session_dir(sid)
    sdir.mkdir(parents=True, exist_ok=True)
    return sid


def save_session_meta(session_id: str, data_root_name: str):
    meta = {
        "created_at": _now(),
        "data_root": data_root_name,
    }
    with _session_meta_path(session_id).open("w", encoding="utf-8") as f:
        json.dump(meta, f)


def load_session(session_id: str):
    """
    Load session metadata, enforce expiry, and return:
      (session_dir: Path, data_root_dir: Path)
    Raises appropriate exceptions if invalid/expired.
    """
    sdir = _session_dir(session_id)
    if not sdir.exists():
        raise FileNotFoundError("Session not found")

    mpath = _session_meta_path(session_id)
    if not mpath.exists():
        # No metadata → treat as invalid session
        raise FileNotFoundError("Session metadata missing")

    with mpath.open("r", encoding="utf-8") as f:
        meta = json.load(f)

    created_at = meta.get("created_at", 0)
    data_root_name = meta.get("data_root", "converted")

    if _now() - created_at > SESSION_LIFETIME:
        # Expired: remove session dir
        try:
            shutil.rmtree(sdir, ignore_errors=True)
        finally:
            raise PermissionError("Session expired")

    data_root_dir = sdir / data_root_name
    if not data_root_dir.exists():
        raise FileNotFoundError("Session data root not found")

    return sdir, data_root_dir


def unwrap_zip_to_dir(file_storage, dest_dir: Path):
    """Save uploaded ZIP to dest_dir and unpack into it."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp_zip = dest_dir / "upload.zip"
    file_storage.save(tmp_zip)
    shutil.unpack_archive(str(tmp_zip), str(dest_dir))
    tmp_zip.unlink(missing_ok=True)


def zip_dir(src_dir: Path, out_zip: Path):
    """Zip contents of src_dir into out_zip."""
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(src_dir):
            root_path = Path(root)
            for name in files:
                full = root_path / name
                rel = full.relative_to(src_dir)
                zf.write(full, arcname=rel)


# =====================================================================
# ROUTES
# =====================================================================

@app.get("/")
def index():
    return jsonify({
        "status": "ok",
        "message": "PET QA API (converter + sessions)",
        "converter": CONVERTER_SCRIPT,
        "scripts": list(SCRIPT_MAP.keys()),
        "session_lifetime_seconds": SESSION_LIFETIME,
    })


@app.post("/convert")
def convert_to_dicom():
    """
    Step 1: Convert raw data → DICOM and organized structure.
    """
    upload = request.files.get("data_zip")
    if upload is None:
        return jsonify({"error": "Missing 'data_zip' file upload"}), 400

    # Locate converter script
    try:
        converter_path = ensure_script_path(CONVERTER_SCRIPT)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 500

    # Create new session
    session_id = create_session()
    sdir = _session_dir(session_id)

    # Folder where we unpack the uploaded ZIP
    raw_dir = sdir / "raw"
    raw_dir.mkdir(exist_ok=True)

    # Work root passed to 1._Convert_to_DICOM.py as --work-root
    work_root = sdir / "work_root"
    work_root.mkdir(exist_ok=True)

    try:
        # 1) Unpack uploaded ZIP into raw_dir
        unwrap_zip_to_dir(upload, raw_dir)

        # 2) Run converter script (full PET pipeline)
        cmd = [
            "python",
            str(converter_path),
            "--input", str(raw_dir),
            "--work-root", str(work_root),
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(SCRIPT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        stderr_msg = proc.stderr or ""

        has_any_output = any(work_root.rglob("*"))
        if proc.returncode != 0 and not has_any_output:
            shutil.rmtree(sdir, ignore_errors=True)
            return jsonify({
                "error": "Converter script failed.",
                "returncode": proc.returncode,
                "stderr": stderr_msg,
            }), 500

        tree = build_dir_tree(work_root)
        save_session_meta(session_id, data_root_name="work_root")

        return jsonify({
            "status": "ok",
            "session_id": session_id,
            "expires_in_seconds": SESSION_LIFETIME,
            "tree": tree,
            "returncode": proc.returncode,
            "stderr": stderr_msg,
        })

    except Exception as exc:
        shutil.rmtree(sdir, ignore_errors=True)
        return jsonify({
            "error": "Unexpected error during conversion.",
            "details": str(exc),
        }), 500

    # Create new session
    session_id = create_session()
    sdir = _session_dir(session_id)

    raw_dir = sdir / "raw"
    converted_dir = sdir / "converted"
    raw_dir.mkdir(exist_ok=True)
    converted_dir.mkdir(exist_ok=True)

    try:
        # 1) Unpack uploaded ZIP into raw_dir
        unwrap_zip_to_dir(upload, raw_dir)

        # 2) Run converter script
        cmd = [
            "python",
            str(converter_path),
            "--input", str(raw_dir),
            "--output", str(converted_dir),
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(SCRIPT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        stderr_msg = proc.stderr or ""
        # If converter failed and nothing was produced, treat as error
        if proc.returncode != 0 and not any(converted_dir.rglob("*")):
            # Clean up dead session
            shutil.rmtree(sdir, ignore_errors=True)
            return jsonify({
                "error": "Converter script failed.",
                "returncode": proc.returncode,
                "stderr": stderr_msg,
            }), 500

        # 3) Build directory tree from converted_dir
        tree = build_dir_tree(converted_dir)

        # 4) Save metadata and respond
        save_session_meta(session_id, data_root_name="converted")

        return jsonify({
            "status": "ok",
            "session_id": session_id,
            "expires_in_seconds": SESSION_LIFETIME,
            "tree": tree,
            "returncode": proc.returncode,
            "stderr": stderr_msg,
        })

    except Exception as exc:
        # Hard failure → clean up
        shutil.rmtree(sdir, ignore_errors=True)
        return jsonify({
            "error": "Unexpected error during conversion.",
            "details": str(exc),
        }), 500


@app.post("/run/<script_key>")
def run_script(script_key: str):
    """
    Step 2: Run an automatic PET script on the already converted structure.

    Request (JSON):
      {
        "session_id": "....",
        "subpath": "optional/relative/path/inside/converted"
      }

    Response:
      - 200: ZIP of script outputs
      - 4xx/5xx: JSON error
    """
    if script_key not in SCRIPT_MAP:
        return jsonify({
            "error": f"Unknown script '{script_key}'. Valid: {list(SCRIPT_MAP.keys())}"
        }), 400

    try:
        script_path = ensure_script_path(SCRIPT_MAP[script_key])
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 500

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON body"}), 400

    session_id = payload.get("session_id")
    subpath = (payload.get("subpath") or "").strip()

    if not session_id:
        return jsonify({"error": "Missing 'session_id' in request body"}), 400

    try:
        session_dir, data_root_dir = load_session(session_id)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except PermissionError as e:  # expired
        return jsonify({"error": str(e)}), 410

    # --- DEBUG: log incoming request and resolved data root ---
    print(
        f"[DEBUG] run_script: script_key={script_key!r}, "
        f"session_id={session_id!r}, "
        f"raw_subpath={payload.get('subpath')!r}, "
        f"trimmed_subpath={subpath!r}, "
        f"data_root_dir={str(data_root_dir)!r}",
        file=sys.stderr,
        flush=True,
    )

    # Determine input folder (data_root or subfolder) — Windows-safe
    import os

    raw_subpath = (subpath or "").strip()
    normalized_subpath = raw_subpath.replace("\\", "/").lstrip("/")

    print(
        f"[DEBUG] run_script: raw_subpath={raw_subpath!r}, normalized_subpath={normalized_subpath!r}",
        file=sys.stderr,
        flush=True,
    )

    # Reject absolute paths and traversal
    if normalized_subpath:
        if ":" in normalized_subpath or normalized_subpath.startswith(("/", "\\")):
            print(
                "[DEBUG] run_script: rejected absolute path in subpath",
                file=sys.stderr,
                flush=True,
            )
            return jsonify({"error": "Invalid subpath (absolute path not allowed)"}), 400

        if any(part == ".." for part in normalized_subpath.split("/")):
            print(
                "[DEBUG] run_script: rejected path traversal ('..') in subpath",
                file=sys.stderr,
                flush=True,
            )
            return jsonify({"error": "Invalid subpath ('..' not allowed)"}), 400

    # Normalize base and input directories
    base_dir = os.path.normcase(os.path.abspath(str(data_root_dir)))

    if normalized_subpath:
        candidate_input = os.path.normcase(
            os.path.abspath(str(data_root_dir / normalized_subpath))
        )
    else:
        candidate_input = base_dir

    print(
        f"[DEBUG] run_script: base_dir={base_dir!r}, candidate_input={candidate_input!r}",
        file=sys.stderr,
        flush=True,
    )

    # Ensure candidate_input is inside base_dir
    try:
        common = os.path.commonpath([base_dir, candidate_input])
    except ValueError:
        print(
            "[DEBUG] run_script: os.path.commonpath() raised ValueError",
            file=sys.stderr,
            flush=True,
        )
        return jsonify({"error": "Invalid subpath (path mismatch)"}), 400

    print(
        f"[DEBUG] run_script: commonpath={common!r}",
        file=sys.stderr,
        flush=True,
    )

    if common != base_dir:
        print(
            "[DEBUG] run_script: candidate_input is outside base_dir",
            file=sys.stderr,
            flush=True,
        )
        return jsonify({"error": "Invalid subpath (outside data root)"}), 400

    # Convert back to Path for downstream use
    input_dir = Path(candidate_input)

    print(
        f"[DEBUG] run_script: final input_dir={str(input_dir)!r}",
        file=sys.stderr,
        flush=True,
    )

    # Final existence check
    if not input_dir.exists() or not input_dir.is_dir():
        print(
            f"[DEBUG] run_script: input_dir does not exist or is not a directory: {str(input_dir)!r}",
            file=sys.stderr,
            flush=True,
        )
        return jsonify({
            "error": f"Input directory does not exist: {input_dir}"
        }), 400

    # Output folder for this script under the same session
    output_dir = session_dir / f"{script_key}_output"
    if output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run script
    cmd = [
        "python",
        str(script_path),
        "--input", str(input_dir),
        "--output", str(output_dir),
    ]
    print(
        f"[DEBUG] run_script: running subprocess cmd={cmd!r}, cwd={str(SCRIPT_ROOT)!r}",
        file=sys.stderr,
        flush=True,
    )

    proc = subprocess.run(
        cmd,
        cwd=str(SCRIPT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stderr_msg = proc.stderr or ""
    if stderr_msg:
        print(
            f"[DEBUG] run_script: subprocess returncode={proc.returncode}, stderr (truncated)=\n"
            f"{stderr_msg[:1000]}",
            file=sys.stderr,
            flush=True,
        )

    # If failure and no output produced
    if proc.returncode != 0 and not any(output_dir.rglob("*")):
        return jsonify({
            "error": "Script failed.",
            "returncode": proc.returncode,
            "stderr": stderr_msg,
        }), 500

    # Zip the output and send it back
    result_zip = session_dir / f"{script_key}_results.zip"
    if result_zip.exists():
        result_zip.unlink()
    zip_dir(output_dir, result_zip)

    resp = send_file(
        result_zip,
        as_attachment=True,
        download_name=f"{script_key}_results.zip",
    )
    resp.headers["X-Script-ReturnCode"] = str(proc.returncode)
    if stderr_msg:
        resp.headers["X-Script-Stderr"] = stderr_msg[:1000]
    return resp


if __name__ == "__main__":
    # For local testing only
    app.run(host="0.0.0.0", port=5000, debug=True)