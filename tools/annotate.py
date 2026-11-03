#!/usr/bin/env python3
"""Select screen regions and save their templates and metadata."""

import argparse
import base64
import json
import math
import os
import re
import shutil
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2


ROOT_DIR = Path(__file__).resolve().parents[1]
REGIONS_PATH = ROOT_DIR / "regions.json"
ELEMENT_TYPES = ("button", "list", "number", "icon", "anchor")
MAX_PREVIEW_SIZE = (1150, 650)


def rect_to_region(start, end, scale, image_width, image_height):
    """Convert preview canvas points into a bounded source-image rectangle."""
    left = min(start[0], end[0])
    top = min(start[1], end[1])
    right = max(start[0], end[0])
    bottom = max(start[1], end[1])

    epsilon = 1e-9
    x = max(0, min(image_width - 1, math.floor(left / scale + epsilon)))
    y = max(0, min(image_height - 1, math.floor(top / scale + epsilon)))
    end_x = max(x + 1, min(image_width, math.ceil(right / scale - epsilon)))
    end_y = max(y + 1, min(image_height, math.ceil(bottom / scale - epsilon)))
    return {"x": x, "y": y, "w": end_x - x, "h": end_y - y}


def load_regions(path):
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("regions.json musi zawierać obiekt JSON na najwyższym poziomie.")
    return data


