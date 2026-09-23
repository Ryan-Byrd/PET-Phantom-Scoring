import os
import sys
import json
import subprocess
import importlib.util
import tkinter as tk
from tkinter import messagebox, filedialog
import argparse
import runpy
import traceback
from datetime import datetime
from pathlib import Path

try:
    import customtkinter as ctk
except Exception:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Missing Component",
        "customtkinter is missing.\n\n"
        "If you are running the EXE, this indicates a packaging error.\n"
        "If you are running from source, install it with:\n"
        "  pip install customtkinter"
    )
    raise

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None

# ------------------------------
# 🔴 MULTIPROCESSING HANDOFF
# ------------------------------
if any(a.startswith("--multiprocessing-") for a in sys.argv[1:]):
    import multiprocessing as mp
    mp.freeze_support()
    raise SystemExit(0)


APP_NAME = "PET QA Toolkit"
AUTHOR = "By: Ryan Byrd"
MIN_PROCESSED_PANEL_WIDTH = 120
MIN_DICOM_PREVIEW_PANEL_WIDTH = 300
MIN_PROGRAMS_PANEL_WIDTH = 370
INITIAL_PROCESSED_PANEL_WIDTH = 260
DICOM_PREVIEW_PADDING = 16
DICOM_WINDOW_DRAG_PIXELS = 200

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".rb_launcher")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")
THEME_PATH = os.path.join(SETTINGS_DIR, "maroon_theme.json")

DEFAULT_SETTINGS = {
    "appearance_mode": "system",
    "global_output_dir": "",
    "processed_input_dir": "",
}

MAROON_THEME = {
    "CTk": {
        "fg_color": ["#F2F2F2", "#1a1a1a"],
        "top_fg_color": ["#EAEAEA", "#121212"],
        "border_color": ["#D0D0D0", "#2B2B2B"],
        "text_color": ["#111111", "#EEEEEE"],
        "text_color_disabled": ["#8B8B8B", "#7A7A7A"]
    },
    "CTkFont": {"family": "Segoe UI", "size": 13, "weight": "normal"},
    "CTkButton": {
        "corner_radius": 10, "border_width": 0,
        "fg_color": ["#7a0019", "#7a0019"],
        "hover_color": ["#8b001c", "#8b001c"],
        "text_color": ["#FFFFFF", "#FFFFFF"],
        "text_color_disabled": ["#BBBBBB", "#555555"],
        "border_color": ["#5c0013", "#5c0013"]
    },
    "CTkEntry": {
        "corner_radius": 8, "border_width": 1,
        "fg_color": ["#FFFFFF", "#2A2A2A"],
        "border_color": ["#C0C0C0", "#3A3A3A"],
        "text_color": ["#111111", "#FFFFFF"],
        "placeholder_text_color": ["#7A7A7A", "#A0A0A0"]
    },
    "CTkLabel": {"fg_color": "transparent", "text_color": ["#111111", "#EEEEEE"], "corner_radius": 0},
    "CTkFrame": {
        "corner_radius": 12, "border_width": 1,
        "fg_color": ["#FFFFFF", "#242424"],
        "top_fg_color": ["#F8F8F8", "#1E1E1E"],
        "border_color": ["#D0D0D0", "#2B2B2B"]
    },
    "CTkToplevel": {
        "fg_color": ["#F2F2F2", "#1A1A1A"]
    },
    "CTkScrollableFrame": {
        "label_fg_color": ["#FFFFFF", "#242424"],
        "border_color": ["#D0D0D0", "#2B2B2B"],
        "fg_color": ["#FFFFFF", "#242424"],
        "corner_radius": 12,
        "top_fg_color": ["#F8F8F8", "#1E1E1E"]
    },
    "CTkOptionMenu": {
        "corner_radius": 10,
        "fg_color": ["#7a0019", "#7a0019"],
        "button_color": ["#5c0013", "#5c0013"],
        "button_hover_color": ["#8b001c", "#8b001c"],
        "text_color": ["#FFFFFF", "#FFFFFF"],
        "text_color_disabled": ["#BBBBBB", "#555555"],
        "dropdown_fg_color": ["#FFFFFF", "#242424"],
        "dropdown_hover_color": ["#EAEAEA", "#2E2E2E"],
        "dropdown_text_color": ["#111111", "#EEEEEE"]
    },
    "CTkTabview": {
        "corner_radius": 10,
        "border_width": 1,
        "fg_color": ["#FFFFFF", "#242424"],
        "border_color": ["#D0D0D0", "#2B2B2B"],
        "segmented_button_fg_color": ["#E8E8E8", "#2B2B2B"],
        "segmented_button_selected_color": ["#7a0019", "#7a0019"],
        "segmented_button_selected_hover_color": ["#8b001c", "#8b001c"],
        "segmented_button_unselected_color": ["#DADADA", "#343434"],
        "segmented_button_unselected_hover_color": ["#CFCFCF", "#3D3D3D"],
        "text_color": ["#111111", "#EEEEEE"],
        "text_color_disabled": ["#8B8B8B", "#7A7A7A"]
    },
    "CTkSegmentedButton": {
        "corner_radius": 10,
        "border_width": 1,
        "fg_color": ["#E8E8E8", "#2B2B2B"],
        "selected_color": ["#7a0019", "#7a0019"],
        "selected_hover_color": ["#8b001c", "#8b001c"],
        "unselected_color": ["#DADADA", "#343434"],
        "unselected_hover_color": ["#CFCFCF", "#3D3D3D"],
        "text_color": ["#111111", "#EEEEEE"],
        "text_color_disabled": ["#8B8B8B", "#7A7A7A"]
    },
    "DropdownMenu": {
        "fg_color": ["#FFFFFF", "#242424"],
        "hover_color": ["#EAEAEA", "#2E2E2E"],
        "text_color": ["#111111", "#EEEEEE"]
    },
    "CTkProgressBar": {
        "progress_color": ["#7a0019", "#7a0019"],
        "fg_color": ["#E0E0E0", "#333333"],
        "border_color": ["#C0C0C0", "#3A3A3A"]
    },
    "CTkScrollbar": {
        "fg_color": ["#F0F0F0", "#1E1E1E"],
        "button_color": ["#7a0019", "#7a0019"],
        "button_hover_color": ["#8b001c", "#8b001c"],
        "border_color": ["#C0C0C0", "#3A3A3A"],
        "corner_radius": 6,
        "border_spacing": 4
    }
}


