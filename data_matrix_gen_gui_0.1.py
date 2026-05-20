#!/usr/bin/env python3
"""Create and preview Data Matrix barcode PNGs with a GUI."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk
import zxingcpp


# -----------------------------
# Settings
# -----------------------------

SCALE = 10
MARGIN = 10
OUTPUT_DIR = Path("Output")


# -----------------------------
# Helpers
# -----------------------------


def safe_filename(text: str) -> str:
    """Convert text into a Windows-safe filename."""

    cleaned = re.sub(r'[\\/:*?"<>|]', '_', text)
    cleaned = cleaned.rstrip(" .")

    if not cleaned:
        cleaned = "data_matrix"

    return cleaned



def generate_datamatrix_image(data: str) -> Image.Image:
    """Generate a PIL image containing a Data Matrix barcode."""

    barcode = zxingcpp.create_barcode(
        data,
        zxingcpp.BarcodeFormat.DataMatrix,
        force_square=True,
    )

    image = Image.fromarray(
        barcode.to_image(scale=SCALE, add_quiet_zones=False)
    ).convert("L")

    if MARGIN:
        margin_px = MARGIN * SCALE

        bordered = Image.new(
            "L",
            (
                image.width + (2 * margin_px),
                image.height + (2 * margin_px),
            ),
            color=255,
        )

        bordered.paste(image, (margin_px, margin_px))
        image = bordered

    return image


# -----------------------------
# GUI App
# -----------------------------


class DataMatrixApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Data Matrix Generator")
        self.root.geometry("700x700")

        OUTPUT_DIR.mkdir(exist_ok=True)

        self.current_image = None
        self.preview_photo = None

        self.build_ui()

    def build_ui(self):
        # Main frame
        frame = ttk.Frame(self.root, padding=15)
        frame.pack(fill="both", expand=True)

        # Label
        ttk.Label(
            frame,
            text="Text to Encode",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")

        # Text input
        self.text_input = tk.Text(
            frame,
            height=5,
            wrap="word",
            font=("Segoe UI", 14),
            bg="#2b2b2b",
            fg="#f0f0f0",
            insertbackground="#f0f0f0",
            selectbackground="#505050",
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=0,
        )
        self.text_input.pack(fill="x", pady=(5, 10))

        self.text_input.bind("<KeyRelease>", self.update_preview)

        # Buttons
        button_style = ttk.Style()
        button_style.configure(
            "Large.TButton",
            font=("Segoe UI", 15),
            padding=6,
        )

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill="x", pady=(0, 10))

        ttk.Button(
            button_frame,
            text="Generate Preview",
            command=self.update_preview,
            style="Large.TButton",
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            button_frame,
            text="Save PNG",
            command=self.save_png,
            style="Large.TButton",
        ).pack(side="left")

        # Preview label
        ttk.Label(
            frame,
            text="Preview",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w", pady=(10, 5))

        # Preview box
        self.preview_label = ttk.Label(frame)
        self.preview_label.pack(expand=True)

    def get_text(self) -> str:
        return self.text_input.get("1.0", "end").strip()

    def update_preview(self, event=None):
        data = self.get_text()

        if not data:
            self.preview_label.configure(image="")
            self.current_image = None
            return

        try:
            image = generate_datamatrix_image(data)

            # Resize preview if too large
            preview = image.copy()
            preview.thumbnail((500, 500))

            self.preview_photo = ImageTk.PhotoImage(preview)

            self.preview_label.configure(image=self.preview_photo)

            self.current_image = image

        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def save_png(self):
        data = self.get_text()

        if not data:
            messagebox.showwarning(
                "No Text",
                "Please enter text to encode.",
            )
            return

        try:
            image = generate_datamatrix_image(data)

            filename = safe_filename(data) + ".png"
            output_path = OUTPUT_DIR / filename

            image.save(output_path)

            messagebox.showinfo(
                "Saved",
                f"Saved PNG:\n{output_path}",
            )

        except Exception as exc:
            messagebox.showerror("Error", str(exc))


# -----------------------------
# Main
# -----------------------------


def main():
    root = tk.Tk()

    # -----------------------------
    # Dark Mode Styling
    # -----------------------------

    DARK_BG = "#1e1e1e"
    DARK_PANEL = "#2b2b2b"
    DARK_TEXT = "#f0f0f0"

    root.configure(bg=DARK_BG)

    style = ttk.Style()

    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure(
        ".",
        background=DARK_BG,
        foreground=DARK_TEXT,
        fieldbackground=DARK_PANEL,
    )

    style.configure(
        "TFrame",
        background=DARK_BG,
    )

    style.configure(
        "TLabel",
        background=DARK_BG,
        foreground=DARK_TEXT,
    )

    style.configure(
        "Large.TButton",
        background=DARK_PANEL,
        foreground=DARK_TEXT,
    )

    style.map(
        "Large.TButton",
        background=[("active", "#3a3a3a")],
    )

    # Use modern Windows theme if available
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = DataMatrixApp(root)

    root.mainloop()


if __name__ == "__main__":
    main()