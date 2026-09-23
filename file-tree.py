from pathlib import Path
import tkinter as tk
import customtkinter as ctk


class CTkFileTreeItem(ctk.CTkFrame):
    selected_item = None

    def __init__(self, master, path: Path, level=0, on_select=None):
        super().__init__(
            master,
            fg_color="transparent",
            corner_radius=8,
            border_width=0
        )

        self.path = Path(path)
        self.level = level
        self.expanded = False
        self.loaded = False
        self.children_items = []
        self.on_select = on_select

        # Child nodes are rendered inside this item so expand/collapse stays in-place.
        self.children_container = ctk.CTkFrame(self, fg_color="transparent")

        icon = "📁" if self.path.is_dir() else "📄"

        self.label = ctk.CTkLabel(
            self,
            text=f"{icon} {self.path.name}",
            anchor="w"
        )
        self.label.pack(fill="x", padx=(level * 22 + 8, 8), pady=4)

        self.bind("<Button-1>", self.on_click)
        self.label.bind("<Button-1>", self.on_click)

    def on_click(self, event=None):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return

        # Deselect previous item only if it still exists in the widget tree
        if CTkFileTreeItem.selected_item is not None:
            try:
                # Check if widget is still valid by testing winfo_exists()
                if CTkFileTreeItem.selected_item.winfo_exists():
                    CTkFileTreeItem.selected_item.configure(border_width=0)
            except Exception:
                # Widget has been destroyed; skip deselection
                pass

        CTkFileTreeItem.selected_item = self
        self.configure(border_width=1, border_color="#540908")

        if self.on_select is not None:
            self.on_select(str(self.path))

        if self.path.is_dir():
            self.toggle()

    def toggle(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return

        if not self.loaded:
            self.load_children()

        self.expanded = not self.expanded

        for child in self.children_items:
            if self.expanded:
                try:
                    if not self.children_container.winfo_ismapped():
                        self.children_container.pack(fill="x")
                    child.pack(fill="x", padx=0, pady=1)
                except Exception:
                    continue
            else:
                try:
                    child.pack_forget()
                except Exception:
                    continue

        try:
            if not self.expanded and self.children_container.winfo_ismapped():
                self.children_container.pack_forget()
        except Exception:
            pass

    def load_children(self):
        try:
            entries = sorted(
                self.path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except (PermissionError, FileNotFoundError, OSError):
            entries = []

        for entry in entries:
            try:
                child = CTkFileTreeItem(
                    self.children_container,
                    entry,
                    self.level + 1,
                    on_select=self.on_select
                )
                self.children_items.append(child)
            except Exception:
                continue

        self.loaded = True


def populate_file_tree(parent_frame, root_folder, on_select=None):
    root_folder = Path(root_folder)

    for widget in parent_frame.winfo_children():
        widget.destroy()

    root_item = CTkFileTreeItem(parent_frame, root_folder, level=0, on_select=on_select)
    root_item.pack(fill="x", padx=4, pady=1)
    root_item.toggle()

    return root_item