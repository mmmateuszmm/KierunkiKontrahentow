"""
Nakladka "Kierunki kontrahentow" - niezalezne, malutkie okienko always-on-top
do trzymania obok glownego programu wagowego w pracy.

Nie laczy sie z IT9000PC/LibraNet, nie czyta ani nie modyfikuje jego procesu
ani bazy - to osobne male narzedzie z wlasna baza SQLite. Wpisujesz kod
kontrahenta recznie (tak jak robisz to w glownym programie), a nakladka:
  - jesli kontrahent ma juz zapisany kierunek na dzisiaj -> od razu go pokazuje,
  - jesli nie -> pozwala go zapisac (kierunek + Faktura/Gratis) na przyszlosc,
  - jeden kontrahent moze miec ROZNE kierunki na rozne dni tygodnia
    (np. poniedzialek -> Rampa 3, sroda -> Rampa 5),
  - dzien roboczy zmienia sie o 5:00 (nie o polnocy), takze gdy okno stoi zminimalizowane.
"""

import csv
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

import db

VERSION = "1.0.0"
SPRAWDZ_DZIEN_CO_MS = 20_000

AKCJE_PL = {
    "LOOKUP_FOUND": "znaleziono",
    "LOOKUP_MISSING": "brak w bazie",
    "SAVED": "zapisano kierunek",
    "FILL_ALL_DAYS": "wypelniono wszystkie dni",
}

if getattr(sys, "frozen", False):
    # spakowane .exe (PyInstaller) - baza ma siedziec obok pliku .exe,
    # a nie w tymczasowym folderze rozpakowania (ktory znika po zamknieciu)
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "kierunki.db")


def wypelnij_dni_z_potwierdzeniem(parent, conn, row, on_done=None):
    """Kopiuje kierunek z `row` na wszystkie dni, ktore go jeszcze nie maja - po potwierdzeniu.
    Istniejace wpisy nie sa zmieniane."""
    brakujace = db.dni_do_uzupelnienia(conn, row)
    if not brakujace:
        messagebox.showinfo(
            "Wszystkie dni sa juz uzupelnione",
            "Ten kierunek jest juz zapisany na kazdy dzien tygodnia.", parent=parent,
        )
        return
    opis_txt = f', opis: "{row["opis"]}"' if row["opis"] else ""
    if not messagebox.askyesno(
        "Wypelnic wszystkie dni?",
        f'Kontrahent {row["code"]}: kierunek "{row["kierunek"]}" ({row["typ"]}{opis_txt}) '
        f"zostanie dopisany na dni:\n\n{', '.join(brakujace)}\n\n"
        "Istniejace wpisy NIE zostana zmienione ani nadpisane. Kontynuowac?",
        parent=parent,
    ):
        return
    db.wypelnij_wszystkie_dni(conn, row)
    db.log_history(conn, row["code"], "FILL_ALL_DAYS", row["kierunek"])
    if on_done:
        on_done()


