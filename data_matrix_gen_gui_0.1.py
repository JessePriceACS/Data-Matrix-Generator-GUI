#!/usr/bin/env python3
"""Create and preview Data Matrix barcode PNGs with a GUI."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageOps
import zxingcpp

try:
    import svgwrite
except ImportError:
    svgwrite = None


# -----------------------------
# Settings
# -----------------------------

OUTPUT_DIR = Path("Output")

TAG_FORMATS = {
    "Barcode Only": {"width_mm": 25, "height_mm": 25, "dpi": 300},
    "AL00003 - Turret ASM AA00063": {"width_mm": 103, "height_mm": 35, "dpi": 300},
    "1.5\" x 0.5\" (300 DPI)": {"width_mm": 38.1, "height_mm": 12.7, "dpi": 300},
    "2.0\" x 1.0\" (300 DPI)": {"width_mm": 50.8, "height_mm": 25.4, "dpi": 300},
    "3.0\" x 1.0\" (300 DPI)": {"width_mm": 76.2, "height_mm": 25.4, "dpi": 300},
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


# -----------------------------
# GUI App
# -----------------------------


class DataMatrixApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Data Matrix Generator") # Set the window title
        self.root.geometry("850x1000") # Widen and heighten the default window size

        OUTPUT_DIR.mkdir(exist_ok=True)

        self.current_image = None
        self.preview_photo = None
        self.fields: dict[str, tk.Entry] = {}

        self.build_ui()

    def build_ui(self):
        # Main frame
        frame = ttk.Frame(self.root, padding=15)
        frame.pack(fill="both", expand=True)

        # Format Selection Dropdown
        ttk.Label(frame, text="Tag Format", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.format_var = tk.StringVar()
        self.format_combo = ttk.Combobox(
            frame,
            textvariable=self.format_var,
            values=list(TAG_FORMATS.keys()),
            state="readonly",
            font=("Segoe UI", 14)
        )
        self.format_combo.pack(fill="x", pady=(5, 15))
        self.format_combo.current(0) # Set initial selection
        self.format_combo.bind("<<ComboboxSelected>>", self._on_format_selected)

        # Input Fields
        for label_text in ["Plain Text", "MFR", "SER", "PNR", "REV"]:
            ttk.Label(frame, text=label_text, font=("Segoe UI", 12, "bold")).pack(anchor="w")
            
            entry = tk.Entry(
                frame,
                font=("Segoe UI", 14),
                bg="#2b2b2b",
                fg="#f0f0f0",
                insertbackground="#f0f0f0",
                selectbackground="#505050",
                selectforeground="#ffffff",
                readonlybackground="#2b2b2b",
                relief="flat",
                borderwidth=0,
            )

            entry.pack(fill="x", pady=(2, 10))
            entry.bind("<KeyRelease>", self.update_preview)
            self.fields[label_text] = entry

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
            text="Save SVG to Output Dir",
            command=self.save_to_output_dir,
            style="Large.TButton",
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            button_frame,
            text="Save SVG to another folder",
            command=self.save_to_custom_dir,
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
        self._update_field_defaults() # Set defaults based on initial format
        self.update_preview()

    def _on_format_selected(self, event=None):
        """Handle format selection change."""
        self._update_field_defaults()
        self.update_preview()

    def _update_field_defaults(self):
        """Sets or clears field defaults based on the selected format."""
        mfr_entry = self.fields["MFR"]
        pnr_entry = self.fields["PNR"]
        plain_entry = self.fields["Plain Text"]

        # Clear override field whenever format changes to prevent accidental data mismatch
        plain_entry.delete(0, tk.END)

        current_mfr = mfr_entry.get().strip()
        current_pnr = pnr_entry.get().strip()
        selected_format = self.format_var.get()

        if selected_format == "AL00003 - Turret ASM AA00063":
            # MFR: Force 9G8G8 and lock
            mfr_entry.config(state="normal", fg="#f0f0f0")
            mfr_entry.delete(0, tk.END)
            mfr_entry.insert(0, "9G8G8")
            mfr_entry.config(state="readonly", fg="#aaaaaa")

            # PNR: Force AA00063 and lock
            pnr_entry.config(state="normal", fg="#f0f0f0")
            pnr_entry.delete(0, tk.END)
            pnr_entry.insert(0, "AA00063")
            pnr_entry.config(state="readonly", fg="#aaaaaa")
        else:
            # Reset MFR if it matches the default
            mfr_entry.config(state="normal", fg="#f0f0f0")
            if current_mfr == "9G8G8":
                mfr_entry.delete(0, tk.END)
            
            # Reset PNR if it matches the default
            pnr_entry.config(state="normal", fg="#f0f0f0")
            if current_pnr == "AA00063":
                pnr_entry.delete(0, tk.END)

    def get_text(self) -> str:
        # Check for plain text override first
        plain_text = self.fields["Plain Text"].get().strip()
        if plain_text:
            return plain_text

        parts = []
        mfr = self.fields["MFR"].get().strip()
        ser = self.fields["SER"].get().strip()
        pnr = self.fields["PNR"].get().strip()
        rev = self.fields["REV"].get().strip()

        if not any([mfr, ser, pnr, rev]):
            return ""

        if mfr:
            parts.append(f"MFR {mfr}")
        if ser:
            parts.append(f"SER {ser}")
        if pnr:
            parts.append(f"PNR {pnr}")

        # REV is always included in the string unless the entire form is empty
        parts.append(f"REV {rev}".strip())

        return " ".join(parts)

    def create_composite_image(self, data: str) -> Image.Image:
        """Creates a composite image with the barcode and labeled text."""
        fmt_name = self.format_var.get()
        fmt = TAG_FORMATS[fmt_name]
        
        dpi = fmt["dpi"]
        width = int((fmt["width_mm"] / 25.4) * dpi)
        height = int((fmt["height_mm"] / 25.4) * dpi)
        
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
        padding = int((2.5 / 25.4) * dpi)  # Match 2.5mm padding from SVG
        available_h = height - (2 * padding)
        aspect = barcode_img.width / barcode_img.height
        barcode_img = barcode_img.resize((int(available_h * aspect), available_h), Image.LANCZOS)
            
        if "AL00003" in fmt_name:
            # AL00003 Layout: Text on Left, Barcode specifically positioned on Right
            # Resize barcode to 16mm x 16mm
            bc_size_px = int((16 / 25.4) * dpi)
            barcode_img = barcode_img.resize((bc_size_px, bc_size_px), Image.LANCZOS)

            # Position: 83mm right, 4mm down
            barcode_x = int((83 / 25.4) * dpi)
            barcode_y = int((4 / 25.4) * dpi)
            base.paste(barcode_img, (barcode_x, barcode_y))

            # Offsets converted to pixels (x=4mm, y=2.8mm)
            off_x = int((4 / 25.4) * dpi)
            off_y = int((2.8 / 25.4) * dpi)
            f_size = int((24 / 72) * dpi)      # 24pt
            leading = int((30 / 72) * dpi)     # 30pt
            tracking_px = int((0.6 / 25.4) * dpi) # 0.6mm tracking

            try:
                font = ImageFont.truetype("arialbd.ttf", size=f_size)
            except:
                font = ImageFont.load_default()

            mfr = self.fields["MFR"].get().strip()
            ser = self.fields["SER"].get().strip()
            pnr = self.fields["PNR"].get().strip()
            rev = self.fields["REV"].get().strip()

            lines = [
                f"MFR {mfr}",
                f"SER {ser}",
                f"PNR {pnr} REV {rev}"
            ]
            
            for i, line in enumerate(lines):
                curr_x = off_x
                y_pos = off_y + (i * leading)
                for char in line:
                    draw.text((curr_x, y_pos), char, fill=0, font=font)
                    char_w = draw.textlength(char, font=font)
                    curr_x += char_w + tracking_px

            # Add 0.25mm tag perimeter border with 2mm corner radius
            tag_border_px = max(1, int((0.25 / 25.4) * dpi))
            radius_px = int((2.0 / 25.4) * dpi)
            draw.rounded_rectangle([0, 0, width - 1, height - 1], radius=radius_px, outline=0, width=tag_border_px)
        elif "Barcode Only" in fmt_name:
            # Centered barcode, no text
            base.paste(barcode_img, ((width - barcode_img.width) // 2, (height - barcode_img.height) // 2))
            return base
        else:
            # Generic Layout: Barcode on Left, Text on Right
            base.paste(barcode_img, (padding, (height - barcode_img.height) // 2))
        
            try:
                font_size = int(height * 0.15)
                font_bold = ImageFont.truetype("arialbd.ttf", size=font_size)
                font_reg = ImageFont.truetype("arial.ttf", size=font_size)
            except:
                font_bold = font_reg = ImageFont.load_default()
                
            text_x = barcode_img.width + (padding * 3)
            rows = [
                ("MFR:", self.fields["MFR"].get().strip()),
                ("PNR:", self.fields["PNR"].get().strip()),
                ("SER:", self.fields["SER"].get().strip()),
                ("REV:", self.fields["REV"].get().strip()),
            ]
            
            line_height = int(font_size * 1.4)
            curr_y = (height - (len(rows) * line_height)) // 2
            for label, val in rows:
                if not val: val = "-"
                draw.text((text_x, curr_y), label, fill=0, font=font_bold)
                val_x = text_x + int(font_size * 2.5) 
                draw.text((val_x, curr_y), val, fill=0, font=font_reg)
                curr_y += line_height
            
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
            preview.thumbnail((625, 625))

            self.preview_photo = ImageTk.PhotoImage(preview)

            self.preview_label.configure(image=self.preview_photo)

            self.current_image = image

        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def save_to_output_dir(self):
        """Save SVG to the default Output directory."""
        self._perform_save(use_dialog=False)

    def save_to_custom_dir(self):
        """Open a dialog to save SVG to a custom location."""
        self._perform_save(use_dialog=True)

    def _perform_save(self, use_dialog: bool):
        """Core saving logic handling both automatic and manual paths."""
        data = self.get_text()

        if not data:
            messagebox.showwarning("No Text", "Please enter text to encode.")
            return

        if not svgwrite:
            messagebox.showerror("Missing Library", "Please install svgwrite: pip install svgwrite")
            return

        try:
            if use_dialog:
                file_path = filedialog.asksaveasfilename(
                    defaultextension=".svg",
                    filetypes=[("SVG Vector", "*.svg")],
                    initialfile=safe_filename(data) + ".svg"
                )
                if not file_path:
                    return
            else:
                # Automatically define the path in the Output folder
                filename = safe_filename(data) + ".svg"
                file_path = str(OUTPUT_DIR / filename)
            
            self.save_svg(data, file_path)
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def save_svg(self, data: str, file_path: str):
        """Generates a true vector SVG of the tag."""
        try:
            fmt_name = self.format_var.get()
            fmt = TAG_FORMATS[fmt_name]
            width_mm = fmt["width_mm"]
            height_mm = fmt["height_mm"]

            # Initialize drawing in mm
            dwg = svgwrite.Drawing(file_path, size=(f"{width_mm}mm", f"{height_mm}mm"), profile='full')
            # Set the coordinate system viewbox: 1 unit = 1mm
            dwg.viewbox(0, 0, width_mm, height_mm)
            
            # Background (White)
            dwg.add(dwg.rect(insert=(0, 0), size=('100%', '100%'), fill='white'))
            
            if "AL00003" in fmt_name:
                # Add 0.25mm tag perimeter border with 2mm corner radius
                # Offset by 0.125mm (half stroke) to keep the line inside the tag edge
                dwg.add(dwg.rect(insert=(0.125, 0.125), 
                                 size=(width_mm - 0.25, height_mm - 0.25), 
                                 rx=2, ry=2,
                                 fill='none', stroke='black', stroke_width=0.25))
                
            # Generate Barcode bits
            barcode_raw = zxingcpp.create_barcode(data, zxingcpp.BarcodeFormat.DataMatrix, force_square=True)
            matrix_img = Image.fromarray(barcode_raw.to_image(scale=1, add_quiet_zones=False))
            
            m_size = matrix_img.width
            padding = 2.5  # 2.5mm padding
            
            if "AL00003" in fmt_name:
                target_h = 16  # 16mm barcode size
                barcode_x = 83 # 83mm from left
                barcode_y = 4  # 4mm from top
            elif "Barcode Only" in fmt_name:
                target_h = height_mm * 0.8
                barcode_x = (width_mm - target_h) / 2
                barcode_y = (height_mm - target_h) / 2
            else:
                target_h = height_mm * 0.7
                barcode_x = padding
                barcode_y = (height_mm - target_h) / 2

            module_scale = target_h / m_size

            # Border (0.5mm)
            border_mm = 0.5
            
            # Draw the black background box for the inverted barcode
            dwg.add(dwg.rect(
                insert=(barcode_x - border_mm, barcode_y - border_mm),
                size=(target_h + (border_mm * 2), target_h + (border_mm * 2)),
                fill='black'
            ))

            # Draw the white modules (inverted)
            for y in range(m_size):
                for x in range(m_size):
                    if matrix_img.getpixel((x, y)) == 0:
                        dwg.add(dwg.rect(
                            insert=(barcode_x + (x * module_scale), barcode_y + (y * module_scale)),
                            size=(module_scale, module_scale), # Squares are now perfectly adjacent
                            fill='white'
                        ))

            if "AL00003" in fmt_name:
                # Custom AL00003 Text Layout (All Left)
                tx, ty = 4, 2.8 # x=4mm, y=2.8mm (moved up by 1.2mm)
                fs_mm = (24 / 72) * 25.4 # 24pt in mm
                ld_mm = (30 / 72) * 25.4 # 30pt in mm
                tracking_mm = 0.6 # 0.6mm tracking

                mfr = self.fields["MFR"].get().strip()
                ser = self.fields["SER"].get().strip()
                pnr = self.fields["PNR"].get().strip()
                rev = self.fields["REV"].get().strip()

                dwg.add(dwg.text(f"MFR {mfr}", insert=(tx, ty), fill='black', font_family="Arial", font_weight="bold", font_size=fs_mm, dominant_baseline="hanging", letter_spacing=tracking_mm))
                dwg.add(dwg.text(f"SER {ser}", insert=(tx, ty + ld_mm), fill='black', font_family="Arial", font_weight="bold", font_size=fs_mm, dominant_baseline="hanging", letter_spacing=tracking_mm))
                dwg.add(dwg.text(f"PNR {pnr} REV {rev}", insert=(tx, ty + (2 * ld_mm)), fill='black', font_family="Arial", font_weight="bold", font_size=fs_mm, dominant_baseline="hanging", letter_spacing=tracking_mm))
            elif "Barcode Only" in fmt_name:
                pass
            else:
                # Generic Text Layout (Next to barcode)
                text_x = barcode_x + target_h + (padding * 2)
                font_size = height_mm * 0.15
                rows = [
                    ("MFR:", self.fields["MFR"].get().strip()),
                    ("PNR:", self.fields["PNR"].get().strip()),
                    ("SER:", self.fields["SER"].get().strip()),
                    ("REV:", self.fields["REV"].get().strip()),
                ]
                curr_y = barcode_y + font_size
                for label, val in rows:
                    if not val: val = "-"
                    dwg.add(dwg.text(label, insert=(text_x, curr_y), fill='black', font_family="Arial", font_weight="bold", font_size=font_size))
                    dwg.add(dwg.text(val, insert=(text_x + (font_size * 2.5), curr_y), fill='black', font_family="Arial", font_size=font_size))
                    curr_y += font_size * 1.3

            dwg.save()
            messagebox.showinfo("Saved", f"Vector SVG saved successfully:\n{file_path}")

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

    # -----------------------------
    # Platform Specifics & Start
    # -----------------------------

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