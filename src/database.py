"""Módulo 4 — Capa de acceso a la base de datos SQLite.

Usa exclusivamente ``sqlite3`` de la librería estándar (sin ORM).
Todas las funciones reciben ``db_path`` como primer argumento para
permitir bases de datos temporales en los tests.

Tablas:
    horses      -- catálogo de caballos.
    races       -- carreras (evento + número de carrera).
    entries     -- participación de un caballo en una carrera.
    enrichment  -- datos externos cacheados por caballo (JSON).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS horses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    birth_year INTEGER,
    sex TEXT,
    sire TEXT,
    dam TEXT,
    last_updated TEXT
);
CREATE TABLE IF NOT EXISTS races (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    track TEXT,
    distance REAL,
    surface TEXT,
    race_number INTEGER
);
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id INTEGER NOT NULL REFERENCES races(id),
    horse_id INTEGER NOT NULL REFERENCES horses(id),
    jockey TEXT,
    trainer TEXT,
    weight REAL,
    odds REAL,
    post_position INTEGER,
    result_position INTEGER
);
CREATE TABLE IF NOT EXISTS enrichment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    horse_id INTEGER NOT NULL REFERENCES horses(id),
    source TEXT,
    data_json TEXT,
    fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_entries_horse ON entries(horse_id);
CREATE INDEX IF NOT EXISTS idx_entries_race ON entries(race_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_horse ON enrichment(horse_id);
CREATE TABLE IF NOT EXISTS race_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track TEXT NOT NULL,
    date TEXT NOT NULL,
    race_number INTEGER NOT NULL,
    url TEXT NOT NULL,
    added_at TEXT,
    UNIQUE (track, date, race_number)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


@contextmanager
def get_connection(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Abre una conexión SQLite con claves foráneas activadas.

    Hace ``commit`` automático al salir del bloque y ``rollback`` si
    ocurre una excepción.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path) -> None:
    """Crea las tablas del esquema si no existen."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
    logger.info("Base de datos inicializada en %s", db_path)


def upsert_horse(
    db_path: str | Path,
    name: str,
    birth_year: int | None = None,
    sex: str | None = None,
    sire: str | None = None,
    dam: str | None = None,
) -> int:
    """Inserta o actualiza un caballo por nombre. Devuelve su ``id``."""
    with get_connection(db_path) as conn:
        return _upsert_horse(conn, name, birth_year, sex, sire, dam)


def _upsert_horse(
    conn: sqlite3.Connection,
    name: str,
    birth_year: int | None = None,
    sex: str | None = None,
    sire: str | None = None,
    dam: str | None = None,
) -> int:
    """Upsert de caballo reutilizando una conexión abierta."""
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute("SELECT id FROM horses WHERE name = ?", (name,)).fetchone()
    if row:
        conn.execute(
            """UPDATE horses
               SET birth_year = COALESCE(?, birth_year),
                   sex = COALESCE(?, sex),
                   sire = COALESCE(?, sire),
                   dam = COALESCE(?, dam),
                   last_updated = ?
               WHERE id = ?""",
            (birth_year, sex, sire, dam, now, row["id"]),
        )
        return int(row["id"])
    cur = conn.execute(
        """INSERT INTO horses (name, birth_year, sex, sire, dam, last_updated)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, birth_year, sex, sire, dam, now),
    )
    return int(cur.lastrowid)


def save_race(
    db_path: str | Path,
    race_number: int,
    date: str | None = None,
    track: str | None = None,
    distance: float | None = None,
    surface: str | None = None,
) -> int:
    """Inserta una carrera y devuelve su ``id``."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO races (date, track, distance, surface, race_number)
               VALUES (?, ?, ?, ?, ?)""",
            (date, track, distance, surface, race_number),
        )
        return int(cur.lastrowid)


def save_entries(
    db_path: str | Path,
    race_id: int,
    entries: list[dict[str, Any]],
) -> int:
    """Guarda las entradas (caballos participantes) de una carrera.

    Cada dict de ``entries`` acepta las claves devueltas por
    ``pdf_extractor.extract_races``: ``horse_name``, ``jockey``,
    ``trainer``, ``weight``, ``odds``, ``post_position`` y
    ``result_position`` (opcional). Devuelve cuántas filas se insertaron.
    """
    count = 0
    with get_connection(db_path) as conn:
        for entry in entries:
            name = entry.get("horse_name")
            if not name:
                logger.warning("Entrada sin nombre de caballo ignorada: %s", entry)
                continue
            horse_id = _upsert_horse(conn, name)
            conn.execute(
                """INSERT INTO entries
                   (race_id, horse_id, jockey, trainer, weight, odds,
                    post_position, result_position)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    race_id,
                    horse_id,
                    entry.get("jockey"),
                    entry.get("trainer"),
                    entry.get("weight"),
                    entry.get("odds"),
                    entry.get("post_position"),
                    entry.get("result_position"),
                ),
            )
            count += 1
    return count