class DirectionDialog(tk.Toplevel):
    """Formularz dodania / edycji JEDNEGO kierunku kontrahenta (na wybrany dzien tygodnia)."""

    def __init__(self, parent, conn, code, row=None, on_saved=None):
        super().__init__(parent)
        self.conn = conn
        self.code = code
        self.row = row  # None = nowy kierunek, sqlite3.Row = edycja istniejacego
        self.on_saved = on_saved

        self.title(f"Nowy kierunek: {code}" if row is None else f"Edycja kierunku: {code}")
        self.geometry("320x340")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        ttk.Label(self, text=f"Kontrahent: {code}", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 0)
        )

        ttk.Label(self, text="Kierunek:").pack(anchor="w", padx=10, pady=(8, 0))
        self.kierunek_var = tk.StringVar(value=row["kierunek"] if row else "")
        entry = ttk.Entry(self, textvariable=self.kierunek_var)
        entry.pack(fill="x", padx=10, pady=4)
        entry.focus_set()

        self.typ_var = tk.StringVar(value=row["typ"] if row else "FAKTURA")
        typ_row = ttk.Frame(self)
        typ_row.pack(anchor="w", padx=10, pady=4)
        ttk.Radiobutton(typ_row, text="Faktura", variable=self.typ_var, value="FAKTURA").pack(side="left")
        ttk.Radiobutton(typ_row, text="Gratis", variable=self.typ_var, value="GRATIS").pack(side="left", padx=8)

        ttk.Label(self, text="Dzien pakowania:").pack(anchor="w", padx=10, pady=(6, 0))
        domyslny_dzien = row["dzien_tygodnia"] if row else db.dzisiejszy_dzien()
        self.dzien_var = tk.StringVar(value=domyslny_dzien or db.dzisiejszy_dzien())
        ttk.Combobox(self, textvariable=self.dzien_var, values=db.DNI, state="readonly").pack(
            fill="x", padx=10, pady=4
        )

        ttk.Label(self, text="Opis / nazwa dostawy (gdy ten sam kod jedzie w kilka miejsc):").pack(
            anchor="w", padx=10, pady=(6, 0)
        )
        self.opis_var = tk.StringVar(value=row["opis"] if row else "")
        opis_entry = ttk.Entry(self, textvariable=self.opis_var)
        opis_entry.pack(fill="x", padx=10, pady=4)

        entry.bind("<Return>", lambda e: self.save())
        opis_entry.bind("<Return>", lambda e: self.save())
        ttk.Button(self, text="Zapisz", command=self.save).pack(pady=10)

    def save(self):
        kier = self.kierunek_var.get().strip()
        if not kier:
            messagebox.showwarning("Brak kierunku", "Wpisz kierunek przed zapisem.", parent=self)
            return
        nowy_dzien = self.dzien_var.get()
        nowy_opis = self.opis_var.get().strip()

        konflikt = db.find_exact(self.conn, self.code, nowy_dzien, nowy_opis)
        koliduje = konflikt and (self.row is None or konflikt["id"] != self.row["id"])
        if koliduje:
            opis_txt = f' / "{nowy_opis}"' if nowy_opis else ""
            if not messagebox.askyesno(
                "Nadpisac?",
                f"Kontrahent {self.code} ma juz zapisany kierunek na {nowy_dzien}{opis_txt}: "
                f"{konflikt['kierunek']}. Nadpisac go?",
                parent=self,
            ):
                return
            db.delete_contractor(self.conn, konflikt["id"])

        if self.row is None:
            db.insert_contractor(self.conn, self.code, kier, self.typ_var.get(), nowy_dzien, nowy_opis)
        else:
            db.update_contractor(self.conn, self.row["id"], kier, self.typ_var.get(), nowy_dzien, nowy_opis)
        db.log_history(self.conn, self.code, "SAVED", kier)
        self.destroy()
        if self.on_saved:
            self.on_saved()


