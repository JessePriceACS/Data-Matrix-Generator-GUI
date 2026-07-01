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
    "AL00004 - Pitch Motor Assembly AA00062": {"width_mm": 120, "height_mm": 32, "dpi": 300},
    "AL00005 - Cradle Assembly AA00031": {"width_mm": 120, "height_mm": 32, "dpi": 300},
    "AL00006 - Base Motor Assembly AA00050": {"width_mm": 120, "height_mm": 32, "dpi": 300},
    "AL00007 - Base Signal Box AA00047": {"width_mm": 120, "height_mm": 32, "dpi": 300},
    "AL00008 - Camera Damper AA00019": {"width_mm": 75, "height_mm": 17, "dpi": 300},
    "AL00009 - Electronics Enclosure AA00014": {"width_mm": 104, "height_mm": 29, "dpi": 300},
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

        # Fields Container Frame
        self.fields_container = ttk.Frame(frame)
        self.fields_container.pack(fill="x", pady=(0, 10))

        self.field_widgets = {}
        # Input Fields
        for label_text in ["Plain Text", "MFR", "SER", "PNR", "REV"]:
            lbl = ttk.Label(self.fields_container, text=label_text, font=("Segoe UI", 12, "bold"))
            
            entry = tk.Entry(
                self.fields_container,
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

            entry.bind("<KeyRelease>", self.update_preview)
            self.fields[label_text] = entry
            self.field_widgets[label_text] = (lbl, entry)

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
        ).pack(side="left", padx=(0, 10))

        ttk.Button(
            button_frame,
            text="Bulk Import CSV/TSV",
            command=self.bulk_import_csv,
            style="Large.TButton",
        ).pack(side="left")

        # Second row of buttons
        button_frame2 = ttk.Frame(frame)
        button_frame2.pack(fill="x", pady=(5, 10))

        ttk.Button(
            button_frame2,
            text="Load Full Turret CSV to One Image",
            command=self.load_full_turret_csv,
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
        self._update_field_visibility()
        self.update_preview()

    def _on_format_selected(self, event=None):
        """Handle format selection change."""
        self._update_field_defaults()
        self._update_field_visibility()
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
        elif selected_format == "AL00004 - Pitch Motor Assembly AA00062":
            # MFR: Force 9G8G8 and lock
            mfr_entry.config(state="normal", fg="#f0f0f0")
            mfr_entry.delete(0, tk.END)
            mfr_entry.insert(0, "9G8G8")
            mfr_entry.config(state="readonly", fg="#aaaaaa")

            # PNR: Force AA00062 and lock
            pnr_entry.config(state="normal", fg="#f0f0f0")
            pnr_entry.delete(0, tk.END)
            pnr_entry.insert(0, "AA00062")
            pnr_entry.config(state="readonly", fg="#aaaaaa")
        elif selected_format == "AL00005 - Cradle Assembly AA00031":
            # MFR: Force 9G8G8 and lock
            mfr_entry.config(state="normal", fg="#f0f0f0")
            mfr_entry.delete(0, tk.END)
            mfr_entry.insert(0, "9G8G8")
            mfr_entry.config(state="readonly", fg="#aaaaaa")

            # PNR: Force AA00031 and lock
            pnr_entry.config(state="normal", fg="#f0f0f0")
            pnr_entry.delete(0, tk.END)
            pnr_entry.insert(0, "AA00031")
            pnr_entry.config(state="readonly", fg="#aaaaaa")
        elif selected_format == "AL00006 - Base Motor Assembly AA00050":
            # MFR: Force 9G8G8 and lock
            mfr_entry.config(state="normal", fg="#f0f0f0")
            mfr_entry.delete(0, tk.END)
            mfr_entry.insert(0, "9G8G8")
            mfr_entry.config(state="readonly", fg="#aaaaaa")

            # PNR: Force AA00050 and lock
            pnr_entry.config(state="normal", fg="#f0f0f0")
            pnr_entry.delete(0, tk.END)
            pnr_entry.insert(0, "AA00050")
            pnr_entry.config(state="readonly", fg="#aaaaaa")
        elif selected_format == "AL00007 - Base Signal Box AA00047":
            # MFR: Force 9G8G8 and lock
            mfr_entry.config(state="normal", fg="#f0f0f0")
            mfr_entry.delete(0, tk.END)
            mfr_entry.insert(0, "9G8G8")
            mfr_entry.config(state="readonly", fg="#aaaaaa")

            # PNR: Force AA00047 and lock
            pnr_entry.config(state="normal", fg="#f0f0f0")
            pnr_entry.delete(0, tk.END)
            pnr_entry.insert(0, "AA00047")
            pnr_entry.config(state="readonly", fg="#aaaaaa")
        elif selected_format == "AL00008 - Camera Damper AA00019":
            # MFR: Force 9G8G8 and lock
            mfr_entry.config(state="normal", fg="#f0f0f0")
            mfr_entry.delete(0, tk.END)
            mfr_entry.insert(0, "9G8G8")
            mfr_entry.config(state="readonly", fg="#aaaaaa")

            # PNR: Force AA00019 and lock
            pnr_entry.config(state="normal", fg="#f0f0f0")
            pnr_entry.delete(0, tk.END)
            pnr_entry.insert(0, "AA00019")
            pnr_entry.config(state="readonly", fg="#aaaaaa")
        elif selected_format == "AL00009 - Electronics Enclosure AA00014":
            # MFR: Force 9G8G8 and lock
            mfr_entry.config(state="normal", fg="#f0f0f0")
            mfr_entry.delete(0, tk.END)
            mfr_entry.insert(0, "9G8G8")
            mfr_entry.config(state="readonly", fg="#aaaaaa")

            # PNR: Force AA00014 and lock
            pnr_entry.config(state="normal", fg="#f0f0f0")
            pnr_entry.delete(0, tk.END)
            pnr_entry.insert(0, "AA00014")
            pnr_entry.config(state="readonly", fg="#aaaaaa")
        else:
            # Reset MFR if it matches the default
            mfr_entry.config(state="normal", fg="#f0f0f0")
            if current_mfr == "9G8G8":
                mfr_entry.delete(0, tk.END)
            
            # Reset PNR if it matches the default
            pnr_entry.config(state="normal", fg="#f0f0f0")
            if current_pnr in ("AA00063", "AA00062", "AA00031", "AA00050", "AA00047", "AA00019", "AA00014"):
                pnr_entry.delete(0, tk.END)

    def _update_field_visibility(self):
        """Update fields visibility based on selected format."""
        selected_format = self.format_var.get()
        is_barcode_only = (selected_format == "Barcode Only")

        for label_text in ["Plain Text", "MFR", "SER", "PNR", "REV"]:
            lbl, entry = self.field_widgets[label_text]
            lbl.pack_forget()
            entry.pack_forget()

            show = False
            if is_barcode_only:
                if label_text == "Plain Text":
                    show = True
            else:
                if label_text != "Plain Text":
                    show = True

            if show:
                lbl.pack(anchor="w")
                entry.pack(fill="x", pady=(2, 10))

    def get_text(self) -> str:
        selected_format = self.format_var.get()
        is_barcode_only = (selected_format == "Barcode Only")

        if is_barcode_only:
            # Check for plain text override first
            plain_text = self.fields["Plain Text"].get().strip()
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
            
        if "AL000" in fmt_name:
            # Custom Layout: Text on Left, Barcode specifically positioned on Right
            if "AL00008" in fmt_name:
                bc_size_mm = 13
                bc_top_mm = 2
                bc_right_mm = 2
                f_size_pt = 12
                leading_pt = 14
                off_x_mm = 2.0
                off_y_mm = 1.5
                tracking_mm = 0.2
            elif "AL00009" in fmt_name:
                bc_size_mm = 20
                bc_top_mm = 4
                bc_right_mm = 4
                f_size_pt = 16
                leading_pt = 24
                off_x_mm = 4.0
                off_y_mm = 3.0
                tracking_mm = 0.2
            elif "AL00003" in fmt_name:
                bc_size_mm = 16
                bc_top_mm = 4
                bc_right_mm = 4
                f_size_pt = 24
                leading_pt = 30
                off_x_mm = 4.0
                off_y_mm = 2.8
                tracking_mm = 0.6
            else:
                bc_size_mm = 20
                bc_top_mm = 4
                bc_right_mm = 4
                f_size_pt = 20
                leading_pt = 26
                off_x_mm = 4.0
                off_y_mm = 3.0
                tracking_mm = 0.2

            bc_size_px = int((bc_size_mm / 25.4) * dpi)
            barcode_img = barcode_img.resize((bc_size_px, bc_size_px), Image.LANCZOS)

            # Position: relative to right and top edges
            barcode_x = int(((fmt["width_mm"] - bc_size_mm - bc_right_mm) / 25.4) * dpi)
            barcode_y = int((bc_top_mm / 25.4) * dpi)
            base.paste(barcode_img, (barcode_x, barcode_y))

            # Offsets converted to pixels (x=off_x_mm, y=off_y_mm)
            off_x = int((off_x_mm / 25.4) * dpi)
            off_y = int((off_y_mm / 25.4) * dpi)
            f_size = int((f_size_pt / 72) * dpi)
            leading = int((leading_pt / 72) * dpi)
            tracking_px = int((tracking_mm / 25.4) * dpi)

            off_y = int((off_y_mm / 25.4) * dpi)
            f_size = int((f_size_pt / 72) * dpi)
            leading = int((leading_pt / 72) * dpi)
            tracking_px = int((tracking_mm / 25.4) * dpi)

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

    def load_full_turret_csv(self):
        """Allows selecting a CSV/TSV file to import 7 specific tags (AL00003-AL00009) and draw them onto one single image/SVG."""
        file_path = filedialog.askopenfilename(
            filetypes=[("CSV/TSV Files", "*.csv;*.tsv;*.txt"), ("All Files", "*.*")]
        )
        if not file_path:
            return

        import csv
        
        # Read the file to see if it uses tabs or commas
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content_sample = f.read(4096)
                f.seek(0)
                
                delimiter = "\t" if "\t" in content_sample else ","
                
                reader = csv.reader(f, delimiter=delimiter)
                rows = [row for row in reader if row]
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to read file:\n{exc}")
            return

        if not rows:
            messagebox.showwarning("Empty File", "The selected file is empty.")
            return

        required_codes = {"AL00003", "AL00004", "AL00005", "AL00006", "AL00007", "AL00008", "AL00009"}
        parsed_tags = {}

        for idx, row in enumerate(rows):
            elements = [el.strip() for el in row]
            if len(elements) < 2:
                continue

            # Detect format code
            matched_code = None
            for element in elements:
                m = re.search(r'AL\d{5}', element, re.IGNORECASE)
                if m:
                    matched_code = m.group(0).upper()
                    break

            if not matched_code or matched_code not in required_codes:
                continue

            # Extract fields (label-value or positional)
            mfr = ""
            ser = ""
            pnr = ""
            rev = ""

            upper_elements = [el.upper() for el in elements]
            
            def get_val_after_label(label):
                if label in upper_elements:
                    i = upper_elements.index(label)
                    if i + 1 < len(elements):
                        return elements[i + 1]
                return ""

            if any(lbl in upper_elements for lbl in ["MFR", "SER", "PNR", "REV"]):
                mfr = get_val_after_label("MFR")
                ser = get_val_after_label("SER")
                pnr = get_val_after_label("PNR")
                rev = get_val_after_label("REV")
            else:
                # Find tag key matching code to look up in positional
                matched_key = None
                for k in TAG_FORMATS.keys():
                    if matched_code in k:
                        matched_key = k
                        break
                
                fmt_idx = -1
                for i, el in enumerate(elements):
                    if el == matched_key or any(el.upper() in k.upper() for k in TAG_FORMATS.keys()):
                        fmt_idx = i
                        break
                
                if fmt_idx != -1:
                    rem = elements[fmt_idx+1:]
                    if len(rem) >= 1: mfr = rem[0]
                    if len(rem) >= 2: ser = rem[1]
                    if len(rem) >= 3: pnr = rem[2]
                    if len(rem) >= 4: rev = rem[3]

            # Apply hardcoded format defaults
            if matched_code == "AL00003":
                mfr, pnr = "9G8G8", "AA00063"
            elif matched_code == "AL00004":
                mfr, pnr = "9G8G8", "AA00062"
            elif matched_code == "AL00005":
                mfr, pnr = "9G8G8", "AA00031"
            elif matched_code == "AL00006":
                mfr, pnr = "9G8G8", "AA00050"
            elif matched_code == "AL00007":
                mfr, pnr = "9G8G8", "AA00047"
            elif matched_code == "AL00008":
                mfr, pnr = "9G8G8", "AA00019"
            elif matched_code == "AL00009":
                mfr, pnr = "9G8G8", "AA00014"

            if not rev or rev.strip() == "--":
                rev = ""

            # Check for duplicates in the CSV
            if matched_code in parsed_tags:
                messagebox.showerror("Error", "CSV should contain one line per subassembly only. No more, no less.")
                return

            parsed_tags[matched_code] = {
                "mfr": mfr,
                "ser": ser,
                "pnr": pnr,
                "rev": rev
            }

        # Check if we parsed exactly the 7 required subassemblies
        if set(parsed_tags.keys()) != required_codes:
            messagebox.showerror("Error", "CSV should contain one line per subassembly only. No more, no less.")
            return

        # Default filename based on AL00003 SER
        ser_al00003 = parsed_tags["AL00003"]["ser"]
        default_fn = safe_filename(f"{ser_al00003} All Tags") + ".svg"

        # Prompt user where to save the composite SVG
        save_path = filedialog.asksaveasfilename(
            initialfile=default_fn,
            defaultextension=".svg",
            filetypes=[("SVG Vector", "*.svg")]
        )
        if not save_path:
            return

        try:
            # Composite Layout Parameters: 122mm wide, 235mm high
            width_mm = 122.0
            height_mm = 235.0

            dwg = svgwrite.Drawing(save_path, size=(f"{width_mm}mm", f"{height_mm}mm"), profile='full')
            dwg.viewbox(0, 0, width_mm, height_mm)

            # Background (White)
            dwg.add(dwg.rect(insert=(0, 0), size=('100%', '100%'), fill='white'))

            # Sequence of formats: AL00004, AL00005, AL00006, AL00007, AL00003, AL00009, AL00008
            sequence = ["AL00004", "AL00005", "AL00006", "AL00007", "AL00003", "AL00009", "AL00008"]
            
            curr_y = 1.0  # Starts at 1mm from top edge
            left_margin = 1.0  # Left-justified at 1mm from left edge

            for code in sequence:
                tag_data = parsed_tags[code]
                
                # Find matching TAG_FORMAT key to get dimensions
                matched_key = None
                for k in TAG_FORMATS.keys():
                    if code in k:
                        matched_key = k
                        break
                
                fmt = TAG_FORMATS[matched_key]
                tag_w = fmt["width_mm"]
                tag_h = fmt["height_mm"]

                # Generate encoded data string
                parts = []
                if tag_data["mfr"]: parts.append(f"MFR {tag_data['mfr']}")
                if tag_data["ser"]: parts.append(f"SER {tag_data['ser']}")
                if tag_data["pnr"]: parts.append(f"PNR {tag_data['pnr']}")
                parts.append(f"REV {tag_data['rev']}".strip())
                data_str = " ".join(parts).strip()

                # Create nested SVG element positioned at left_margin, curr_y
                nested_svg = dwg.svg(insert=(left_margin, curr_y), size=(tag_w, tag_h))
                dwg.add(nested_svg)

                # Draw the tag elements into the nested SVG element
                self.draw_tag_svg_elements(
                    dwg,
                    nested_svg,
                    fmt_name=matched_key,
                    data=data_str,
                    mfr=tag_data["mfr"],
                    ser=tag_data["ser"],
                    pnr=tag_data["pnr"],
                    rev=tag_data["rev"]
                )

                # Space between tags is 4mm
                curr_y += tag_h + 4.0

            dwg.save()
            messagebox.showinfo("Success", f"Composite SVG saved successfully:\n{save_path}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate composite SVG:\n{e}")

    def bulk_import_csv(self):
        """Allows selecting a CSV/TSV file to import and generate tags in bulk."""
        file_path = filedialog.askopenfilename(
            filetypes=[("CSV/TSV Files", "*.csv;*.tsv;*.txt"), ("All Files", "*.*")]
        )
        if not file_path:
            return

        import csv
        
        # Read the file to see if it uses tabs or commas
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content_sample = f.read(4096)
                f.seek(0)
                
                # Check for tab presence to determine delimiter
                delimiter = "\t" if "\t" in content_sample else ","
                
                reader = csv.reader(f, delimiter=delimiter)
                rows = [row for row in reader if row]
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to read file:\n{exc}")
            return

        if not rows:
            messagebox.showwarning("Empty File", "The selected file is empty.")
            return

        # Let user select output folder
        output_dir_path = filedialog.askdirectory(title="Select Folder to Save Generated SVGs")
        if not output_dir_path:
            return
        output_dir = Path(output_dir_path)

        success_count = 0
        errors = []

        for idx, row in enumerate(rows):
            # Clean elements
            elements = [el.strip() for el in row]
            if len(elements) < 2:
                # Too short to be a valid tag row, skip (e.g. empty line or footer)
                continue

            # 1. Detect format
            matched_fmt_name = None
            # Prioritize matching AL000xx code via regex
            for element in elements:
                m = re.search(r'AL\d{5}', element, re.IGNORECASE)
                if m:
                    code = m.group(0).upper()
                    # Find tag key containing this code
                    for tag_key in TAG_FORMATS.keys():
                        if code in tag_key:
                            matched_fmt_name = tag_key
                            break
                if matched_fmt_name:
                    break

            if not matched_fmt_name:
                for element in elements:
                    for tag_key in TAG_FORMATS.keys():
                        norm_el = re.sub(r'[^A-Z0-9]', '', element.upper())
                        norm_key = re.sub(r'[^A-Z0-9]', '', tag_key.upper())
                        if norm_el and norm_el in norm_key:
                            matched_fmt_name = tag_key
                            break
                    if matched_fmt_name:
                        break

            if not matched_fmt_name:
                errors.append(f"Row {idx+1}: Could not detect valid format from elements: {row}")
                continue

            # 2. Extract values
            mfr = ""
            ser = ""
            pnr = ""
            rev = ""
            plain_text = ""

            # Check if this row is label-value formatted (e.g. elements contain "MFR", "SER", etc.)
            upper_elements = [el.upper() for el in elements]
            
            # Helper to safely extract next element after a label
            def get_val_after_label(label):
                if label in upper_elements:
                    i = upper_elements.index(label)
                    if i + 1 < len(elements):
                        return elements[i + 1]
                return ""

            if any(lbl in upper_elements for lbl in ["MFR", "SER", "PNR", "REV"]):
                # Label-value pattern (like the user's spreadsheet)
                mfr = get_val_after_label("MFR")
                ser = get_val_after_label("SER")
                pnr = get_val_after_label("PNR")
                rev = get_val_after_label("REV")
                plain_text = elements[0] if len(elements) > 0 else "" # fallback first column for plain text
            else:
                # Positional fallback mapping relative to format index
                fmt_idx = -1
                for i, el in enumerate(elements):
                    if el == matched_fmt_name or any(el.upper() in k.upper() for k in TAG_FORMATS.keys()):
                        fmt_idx = i
                        break
                
                if fmt_idx != -1:
                    rem = elements[fmt_idx+1:]
                    if len(rem) >= 1: mfr = rem[0]
                    if len(rem) >= 2: ser = rem[1]
                    if len(rem) >= 3: pnr = rem[2]
                    if len(rem) >= 4: rev = rem[3]
                else:
                    # Positional fallback starting from 0
                    if len(elements) >= 1: plain_text = elements[0]
                    if len(elements) >= 2: ser = elements[1]

            # 3. Apply custom format locking constraints
            if matched_fmt_name == "AL00003 - Turret ASM AA00063":
                mfr = "9G8G8"
                pnr = "AA00063"
            elif matched_fmt_name == "AL00004 - Pitch Motor Assembly AA00062":
                mfr = "9G8G8"
                pnr = "AA00062"
            elif matched_fmt_name == "AL00005 - Cradle Assembly AA00031":
                mfr = "9G8G8"
                pnr = "AA00031"
            elif matched_fmt_name == "AL00006 - Base Motor Assembly AA00050":
                mfr = "9G8G8"
                pnr = "AA00050"
            elif matched_fmt_name == "AL00007 - Base Signal Box AA00047":
                mfr = "9G8G8"
                pnr = "AA00047"
            elif matched_fmt_name == "AL00008 - Camera Damper AA00019":
                mfr = "9G8G8"
                pnr = "AA00019"
            elif matched_fmt_name == "AL00009 - Electronics Enclosure AA00014":
                mfr = "9G8G8"
                pnr = "AA00014"

            # Normalize revision if it is empty/unset or default marker like "--"
            if not rev or rev.strip() == "--":
                rev = ""

            # 4. Generate the encoded data string
            is_barcode_only = (matched_fmt_name == "Barcode Only")
            if is_barcode_only:
                data_string = plain_text.strip()
            else:
                parts = []
                if mfr: parts.append(f"MFR {mfr}")
                if ser: parts.append(f"SER {ser}")
                if pnr: parts.append(f"PNR {pnr}")
                parts.append(f"REV {rev}".strip())
                data_string = " ".join(parts).strip()

            if not data_string:
                errors.append(f"Row {idx+1}: Resulting encode string is empty.")
                continue

            # 5. Generate filename
            if is_barcode_only:
                fn = f"BARCODE_{safe_filename(data_string)}"
            else:
                fn_parts = []
                if mfr: fn_parts.append(f"MFR {mfr}")
                if ser: fn_parts.append(f"SER {ser}")
                if pnr: fn_parts.append(f"PNR {pnr}")
                if rev: fn_parts.append(f"REV {rev}")
                fn = safe_filename(" ".join(fn_parts))

            filepath = str(output_dir / f"{fn}.svg")

            # 6. Call save_svg silently
            try:
                self.save_svg(data_string, filepath, fmt_name=matched_fmt_name, mfr=mfr, ser=ser, pnr=pnr, rev=rev, silent=True)
                success_count += 1
            except Exception as e:
                errors.append(f"Row {idx+1}: {e}")

        # Summary popup
        msg = f"Bulk processing complete.\n\nSuccessfully generated: {success_count} SVGs."
        if errors:
            msg += f"\n\nFailed/Skipped rows: {len(errors)}\nFirst few errors:\n" + "\n".join(errors[:5])
            messagebox.showwarning("Bulk Process Complete with Warnings", msg)
        else:
            messagebox.showinfo("Bulk Process Complete", msg)

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

    def save_svg(self, data: str, file_path: str, fmt_name: str = None, mfr: str = None, ser: str = None, pnr: str = None, rev: str = None, silent: bool = False):
        """Generates a true vector SVG of the tag."""
        try:
            if fmt_name is None:
                fmt_name = self.format_var.get()
            
            # Resolve fields: use passed arguments if not None, otherwise get from UI
            if mfr is None: mfr = self.fields["MFR"].get().strip()
            if ser is None: ser = self.fields["SER"].get().strip()
            if pnr is None: pnr = self.fields["PNR"].get().strip()
            if rev is None: rev = self.fields["REV"].get().strip()

            fmt = TAG_FORMATS[fmt_name]
            width_mm = fmt["width_mm"]
            height_mm = fmt["height_mm"]

            # Initialize drawing in mm
            dwg = svgwrite.Drawing(file_path, size=(f"{width_mm}mm", f"{height_mm}mm"), profile='full')
            # Set the coordinate system viewbox: 1 unit = 1mm
            dwg.viewbox(0, 0, width_mm, height_mm)
            
            self.draw_tag_svg_elements(dwg, dwg, fmt_name, data, mfr, ser, pnr, rev)

            dwg.save()
            if not silent:
                messagebox.showinfo("Saved", f"Vector SVG saved successfully:\n{file_path}")

        except Exception as exc:
            if not silent:
                messagebox.showerror("Error", str(exc))
            else:
                raise exc

    def draw_tag_svg_elements(self, dwg, container, fmt_name, data, mfr, ser, pnr, rev):
        """Draws the tag borders, barcode, and text onto the given container (Drawing or nested SVG)."""
        fmt = TAG_FORMATS[fmt_name]
        width_mm = fmt["width_mm"]
        height_mm = fmt["height_mm"]

        # Background (White)
        container.add(dwg.rect(insert=(0, 0), size=('100%', '100%'), fill='white'))
        
        if "AL000" in fmt_name:
            # Add 0.25mm tag perimeter border with 2mm corner radius
            # Offset by 0.125mm (half stroke) to keep the line inside the tag edge
            container.add(dwg.rect(insert=(0.125, 0.125), 
                             size=(width_mm - 0.25, height_mm - 0.25), 
                             rx=2, ry=2,
                             fill='none', stroke='black', stroke_width=0.25))
            
        # Generate Barcode bits
        barcode_raw = zxingcpp.create_barcode(data, zxingcpp.BarcodeFormat.DataMatrix, force_square=True)
        matrix_img = Image.fromarray(barcode_raw.to_image(scale=1, add_quiet_zones=False))
        
        m_size = matrix_img.width
        padding = 2.5  # 2.5mm padding
        
        if "AL000" in fmt_name:
            if "AL00008" in fmt_name:
                target_h = 13
                bc_top_mm = 2
                bc_right_mm = 2
                ty = 1.5
                tx = 2.0
                f_size_pt = 12
                leading_pt = 14
                tracking_mm = 0.2
            elif "AL00009" in fmt_name:
                target_h = 20
                bc_top_mm = 4
                bc_right_mm = 4
                ty = 3.0
                tx = 4.0
                f_size_pt = 16
                leading_pt = 24
                tracking_mm = 0.2
            elif "AL00003" in fmt_name:
                target_h = 16
                bc_top_mm = 4
                bc_right_mm = 4
                ty = 2.8
                tx = 4.0
                f_size_pt = 24
                leading_pt = 30
                tracking_mm = 0.6
            else:
                target_h = 20
                bc_top_mm = 4
                bc_right_mm = 4
                ty = 3.0
                tx = 4.0
                f_size_pt = 20
                leading_pt = 26
                tracking_mm = 0.2

            barcode_x = width_mm - target_h - bc_right_mm
            barcode_y = bc_top_mm
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
        container.add(dwg.rect(
            insert=(barcode_x - border_mm, barcode_y - border_mm),
            size=(target_h + (border_mm * 2), target_h + (border_mm * 2)),
            fill='black'
        ))

        # Draw the white modules (inverted)
        for y in range(m_size):
            for x in range(m_size):
                if matrix_img.getpixel((x, y)) == 0:
                    container.add(dwg.rect(
                        insert=(barcode_x + (x * module_scale), barcode_y + (y * module_scale)),
                        size=(module_scale, module_scale), # Squares are now perfectly adjacent
                        fill='white'
                    ))

        if "AL000" in fmt_name:
            # Custom Text Layout (All Left)
            fs_mm = (f_size_pt / 72) * 25.4 # font size in mm
            ld_mm = (leading_pt / 72) * 25.4 # leading in mm

            container.add(dwg.text(f"MFR {mfr}", insert=(tx, ty), fill='black', font_family="Arial", font_weight="bold", font_size=fs_mm, dominant_baseline="hanging", letter_spacing=tracking_mm))
            container.add(dwg.text(f"SER {ser}", insert=(tx, ty + ld_mm), fill='black', font_family="Arial", font_weight="bold", font_size=fs_mm, dominant_baseline="hanging", letter_spacing=tracking_mm))
            container.add(dwg.text(f"PNR {pnr} REV {rev}", insert=(tx, ty + (2 * ld_mm)), fill='black', font_family="Arial", font_weight="bold", font_size=fs_mm, dominant_baseline="hanging", letter_spacing=tracking_mm))
        elif "Barcode Only" in fmt_name:
            pass
        else:
            # Generic Text Layout (Next to barcode)
            text_x = barcode_x + target_h + (padding * 2)
            font_size = height_mm * 0.15
            rows = [
                ("MFR:", mfr),
                ("PNR:", pnr),
                ("SER:", ser),
                ("REV:", rev),
            ]
            curr_y = barcode_y + font_size
            for label, val in rows:
                if not val: val = "-"
                container.add(dwg.text(label, insert=(text_x, curr_y), fill='black', font_family="Arial", font_weight="bold", font_size=font_size))
                container.add(dwg.text(val, insert=(text_x + (font_size * 2.5), curr_y), fill='black', font_family="Arial", font_size=font_size))
                curr_y += font_size * 1.3


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