class Annotator:
    def __init__(self, root, image_path, screen_name=""):
        self.root = root
        self.image_path = Path(image_path).resolve()
        self.screen_name = tk.StringVar(value=screen_name)
        self.element_name = tk.StringVar()
        self.element_type = tk.StringVar(value="button")
        self.pending = []
        self.selection = None
        self.drag_origin = None
        self.regions = load_regions(REGIONS_PATH)

        self.image = cv2.imread(str(self.image_path), cv2.IMREAD_COLOR)
        if self.image is None:
            raise ValueError(f"Nie można otworzyć obrazu PNG: {self.image_path}")
        self.image_height, self.image_width = self.image.shape[:2]

        scale_x = MAX_PREVIEW_SIZE[0] / self.image_width
        scale_y = MAX_PREVIEW_SIZE[1] / self.image_height
        self.preview_scale = min(1.0, scale_x, scale_y)
        self.preview_width = max(1, round(self.image_width * self.preview_scale))
        self.preview_height = max(1, round(self.image_height * self.preview_scale))
        preview = cv2.resize(
            self.image,
            (self.preview_width, self.preview_height),
            interpolation=cv2.INTER_AREA if self.preview_scale < 1 else cv2.INTER_LINEAR,
        )
        preview_rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
        success, encoded = cv2.imencode(".png", preview_rgb)
        if not success:
            raise ValueError("Nie udało się przygotować podglądu obrazu.")
        self.preview_photo = tk.PhotoImage(data=base64.b64encode(encoded).decode("ascii"))

        self._build_ui()
        self._draw_regions()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.bind_all("<KeyPress>", self._on_shortcut)

    def _build_ui(self):
        self.root.title("Total Battle - zaznaczanie elementów")
        self.root.geometry(f"{self.preview_width + 30}x{self.preview_height + 175}")
        self.root.minsize(800, 500)

        fields = ttk.Frame(self.root, padding=(10, 8))
        fields.pack(fill="x")
        ttk.Label(fields, text="Ekran:").grid(row=0, column=0, sticky="w")
        ttk.Entry(fields, textvariable=self.screen_name, width=22).grid(row=0, column=1, padx=(5, 16))
        ttk.Label(fields, text="Nazwa elementu:").grid(row=0, column=2, sticky="w")
        self.name_entry = ttk.Entry(fields, textvariable=self.element_name, width=22)
        self.name_entry.grid(row=0, column=3, padx=(5, 16))
        ttk.Label(fields, text="Typ:").grid(row=0, column=4, sticky="w")
        ttk.Combobox(
            fields,
            textvariable=self.element_type,
            values=ELEMENT_TYPES,
            state="readonly",
            width=12,
        ).grid(row=0, column=5, padx=(5, 0))

        image_label = ttk.Label(self.root, text=str(self.image_path), padding=(10, 0, 10, 5))
        image_label.pack(anchor="w")
        self.canvas = tk.Canvas(
            self.root,
            width=self.preview_width,
            height=self.preview_height,
            background="#252525",
            highlightthickness=0,
        )
        self.canvas.pack(padx=10, pady=(0, 8), anchor="nw")
        self.canvas.create_image(0, 0, image=self.preview_photo, anchor="nw", tags=("source",))
        self.canvas.bind("<ButtonPress-1>", self._start_selection)
        self.canvas.bind("<B1-Motion>", self._update_selection)
        self.canvas.bind("<ButtonRelease-1>", self._finish_selection)

        actions = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        actions.pack(fill="x")
        ttk.Button(actions, text="Dodaj element", command=self.add_selection).pack(side="left")
        ttk.Button(actions, text="Zapisz", command=self.save).pack(side="left", padx=6)
        ttk.Button(actions, text="Cofnij", command=self.undo).pack(side="left")
        ttk.Button(actions, text="Wyjdź", command=self.quit).pack(side="right")
        ttk.Label(actions, text="S: zapisz   U: cofnij   Q: wyjdź").pack(side="right", padx=12)

    def _screen_regions(self):
        regions = self.regions.get(self.screen_name.get().strip(), {})
        return regions if isinstance(regions, dict) else {}

    def _draw_box(self, region, number, color):
        x1 = round(region["x"] * self.preview_scale)
        y1 = round(region["y"] * self.preview_scale)
        x2 = round((region["x"] + region["w"]) * self.preview_scale)
        y2 = round((region["y"] + region["h"]) * self.preview_scale)
        name = region.get("name", "")
        self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2, tags=("overlay",))
        self.canvas.create_text(
            x1 + 4,
            max(8, y1 - 8),
            text=f"{number}. {name}",
            fill=color,
            anchor="sw",
            font=("Segoe UI", 10, "bold"),
            tags=("overlay",),
        )

    def _draw_regions(self):
        self.canvas.delete("overlay")
        number = 1
        for name, region in self._screen_regions().items():
            try:
                visible = {key: int(region[key]) for key in ("x", "y", "w", "h")}
                visible["name"] = name
                self._draw_box(visible, number, "#55d68b")
                number += 1
            except (KeyError, TypeError, ValueError):
                continue
        for region in self.pending:
            self._draw_box(region, number, "#ffca55")
            number += 1
        if self.selection is not None:
            self.canvas.create_rectangle(
                *self.selection,
                outline="#69a7ff",
                width=2,
                dash=(5, 3),
                tags=("overlay",),
            )

    def _canvas_point(self, event):
        x = max(0, min(self.preview_width, self.canvas.canvasx(event.x)))
        y = max(0, min(self.preview_height, self.canvas.canvasy(event.y)))
        return x, y

    def _start_selection(self, event):
        self.drag_origin = self._canvas_point(event)
        self.selection = (*self.drag_origin, *self.drag_origin)
        self._draw_regions()

    def _update_selection(self, event):
        if self.drag_origin is None:
            return
        current = self._canvas_point(event)
        self.selection = (*self.drag_origin, *current)
        self._draw_regions()

    def _finish_selection(self, event):
        if self.drag_origin is None:
            return
        current = self._canvas_point(event)
        self.selection = (*self.drag_origin, *current)
        self.drag_origin = None
        self._draw_regions()
        self.name_entry.focus_set()

    @staticmethod
    def _valid_identifier(value):
        return bool(value) and value not in (".", "..") and re.fullmatch(r"[\w-]+", value, re.UNICODE) is not None

    def add_selection(self):
        screen = self.screen_name.get().strip()
        name = self.element_name.get().strip()
        if not self._valid_identifier(screen):
            messagebox.showerror("Nieprawidłowa nazwa", "Nazwa ekranu może zawierać litery, cyfry, '_' i '-'.", parent=self.root)
            return False
        if not self._valid_identifier(name):
            messagebox.showerror("Nieprawidłowa nazwa", "Nazwa elementu może zawierać litery, cyfry, '_' i '-'.", parent=self.root)
            return False
        if self.selection is None:
            messagebox.showerror("Brak zaznaczenia", "Zaznacz prostokąt na obrazie.", parent=self.root)
            return False

        existing = self._screen_regions()
        if name in existing or any(region["name"] == name for region in self.pending):
            messagebox.showerror("Nazwa zajęta", f"Element '{name}' już istnieje dla tego ekranu.", parent=self.root)
            return False

        x1, y1, x2, y2 = self.selection
        region = rect_to_region(
            (x1, y1),
            (x2, y2),
            self.preview_scale,
            self.image_width,
            self.image_height,
        )
        region.update({
            "name": name,
            "type": self.element_type.get(),
            "template": f"templates/{screen}/{name}.png",
        })
        self.pending.append(region)
        self.selection = None
        self.element_name.set("")
        self._draw_regions()
        return True

    def undo(self):
        if self.selection is not None:
            self.selection = None
        elif self.pending:
            self.pending.pop()
        else:
            return
        self._draw_regions()

    def _on_shortcut(self, event):
        if isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Combobox, ttk.Spinbox, tk.Text)):
            return None
        key = event.keysym.lower()
        if key == "s":
            self.save()
        elif key == "u":
            self.undo()
        elif key == "q":
            self.quit()
        else:
            return None
        return "break"

    def _save_regions_json(self, regions):
        fd, temp_name = tempfile.mkstemp(prefix="regions-", suffix=".json", dir=ROOT_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(regions, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.replace(temp_name, REGIONS_PATH)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def save(self):
        if self.selection is not None and not self.add_selection():
            return False
        if not self.pending:
            messagebox.showinfo("Brak zmian", "Zaznacz i dodaj co najmniej jeden nowy element.", parent=self.root)
            return False

        screen = self.screen_name.get().strip()
        screen_dir = ROOT_DIR / "screenshots" / screen
        template_dir = ROOT_DIR / "templates" / screen
        full_path = screen_dir / "pelny.png"
        annotated_path = screen_dir / "opisany.png"
        if full_path.exists() and full_path.resolve() != self.image_path:
            replace = messagebox.askyesno(
                "Zastąpić screen?",
                f"{full_path.relative_to(ROOT_DIR)} już istnieje. Zastąpić go wybranym obrazem?",
                parent=self.root,
            )
            if not replace:
                return False

        screen_dir.mkdir(parents=True, exist_ok=True)
        template_dir.mkdir(parents=True, exist_ok=True)
        if full_path.resolve() != self.image_path:
            shutil.copy2(self.image_path, full_path)

        updated_regions = dict(self.regions)
        screen_regions = dict(self._screen_regions())
        annotated = self.image.copy()
        number = 1
        for name, region in screen_regions.items():
            try:
                x, y, width, height = (int(region[key]) for key in ("x", "y", "w", "h"))
                cv2.rectangle(annotated, (x, y), (x + width, y + height), (80, 210, 135), 3)
                cv2.putText(annotated, f"{number}. {name}", (x, max(22, y - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (80, 210, 135), 2)
                number += 1
            except (KeyError, TypeError, ValueError):
                continue

        for region in self.pending:
            name = region["name"]
            x, y, width, height = (region[key] for key in ("x", "y", "w", "h"))
            crop = self.image[y:y + height, x:x + width]
            template_path = ROOT_DIR / region["template"]
            if crop.size == 0 or not cv2.imwrite(str(template_path), crop):
                messagebox.showerror("Błąd zapisu", f"Nie udało się zapisać wzorca: {template_path}", parent=self.root)
                return False
            screen_regions[name] = {key: region[key] for key in ("x", "y", "w", "h", "type", "template")}
            cv2.rectangle(annotated, (x, y), (x + width, y + height), (85, 170, 255), 3)
            cv2.putText(annotated, f"{number}. {name}", (x, max(22, y - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (85, 170, 255), 2)
            number += 1

        updated_regions[screen] = screen_regions
        if not cv2.imwrite(str(annotated_path), annotated):
            messagebox.showerror("Błąd zapisu", f"Nie udało się zapisać: {annotated_path}", parent=self.root)
            return False
        try:
            self._save_regions_json(updated_regions)
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror("Błąd zapisu", f"Nie udało się zaktualizować regions.json:\n{error}", parent=self.root)
            return False

        self.regions = updated_regions
        self.pending.clear()
        self._draw_regions()
        messagebox.showinfo("Zapisano", f"Zapisano {len(screen_regions)} elementów dla ekranu '{screen}'.", parent=self.root)
        return True

    def quit(self):
        if self.pending or self.selection is not None:
            answer = messagebox.askyesnocancel(
                "Niezapisane elementy",
                "Zapisać zaznaczone elementy przed wyjściem?",
                parent=self.root,
            )
            if answer is None:
                return
            if answer and not self.save():
                return
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Zaznaczaj elementy ekranu i zapisuj ich szablony.")
    parser.add_argument("--image", help="ścieżka do wejściowego screena PNG; bez opcji otworzy się wybór pliku")
    parser.add_argument("--screen", default="", help="nazwa ekranu do wstępnego wpisania w oknie")
    args = parser.parse_args()

    root = tk.Tk()
    root.withdraw()
    image_path = args.image
    if not image_path:
        image_path = filedialog.askopenfilename(
            title="Wybierz screen gry",
            filetypes=(("Obrazy PNG", "*.png"), ("Wszystkie pliki", "*.*")),
        )
    if not image_path:
        root.destroy()
        return

    try:
        app = Annotator(root, image_path, args.screen)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        messagebox.showerror("Nie można uruchomić narzędzia", str(error), parent=root)
        root.destroy()
        return
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