class OverlayApp(tk.Tk):
    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = db_path or DB_PATH
        self.conn = db.connect(self.db_path)

        self.title(f"Kierunki kontrahentow v{VERSION}")
        self.geometry("400x520")
        self.minsize(360, 440)
        self.attributes("-topmost", True)

        self._dzien_roboczy = db.dzien_roboczy()
        self._build_layout()
        self.code_entry.focus_set()
        self.after(SPRAWDZ_DZIEN_CO_MS, self._sprawdz_zmiane_dnia)

    # ---------- zmiana dnia roboczego (5:00) ----------

    def _sprawdz_zmiane_dnia(self):
        """Dzien roboczy zmienia sie o 5:00. Sprawdzamy cyklicznie, wiec dziala tez po wybudzeniu
        komputera i gdy okno jest zminimalizowane."""
        try:
            biezacy = db.dzien_roboczy()
            if biezacy != self._dzien_roboczy:
                self._dzien_roboczy = biezacy
                self._restart_widoku()
        finally:
            self.after(SPRAWDZ_DZIEN_CO_MS, self._sprawdz_zmiane_dnia)

    def _restart_widoku(self):
        """Odpowiednik restartu o 5:00: zamyka okna pomocnicze, czysci ekran, odswieza dzien
        i robi dzienna kopie zapasowa. Dane w bazie nie sa ruszane."""
        for w in self.winfo_children():
            if isinstance(w, tk.Toplevel):
                w.destroy()
        self.code_var.set("")
        self.render_idle()
        self._odswiez_naglowek()
        db.backup_db(self.db_path)
        self.code_entry.focus_set()

    def _odswiez_naglowek(self):
        self.dzis_label.config(
            text=f"Wysylka dnia {db.dzisiejszy_dzien()} na {db.jutrzejszy_dzien()}"
        )

    # ---------- UI ----------

    def _build_layout(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        dzis = db.dzisiejszy_dzien()
        jutro = db.jutrzejszy_dzien()
        self.dzis_label = ttk.Label(
            top, text=f"Wysylka dnia {dzis} na {jutro}",
            font=("Segoe UI", 9, "bold"), foreground="#2b6cb0",
        )
        self.dzis_label.pack(anchor="w", pady=(0, 6))

        ttk.Label(top, text="Kod kontrahenta:", font=("Segoe UI", 10)).pack(anchor="w")
        self.code_var = tk.StringVar()
        self.code_entry = ttk.Entry(top, textvariable=self.code_var, font=("Segoe UI", 16))
        self.code_entry.pack(fill="x", pady=4)
        self.code_entry.bind("<Return>", lambda e: self.on_lookup())
        self.code_entry.bind("<KeyRelease>", self.on_type)

        topmost_var = tk.BooleanVar(value=True)
        self.topmost_var = topmost_var
        ttk.Checkbutton(
            top, text="Zawsze na wierzchu", variable=topmost_var,
            command=lambda: self.attributes("-topmost", topmost_var.get()),
        ).pack(anchor="w")

        self.result_frame = ttk.Frame(self, padding=10)
        self.result_frame.pack(fill="both", expand=True)
        self.render_idle()

        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Zarzadzaj baza / historia...", command=self.open_manager).pack(fill="x")

    def _clear_result(self):
        for w in self.result_frame.winfo_children():
            w.destroy()

    def render_idle(self):
        self._clear_result()
        ttk.Label(
            self.result_frame,
            text="Wpisz kod kontrahenta i wcisnij Enter.",
            foreground="#666", wraplength=320, justify="left",
        ).pack(anchor="w")

    def on_type(self, _event=None):
        if self.code_var.get() == "":
            self.render_idle()

    # ---------- logika ----------

    def on_lookup(self):
        code = self.code_var.get().strip()
        if not code:
            return
        rows = db.find_contractor_all(self.conn, code)
        if rows:
            dzis_row = next((r for r in rows if r["dzien_tygodnia"] == db.dzisiejszy_dzien()), None)
            db.log_history(self.conn, code, "LOOKUP_FOUND", dzis_row["kierunek"] if dzis_row else "")
            self.render_found_multi(code, rows)
        else:
            db.log_history(self.conn, code, "LOOKUP_MISSING")
            self.render_new(code)

    def _refresh_code_view(self, code):
        rows = db.find_contractor_all(self.conn, code)
        if rows:
            self.render_found_multi(code, rows)
        else:
            self.render_new(code)

    def _box_kierunek(self, row, box_bg, naglowek):
        box = tk.Frame(self.result_frame, bg=box_bg, padx=12, pady=8)
        box.pack(fill="x", pady=(0, 4))
        tk.Label(
            box, text=f"KIERUNEK: {row['kierunek']}", bg=box_bg, fg="white",
            font=("Segoe UI", 14, "bold"), wraplength=340, justify="left",
        ).pack(anchor="w")
        if row["opis"]:
            tk.Label(
                box, text=f"Opis: {row['opis']}", bg=box_bg, fg="white",
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w")
        tk.Label(
            box, text=f"Typ: {row['typ']}  |  {naglowek}",
            bg=box_bg, fg="white", font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

    def render_found_multi(self, code, rows):
        self._clear_result()
        dzis = db.dzisiejszy_dzien()
        dzis_rows = [r for r in rows if r["dzien_tygodnia"] == dzis]

        if len(dzis_rows) == 1:
            self._box_kierunek(dzis_rows[0], "#1a7f37", naglowek=f"na dzisiaj ({dzis})")
        elif len(dzis_rows) > 1:
            ttk.Label(
                self.result_frame,
                text=f"Uwaga: {len(dzis_rows)} rozne dostawy dzis ({dzis}) na ten kod - "
                     f"dopasuj wg opisu z faktury:",
                foreground="#c0392b", font=("Segoe UI", 9, "bold"), wraplength=360, justify="left",
            ).pack(anchor="w", pady=(0, 4))
            for r in dzis_rows:
                self._box_kierunek(r, "#1a7f37", naglowek=f"na dzisiaj ({dzis})")
        else:
            box_bg = "#b7791f"
            box = tk.Frame(self.result_frame, bg=box_bg, padx=12, pady=10)
            box.pack(fill="x", pady=(0, 4))
            tk.Label(
                box, text=f"Brak kierunku na dzisiaj ({dzis})", bg=box_bg, fg="white",
                font=("Segoe UI", 13, "bold"), wraplength=340, justify="left",
            ).pack(anchor="w")
            tk.Label(
                box, text="ten kontrahent ma zapisane kierunki na inne dni (lista ponizej)",
                bg=box_bg, fg="white", font=("Segoe UI", 9),
            ).pack(anchor="w", pady=(2, 0))

        ttk.Label(
            self.result_frame, text="Wszystkie dostawy tego kontrahenta (2x klik = edycja):",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(10, 2))

        tree = ttk.Treeview(
            self.result_frame, columns=("dzien", "opis", "kierunek", "typ"), show="headings",
            height=min(6, max(2, len(rows))),
        )
        for col, text, w in [
            ("dzien", "Dzien", 80), ("opis", "Opis", 110), ("kierunek", "Kierunek", 130), ("typ", "Typ", 55),
        ]:
            tree.heading(col, text=text)
            tree.column(col, width=w)
        tree.pack(fill="x", pady=(0, 4))
        tree.tag_configure("dzis", background="#d4f8d4")
        for r in rows:
            tag = "dzis" if r["dzien_tygodnia"] == dzis else ""
            tree.insert(
                "", "end", iid=str(r["id"]),
                values=(r["dzien_tygodnia"] or "-", r["opis"] or "-", r["kierunek"], r["typ"]), tags=(tag,),
            )

        def edit_row(_e=None):
            sel = tree.selection()
            if not sel:
                return
            row = db.find_contractor_by_id(self.conn, int(sel[0]))
            if row:
                DirectionDialog(self, self.conn, code, row=row,
                                 on_saved=lambda: self._refresh_code_view(code))

        tree.bind("<Double-1>", edit_row)

        def wypelnij():
            sel = tree.selection()
            if sel:
                zrodlo = db.find_contractor_by_id(self.conn, int(sel[0]))
            elif len({(r["kierunek"], r["typ"], r["opis"]) for r in rows}) == 1:
                zrodlo = rows[0]
            else:
                messagebox.showinfo(
                    "Wybierz wpis",
                    "Ten kontrahent ma rozne kierunki - zaznacz na liscie ten, ktory ma zostac "
                    "skopiowany na wszystkie dni.", parent=self,
                )
                return
            if zrodlo:
                wypelnij_dni_z_potwierdzeniem(self, self.conn, zrodlo,
                                               on_done=lambda: self._refresh_code_view(code))

        btn_row = ttk.Frame(self.result_frame)
        btn_row.pack(anchor="w", pady=(6, 0))
        ttk.Button(
            btn_row, text="Dodaj kierunek na inny dzien",
            command=lambda: DirectionDialog(self, self.conn, code, row=None,
                                             on_saved=lambda: self._refresh_code_view(code)),
        ).pack(side="left")
        ttk.Button(btn_row, text="Wypelnij wszystkie dni", command=wypelnij).pack(side="left", padx=6)

    def render_new(self, code):
        self._clear_result()
        tk.Label(
            self.result_frame, text=f"Nieznany kontrahent: {code}",
            fg="#c0392b", font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            self.result_frame, text="Podaj kierunek, zeby zapisac na przyszlosc:",
            fg="#666",
        ).pack(anchor="w", pady=(2, 8))

        kierunek_var = tk.StringVar()
        entry = ttk.Entry(self.result_frame, textvariable=kierunek_var, font=("Segoe UI", 13))
        entry.pack(fill="x", pady=4)
        entry.focus_set()

        typ_var = tk.StringVar(value="FAKTURA")
        typ_row = ttk.Frame(self.result_frame)
        typ_row.pack(anchor="w", pady=4)
        ttk.Radiobutton(typ_row, text="Faktura", variable=typ_var, value="FAKTURA").pack(side="left")
        ttk.Radiobutton(typ_row, text="Gratis", variable=typ_var, value="GRATIS").pack(side="left", padx=8)

        ttk.Label(self.result_frame, text="Dzien pakowania:").pack(anchor="w", pady=(6, 0))
        dzien_var = tk.StringVar(value=db.dzisiejszy_dzien())
        ttk.Combobox(
            self.result_frame, textvariable=dzien_var, values=db.DNI, state="readonly", font=("Segoe UI", 11)
        ).pack(fill="x", pady=4)

        ttk.Label(self.result_frame, text="Opis / nazwa dostawy (opcjonalnie, gdy ten kod jedzie w kilka "
                                           "miejsc):").pack(anchor="w", pady=(6, 0))
        opis_var = tk.StringVar()
        ttk.Entry(self.result_frame, textvariable=opis_var).pack(fill="x", pady=4)

        def save():
            kier = kierunek_var.get().strip()
            if not kier:
                messagebox.showwarning("Brak kierunku", "Wpisz kierunek przed zapisem.")
                return
            db.insert_contractor(self.conn, code, kier, typ_var.get(), dzien_var.get(), opis_var.get().strip())
            db.log_history(self.conn, code, "SAVED", kier)
            self.code_var.set("")
            self.render_idle()
            self.code_entry.focus_set()

        entry.bind("<Return>", lambda e: save())
        ttk.Button(self.result_frame, text="Zapisz kierunek", command=save).pack(anchor="w", pady=(8, 0))

    def open_manager(self):
        ManagerWindow(self, self.conn)


class ManagerWindow(tk.Toplevel):
    def __init__(self, parent, conn):
        super().__init__(parent)
        self.conn = conn
        self.title("Baza kierunkow - zarzadzanie")
        self.geometry("820x500")

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Szukaj:").pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(top, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True, padx=6)
        search_entry.bind("<KeyRelease>", lambda e: self.refresh())

        ttk.Label(top, text="Dzien:").pack(side="left", padx=(8, 0))
        self.dzien_filter_var = tk.StringVar(value=f"Dzisiaj ({db.dzisiejszy_dzien()})")
        dzien_values = [f"Dzisiaj ({db.dzisiejszy_dzien()})", "Wszystkie dni"] + db.DNI
        dzien_combo = ttk.Combobox(
            top, textvariable=self.dzien_filter_var, values=dzien_values, state="readonly", width=16
        )
        dzien_combo.pack(side="left", padx=4)
        dzien_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        ttk.Button(top, text="Eksport CSV", command=self.export_csv).pack(side="left", padx=2)
        ttk.Button(top, text="Import CSV", command=self.import_csv).pack(side="left", padx=2)

        self.tree = ttk.Treeview(
            self, columns=("code", "opis", "kierunek", "typ", "dzien", "updated"), show="headings", height=14
        )
        for col, text, w in [
            ("code", "Kod kontrahenta", 110), ("opis", "Opis", 140), ("kierunek", "Kierunek", 150),
            ("typ", "Typ", 60), ("dzien", "Dzien", 90), ("updated", "Zaktualizowano", 120),
        ]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree.bind("<Double-1>", self.edit_selected)

        btns = ttk.Frame(self, padding=8)
        btns.pack(fill="x")
        ttk.Button(btns, text="Nowy kierunek...", command=self.add_new).pack(side="left")
        ttk.Button(btns, text="Edytuj zaznaczone", command=self.edit_selected).pack(side="left", padx=6)
        ttk.Button(btns, text="Wypelnij wszystkie dni (zaznaczony)", command=self.fill_selected).pack(
            side="left")
        ttk.Button(btns, text="Usun zaznaczone", command=self.delete_selected).pack(side="left", padx=6)
        ttk.Button(btns, text="Historia...", command=lambda: HistoryWindow(self, self.conn)).pack(
            side="left")

        plik = self.conn.execute("PRAGMA database_list").fetchone()["file"]
        folder_kopii = os.path.join(os.path.dirname(plik), db.BACKUP_FOLDER)
        ttk.Label(
            self, text=f"Baza: {plik}\nKopie zapasowe (automatyczne, raz dziennie): {folder_kopii}",
            foreground="#666", font=("Segoe UI", 8), justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 6))

        self.refresh()

    def _active_dzien_filter(self):
        wybor = self.dzien_filter_var.get()
        if wybor == "Wszystkie dni":
            return ""
        if wybor.startswith("Dzisiaj"):
            return db.dzisiejszy_dzien()
        return wybor

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        rows = db.list_contractors(self.conn, self.search_var.get().strip(), self._active_dzien_filter())
        for row in rows:
            self.tree.insert(
                "", "end", iid=str(row["id"]),
                values=(row["code"], row["opis"] or "-", row["kierunek"], row["typ"],
                        row["dzien_tygodnia"] or "-", row["updated_at"]),
            )

    def _selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def add_new(self):
        code = simpledialog.askstring("Nowy kierunek", "Kod kontrahenta:", parent=self)
        if not code:
            return
        DirectionDialog(self, self.conn, code.strip(), row=None, on_saved=self.refresh)

    def edit_selected(self, _event=None):
        row_id = self._selected_id()
        if row_id is None:
            return
        row = db.find_contractor_by_id(self.conn, row_id)
        if not row:
            return
        DirectionDialog(self, self.conn, row["code"], row=row, on_saved=self.refresh)

    def fill_selected(self):
        row_id = self._selected_id()
        if row_id is None:
            messagebox.showinfo("Wybierz wpis", "Zaznacz na liscie kierunek, ktory ma zostac "
                                                "skopiowany na wszystkie dni.", parent=self)
            return
        row = db.find_contractor_by_id(self.conn, row_id)
        if row:
            wypelnij_dni_z_potwierdzeniem(self, self.conn, row, on_done=self.refresh)

    def delete_selected(self):
        row_id = self._selected_id()
        if row_id is None:
            return
        row = db.find_contractor_by_id(self.conn, row_id)
        if not row:
            return
        if messagebox.askyesno(
            "Usun", f"Na pewno usunac kierunek {row['kierunek']} ({row['dzien_tygodnia']}) "
                    f"dla kontrahenta {row['code']}?"
        ):
            db.delete_contractor(self.conn, row_id)
            self.refresh()

    def export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="kierunki_export.csv"
        )
        if not path:
            return
        rows = db.list_contractors(self.conn)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["code", "opis", "kierunek", "typ", "dzien_tygodnia", "updated_at"])
            for r in rows:
                writer.writerow([r["code"], r["opis"], r["kierunek"], r["typ"],
                                  r["dzien_tygodnia"], r["updated_at"]])
        messagebox.showinfo("Eksport", f"Zapisano {len(rows)} wpisow do {path}")

    def import_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path:
            return
        count = 0
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                code = (row.get("code") or "").strip()
                kierunek = (row.get("kierunek") or "").strip()
                typ = (row.get("typ") or "FAKTURA").strip() or "FAKTURA"
                dzien = (row.get("dzien_tygodnia") or "").strip()
                opis = (row.get("opis") or "").strip()
                if code and kierunek:
                    db.upsert_contractor(self.conn, code, kierunek, typ, dzien, opis)
                    count += 1
        self.refresh()
        messagebox.showinfo("Import", f"Zaimportowano/zaktualizowano {count} wpisow")


class HistoryWindow(tk.Toplevel):
    """Podglad ostatnich operacji (wyszukania, zapisy). Tylko do odczytu."""

    def __init__(self, parent, conn):
        super().__init__(parent)
        self.title("Historia operacji")
        self.geometry("620x420")

        tree = ttk.Treeview(self, columns=("czas", "code", "akcja", "kierunek"), show="headings")
        for col, text, w in [("czas", "Czas", 150), ("code", "Kod kontrahenta", 120),
                              ("akcja", "Operacja", 170), ("kierunek", "Kierunek", 160)]:
            tree.heading(col, text=text)
            tree.column(col, width=w)
        tree.pack(fill="both", expand=True, padx=8, pady=8)
        for r in db.recent_history(conn, 300):
            tree.insert(
                "", "end",
                values=(r["created_at"].replace("T", " "), r["code"],
                        AKCJE_PL.get(r["action"], r["action"]), r["kierunek"] or ""),
            )


if __name__ == "__main__":
    OverlayApp().mainloop()
