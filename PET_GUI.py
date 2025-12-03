# rb_program_launcher.py
# A modern program launcher (tkinter + customtkinter)
# By: Ryan Byrd

import os
import sys
import json
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import webbrowser

try:
    import customtkinter as ctk
except ImportError:
    print("[INFO] Installing customtkinter...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "customtkinter"])
    import customtkinter as ctk

APP_NAME = "Program Launcher"
AUTHOR = "By: Ryan Byrd"
SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".rb_launcher")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")
THEME_PATH = os.path.join(SETTINGS_DIR, "maroon_theme.json")

DEFAULT_SETTINGS = {
    "programs_dir": ""
}

# --- Create a minimal maroon theme for customtkinter ---
MAROON_THEME = {
    "CTk": {
        "fg_color": ["#F2F2F2", "#1a1a1a"],
        "top_fg_color": ["#EAEAEA", "#121212"],
        "border_color": ["#D0D0D0", "#2B2B2B"],
        "text_color": ["#111111", "#EEEEEE"],
        "text_color_disabled": ["#8B8B8B", "#7A7A7A"]
    },

    "CTkFont": {
        "family": "Segoe UI",
        "size": 13,
        "weight": "normal"
    },

    "CTkButton": {
        "corner_radius": 10,
        "border_width": 0,
        "fg_color": ["#7a0019", "#7a0019"],
        "hover_color": ["#8b001c", "#8b001c"],
        "text_color": ["#FFFFFF", "#FFFFFF"],
        "text_color_disabled": ["#BBBBBB", "#555555"],
        "border_color": ["#5c0013", "#5c0013"]
    },

    "CTkEntry": {
        "corner_radius": 8,
        "border_width": 1,
        "fg_color": ["#FFFFFF", "#2A2A2A"],
        "border_color": ["#C0C0C0", "#3A3A3A"],
        "text_color": ["#111111", "#FFFFFF"],
        "placeholder_text_color": ["#7A7A7A", "#A0A0A0"]
    },

    "CTkLabel": {
        "fg_color": "transparent",
        "text_color": ["#111111", "#EEEEEE"],
        "corner_radius": 0
    },

    "CTkFrame": {
        "corner_radius": 12,
        "border_width": 1,
        "fg_color": ["#FFFFFF", "#242424"],
        "top_fg_color": ["#F8F8F8", "#1E1E1E"],  # ✅ added key for CTkScrollableFrame
        "border_color": ["#D0D0D0", "#2B2B2B"]
    },

    "CTkScrollableFrame": {
        "label_fg_color": ["#FFFFFF", "#242424"],
        "border_color": ["#D0D0D0", "#2B2B2B"],
        "fg_color": ["#FFFFFF", "#242424"],
        "corner_radius": 12,
        "top_fg_color": ["#F8F8F8", "#1E1E1E"]   # ✅ also added
    },

    "CTkSwitch": {
        "progress_color": ["#7a0019", "#7a0019"]
    },

    "CTkCheckBox": {
        "border_color": ["#7a0019", "#7a0019"],
        "fg_color": ["#7a0019", "#7a0019"],
        "hover_color": ["#8b001c", "#8b001c"]
    },

    "CTkRadioButton": {
        "fg_color": ["#7a0019", "#7a0019"],
        "border_color": ["#7a0019", "#7a0019"],
        "hover_color": ["#8b001c", "#8b001c"]
    },

    "CTkProgressBar": {
        "progress_color": ["#7a0019", "#7a0019"],
        "fg_color": ["#E0E0E0", "#333333"],
        "border_color": ["#C0C0C0", "#3A3A3A"]
    }
    ,
    "CTkScrollbar": {
        "fg_color": ["#F0F0F0", "#1E1E1E"],
        "button_color": ["#7a0019", "#7a0019"],
        "button_hover_color": ["#8b001c", "#8b001c"],
        "border_color": ["#C0C0C0", "#3A3A3A"],
        "corner_radius": 6,
        "border_spacing": 4
    }

}



