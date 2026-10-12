"""Lokalna baza SQLite: mapowanie kod kontrahenta -> kierunki wysylki.

Jeden kod kontrahenta moze miec WIELE wpisow: rozne dni tygodnia (np. pon/sroda/piatek
inne trasy) ORAZ, tego samego dnia, rozne dostawy pod tym samym kodem rozroznione
opisem (np. "Sklep Centrum" -> Leszno, "Sklep Rynek" -> Wroclaw)."""

import os
import re
import sqlite3
from datetime import date, datetime, timedelta

DNI = ["Poniedzialek", "Wtorek", "Sroda", "Czwartek", "Piatek", "Sobota", "Niedziela"]
DNI_KOLEJNOSC = {nazwa: i for i, nazwa in enumerate(DNI)}

# Dzien roboczy zmienia sie o 5:00, a nie o 00:00 - towar jest wazony takze po polnocy
# i nadal nalezy do poprzedniego dnia pakowania.
GODZINA_ZMIANY_DNIA = 5

BACKUP_FOLDER = "kopie_zapasowe"
BACKUP_KEEP = 14

SCHEMA = """
CREATE TABLE IF NOT EXISTS contractors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    kierunek TEXT NOT NULL,
    typ TEXT NOT NULL DEFAULT 'FAKTURA',
    dzien_tygodnia TEXT NOT NULL DEFAULT '',
    opis TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(code, dzien_tygodnia, opis)
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    action TEXT NOT NULL,
    kierunek TEXT,
    created_at TEXT NOT NULL
);
"""


# ---------- dzien roboczy ----------

def dzien_roboczy(teraz: datetime = None) -> date:
    """Data biezacego dnia roboczego: do 4:59 nadal poprzedni dzien kalendarzowy."""
    teraz = teraz or datetime.now()
    return (teraz - timedelta(hours=GODZINA_ZMIANY_DNIA)).date()


def dzisiejszy_dzien(teraz: datetime = None) -> str:
    """Dzien tygodnia dnia roboczego (Poniedzialek..Niedziela)."""
    return DNI[dzien_roboczy(teraz).weekday()]


def jutrzejszy_dzien(teraz: datetime = None) -> str:
    return DNI[(dzien_roboczy(teraz).weekday() + 1) % 7]


# ---------- kopie zapasowe ----------

def _kopia(db_path: str, nazwa: str) -> str:
    folder = os.path.join(os.path.dirname(os.path.abspath(db_path)), BACKUP_FOLDER)
    os.makedirs(folder, exist_ok=True)
    cel = os.path.join(folder, nazwa)
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(cel)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return cel


def backup_db(db_path: str, przed_migracja: bool = False):
    """Kopia zapasowa bazy w podfolderze kopie_zapasowe obok pliku bazy.

    Zwykla: najwyzej jedna na dzien roboczy, trzymamy ostatnie BACKUP_KEEP.
    Przed migracja schematu: zawsze, i nigdy nie jest automatycznie kasowana.
    Nie rzuca wyjatkow - blad kopii nie moze blokowac uruchomienia programu."""
    try:
        if not os.path.isfile(db_path) or os.path.getsize(db_path) == 0:
            return None
        teraz = datetime.now()
        if przed_migracja:
            return _kopia(db_path, f"kierunki_{teraz:%Y%m%d_%H%M%S}_przed_migracja.db")

        folder = os.path.join(os.path.dirname(os.path.abspath(db_path)), BACKUP_FOLDER)
        prefix = f"kierunki_{dzien_roboczy(teraz):%Y%m%d}_"
        wzorzec = re.compile(r"kierunki_\d{8}_\d{6}\.db")
        istniejace = os.listdir(folder) if os.path.isdir(folder) else []
        if any(f.startswith(prefix) and wzorzec.fullmatch(f) for f in istniejace):
            return None
        cel = _kopia(db_path, f"{prefix}{teraz:%H%M%S}.db")
        zwykle = sorted(f for f in os.listdir(folder) if wzorzec.fullmatch(f))
        for stara in zwykle[:-BACKUP_KEEP]:
            os.remove(os.path.join(folder, stara))
        return cel
    except Exception:
        return None


