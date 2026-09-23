#!/usr/bin/env python3
"""Debug wrapper for PET_GUI that captures full tkinter callback exceptions to a file."""

import sys
import traceback
import tkinter as tk
from io import StringIO

# Open a log file for exceptions
exception_log = open("tkinter_exceptions.log", "w", buffering=1)

# Monkey-patch tkinter's report_callback_exception to capture full tracebacks
original_report = tk.Tk.report_callback_exception

def patched_report(self, exc_type, exc_value, exc_traceback):
    exception_log.write("\n" + "="*80 + "\n")
    exception_log.write("TKINTER CALLBACK EXCEPTION:\n")
    exception_log.write("="*80 + "\n")
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=exception_log)
    exception_log.write("="*80 + "\n\n")
    exception_log.flush()
    # Still call original to maintain standard behavior
    original_report(self, exc_type, exc_value, exc_traceback)

tk.Tk.report_callback_exception = patched_report

# Also set up global exception hook
def show_exception(exc_type, exc_value, exc_traceback):
    exception_log.write("\n" + "="*80 + "\n")
    exception_log.write("UNCAUGHT EXCEPTION:\n")
    exception_log.write("="*80 + "\n")
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=exception_log)
    exception_log.write("="*80 + "\n\n")
    exception_log.flush()
    print(f"Exception logged to tkinter_exceptions.log", file=sys.stderr)

sys.excepthook = show_exception

try:
    # Now import and run the GUI
    from PET_GUI import *

    if __name__ == "__main__":
        ensure_settings()
        args = parse_args()

        if args.run_tool:
            tail = list(args.tool_args or [])
            if tail and tail[0] == "--":
                tail = tail[1:]
            raise SystemExit(run_tool_module_in_process(args.run_tool, tail))

        settings = load_settings()
        import customtkinter as ctk
        ctk.set_default_color_theme(THEME_PATH)
        ctk.set_appearance_mode("system")
        print("Launching GUI... (exceptions logged to tkinter_exceptions.log)", file=sys.stderr)
        app = LauncherApp()
        app.mainloop()
finally:
    exception_log.close()