def ensure_settings():
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    if not os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)
    if not os.path.exists(THEME_PATH):
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

def is_windows():
    return os.name == "nt"

def open_path(path):
    # Open files/folders with the OS default handler
    try:
        if is_windows():
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Open Error", f"Could not open:\n{path}\n\n{e}")

def find_docs_for_script(py_path):
    """
    Try to find documentation file(s) for a given .py:
    - same directory, same stem with .md/.txt/.pdf
    - or a 'docs' folder next to it containing anything matching stem.*
    Returns best single candidate path or None.
    """
    folder = os.path.dirname(py_path)
    stem = os.path.splitext(os.path.basename(py_path))[0]
    candidates = [
        os.path.join(folder, f"{stem}.md"),
        os.path.join(folder, f"{stem}.txt"),
        os.path.join(folder, f"{stem}.pdf"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    docs_dir = os.path.join(folder, "docs")
    if os.path.isdir(docs_dir):
        for ext in (".md", ".txt", ".pdf", ".html", ".rtf"):
            cand = os.path.join(docs_dir, f"{stem}{ext}")
            if os.path.isfile(cand):
                return cand
        # fall back to any file in docs/
        for name in os.listdir(docs_dir):
            p = os.path.join(docs_dir, name)
            if os.path.isfile(p):
                return p
    return None

def discover_programs(programs_dir):
    """
    Returns a list of .py files (non-underscored, non-__init__).
    """
    if not programs_dir or not os.path.isdir(programs_dir):
        return []
    items = []
    for name in sorted(os.listdir(programs_dir)):
        if not name.lower().endswith(".py"):
            continue
        if name.startswith("_") or name == "__init__.py":
            continue
        items.append(os.path.join(programs_dir, name))
    return items

def create_default_installers(programs_dir):
    """
    If no install script exists, create a basic one:
      - install_deps.bat (Windows)
      - install_deps.sh (posix)
    Each will:
      - check for requirements.txt in programs_dir
      - run pip install -r requirements.txt
    """
    req = os.path.join(programs_dir, "requirements.txt")
    if is_windows():
        bat_path = os.path.join(programs_dir, "install_deps.bat")
        if not os.path.exists(bat_path):
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(
                    "@echo off\r\n"
                    "setlocal\r\n"
                    "echo [INFO] Checking for requirements.txt...\r\n"
                    f'if exist "requirements.txt" (\r\n'
                    f'  echo [INFO] Installing modules from requirements.txt...\r\n'
                    f'  "{sys.executable}" -m pip install -r "requirements.txt"\r\n'
                    ") else (\r\n"
                    "  echo [INFO] No requirements.txt found. Skipping installs.\r\n"
                    ")\r\n"
                    "echo [INFO] Done.\r\n"
                    "endlocal\r\n"
                )
    else:
        sh_path = os.path.join(programs_dir, "install_deps.sh")
        if not os.path.exists(sh_path):
            with open(sh_path, "w", encoding="utf-8") as f:
                f.write(
                    "#!/usr/bin/env bash\n"
                    "set -e\n"
                    'echo "[INFO] Checking for requirements.txt..."\n'
                    'if [ -f "requirements.txt" ]; then\n'
                    f'  echo "[INFO] Installing modules from requirements.txt..."\n'
                    f'  "{sys.executable}" -m pip install -r "requirements.txt"\n'
                    "else\n"
                    '  echo "[INFO] No requirements.txt found. Skipping installs."\n'
                    "fi\n"
                    'echo "[INFO] Done."\n'
                )
            try:
                os.chmod(sh_path, 0o755)
            except Exception:
                pass

def run_install_script_async(programs_dir, log_callback=None):
    """
    Runs install_deps.bat or install_deps.sh on a background thread.
    Passes the programs_dir as an argument so the batch script knows
    which folder contains requirements.txt.
    """
    if not programs_dir or not os.path.isdir(programs_dir):
        if log_callback:
            log_callback("[WARN] Programs folder not set.")
        return

    bat = os.path.join(programs_dir, "install_deps.bat")
    sh = os.path.join(programs_dir, "install_deps.sh")

    # Create default installer scripts if they don't exist
    if not os.path.exists(bat) and not os.path.exists(sh):
        create_default_installers(programs_dir)

    cmd = None
    cwd = programs_dir

    # --- WINDOWS: Run .bat and pass the folder path argument ---
    if is_windows() and os.path.exists(bat):
        cmd = ["cmd", "/c", bat, f'"{programs_dir}"']  # ✅ Pass the folder path here
    # --- macOS/Linux: Run .sh and pass the folder path argument ---
    elif os.path.exists(sh):
        cmd = ["/bin/bash", sh, programs_dir]

    if cmd is None:
        if log_callback:
            log_callback("[INFO] No installer script found. Skipping dependency install.")
        return

    def worker():
        try:
            if log_callback:
                log_callback(f"[INFO] Running installer: {' '.join(cmd)}")
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False
            )
            # Stream output live to the GUI status bar
            for line in iter(proc.stdout.readline, ''):
                if not line:
                    break
                if log_callback:
                    log_callback(line.rstrip())
            proc.wait()
            if log_callback:
                log_callback(f"[INFO] Installer finished with code {proc.returncode}.")
        except Exception as e:
            if log_callback:
                log_callback(f"[ERROR] Installer failed: {e}")

    threading.Thread(target=worker, daemon=True).start()


class LauncherApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        ensure_settings()
        ctk.set_appearance_mode("system")          # match OS light/dark
        ctk.set_default_color_theme(THEME_PATH)    # maroon accent

        self.title(APP_NAME)
        self.geometry("900x600")
        self.minsize(780, 480)

        self.settings = load_settings()

        # --- Layout: sidebar + main area ---
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self)
        header.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=10, pady=(10, 5))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        title_label = ctk.CTkLabel(header, text=APP_NAME, font=ctk.CTkFont(size=20, weight="bold"))
        title_label.grid(row=0, column=0, sticky="w", padx=10, pady=10)

        self.path_label = ctk.CTkLabel(header, text=self._pretty_path(self.settings.get("programs_dir", "")))
        self.path_label.grid(row=0, column=1, sticky="e", padx=10)

        # Sidebar
        sidebar = ctk.CTkFrame(self)
        sidebar.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=5)
        sidebar.grid_rowconfigure(10, weight=1)  # spacer
        set_btn = ctk.CTkButton(sidebar, text="Set Programs Folder", command=self.choose_programs_folder)
        set_btn.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        open_folder_btn = ctk.CTkButton(sidebar, text="Open Folder", command=self.open_current_folder)
        open_folder_btn.grid(row=1, column=0, sticky="ew", padx=10, pady=6)

        refresh_btn = ctk.CTkButton(sidebar, text="Refresh List", command=self.refresh_program_list)
        refresh_btn.grid(row=2, column=0, sticky="ew", padx=10, pady=6)

        install_btn = ctk.CTkButton(sidebar, text="Run Installer Now", command=self.run_installer_now)
        install_btn.grid(row=3, column=0, sticky="ew", padx=10, pady=6)

        # Main area (program list)
        main = ctk.CTkFrame(self)
        main.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=5)
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        list_header = ctk.CTkLabel(main, text="Available Programs", font=ctk.CTkFont(size=16, weight="bold"))
        list_header.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))

        self.scroll = ctk.CTkScrollableFrame(main)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.scroll.grid_columnconfigure(0, weight=1)

        # Footer
        footer = ctk.CTkFrame(self)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(5, 10))
        footer.grid_columnconfigure(0, weight=1)
        footer.grid_columnconfigure(1, weight=0)

        author_label = ctk.CTkLabel(footer, text=AUTHOR, anchor="w")
        author_label.grid(row=0, column=0, sticky="w", padx=10, pady=6)

        self.status_label = ctk.CTkLabel(footer, text="Ready", anchor="e")
        self.status_label.grid(row=0, column=1, sticky="e", padx=10, pady=6)

        # Populate the list
        self.program_buttons = []
        self.refresh_program_list()

        # Kick off dependency install
        self.after(300, lambda: run_install_script_async(self.settings.get("programs_dir", ""), self.log_status))

    def log_status(self, msg):
        # Throttle UI updates slightly
        def update():
            self.status_label.configure(text=msg)
        self.after(0, update)

    def _pretty_path(self, p):
        if not p:
            return "(No folder set)"
        try:
            home = os.path.expanduser("~")
            if p.startswith(home):
                return p.replace(home, "~", 1)
            return p
        except Exception:
            return p

    def choose_programs_folder(self):
        chosen = filedialog.askdirectory(title="Select Programs Folder")
        if not chosen:
            return
        self.settings["programs_dir"] = chosen
        save_settings(self.settings)
        self.path_label.configure(text=self._pretty_path(chosen))
        self.refresh_program_list()
        # Run installer after setting a new folder
        run_install_script_async(chosen, self.log_status)

    def open_current_folder(self):
        p = self.settings.get("programs_dir", "")
        if p and os.path.isdir(p):
            open_path(p)
        else:
            messagebox.showinfo("Open Folder", "No valid programs folder set.")

    def refresh_program_list(self):
        # Clear previous items
        for w in self.scroll.winfo_children():
            w.destroy()
        self.program_buttons.clear()

        programs_dir = self.settings.get("programs_dir", "")
        programs = discover_programs(programs_dir)

        if not programs:
            empty = ctk.CTkLabel(self.scroll, text="No .py programs found. Set a Programs Folder.")
            empty.grid(row=0, column=0, sticky="w", padx=6, pady=6)
            return

        for idx, py in enumerate(programs):
            row = ctk.CTkFrame(self.scroll)
            row.grid(row=idx, column=0, sticky="ew", padx=6, pady=6)
            row.grid_columnconfigure(0, weight=1)
            row.grid_columnconfigure(1, weight=0)
            row.grid_columnconfigure(2, weight=0)

            name = os.path.splitext(os.path.basename(py))[0].replace("_", " ")
            label = ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=14, weight="bold"))
            label.grid(row=0, column=0, sticky="w", padx=8, pady=8)

            run_btn = ctk.CTkButton(row, text="Run",
                                    command=lambda p=py: self.run_program(p))
            run_btn.grid(row=0, column=1, sticky="e", padx=(8, 4), pady=8)

            docs_btn = ctk.CTkButton(row, text="Docs",
                                     command=lambda p=py: self.open_docs(p))
            docs_btn.grid(row=0, column=2, sticky="e", padx=(4, 8), pady=8)

            self.program_buttons.append((label, run_btn, docs_btn))

    def run_program(self, py_path):
        if not os.path.isfile(py_path):
            messagebox.showerror("Run Program", f"File not found:\n{py_path}")
            return
        self.log_status(f"[INFO] Launching: {os.path.basename(py_path)}")
        try:
            # Launch in a separate console window on Windows; else run detached
            if is_windows():
                creationflags = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
                subprocess.Popen([sys.executable, py_path],
                                 cwd=os.path.dirname(py_path),
                                 creationflags=creationflags)
            else:
                subprocess.Popen([sys.executable, py_path],
                                 cwd=os.path.dirname(py_path))
        except Exception as e:
            messagebox.showerror("Run Program", f"Could not start:\n{py_path}\n\n{e}")

    def open_docs(self, py_path):
        doc = find_docs_for_script(py_path)
        if doc:
            open_path(doc)
        else:
            messagebox.showinfo("Docs", "No documentation found for this program.\n\n"
                                        "Tip: place a .md/.txt/.pdf with the same name next to the script, "
                                        "or in a 'docs' folder.")

    def run_installer_now(self):
        run_install_script_async(self.settings.get("programs_dir", ""), self.log_status)


if __name__ == "__main__":
    ensure_settings()
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme(THEME_PATH)
    app = LauncherApp()
    app.mainloop()