# ---------- polaczenie i migracja ----------

def _schema_wymaga_migracji(db_path: str) -> bool:
    try:
        c = sqlite3.connect(db_path)
        try:
            cols = {r[1] for r in c.execute("PRAGMA table_info(contractors)")}
        finally:
            c.close()
        return bool(cols) and not {"id", "dzien_tygodnia", "opis"} <= cols
    except Exception:
        return False


def _migrate(conn: sqlite3.Connection) -> None:
    """Przebudowa starszych schematow do aktualnego, w jednej transakcji (wszystko albo nic).
    Tabela history nie jest ruszana, a wszystkie istniejace wpisy kontrahentow sa kopiowane."""
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "contractors" not in tables:
        return
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(contractors)")]
    if {"id", "dzien_tygodnia", "opis"} <= set(cols):
        return  # juz aktualny schemat

    dzien_expr = "dzien_tygodnia" if "dzien_tygodnia" in cols else "''"
    opis_expr = "opis" if "opis" in cols else "''"
    try:
        conn.executescript(
            "BEGIN;\n"
            "ALTER TABLE contractors RENAME TO contractors_old;\n"
            + SCHEMA +
            "INSERT INTO contractors (code, kierunek, typ, dzien_tygodnia, opis, updated_at) "
            f"SELECT code, kierunek, typ, {dzien_expr}, {opis_expr}, updated_at FROM contractors_old;\n"
            "DROP TABLE contractors_old;\n"
            "COMMIT;"
        )
    except Exception:
        conn.rollback()
        raise


def connect(db_path: str) -> sqlite3.Connection:
    if os.path.isfile(db_path) and os.path.getsize(db_path) > 0:
        backup_db(db_path, przed_migracja=_schema_wymaga_migracji(db_path))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


# ---------- operacje na kierunkach ----------

def find_contractor_all(conn: sqlite3.Connection, code: str):
    """Wszystkie wpisy zapisane dla danego kodu kontrahenta, posortowane kalendarzowo."""
    rows = conn.execute("SELECT * FROM contractors WHERE code = ?", (code,)).fetchall()
    return sorted(
        rows,
        key=lambda r: (DNI_KOLEJNOSC.get(r["dzien_tygodnia"], len(DNI)), r["opis"], r["kierunek"]),
    )


def find_exact(conn: sqlite3.Connection, code: str, dzien_tygodnia: str, opis: str):
    """Wpis o dokladnie tym samym kluczu (code, dzien, opis) - do wykrywania kolizji."""
    return conn.execute(
        "SELECT * FROM contractors WHERE code = ? AND dzien_tygodnia = ? AND opis = ?",
        (code, dzien_tygodnia, opis),
    ).fetchone()


def find_contractor_by_id(conn: sqlite3.Connection, row_id: int):
    return conn.execute("SELECT * FROM contractors WHERE id = ?", (row_id,)).fetchone()


def insert_contractor(conn: sqlite3.Connection, code: str, kierunek: str, typ: str,
                       dzien_tygodnia: str = "", opis: str = "") -> int:
    """Dodaje NOWY wpis (nowy wiersz). Uzyj przy dodawaniu kolejnej dostawy dla kontrahenta."""
    now = datetime.now().isoformat(timespec="seconds")
    dzien_tygodnia = dzien_tygodnia or dzisiejszy_dzien()
    cur = conn.execute(
        "INSERT INTO contractors (code, kierunek, typ, dzien_tygodnia, opis, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (code, kierunek, typ, dzien_tygodnia, opis, now),
    )
    conn.commit()
    return cur.lastrowid