# -----------------------------
# Settings + theme persistence
# -----------------------------
def ensure_settings():
    os.makedirs(SETTINGS_DIR, exist_ok=True)

    if not os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)

    # Write or PATCH theme (prevents KeyErrors after you add new widgets)
    if not os.path.exists(THEME_PATH):
        with open(THEME_PATH, "w", encoding="utf-8") as f:
            json.dump(MAROON_THEME, f, indent=2)
        return

    def _merge_missing(target, source):
        """Recursively add missing keys from source into target."""
        changed_local = False
        for key, value in source.items():
            if key not in target:
                target[key] = value
                changed_local = True
                continue
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                if _merge_missing(target[key], value):
                    changed_local = True
        return changed_local

    try:
        with open(THEME_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
        changed = _merge_missing(existing, MAROON_THEME)
        if changed:
            with open(THEME_PATH, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
    except Exception:
        with open(THEME_PATH, "w", encoding="utf-8") as f:
            json.dump(MAROON_THEME, f, indent=2)


def load_settings():
    ensure_settings()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in DEFAULT_SETTINGS.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(data):
    ensure_settings()
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# -----------------------------
# Runtime helpers
# -----------------------------
def is_windows():
    return os.name == "nt"


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def exe_dir():
    return os.path.dirname(sys.executable) if is_frozen() else os.path.dirname(os.path.abspath(__file__))


def open_path(path):
    try:
        if is_windows():
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Open Error", f"Could not open:\n{path}\n\n{e}")


def pretty_path(p):
    try:
        home = os.path.expanduser("~")
        return p.replace(home, "~", 1) if p.startswith(home) else p
    except Exception:
        return p


def install_tk_callback_logger():
    """Log full Tk callback exceptions to a persistent file for diagnosis."""
    log_path = os.path.join(SETTINGS_DIR, "tk_callback_errors.log")
    original_report = tk.Tk.report_callback_exception

    def _report(self, exc, val, tb):
        try:
            os.makedirs(SETTINGS_DIR, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 80 + "\n")
                f.write(f"{datetime.now().isoformat(timespec='seconds')} Tk callback exception\n")
                f.write("=" * 80 + "\n")
                traceback.print_exception(exc, val, tb, file=f)
                f.write("\n")
        except Exception:
            pass

        original_report(self, exc, val, tb)

    tk.Tk.report_callback_exception = _report


# -----------------------------
# Tool registry (MODULE-BASED)
# -----------------------------
TOOLS = [
    {"id": "convert",      "name": "Convert to DICOM",             "module": "pet_tools.convert_to_dicom",              "docs": None},
    {"id": "extract",      "name": "Extract DICOM Info",           "module": "pet_tools.extract_dicom_info",            "docs": None},
    {"id": "overlay",      "name": "SUV Overlay (Manual)",         "module": "pet_tools.suv_overlay_manual",            "docs": None},
    {"id": "overlay_auto", "name": "SUV Overlay (Auto)",           "module": "pet_tools.suv_overlay_auto",              "docs": None},
    {"id": "uniform",      "name": "Uniformity Scoring (Manual)",  "module": "pet_tools.uniformity_scoring_manual",     "docs": None},
    {"id": "uniform_auto", "name": "Uniformity Scoring (Auto)",    "module": "pet_tools.uniformity_scoring_auto",       "docs": None},
    {"id": "crp",          "name": "Count Rate Performance",       "module": "pet_tools.count_rate_performance",        "docs": None},
    {"id": "coreg",        "name": "PET/CT Coregistration",        "module": "pet_tools.z_axis_coregistration",         "docs": None},
    {"id": "imgsel",       "name": "Image Selection",              "module": "pet_tools.image_selection",               "docs": None},
    {"id": "acr",          "name": "ACR Specific Overlay",         "module": "pet_tools.acr_specific_overlay",          "docs": None},
    {"id": "manifest",     "name": "Run From Manifest",            "module": "pet_tools.run_from_manifest",             "docs": None},
]

TOOL_BY_ID = {t["id"]: t for t in TOOLS}

# Optional output-argument mapping for tools that support CLI output paths.
# Note: "coreg" is intentionally absent here. z_axis_coregistration takes two
# directories (--series1/--series2), which are collected by the coregistration
# picker dialog instead of the single tree selection.
INPUT_ARG_BY_TOOL_ID = {
    "overlay": "--input",
    "overlay_auto": "--input",
    "uniform": "--input",
    "uniform_auto": "--input",
    "crp": "--input",
    "imgsel": "--input",
    "acr": "--input",
}

# These tools take an input FILE instead of a directory. The expected extension
# is used to validate the tree selection before launching:
#  - Extract DICOM Info reads the metadata of one DICOM file.
#  - Run From Manifest runs the analyses listed in one manifest JSON.
INPUT_FILE_ARG_BY_TOOL_ID = {
    "extract": ("--input", ".dcm"),
    "manifest": ("--manifest", ".json"),
}
OUTPUT_ARG_BY_TOOL_ID = {
    "convert": "--work-root",
    "extract": "--output",
    "overlay": "--output",
    "overlay_auto": "--output",
    "uniform": "--output",
    "uniform_auto": "--output",
    "crp": "--output",
    "coreg": "--output",
    "imgsel": "--output",
    "acr": "--output",
    "manifest": "--output",
}

SUV_METADATA_TOOL_IDS = {"overlay", "overlay_auto", "crp"}

# Tools that offer a multi-series uniformity comparison (superimposed deviation
# plot across several reconstructions of the same exam) via the ⋮ menu.
UNIFORMITY_COMPARE_TOOL_IDS = {"uniform_auto"}

# These are the standard DICOM fields read by the three SUV calculation tools.
# The generated JSON remains generic, so a physicist can add other tag paths
# later without requiring another GUI or CLI change.
SUV_METADATA_FIELDS = [
    ("Patient weight", "PatientWeight", "DS", "kg", True),
    ("Patient height", "PatientSize", "DS", "m", True),
    ("Patient sex", "PatientSex", "CS", "", False),
    ("Injected activity", "RadiopharmaceuticalInformationSequence[0].RadionuclideTotalDose", "DS", "Bq", True),
    ("Radionuclide half-life", "RadiopharmaceuticalInformationSequence[0].RadionuclideHalfLife", "DS", "s", True),
    ("Injection or assay date/time", "RadiopharmaceuticalInformationSequence[0].RadiopharmaceuticalStartDateTime", "DT", "YYYYMMDDHHMMSS", False),
    ("Series date", "SeriesDate", "DA", "YYYYMMDD", False),
    ("Series time", "SeriesTime", "TM", "HHMMSS", False),
    ("Decay correction", "DecayCorrection", "CS", "ADMIN, START, or NONE", False),
    ("Rescale slope", "RescaleSlope", "DS", "", True),
    ("Rescale intercept", "RescaleIntercept", "DS", "", True),
]


def load_fancy_tree_item_class():
    """Load CTkFileTreeItem from file-tree.py via importlib."""
    helper_path = Path(__file__).with_name("file-tree.py")
    if not helper_path.exists():
        return None

    try:
        spec = importlib.util.spec_from_file_location("file_tree_helper", helper_path)
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tree_item_class = getattr(module, "CTkFileTreeItem", None)
        return tree_item_class
    except Exception:
        return None


def module_exists(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _parent_dir(path: str) -> str:
    return os.path.dirname(os.path.abspath(path))


def run_tool_module_in_process(tool_id: str, tool_args=None) -> int:
    """
    Runs a tool module as __main__ in THIS process (used by the child EXE process).
    We set sys.argv so argparse inside the tool behaves normally.
    Handles None stdout/stderr gracefully.
    """
    tool_args = tool_args or []
    tool = TOOL_BY_ID.get(tool_id)

    if not tool:
        root = tk.Tk(); root.withdraw()
        messagebox.showerror("Tool Missing", f"Unknown tool id: {tool_id}")
        return 2

    module = tool["module"]

    try:
        # Ensure stdout/stderr are properly set (fixes 'NoneType' write errors)
        import io
        if sys.stdout is None:
            sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        if sys.stderr is None:
            sys.stderr = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')

        old_argv = sys.argv[:]
        sys.argv = [module] + list(tool_args)
        try:
            runpy.run_module(module, run_name="__main__")
        finally:
            sys.argv = old_argv
        return 0

    except SystemExit as e:
        code = getattr(e, "code", 0)
        return int(code) if isinstance(code, int) else 0

    except Exception as e:
        root = tk.Tk(); root.withdraw()
        messagebox.showerror("Tool Error", f"{module} failed.\n\n{e}")
        return 1


def parse_args():
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument("--run-tool", default="", help="(internal) Run a tool by id and exit")
    p.add_argument("tool_args", nargs=argparse.REMAINDER, help="Args passed to the tool after --")
    return p.parse_args()


# -----------------------------
# GUI
# -----------------------------
class LauncherApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.settings = load_settings()
        ensure_settings()
        ctk.set_default_color_theme(THEME_PATH)
        ctk.set_appearance_mode("system")

        self.fancy_tree_item_class = load_fancy_tree_item_class()
        self.selected_processed_path: str | None = None
        self._conversion_watch_job = None
        self._metadata_override_menu = None
        self._coreg_dialog = None
        self._coreg_series: list[str | None] = [None, None]
        self._coreg_slot_labels: list[ctk.CTkLabel] = []
        self._coreg_run_button = None
        self._uniform_compare_dialog = None
        self._uniform_compare_series: list[str] = []
        self._uniform_compare_rows_frame = None
        self._uniform_compare_run_button = None
        self._dicom_preview_image = None
        self._dicom_preview_source_image = None
        self._dicom_preview_pixels = None
        self._dicom_preview_window_center = None
        self._dicom_preview_window_width = None
        self._dicom_preview_drag_start = None
        self._dicom_preview_drag_window = None
        self._dicom_preview_series_directory = None
        self._dicom_preview_paths = []
        self._dicom_preview_index = 0

        self.title(APP_NAME)
        self.geometry("900x600")
        self.minsize(780, 480)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        header.grid_columnconfigure(0, weight=1)

        title_label = ctk.CTkLabel(header, text=APP_NAME, font=ctk.CTkFont(size=20, weight="bold"))
        title_label.grid(row=0, column=0, sticky="w", padx=10, pady=10)

        self.path_label = ctk.CTkLabel(
            header,
            text=self._processed_input_label_text(),
            anchor="e",
        )
        self.path_label.grid(row=0, column=1, sticky="e", padx=10)

        # Main
        main = ctk.CTkFrame(self)
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=0, minsize=INITIAL_PROCESSED_PANEL_WIDTH)
        main.grid_columnconfigure(1, weight=1, minsize=MIN_DICOM_PREVIEW_PANEL_WIDTH)
        main.grid_columnconfigure(2, weight=0, minsize=8)
        main.grid_columnconfigure(3, weight=0, minsize=MIN_PROGRAMS_PANEL_WIDTH)
        self.main_content = main

        # Persistent processed-input panel in the main content area (left)
        left_panel = ctk.CTkFrame(main)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(1, weight=1)

        left_controls = ctk.CTkFrame(left_panel)
        left_controls.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        ctk.CTkButton(
            left_controls,
            text="Set Folder",
            width=90,
            command=self.set_processed_input_dir,
        ).grid(
            row=0, column=0, sticky="w", padx=(10, 4), pady=6
        )
        ctk.CTkButton(
            left_controls,
            text="Clear",
            width=62,
            command=self.clear_processed_input_dir,
        ).grid(
            row=0, column=1, sticky="w", padx=4, pady=6
        )
        ctk.CTkButton(
            left_controls,
            text="Refresh",
            width=72,
            command=self.refresh_processed_tree,
        ).grid(
            row=0, column=2, sticky="w", padx=(4, 10), pady=6
        )

        left_tree_container = ctk.CTkFrame(left_panel)
        left_tree_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        left_tree_container.grid_rowconfigure(0, weight=1)
        left_tree_container.grid_columnconfigure(0, weight=1)
        self.processed_drop_panel = left_tree_container

        self.processed_tree = ctk.CTkScrollableFrame(left_tree_container)
        self.processed_tree.grid(row=0, column=0, sticky="nsew")
        self.processed_tree.grid_columnconfigure(0, weight=1)

        # Lazy DICOM preview panel. It stays empty until a DICOM file is selected.
        dicom_preview_panel = ctk.CTkFrame(main)
        dicom_preview_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 5), pady=10)
        dicom_preview_panel.grid_rowconfigure(1, weight=1)
        dicom_preview_panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            dicom_preview_panel,
            text="DICOM Preview",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        self._dicom_preview_label = ctk.CTkLabel(
            dicom_preview_panel,
            text="Select a DICOM file to preview it.",
        )
        self._dicom_preview_label.grid(row=1, column=0, sticky="nsew", padx=10, pady=(8, 4))
        self._dicom_preview_label.bind("<Configure>", self._on_dicom_preview_resize)
        self._dicom_preview_label.bind("<ButtonPress-1>", self._start_dicom_window_drag)
        self._dicom_preview_label.bind("<B1-Motion>", self._adjust_dicom_window_drag)
        self._dicom_preview_info = ctk.CTkLabel(dicom_preview_panel, text="", anchor="w")
        self._dicom_preview_info.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        dicom_preview_panel.bind("<MouseWheel>", self._on_dicom_preview_wheel)
        self._dicom_preview_label.bind("<MouseWheel>", self._on_dicom_preview_wheel)
        dicom_preview_panel.bind("<Button-4>", lambda event: self._step_dicom_preview(-1))
        dicom_preview_panel.bind("<Button-5>", lambda event: self._step_dicom_preview(1))
        self.dicom_preview_panel = dicom_preview_panel

        self.panel_splitter = ctk.CTkFrame(main, width=8, cursor="sb_h_double_arrow")
        self.panel_splitter.grid(row=0, column=2, sticky="ns", pady=10)
        self.panel_splitter.bind("<ButtonPress-1>", self._start_panel_resize)
        self.panel_splitter.bind("<B1-Motion>", self._resize_programs_panel)

        # Existing program list panel (right)
        programs_panel = ctk.CTkFrame(main)
        programs_panel.grid(row=0, column=3, sticky="nsew", padx=(5, 10), pady=10)
        programs_panel.grid_rowconfigure(1, weight=1)
        programs_panel.grid_columnconfigure(0, weight=1)

        list_header = ctk.CTkLabel(programs_panel, text="Available Programs", font=ctk.CTkFont(size=16, weight="bold"))
        list_header.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))

        self.scroll = ctk.CTkScrollableFrame(programs_panel)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.scroll.grid_columnconfigure(0, weight=1)

        # Footer
        footer = ctk.CTkFrame(self)
        footer.grid(row=2, column=0, sticky="ew", padx=10, pady=(5, 10))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=0)
        footer.grid_columnconfigure(2, weight=0)
        footer.grid_columnconfigure(3, weight=0)
        footer.grid_columnconfigure(4, weight=0)

        ctk.CTkLabel(footer, text=AUTHOR, anchor="w").grid(row=0, column=0, sticky="w", padx=10, pady=6)
        self.status_label = ctk.CTkLabel(footer, text="Ready", anchor="e")
        self.status_label.grid(row=0, column=1, sticky="e", padx=10, pady=6)

        self.output_path_label = ctk.CTkLabel(footer, text=self._output_label_text(), anchor="w")
        self.output_path_label.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 8))

        ctk.CTkButton(footer, text="Set Output", command=self.set_global_output_dir).grid(
            row=1, column=1, sticky="e", padx=(6, 4), pady=(0, 8)
        )
        ctk.CTkButton(footer, text="Clear", command=self.clear_global_output_dir).grid(
            row=1, column=2, sticky="e", padx=(4, 4), pady=(0, 8)
        )
        ctk.CTkButton(footer, text="Open", command=self.open_global_output_dir).grid(
            row=1, column=3, sticky="e", padx=(4, 10), pady=(0, 8)
        )

        self._enable_processed_input_drop_target()
        self.refresh_program_list()
        self.refresh_processed_tree()

    def log_status(self, msg: str):
        self.status_label.configure(text=msg)

    def _start_panel_resize(self, _event):
        """Record the current divider position before processing drag movement."""
        self._resize_programs_panel(_event)

    def _resize_programs_panel(self, event):
        """Resize the programs panel while preserving usable space for the DICOM viewer."""
        main_width = self.main_content.winfo_width()
        divider_x = event.x_root - self.main_content.winfo_rootx()
        programs_panel_width = main_width - divider_x - 18
        maximum_width = max(
            MIN_PROGRAMS_PANEL_WIDTH,
            main_width - INITIAL_PROCESSED_PANEL_WIDTH - MIN_DICOM_PREVIEW_PANEL_WIDTH - 28,
        )
        programs_panel_width = max(
            MIN_PROGRAMS_PANEL_WIDTH,
            min(programs_panel_width, maximum_width),
        )
        self.main_content.grid_columnconfigure(
            3,
            weight=0,
            minsize=programs_panel_width,
        )

    def _output_label_text(self) -> str:
        out_dir = (self.settings.get("global_output_dir") or "").strip()
        if out_dir:
            return f"Global Output: {pretty_path(out_dir)}"
        return "Global Output: <not set>"

    def _processed_input_label_text(self) -> str:
        input_dir = (self.settings.get("processed_input_dir") or "").strip()
        if input_dir:
            clipped = self._ellipsize_middle(pretty_path(input_dir), max_chars=96)
            return f"Processed Input: {clipped}"
        return "Processed Input: <not set>"

    def _ellipsize_middle(self, text: str, max_chars: int = 96) -> str:
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        keep_left = (max_chars - 3) // 2
        keep_right = (max_chars - 3) - keep_left
        return f"{text[:keep_left]}...{text[-keep_right:]}"

    def refresh_output_path_label(self):
        self.output_path_label.configure(text=self._output_label_text())

    def refresh_processed_path_label(self):
        self.path_label.configure(text=self._processed_input_label_text())

    def set_global_output_dir(self):
        initial = (self.settings.get("global_output_dir") or "").strip()
        selected = filedialog.askdirectory(
            title="Select global output folder for PET QA tools",
            initialdir=initial if initial and os.path.isdir(initial) else os.path.expanduser("~"),
        )
        if not selected:
            return

        self.settings["global_output_dir"] = os.path.abspath(selected)
        save_settings(self.settings)
        self.refresh_output_path_label()
        self.log_status("Global output folder set")

    def clear_global_output_dir(self):
        self.settings["global_output_dir"] = ""
        save_settings(self.settings)
        self.refresh_output_path_label()
        self.log_status("Global output folder cleared")

    def open_global_output_dir(self):
        out_dir = (self.settings.get("global_output_dir") or "").strip()
        if not out_dir:
            messagebox.showinfo("Global Output", "No global output folder is set.")
            return
        if not os.path.isdir(out_dir):
            messagebox.showerror("Global Output", f"Configured folder does not exist:\n{out_dir}")
            return
        open_path(out_dir)

    def _enable_processed_input_drop_target(self):
        """Enable native file drops on the processed-input tree when available."""
        if DND_FILES is None or TkinterDnD is None:
            self.log_status("Folder drag-and-drop is unavailable: tkinterdnd2 is not installed")
            return

        try:
            TkinterDnD._require(self)
            for widget in (self.processed_drop_panel, self.processed_tree):
                register_drop_target = getattr(widget, "drop_target_register")
                bind_drop_event = getattr(widget, "dnd_bind")
                register_drop_target(DND_FILES)
                bind_drop_event("<<Drop>>", self._on_processed_folder_drop)
        except Exception as error:
            self.log_status(f"Folder drag-and-drop is unavailable: {error}")

    def _on_processed_folder_drop(self, event):
        """Accept one dropped folder and process it exactly like Set Folder."""
        dropped_paths = self.tk.splitlist(event.data)
        if len(dropped_paths) != 1:
            messagebox.showerror(
                "Drop Folder",
                "Drop exactly one folder onto the processed-input panel.",
            )
            return "refuse_drop"

        dropped_path = os.path.abspath(dropped_paths[0])
        if not os.path.isdir(dropped_path):
            messagebox.showerror(
                "Drop Folder",
                "The dropped item is not a folder. Drop the folder containing the input files.",
            )
            return "refuse_drop"

        self._set_processed_input_directory(dropped_path)
        return "copy"

    def set_processed_input_dir(self):
        initial = (self.settings.get("processed_input_dir") or "").strip()
        selected = filedialog.askdirectory(
            title="Select input folder to process",
            initialdir=initial if initial and os.path.isdir(initial) else os.path.expanduser("~"),
        )
        if not selected:
            return

        self._set_processed_input_directory(selected)

    def _set_processed_input_directory(self, selected: str):
        """Process a selected folder after choosing it by dialog or native drop."""
        selected = os.path.abspath(selected)

        convert_needed = messagebox.askyesnocancel(
            "Convert Input?",
            "Should this folder be converted to DICOM first?\n\n"
            "Yes: Run Convert to DICOM and use the organized output folder.\n"
            "No: Skip conversion and use this folder directly.\n"
            "Cancel: Keep current selection.",
        )

        if convert_needed is None:
            self.log_status("Folder selection cancelled")
            return

        if convert_needed:
            # Run conversion first using the raw selected folder.
            self.log_status("Launching Convert to DICOM")
            self.run_tool(
                "convert",
                extra_args=["--input", selected],
                use_selected_input=False,
            )

            # The convert script creates this output folder.
            work_root = (self.settings.get("global_output_dir") or "").strip()
            if not work_root:
                work_root = selected

            organized_root = os.path.join(work_root, "organized")
            print(f"Looking for organized output in: {work_root}")
            # Conversion is asynchronous; only bind the tree when output exists.
            if os.path.isdir(organized_root):
                processed_root = os.path.abspath(organized_root)
                status_msg = "Processed tree set to organized output"
            else:
                self.settings["processed_input_dir"] = ""
                save_settings(self.settings)
                self.refresh_processed_path_label()
                self.refresh_processed_tree()
                if self._conversion_watch_job is not None:
                    try:
                        self.after_cancel(self._conversion_watch_job)
                    except Exception:
                        pass
                    self._conversion_watch_job = None
                self.log_status("Conversion started. Waiting for organized output")
                self._watch_for_converted_output(organized_root)
                return
        else:
            processed_root = selected
            status_msg = "Processed tree set to selected folder (conversion skipped)"

        self.settings["processed_input_dir"] = processed_root
        save_settings(self.settings)

        self.refresh_processed_path_label()
        self.refresh_processed_tree()
        self.log_status(status_msg)

    def clear_processed_input_dir(self):
        if self._conversion_watch_job is not None:
            try:
                self.after_cancel(self._conversion_watch_job)
            except Exception:
                pass
            self._conversion_watch_job = None

        self.settings["processed_input_dir"] = ""
        save_settings(self.settings)
        self.refresh_processed_path_label()
        self.refresh_processed_tree()
        self.log_status("Processed input folder cleared")

    def _watch_for_converted_output(self, organized_root: str, attempts_left: int = 240):
        """Poll for conversion output and render tree when folder becomes available."""
        if os.path.isdir(organized_root):
            self.settings["processed_input_dir"] = os.path.abspath(organized_root)
            save_settings(self.settings)
            self.refresh_processed_path_label()
            self.refresh_processed_tree()
            self.log_status("Conversion complete. Processed tree loaded")
            self._conversion_watch_job = None
            return

        if attempts_left <= 0:
            self.log_status("Conversion still running. Click Refresh after it completes")
            self._conversion_watch_job = None
            return

        self._conversion_watch_job = self.after(
            1500,
            lambda: self._watch_for_converted_output(organized_root, attempts_left - 1),
        )

    def refresh_processed_tree(self):

        if not hasattr(self, "processed_tree"):
            return

        for widget in self.processed_tree.winfo_children():
            widget.destroy()

        self.selected_processed_path = None

        root_dir = (self.settings.get("processed_input_dir") or "").strip()

        self.refresh_processed_path_label()

        if not root_dir:
            return

        if not os.path.isdir(root_dir):
            self.settings["processed_input_dir"] = ""
            save_settings(self.settings)
            self.refresh_processed_path_label()
            self.log_status("Processed input folder is missing")
            return

        if not self.fancy_tree_item_class:
            self.log_status("Fancy tree item unavailable")
            return

        root_item = self.fancy_tree_item_class(
            self.processed_tree,
            Path(root_dir),
            level=0,
            on_select=self._on_processed_tree_select,
        )
        root_item.pack(fill="x", padx=4, pady=1)
        self.selected_processed_path = root_dir

    def get_selected_processed_path(self) -> str | None:
        path = self.selected_processed_path
        return path if path and os.path.exists(path) else None

    def _on_processed_tree_select(self, path: str):
        self.selected_processed_path = path
        if path.lower().endswith(".dcm") and os.path.isfile(path):
            self.show_dicom_preview(path)
        self._offer_coreg_series_candidate(path)
        self._offer_uniform_compare_series_candidate(path)

    def show_dicom_preview(self, dicom_path: str):
        """Display a selected DICOM file and retain windowing within its directory series."""
        parent_directory = os.path.dirname(dicom_path)
        series_directory = os.path.normcase(os.path.abspath(parent_directory))
        reset_window_settings = series_directory != self._dicom_preview_series_directory
        self._dicom_preview_series_directory = series_directory
        try:
            self._dicom_preview_paths = sorted(
                os.path.join(parent_directory, filename)
                for filename in os.listdir(parent_directory)
                if filename.lower().endswith(".dcm")
            )
            self._dicom_preview_index = self._dicom_preview_paths.index(dicom_path)
        except (OSError, ValueError):
            self._dicom_preview_paths = [dicom_path]
            self._dicom_preview_index = 0

        self._load_dicom_preview(dicom_path, reset_window_settings=reset_window_settings)

    def _on_dicom_preview_wheel(self, event):
        """Move through DICOM files in the selected file's directory with the mouse wheel."""
        if event.delta > 0:
            self._step_dicom_preview(-1)
        elif event.delta < 0:
            self._step_dicom_preview(1)
        return "break"

    def _on_dicom_preview_resize(self, _event):
        """Refit the displayed preview when the available panel space changes."""
        self._render_dicom_preview_image()

    def _start_dicom_window_drag(self, event):
        """Record the window settings at the start of a left-button drag."""
        if self._dicom_preview_pixels is None:
            return

        self._dicom_preview_drag_start = (event.x, event.y)
        self._dicom_preview_drag_window = (
            self._dicom_preview_window_center,
            self._dicom_preview_window_width,
        )

    def _adjust_dicom_window_drag(self, event):
        """Use horizontal drag for width and vertical drag for window center."""
        if self._dicom_preview_drag_start is None or self._dicom_preview_drag_window is None:
            return

        start_x, start_y = self._dicom_preview_drag_start
        initial_center, initial_width = self._dicom_preview_drag_window
        if initial_center is None or initial_width is None:
            return

        width_delta = (event.x - start_x) * initial_width / DICOM_WINDOW_DRAG_PIXELS
        center_delta = (start_y - event.y) * initial_width / DICOM_WINDOW_DRAG_PIXELS
        self._dicom_preview_window_width = max(1.0, initial_width + width_delta)
        self._dicom_preview_window_center = initial_center + center_delta
        self._update_dicom_preview_window()

    def _update_dicom_preview_window(self):
        """Apply the selected center and width to calibrated DICOM pixel values."""
        if (
            self._dicom_preview_pixels is None
            or self._dicom_preview_window_center is None
            or self._dicom_preview_window_width is None
        ):
            return

        import numpy as np
        from PIL import Image

        lower = self._dicom_preview_window_center - (self._dicom_preview_window_width / 2)
        upper = self._dicom_preview_window_center + (self._dicom_preview_window_width / 2)
        display_pixels = np.clip(
            (self._dicom_preview_pixels - lower) / (upper - lower),
            0.0,
            1.0,
        )
        self._dicom_preview_source_image = Image.fromarray(
            (display_pixels * 255).astype(np.uint8),
            mode="L",
        )
        self._render_dicom_preview_image()
        self._update_dicom_preview_info()

    def _update_dicom_preview_info(self):
        """Display the preview file position and active window settings."""
        if self._dicom_preview_window_center is None or self._dicom_preview_window_width is None:
            return

        self._dicom_preview_info.configure(
            text=(
                f"{os.path.basename(self._dicom_preview_paths[self._dicom_preview_index])}  |  "
                f"{self._dicom_preview_index + 1} of {len(self._dicom_preview_paths)}  |  "
                f"C: {self._dicom_preview_window_center:.1f}  "
                f"W: {self._dicom_preview_window_width:.1f}"
            )
        )

    def _render_dicom_preview_image(self):
        """Scale the stored grayscale image to the preview label, preserving aspect ratio."""
        if self._dicom_preview_source_image is None:
            return

        available_width = self._dicom_preview_label.winfo_width() - (2 * DICOM_PREVIEW_PADDING)
        available_height = self._dicom_preview_label.winfo_height() - (2 * DICOM_PREVIEW_PADDING)
        if available_width <= 0 or available_height <= 0:
            return

        source_width, source_height = self._dicom_preview_source_image.size
        scale = min(available_width / source_width, available_height / source_height)
        display_size = (
            max(1, round(source_width * scale)),
            max(1, round(source_height * scale)),
        )

        from PIL import Image

        display_image = self._dicom_preview_source_image.resize(
            display_size,
            Image.Resampling.BILINEAR,
        )
        self._dicom_preview_image = ctk.CTkImage(
            light_image=display_image,
            dark_image=display_image,
            size=display_size,
        )
        self._dicom_preview_label.configure(image=self._dicom_preview_image, text="")

    def _step_dicom_preview(self, direction: int):
        """Load one adjacent DICOM file, wrapping at the ends of the directory list."""
        if not self._dicom_preview_paths:
            return
        self._dicom_preview_index = (
            self._dicom_preview_index + direction
        ) % len(self._dicom_preview_paths)
        dicom_path = self._dicom_preview_paths[self._dicom_preview_index]
        self._sync_tree_selection_to_dicom(dicom_path)
        self._load_dicom_preview(dicom_path, reset_window_settings=False)

    def _sync_tree_selection_to_dicom(self, dicom_path: str):
        """Highlight the previewed DICOM and scroll the tree only when it is out of view."""
        tree_item = self._find_processed_tree_item(dicom_path)
        if tree_item is None:
            return

        selected_item = getattr(self.fancy_tree_item_class, "selected_item", None)
        if selected_item is not None and selected_item is not tree_item:
            try:
                if selected_item.winfo_exists():
                    selected_item.configure(border_width=0)
            except Exception:
                pass

        tree_item.configure(border_width=1, border_color="#540908")
        self.fancy_tree_item_class.selected_item = tree_item
        self.selected_processed_path = dicom_path
        self._scroll_processed_tree_to_item(tree_item)

    def _find_processed_tree_item(self, path: str):
        """Find the already-rendered tree item for a selected DICOM path."""
        target_path = os.path.normcase(os.path.abspath(path))
        widgets = list(self.processed_tree.winfo_children())
        while widgets:
            widget = widgets.pop()
            widgets.extend(widget.winfo_children())
            item_path = getattr(widget, "path", None)
            if item_path is None:
                continue
            if os.path.normcase(os.path.abspath(str(item_path))) == target_path:
                return widget
        return None

    def _scroll_processed_tree_to_item(self, tree_item):
        """Keep the synchronized tree selection visible without rebuilding the tree."""
        canvas = getattr(self.processed_tree, "_parent_canvas", None)
        if canvas is None:
            return

        self.update_idletasks()
        item_top = tree_item.winfo_rooty() - canvas.winfo_rooty()
        item_bottom = item_top + tree_item.winfo_height()
        viewport_height = canvas.winfo_height()

        if item_top < 0:
            canvas.yview_scroll(int((item_top - 8) / 20), "units")
        elif item_bottom > viewport_height:
            canvas.yview_scroll(int((item_bottom - viewport_height + 8) / 20) + 1, "units")

    def _load_dicom_preview(self, dicom_path: str, reset_window_settings: bool):
        """Read one DICOM image and apply either its default or the active series window."""
        try:
            import numpy as np
            import pydicom

            dataset = pydicom.dcmread(dicom_path, stop_before_pixels=False)
            pixels = dataset.pixel_array.astype(np.float32)
            if pixels.ndim == 3:
                pixels = pixels[pixels.shape[0] // 2]
            if pixels.ndim != 2:
                raise ValueError(f"Unsupported pixel array shape: {pixels.shape}")

            slope = float(getattr(dataset, "RescaleSlope", 1.0))
            intercept = float(getattr(dataset, "RescaleIntercept", 0.0))
            pixels = pixels * slope + intercept
            finite_pixels = pixels[np.isfinite(pixels)]
            if finite_pixels.size == 0:
                raise ValueError("DICOM image has no finite pixel values.")

            lower, upper = np.percentile(finite_pixels, [1, 99])
            if upper <= lower:
                lower = float(np.min(finite_pixels))
                upper = float(np.max(finite_pixels))
            if upper <= lower:
                upper = lower + 1.0

            self._dicom_preview_pixels = pixels
            if reset_window_settings or self._dicom_preview_window_center is None:
                self._dicom_preview_window_center = (lower + upper) / 2
                self._dicom_preview_window_width = upper - lower
            self._dicom_preview_drag_start = None
            self._dicom_preview_drag_window = None
            self._update_dicom_preview_window()
        except Exception as error:
            self._dicom_preview_source_image = None
            self._dicom_preview_pixels = None
            self._dicom_preview_window_center = None
            self._dicom_preview_window_width = None
            self._dicom_preview_drag_start = None
            self._dicom_preview_drag_window = None
            self._dicom_preview_label.configure(image=None, text="Unable to display this DICOM file.")
            self._dicom_preview_info.configure(text=f"{os.path.basename(dicom_path)}: {error}")

    def build_tool_args(self, tool_id: str) -> list[str]:
        """Build optional CLI args for a tool based on GUI settings."""
        tool_args: list[str] = []
        out_dir = (self.settings.get("global_output_dir") or "").strip()
        out_flag = OUTPUT_ARG_BY_TOOL_ID.get(tool_id)

        if out_dir and out_flag:
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception:
                messagebox.showerror(
                    "Output Folder",
                    f"Could not create/access the configured output folder:\n{out_dir}",
                )
                return []
            tool_args.extend([out_flag, out_dir])

        return tool_args

    def _handle_ellipsis_click(self, button, tool_id: str):
        """Route a program's ⋮ button to whichever extra action it supports."""
        if tool_id in SUV_METADATA_TOOL_IDS:
            self.show_metadata_override_menu(button, tool_id)
        elif tool_id in UNIFORMITY_COMPARE_TOOL_IDS:
            self.open_uniformity_compare_dialog()

    def show_metadata_override_menu(self, button, tool_id: str):
        """Show the contextual action menu for a tool that calculates SUV."""
        self._metadata_override_menu = tk.Menu(self, tearoff=0)
        self._metadata_override_menu.add_command(
            label="Run with metadata overrides",
            command=lambda: self.open_metadata_override_dialog(tool_id),
        )
        try:
            self._metadata_override_menu.tk_popup(
                button.winfo_rootx(),
                button.winfo_rooty() + button.winfo_height(),
            )
        finally:
            self._metadata_override_menu.grab_release()

    def open_metadata_override_dialog(self, tool_id: str):
        """Collect optional SUV metadata corrections and launch the selected tool."""
        selected_path = self.get_selected_processed_path()
        if not selected_path or not os.path.isdir(selected_path):
            messagebox.showerror(
                "Metadata Overrides",
                "Select the input DICOM directory in the processed-input tree first.",
            )
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("SUV Metadata Overrides")
        dialog.geometry("760x650")
        dialog.minsize(620, 480)
        dialog.transient(self)
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            dialog,
            text="SUV Metadata Overrides",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 8))

        form = ctk.CTkScrollableFrame(dialog)
        form.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        form.grid_columnconfigure(1, weight=1)
        field_entries = {}

        for row_index, (label, path, _vr, units, _is_numeric) in enumerate(SUV_METADATA_FIELDS):
            ctk.CTkLabel(form, text=label, anchor="w").grid(
                row=row_index,
                column=0,
                sticky="w",
                padx=(8, 10),
                pady=6,
            )
            entry = ctk.CTkEntry(form, placeholder_text="Leave blank to keep DICOM value")
            entry.grid(row=row_index, column=1, sticky="ew", padx=(0, 10), pady=6)
            field_entries[path] = entry
            ctk.CTkLabel(form, text=units, anchor="w", width=130).grid(
                row=row_index,
                column=2,
                sticky="w",
                padx=(0, 8),
                pady=6,
            )

        footer = ctk.CTkFrame(dialog)
        footer.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(footer, text="Cancel", command=dialog.destroy).grid(
            row=0, column=1, padx=(8, 4), pady=10
        )
        ctk.CTkButton(
            footer,
            text="Run",
            command=lambda: self._write_metadata_overrides_and_run(
                dialog,
                tool_id,
                selected_path,
                field_entries,
            ),
        ).grid(row=0, column=2, padx=(4, 10), pady=10)

    def _write_metadata_overrides_and_run(
        self,
        dialog,
        tool_id: str,
        input_directory: str,
        field_entries: dict[str, ctk.CTkEntry],
    ):
        """Write only supplied values as a generic override document, then launch."""
        overrides = {}
        for _label, path, vr, units, is_numeric in SUV_METADATA_FIELDS:
            raw_value = field_entries[path].get().strip()
            if not raw_value:
                continue

            if is_numeric:
                try:
                    value = float(raw_value)
                except ValueError:
                    messagebox.showerror(
                        "Metadata Overrides",
                        f"{path} must be a numeric value.",
                        parent=dialog,
                    )
                    return
            else:
                value = raw_value.upper() if path in {"PatientSex", "DecayCorrection"} else raw_value

            overrides[path] = {"value": value, "vr": vr, "units": units}

        if not overrides:
            messagebox.showerror(
                "Metadata Overrides",
                "Enter at least one replacement value before running the tool.",
                parent=dialog,
            )
            return

        override_path = os.path.join(input_directory, "metadata_overrides.json")
        if os.path.exists(override_path):
            replace_existing = messagebox.askyesno(
                "Metadata Overrides",
                f"Replace the existing override file?\n\n{override_path}",
                parent=dialog,
            )
            if not replace_existing:
                return

        override_document = {
            "description": "SUV metadata corrections entered in PET QA Toolkit",
            "dicom_overrides": overrides,
        }
        try:
            with open(override_path, "w", encoding="utf-8") as override_file:
                json.dump(override_document, override_file, indent=2)
        except OSError as error:
            messagebox.showerror(
                "Metadata Overrides",
                f"Could not write the override file:\n\n{error}",
                parent=dialog,
            )
            return

        dialog.destroy()
        self.log_status(f"Launching {tool_id} with metadata overrides")
        self.run_tool(
            tool_id,
            extra_args=["--metadata-overrides", override_path],
        )

    # -----------------------------
    # PET/CT Coregistration picker
    # -----------------------------
    # The coregistration tool compares exactly two series directories. This
    # non-modal dialog collects them from clicks in the processed-input tree:
    # each clicked directory fills the next open slot, and Run stays disabled
    # until both slots hold valid directories.
    def open_coregistration_dialog(self):
        """Open the two-series picker fed by clicks in the processed tree."""
        if not (self.settings.get("processed_input_dir") or "").strip():
            messagebox.showerror(
                "PET/CT Coregistration",
                "Set a processed input folder first, then pick two series directories.",
            )
            return

        if self._coreg_dialog is not None and self._coreg_dialog.winfo_exists():
            self._coreg_dialog.lift()
            self._coreg_dialog.focus_force()
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("PET/CT Coregistration")
        dialog.geometry("680x240")
        dialog.minsize(560, 220)
        dialog.transient(self)
        dialog.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            dialog,
            text="Select two series directories from the processed-input tree.",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 2))

        ctk.CTkLabel(
            dialog,
            text="Each directory you click in the tree fills the next open slot below.",
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

        slots_frame = ctk.CTkFrame(dialog)
        slots_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        slots_frame.grid_columnconfigure(1, weight=1)

        self._coreg_slot_labels = []
        for slot_index, slot_name in enumerate(("Series 1", "Series 2")):
            ctk.CTkLabel(
                slots_frame,
                text=f"{slot_name}:",
                anchor="w",
                width=70,
            ).grid(row=slot_index, column=0, sticky="nw", padx=(8, 6), pady=8)
            path_label = ctk.CTkLabel(
                slots_frame,
                text="(click a directory in the tree)",
                anchor="w",
                justify="left",
                wraplength=460,
                text_color=("gray40", "gray60"),
            )
            path_label.grid(row=slot_index, column=1, sticky="ew", padx=(0, 6), pady=8)
            ctk.CTkButton(
                slots_frame,
                text="✕",
                width=30,
                command=lambda index=slot_index: self._clear_coreg_slot(index),
            ).grid(row=slot_index, column=2, sticky="ne", padx=(0, 8), pady=8)
            self._coreg_slot_labels.append(path_label)

        footer = ctk.CTkFrame(dialog)
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            footer,
            text="Cancel",
            command=self._close_coregistration_dialog,
        ).grid(row=0, column=1, padx=(8, 4), pady=10)
        self._coreg_run_button = ctk.CTkButton(
            footer,
            text="Run",
            state="disabled",
            command=self._run_coregistration_from_dialog,
        )
        self._coreg_run_button.grid(row=0, column=2, padx=(4, 10), pady=10)

        self._coreg_series = [None, None]
        self._coreg_dialog = dialog
        dialog.protocol("WM_DELETE_WINDOW", self._close_coregistration_dialog)
        self._refresh_coreg_dialog_state()

    def _close_coregistration_dialog(self):
        """Tear down the picker so tree clicks stop feeding it."""
        if self._coreg_dialog is not None and self._coreg_dialog.winfo_exists():
            self._coreg_dialog.destroy()
        self._coreg_dialog = None
        self._coreg_series = [None, None]
        self._coreg_slot_labels = []
        self._coreg_run_button = None

    def _offer_coreg_series_candidate(self, path: str):
        """Fill the next open slot when a directory is clicked in the tree."""
        if self._coreg_dialog is None or not self._coreg_dialog.winfo_exists():
            return
        if not os.path.isdir(path):
            return
        if path in self._coreg_series:
            self.log_status("Coregistration: directory is already selected")
            return

        for slot_index in range(2):
            if self._coreg_series[slot_index] is None:
                self._coreg_series[slot_index] = path
                self._refresh_coreg_dialog_state()
                return

        self.log_status("Coregistration slots are full; clear one with ✕ before picking another")

    def _clear_coreg_slot(self, slot_index: int):
        """Empty one slot so the next tree click refills it."""
        self._coreg_series[slot_index] = None
        self._refresh_coreg_dialog_state()

    def _refresh_coreg_dialog_state(self):
        """Sync slot labels and enable Run only when both slots are valid."""
        for slot_index, path_label in enumerate(self._coreg_slot_labels):
            selected = self._coreg_series[slot_index]
            if selected:
                path_label.configure(text=selected, text_color=("#111111", "#EEEEEE"))
            else:
                path_label.configure(
                    text="(click a directory in the tree)",
                    text_color=("gray40", "gray60"),
                )

        if self._coreg_run_button is not None:
            ready = all(p and os.path.isdir(p) for p in self._coreg_series)
            self._coreg_run_button.configure(state="normal" if ready else "disabled")

    def _run_coregistration_from_dialog(self):
        """Launch z_axis_coregistration with the two picked series directories."""
        dialog = self._coreg_dialog
        series1, series2 = self._coreg_series
        if not (series1 and os.path.isdir(series1)) or not (series2 and os.path.isdir(series2)):
            messagebox.showerror(
                "PET/CT Coregistration",
                "Both series slots must contain valid directories.",
                parent=dialog if dialog is not None else self,
            )
            return

        self.log_status(f"Launching coregistration:\n  Series 1: {series1}\n  Series 2: {series2}")
        self._close_coregistration_dialog()
        self.run_tool(
            "coreg",
            extra_args=["--series1", series1, "--series2", series2],
            use_selected_input=False,
        )

    # -----------------------------
    # Uniformity multi-series compare picker
    # -----------------------------
    # Overlays the uniformity deviation curve of several reconstructions of the
    # same exam on one plot. The ROI center/radius and axial slice range are
    # computed once from the first (reference) series and reused for the rest,
    # since comparison series share identical geometry. Directories are added
    # by clicking them in the processed-input tree, in the same style as the
    # coregistration picker, but the list is open-ended instead of two fixed
    # slots.
    def open_uniformity_compare_dialog(self):
        """Open the picker fed by clicks in the processed tree."""
        if not (self.settings.get("processed_input_dir") or "").strip():
            messagebox.showerror(
                "Compare Uniformity",
                "Set a processed input folder first, then pick two or more series directories.",
            )
            return

        if self._uniform_compare_dialog is not None and self._uniform_compare_dialog.winfo_exists():
            self._uniform_compare_dialog.lift()
            self._uniform_compare_dialog.focus_force()
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Compare Uniformity Across Series")
        dialog.geometry("680x420")
        dialog.minsize(560, 320)
        dialog.transient(self)
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            dialog,
            text="Select two or more reconstructions of the same PET exam.",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 2))

        ctk.CTkLabel(
            dialog,
            text=(
                "Click each series directory in the processed-input tree to add it below. "
                "The first series picked sets the ROI and slice range used for all of them; "
                "the legend uses each series' DICOM ReconstructionMethod (0054,1103)."
            ),
            anchor="w",
            justify="left",
            wraplength=620,
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

        rows_frame = ctk.CTkScrollableFrame(dialog)
        rows_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        rows_frame.grid_columnconfigure(0, weight=1)
        self._uniform_compare_rows_frame = rows_frame

        footer = ctk.CTkFrame(dialog)
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(footer, text="Cancel", command=self._close_uniform_compare_dialog).grid(
            row=0, column=1, padx=(8, 4), pady=10
        )
        self._uniform_compare_run_button = ctk.CTkButton(
            footer,
            text="Run",
            state="disabled",
            command=self._run_uniform_compare_from_dialog,
        )
        self._uniform_compare_run_button.grid(row=0, column=2, padx=(4, 10), pady=10)

        self._uniform_compare_series = []
        self._uniform_compare_dialog = dialog
        dialog.protocol("WM_DELETE_WINDOW", self._close_uniform_compare_dialog)
        self._refresh_uniform_compare_dialog_state()

    def _close_uniform_compare_dialog(self):
        """Tear down the picker so tree clicks stop feeding it."""
        if self._uniform_compare_dialog is not None and self._uniform_compare_dialog.winfo_exists():
            self._uniform_compare_dialog.destroy()
        self._uniform_compare_dialog = None
        self._uniform_compare_series = []
        self._uniform_compare_rows_frame = None
        self._uniform_compare_run_button = None

    def _offer_uniform_compare_series_candidate(self, path: str):
        """Append a clicked directory to the compare list, up to a small cap."""
        max_compare_series = 8
        if self._uniform_compare_dialog is None or not self._uniform_compare_dialog.winfo_exists():
            return
        if not os.path.isdir(path):
            return
        if path in self._uniform_compare_series:
            self.log_status("Compare uniformity: directory is already selected")
            return
        if len(self._uniform_compare_series) >= max_compare_series:
            self.log_status(f"Compare uniformity: maximum of {max_compare_series} series reached")
            return

        self._uniform_compare_series.append(path)
        self._refresh_uniform_compare_dialog_state()

    def _remove_uniform_compare_series(self, index: int):
        """Drop one picked series so a tree click can replace it."""
        if 0 <= index < len(self._uniform_compare_series):
            del self._uniform_compare_series[index]
            self._refresh_uniform_compare_dialog_state()

    def _refresh_uniform_compare_dialog_state(self):
        """Redraw the picked-series rows and enable Run once >= 2 are valid."""
        rows_frame = self._uniform_compare_rows_frame
        if rows_frame is None:
            return

        for widget in rows_frame.winfo_children():
            widget.destroy()

        if not self._uniform_compare_series:
            ctk.CTkLabel(
                rows_frame,
                text="(no series selected yet)",
                anchor="w",
                text_color=("gray40", "gray60"),
            ).grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        else:
            for row_index, series_path in enumerate(self._uniform_compare_series):
                prefix = "Reference: " if row_index == 0 else f"Series {row_index + 1}: "
                ctk.CTkLabel(
                    rows_frame,
                    text=f"{prefix}{series_path}",
                    anchor="w",
                    justify="left",
                    wraplength=520,
                ).grid(row=row_index, column=0, sticky="ew", padx=(8, 6), pady=4)
                ctk.CTkButton(
                    rows_frame,
                    text="✕",
                    width=30,
                    command=lambda index=row_index: self._remove_uniform_compare_series(index),
                ).grid(row=row_index, column=1, sticky="e", padx=(0, 8), pady=4)

        if self._uniform_compare_run_button is not None:
            ready = len(self._uniform_compare_series) >= 2 and all(
                os.path.isdir(p) for p in self._uniform_compare_series
            )
            self._uniform_compare_run_button.configure(state="normal" if ready else "disabled")

    def _run_uniform_compare_from_dialog(self):
        """Launch uniformity_scoring_auto in multi-series compare mode."""
        dialog = self._uniform_compare_dialog
        series_dirs = list(self._uniform_compare_series)
        if len(series_dirs) < 2 or not all(os.path.isdir(p) for p in series_dirs):
            messagebox.showerror(
                "Compare Uniformity",
                "Select at least two valid series directories before running.",
                parent=dialog if dialog is not None else self,
            )
            return

        self.log_status(f"Launching uniformity compare across {len(series_dirs)} series")
        self._close_uniform_compare_dialog()
        self.run_tool(
            "uniform_auto",
            extra_args=["--compare"] + series_dirs,
            use_selected_input=False,
        )

    def open_app_folder(self):
        open_path(exe_dir())

    def show_about(self):
        messagebox.showinfo(
            "About",
            f"{APP_NAME}\n{AUTHOR}\n\n"
            "This build runs tools as Python modules.\n"
            "That enables true single-file packaging."
        )

    def set_mode(self, mode: str):
        mode = (mode or "system").lower().strip()
        if mode not in ("system", "light", "dark"):
            mode = "system"
        ctk.set_appearance_mode(mode)
        self.settings["appearance_mode"] = mode
        save_settings(self.settings)

    def refresh_program_list(self):
        for w in self.scroll.winfo_children():
            w.destroy()

        missing_any = False

        # Build compact launch entries while keeping manual/automatic tools distinct.
        skip_ids: set[str] = set()
        program_entries = []

        for t in TOOLS:
            tid = t["id"]
            if tid in skip_ids:
                continue
            if tid == "overlay":
                program_entries.append((
                    "pair",
                    ("SUV Auto", TOOL_BY_ID.get("overlay_auto")),
                    ("SUV Manual", TOOL_BY_ID.get("overlay")),
                ))
                skip_ids.update(["overlay", "overlay_auto"])
                continue
            if tid == "uniform":
                program_entries.append((
                    "pair",
                    ("Uniformity Auto", TOOL_BY_ID.get("uniform_auto")),
                    ("Uniformity Manual", TOOL_BY_ID.get("uniform")),
                ))
                skip_ids.update(["uniform", "uniform_auto"])
                continue
            program_entries.append(("single", (t["name"], t)))

        # Render one compact launch button per program entry.
        for row_index, entry in enumerate(program_entries):
            entry_type = entry[0]
            if entry_type == "pair":
                paired_entries = entry[1:]
                self.scroll.grid_columnconfigure(0, weight=1)
                self.scroll.grid_columnconfigure(1, weight=0)
                self.scroll.grid_columnconfigure(2, weight=1)
                self.scroll.grid_columnconfigure(3, weight=0)
                for column, (display_name, tool) in enumerate(paired_entries):
                    button_column = column * 2
                    if tool is None:
                        missing_any = True
                        continue
                    is_available = module_exists(tool["module"])
                    missing_any = missing_any or not is_available
                    has_ellipsis_menu = (
                        tool["id"] in SUV_METADATA_TOOL_IDS
                        or tool["id"] in UNIFORMITY_COMPARE_TOOL_IDS
                    )
                    ctk.CTkButton(
                        self.scroll,
                        text=display_name,
                        height=34,
                        font=ctk.CTkFont(size=13, weight="bold"),
                        anchor="w",
                        state="normal" if is_available else "disabled",
                        command=lambda tid=tool["id"]: self.run_tool(tid),
                    ).grid(
                        row=row_index,
                        column=button_column,
                        columnspan=1 if has_ellipsis_menu else 2,
                        sticky="ew",
                        padx=(2, 2),
                        pady=3,
                    )

                    if has_ellipsis_menu:
                        ellipsis_button = ctk.CTkButton(
                            self.scroll,
                            text="⋮",
                            width=30,
                            height=34,
                            command=lambda: None,
                        )
                        ellipsis_button.configure(
                            command=lambda button=ellipsis_button, tid=tool["id"]: self._handle_ellipsis_click(
                                button,
                                tid,
                            )
                        )
                        ellipsis_button.grid(
                            row=row_index,
                            column=button_column + 1,
                            sticky="e",
                            padx=(0, 2),
                            pady=3,
                        )
                continue

            display_name, tool = entry[1]
            if tool is None:
                missing_any = True
                continue
            is_available = module_exists(tool["module"])
            missing_any = missing_any or not is_available
            if tool["id"] == "coreg":
                # Coregistration needs two series directories, so open the
                # picker dialog instead of launching with one tree selection.
                button_command = self.open_coregistration_dialog
            else:
                button_command = lambda tid=tool["id"]: self.run_tool(tid)
            ctk.CTkButton(
                self.scroll,
                text=display_name,
                height=34,
                font=ctk.CTkFont(size=13, weight="bold"),
                anchor="w",
                state="normal" if is_available else "disabled",
                command=button_command,
            ).grid(
                row=row_index,
                column=0,
                columnspan=3 if tool["id"] in SUV_METADATA_TOOL_IDS else 4,
                sticky="ew",
                padx=(2, 4),
                pady=3,
            )

            if tool["id"] in SUV_METADATA_TOOL_IDS:
                metadata_menu_button = ctk.CTkButton(
                    self.scroll,
                    text="⋮",
                    width=30,
                    height=34,
                    command=lambda: None,
                )
                metadata_menu_button.configure(
                    command=lambda button=metadata_menu_button, tid=tool["id"]: self.show_metadata_override_menu(
                        button,
                        tid,
                    )
                )
                metadata_menu_button.grid(row=row_index, column=3, sticky="e", padx=(0, 2), pady=3)

        if missing_any:
            warn = ctk.CTkLabel(
                self.scroll,
                text=(
                    "One or more tool modules could not be imported.\n"
                    "Make sure your folder is named 'pet_tools' and contains '__init__.py'."
                )
            )
            warn.grid(row=len(program_entries), column=0, sticky="w", padx=8, pady=(8, 2))

    def run_tool(
        self,
        tool_id: str,
        extra_args: list[str] | None = None,
        use_selected_input: bool = True,
    ):
        tool = TOOL_BY_ID.get(tool_id)
        if not tool:
            messagebox.showerror("Run Program", f"Unknown tool id: {tool_id}")
            return

        if not module_exists(tool["module"]):
            messagebox.showerror(
                "Run Program",
                "Tool module not importable.\n\n"
                f"Module: {tool['module']}\n\n"
                "Fix:\n"
                " - Rename PET-Tools to pet_tools\n"
                " - Ensure pet_tools\\__init__.py exists"
            )
            return

        self.log_status(f"Launching: {tool['module']}")

        tool_args = self.build_tool_args(tool_id)

        if use_selected_input:
            input_flag = INPUT_ARG_BY_TOOL_ID.get(tool_id)
            input_file_spec = INPUT_FILE_ARG_BY_TOOL_ID.get(tool_id)
            selected_path = self.get_selected_processed_path()

            # Safeguard: every tool in INPUT_ARG_BY_TOOL_ID expects an input
            # DIRECTORY. Error out explicitly instead of silently passing a
            # file path (or nothing) to the tool CLI.
            if input_flag:
                if selected_path is None:
                    messagebox.showerror(
                        "Run Program",
                        f"{tool['name']} requires an input directory.\n\n"
                        "Select a directory in the processed-input tree first.",
                    )
                    return
                if os.path.isfile(selected_path):
                    messagebox.showerror(
                        "Run Program",
                        f"{tool['name']} requires an input directory, the current "
                        f"selection is a file "
                        "select a directory instead.",
                    )
                    return
                tool_args.extend([input_flag, selected_path])

            # Safeguard: tools in INPUT_FILE_ARG_BY_TOOL_ID expect an input
            # FILE of a specific type. Error out explicitly instead of silently
            # passing a directory (or the wrong file type) to the tool CLI.
            if input_file_spec:
                file_flag, file_extension = input_file_spec
                if selected_path is None:
                    messagebox.showerror(
                        "Run Program",
                        f"{tool['name']} requires a {file_extension} file.\n\n"
                        f"Select a {file_extension} file in the processed-input tree first.",
                    )
                    return
                if os.path.isdir(selected_path):
                    messagebox.showerror(
                        "Run Program",
                        f"{tool['name']} requires a {file_extension} file, the current "
                        f"selection is a directory "
                        f"select a {file_extension} file instead.",
                    )
                    return
                if not selected_path.lower().endswith(file_extension):
                    messagebox.showerror(
                        "Run Program",
                        f"{tool['name']} requires a {file_extension} file, the current "
                        f"selection is not a {file_extension} file "
                        f"select a {file_extension} file instead.",
                    )
                    return
                tool_args.extend([file_flag, selected_path])

        if extra_args:
            tool_args.extend(extra_args)

        try:
            if is_frozen():
                cmd = [sys.executable, "--run-tool", tool_id, "--"] + tool_args
                cwd = exe_dir()
            else:
                cmd = [
                    sys.executable,
                    os.path.abspath(__file__),
                    "--run-tool",
                    tool_id,
                    "--"
                ] + tool_args
                cwd = exe_dir()

            if is_windows():
                creationflags = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
                subprocess.Popen(cmd, cwd=cwd, creationflags=creationflags)
            else:
                subprocess.Popen(cmd, cwd=cwd)

        except Exception as e:
            messagebox.showerror("Run Program", f"Could not start tool.\n\n{e}")


if __name__ == "__main__":
    ensure_settings()
    install_tk_callback_logger()
    args = parse_args()

    if args.run_tool:
        tail = list(args.tool_args or [])
        if tail and tail[0] == "--":
            tail = tail[1:]
        raise SystemExit(run_tool_module_in_process(args.run_tool, tail))

    settings = load_settings()
    ctk.set_default_color_theme(THEME_PATH)
    ctk.set_appearance_mode("system")
    app = LauncherApp()
    app.mainloop()
