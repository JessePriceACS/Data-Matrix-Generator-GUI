#!/usr/bin/env python3
"""Create and preview Data Matrix barcode PNGs with a GUI."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageOps
import zxingcpp


# -----------------------------
# Settings
# -----------------------------

SCALE = 10
MARGIN = 10
OUTPUT_DIR = Path("Output")

TAG_FORMATS = {
    "1.5\" x 0.5\" (300 DPI)": {"width_in": 1.5, "height_in": 0.5, "dpi": 300},
    "2.0\" x 1.0\" (300 DPI)": {"width_in": 2.0, "height_in": 1.0, "dpi": 300},
    "3.0\" x 1.0\" (300 DPI)": {"width_in": 3.0, "height_in": 1.0, "dpi": 300},
}


# -----------------------------
# Helpers
# -----------------------------


def safe_filename(text: str) -> str:
    """Convert text into a Windows-safe filename."""

    cleaned = re.sub(r'[\\/:*?"<>|]', '_', text)
    # Remove leading/trailing spaces and dots which are problematic on Windows
    cleaned = cleaned.strip(" .")

    if not cleaned:
        return "data_matrix"

    # Truncate to prevent OS path length issues
    return cleaned[:128]



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
        self.root.title("Data Matrix Generator") # Set the window title
        self.root.geometry("850x850") # Widen the default window size

        OUTPUT_DIR.mkdir(exist_ok=True)

        self.current_image = None
        self.preview_photo = None
        self.fields: dict[str, tk.Entry] = {}

        self.build_ui()

    def build_ui(self):
        # Main frame
        frame = ttk.Frame(self.root, padding=15)
        frame.pack(fill="both", expand=True)

        # Input Fields
        for label_text in ["MFR", "SER", "PNR", "REV"]:
            ttk.Label(frame, text=label_text, font=("Segoe UI", 12, "bold")).pack(anchor="w")
            
            entry = tk.Entry(
                frame,
                font=("Segoe UI", 14),
                bg="#2b2b2b",
                fg="#f0f0f0",
                insertbackground="#f0f0f0",
                selectbackground="#505050",
                selectforeground="#ffffff",
                relief="flat",
                borderwidth=0,
            )

            if label_text == "MFR":
                entry.insert(0, "9G8G8")

            entry.pack(fill="x", pady=(2, 10))
            entry.bind("<KeyRelease>", self.update_preview)
            self.fields[label_text] = entry

        # Format Selection Dropdown
        ttk.Label(frame, text="Tag Format", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(10, 0))
        self.format_var = tk.StringVar()
        self.format_combo = ttk.Combobox(
            frame,
            textvariable=self.format_var,
            values=list(TAG_FORMATS.keys()),
            state="readonly",
            font=("Segoe UI", 14)
        )
        self.format_combo.pack(fill="x", pady=(5, 15))
        self.format_combo.current(0)
        self.format_combo.bind("<<ComboboxSelected>>", self.update_preview)

        # Buttons
        button_style = ttk.Style()
        button_style.configure(
            "Large.TButton",
            font=("Segoe UI", 15),
            padding=6,
        )

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill="x", pady=(0, 10))

        # The "Generate Preview" button is redundant as the preview updates on KeyRelease.
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

        # Encoded string preview
        self.encoded_text_label = ttk.Label(
            frame,
            font=("Consolas", 16),
            foreground="#aaaaaa",
            wraplength=800,
        )
        self.encoded_text_label.pack(anchor="w", pady=(0, 10))

        # Preview box
        self.preview_label = ttk.Label(frame)
        self.preview_label.pack(expand=True)

        # Run initial preview for default values
        self.update_preview()

    def get_text(self) -> str:
        parts = []
        mfr = self.fields["MFR"].get().strip()
        ser = self.fields["SER"].get().strip()
        pnr = self.fields["PNR"].get().strip()
        rev = self.fields["REV"].get().strip()

        if mfr:
            parts.append(f"MFR {mfr}")
        if ser:
            parts.append(f"SER {ser}")
        if pnr:
            parts.append(f"PNR {pnr}")
        if rev:
            parts.append(f"REV {rev}")

        if not parts:
            return ""

        return " ".join(parts)

    def create_composite_image(self, data: str) -> Image.Image:
        """Creates a composite image with the barcode and labeled text."""
        fmt_name = self.format_var.get()
        fmt = TAG_FORMATS[fmt_name]
        
        dpi = fmt["dpi"]
        width = int(fmt["width_in"] * dpi)
        height = int(fmt["height_in"] * dpi)
        
        # Create a white background
        base = Image.new("L", (width, height), color=255)
        draw = ImageDraw.Draw(base)
        
        # Generate the barcode part
        # We use a smaller internal scale so it fits nicely in the composite
        barcode_raw = zxingcpp.create_barcode(data, zxingcpp.BarcodeFormat.DataMatrix, force_square=True)
        barcode_img = Image.fromarray(barcode_raw.to_image(scale=5, add_quiet_zones=False)).convert("L")
        
        # Invert the barcode colors (black becomes white, white becomes black)
        barcode_img = ImageOps.invert(barcode_img)
        
        # Add 0.5mm black border
        border_px = int(round((0.5 / 25.4) * dpi))
        barcode_img = ImageOps.expand(barcode_img, border=border_px, fill=0)

        # Resize barcode to fit height (with padding)
        padding = int(height * 0.15)
        available_h = height - (2 * padding)
        if barcode_img.height > available_h:
            aspect = barcode_img.width / barcode_img.height
            barcode_img = barcode_img.resize((int(available_h * aspect), available_h), Image.LANCZOS)
            
        # Paste barcode on the left
        base.paste(barcode_img, (padding, (height - barcode_img.height) // 2))
        
        # Text Layout
        try:
            # Common Windows font. Fallback to default if not found.
            font_bold = ImageFont.truetype("arialbd.ttf", size=int(height * 0.18))
            font_reg = ImageFont.truetype("arial.ttf", size=int(height * 0.18))
        except:
            font_bold = font_reg = ImageFont.load_default()
            
        text_x = barcode_img.width + (padding * 2)
        
        # Define the fields to draw
        rows = [
            ("MFR:", self.fields["MFR"].get().strip()),
            ("PNR:", self.fields["PNR"].get().strip()),
            ("SER:", self.fields["SER"].get().strip()),
            ("REV:", self.fields["REV"].get().strip()),
        ]
        
        # Draw rows (two columns if height is small, or stacked)
        curr_y = (height - (len(rows) * int(height * 0.22))) // 2
        for label, val in rows:
            if not val: val = "-"
            draw.text((text_x, curr_y), label, fill=0, font=font_bold)
            # Offset value slightly from the label
            val_x = text_x + int(dpi * 0.4) 
            draw.text((val_x, curr_y), val, fill=0, font=font_reg)
            curr_y += int(height * 0.22)
            
        return base

    def update_preview(self, event=None):
        data = self.get_text()

        if not data:
            self.preview_label.configure(image="")
            self.encoded_text_label.configure(text="")
            self.current_image = None
            return

        try:
            self.encoded_text_label.configure(text=data)
            image = self.create_composite_image(data)

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
            # Save the composite image currently shown in the preview
            image = self.current_image if self.current_image else self.create_composite_image(data)

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

    # Dropdown (Combobox) styling
    style.configure(
        "TCombobox",
        fieldbackground=DARK_PANEL,
        background=DARK_PANEL,
        foreground=DARK_TEXT,
        arrowcolor=DARK_TEXT,
    )
    # Ensure the readonly state stays dark
    style.map("TCombobox", fieldbackground=[("readonly", DARK_PANEL)], foreground=[("readonly", DARK_TEXT)])

    # Use modern Windows theme if available
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    # Set the font for the dropdown listbox items specifically
    root.option_add('*TCombobox*Listbox.font', ("Segoe UI", 14))
    root.option_add('*TCombobox*Listbox.background', DARK_PANEL)
    root.option_add('*TCombobox*Listbox.foreground', DARK_TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground', "#505050")

    app = DataMatrixApp(root)

    root.mainloop()


if __name__ == "__main__":
    main()