def update_contractor(conn: sqlite3.Connection, row_id: int, kierunek: str, typ: str,
                       dzien_tygodnia: str, opis: str) -> None:
    """Nadpisuje ISTNIEJACY wpis po jego id (edycja, nie tworzy nowego wiersza)."""
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "UPDATE contractors SET kierunek = ?, typ = ?, dzien_tygodnia = ?, opis = ?, updated_at = ? "
        "WHERE id = ?",
        (kierunek, typ, dzien_tygodnia, opis, now, row_id),
    )
    conn.commit()


def upsert_contractor(conn: sqlite3.Connection, code: str, kierunek: str, typ: str,
                       dzien_tygodnia: str = "", opis: str = "") -> None:
    """Wstawia albo aktualizuje PO KLUCZU NATURALNYM (code, dzien, opis) - wygodne przy imporcie CSV,
    gdzie nie mamy id wiersza. Do edycji konkretnego wiersza w UI uzywaj update_contractor()."""
    now = datetime.now().isoformat(timespec="seconds")
    dzien_tygodnia = dzien_tygodnia or dzisiejszy_dzien()
    conn.execute(
        "INSERT INTO contractors (code, kierunek, typ, dzien_tygodnia, opis, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(code, dzien_tygodnia, opis) DO UPDATE SET kierunek = excluded.kierunek, "
        "typ = excluded.typ, updated_at = excluded.updated_at",
        (code, kierunek, typ, dzien_tygodnia, opis, now),
    )
    conn.commit()


def dni_do_uzupelnienia(conn: sqlite3.Connection, row) -> list:
    """Dni tygodnia, na ktore kontrahent nie ma jeszcze wpisu o tym samym (code, opis) co `row`."""
    zajete = {
        r["dzien_tygodnia"]
        for r in conn.execute(
            "SELECT dzien_tygodnia FROM contractors WHERE code = ? AND opis = ?",
            (row["code"], row["opis"]),
        )
    }
    return [d for d in DNI if d not in zajete]


def wypelnij_wszystkie_dni(conn: sqlite3.Connection, row) -> list:
    """Kopiuje kierunek/typ/opis z `row` na KAZDY dzien tygodnia, ktory jeszcze go nie ma.
    Istniejace wpisy (rowniez z innym kierunkiem) nie sa zmieniane ani nadpisywane."""
    brakujace = dni_do_uzupelnienia(conn, row)
    if not brakujace:
        return []
    now = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT INTO contractors (code, kierunek, typ, dzien_tygodnia, opis, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(row["code"], row["kierunek"], row["typ"], d, row["opis"], now) for d in brakujace],
    )
    conn.commit()
    return brakujace


def delete_contractor(conn: sqlite3.Connection, row_id: int) -> None:
    conn.execute("DELETE FROM contractors WHERE id = ?", (row_id,))
    conn.commit()


def list_contractors(conn: sqlite3.Connection, search: str = "", dzien: str = ""):
    """Lista wpisow posortowana kalendarzowo (Poniedzialek -> Niedziela),
    opcjonalnie filtrowana po dniu tygodnia i/lub wyszukiwanej frazie (kod/kierunek/opis)."""
    query = "SELECT * FROM contractors WHERE 1=1"
    params = []
    if search:
        query += " AND (code LIKE ? OR kierunek LIKE ? OR opis LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    if dzien:
        query += " AND dzien_tygodnia = ?"
        params.append(dzien)
    rows = conn.execute(query, params).fetchall()
    return sorted(
        rows,
        key=lambda r: (DNI_KOLEJNOSC.get(r["dzien_tygodnia"], len(DNI)), r["code"], r["opis"]),
    )


def log_history(conn: sqlite3.Connection, code: str, action: str, kierunek: str = "") -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO history (code, action, kierunek, created_at) VALUES (?, ?, ?, ?)",
        (code, action, kierunek, now),
    )
    conn.commit()


def recent_history(conn: sqlite3.Connection, limit: int = 30):
    return conn.execute(
        "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