def get_horse_history(db_path: str | Path, horse_name: str) -> dict[str, Any] | None:
    """Devuelve los datos del caballo, sus actuaciones y enriquecimiento.

    Retorna ``None`` si el caballo no existe en la base de datos.
    """
    with get_connection(db_path) as conn:
        horse = conn.execute(
            "SELECT * FROM horses WHERE name = ?", (horse_name,)
        ).fetchone()
        if horse is None:
            return None
        actuaciones = [
            dict(r)
            for r in conn.execute(
                """SELECT e.*, r.date, r.track, r.distance, r.surface,
                          r.race_number
                   FROM entries e JOIN races r ON r.id = e.race_id
                   WHERE e.horse_id = ?
                   ORDER BY r.date DESC""",
                (horse["id"],),
            ).fetchall()
        ]
        enriquecimiento = [
            {**dict(r), "data_json": json.loads(r["data_json"] or "null")}
            for r in conn.execute(
                "SELECT * FROM enrichment WHERE horse_id = ? ORDER BY fetched_at DESC",
                (horse["id"],),
            ).fetchall()
        ]
        return {
            "horse": dict(horse),
            "entries": actuaciones,
            "enrichment": enriquecimiento,
        }


def save_enrichment(
    db_path: str | Path,
    horse_id: int,
    source: str,
    data: dict[str, Any],
) -> int:
    """Guarda un registro de enriquecimiento. Devuelve su ``id``."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO enrichment (horse_id, source, data_json, fetched_at)
               VALUES (?, ?, ?, ?)""",
            (horse_id, source, json.dumps(data, ensure_ascii=False), now),
        )
        return int(cur.lastrowid)


def save_race_video(
    db_path: str | Path, track: str, date: str, race_number: int, url: str
) -> None:
    """Guarda (o reemplaza) el video de una carrera identificada por
    hipódromo, fecha ISO (``YYYY-MM-DD``) y número de carrera."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO race_videos (track, date, race_number, url, added_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (track, date, race_number)
               DO UPDATE SET url = excluded.url, added_at = excluded.added_at""",
            (track, date, race_number, url, now),
        )


def get_race_video(
    db_path: str | Path, track: str, date: str, race_number: int
) -> str | None:
    """URL o ruta local del video guardado para una carrera, si existe."""
    with get_connection(db_path) as conn:
        fila = conn.execute(
            """SELECT url FROM race_videos
               WHERE track = ? AND date = ? AND race_number = ?""",
            (track, date, race_number),
        ).fetchone()
    return fila["url"] if fila else None


def delete_race_video(
    db_path: str | Path, track: str, date: str, race_number: int
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "DELETE FROM race_videos WHERE track = ? AND date = ? AND race_number = ?",
            (track, date, race_number),
        )


def set_setting(db_path: str | Path, key: str, value: str | None) -> None:
    """Guarda un ajuste de usuario (p. ej. el enlace de la señal en vivo)."""
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )


def get_setting(db_path: str | Path, key: str, default: str | None = None) -> str | None:
    with get_connection(db_path) as conn:
        fila = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return fila["value"] if fila and fila["value"] is not None else default
