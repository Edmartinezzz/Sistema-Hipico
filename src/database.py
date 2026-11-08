"""Capa de acceso a SQLite para el sistema de análisis de caballos.

Usa únicamente ``sqlite3`` de la biblioteca estándar. Cada función pública abre
su propia conexión, de modo que puede llamarse desde cualquier módulo sin
compartir estado.

Tablas:

- ``horses``: datos fijos del caballo. La identidad es ``name_key``: el nombre
  normalizado (Unicode NFC, espacios colapsados y ``casefold``), de modo que
  «Relámpago» y «RELÁMPAGO» son el mismo caballo.
- ``races``: carreras, únicas por (fecha, hipódromo, número de carrera); los
  tres campos son obligatorios.
- ``entries``: participación de un caballo en una carrera.
- ``enrichment``: datos externos en JSON, con su fuente y fecha de obtención.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.getenv("HORSE_DB_PATH", "data/horse_analytics.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS horses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    birth_year INTEGER,
    sex TEXT,
    sire TEXT,
    dam TEXT,
    last_updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS races (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    track TEXT NOT NULL,
    distance TEXT,
    surface TEXT,
    race_number INTEGER NOT NULL,
    UNIQUE (date, track, race_number)
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id INTEGER NOT NULL REFERENCES races(id) ON DELETE CASCADE,
    horse_id INTEGER NOT NULL REFERENCES horses(id) ON DELETE CASCADE,
    jockey TEXT,
    trainer TEXT,
    weight REAL,
    odds REAL,
    post_position INTEGER,
    result_position INTEGER,
    UNIQUE (race_id, horse_id)
);

CREATE TABLE IF NOT EXISTS enrichment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    horse_id INTEGER NOT NULL REFERENCES horses(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    data_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_horse ON entries(horse_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_horse ON enrichment(horse_id);
"""

_HORSE_FIELDS = ("birth_year", "sex", "sire", "dam")
_ENTRY_FIELDS = (
    "jockey",
    "trainer",
    "weight",
    "odds",
    "post_position",
    "result_position",
)


def _now() -> str:
    """Devuelve la fecha y hora actual en UTC en formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_name(name: str | None) -> str:
    """Recorta el nombre y colapsa los espacios internos."""
    return " ".join((name or "").split())


def name_key(name: str | None) -> str:
    """Clave de identidad de un caballo: nombre limpio, NFC y ``casefold``.

    ``casefold`` trata mayúsculas Unicode (Á/á, Ñ/ñ), a diferencia de la
    colación ``NOCASE`` de SQLite, que solo cubre ASCII.
    """
    return unicodedata.normalize("NFC", _clean_name(name)).casefold()


def _resolve_path(db_path: str | None) -> str:
    """Devuelve la ruta de la base de datos, creando la carpeta si hace falta."""
    path = db_path or DEFAULT_DB_PATH
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def get_connection(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    """Abre una conexión con claves foráneas activas y filas tipo diccionario.

    Hace ``commit`` al salir sin errores y ``rollback`` si ocurre una excepción.
    """
    conn = sqlite3.connect(_resolve_path(db_path))
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


def init_db(db_path: str | None = None) -> str:
    """Crea las tablas si no existen. Es idempotente.

    Args:
        db_path: ruta del archivo SQLite. Si es ``None`` se usa
            ``HORSE_DB_PATH`` o ``data/horse_analytics.db``.

    Returns:
        La ruta efectiva de la base de datos.
    """
    path = _resolve_path(db_path)
    with get_connection(path) as conn:
        conn.executescript(_SCHEMA)
    logger.debug("Base de datos inicializada en %s", path)
    return path


def _upsert_horse(conn: sqlite3.Connection, name: str, **fields: Any) -> int:
    """Inserta o actualiza un caballo usando una conexión abierta.

    Los campos con valor ``None`` no sobrescriben datos ya guardados.
    """
    clean_name = _clean_name(name)
    if not clean_name:
        raise ValueError("El nombre del caballo no puede estar vacío")
    key = name_key(clean_name)

    values = [fields.get(f) for f in _HORSE_FIELDS]
    conn.execute(
        """
        INSERT INTO horses (name, name_key, birth_year, sex, sire, dam, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name_key) DO UPDATE SET
            birth_year = COALESCE(excluded.birth_year, horses.birth_year),
            sex = COALESCE(excluded.sex, horses.sex),
            sire = COALESCE(excluded.sire, horses.sire),
            dam = COALESCE(excluded.dam, horses.dam),
            last_updated = excluded.last_updated
        """,
        (clean_name, key, *values, _now()),
    )
    row = conn.execute("SELECT id FROM horses WHERE name_key = ?", (key,)).fetchone()
    return int(row["id"])


def upsert_horse(
    name: str,
    birth_year: int | None = None,
    sex: str | None = None,
    sire: str | None = None,
    dam: str | None = None,
    db_path: str | None = None,
) -> int:
    """Inserta un caballo o actualiza el existente (misma :func:`name_key`).

    Los argumentos en ``None`` conservan el valor previo en la base de datos,
    así nunca se borran datos conocidos por falta de información.

    Returns:
        El ``id`` del caballo.
    """
    with get_connection(db_path) as conn:
        return _upsert_horse(
            conn, name, birth_year=birth_year, sex=sex, sire=sire, dam=dam
        )


def _race_key(race: dict[str, Any]) -> tuple[str, str, int]:
    """Valida y devuelve la clave (fecha, hipódromo, número) de una carrera.

    Raises:
        ValueError: si falta algún componente; sin clave completa no se puede
            distinguir una carrera de otra y se mezclarían inscripciones.
    """
    date = str(race.get("date") or "").strip()
    track = _clean_name(race.get("track"))
    number = race.get("race_number")
    if not date or not track or number is None or str(number).strip() == "":
        raise ValueError(
            "La carrera necesita 'date', 'track' y 'race_number': "
            f"{ {k: race.get(k) for k in ('date', 'track', 'race_number')} }"
        )
    try:
        return date, track, int(number)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'race_number' no es un entero: {number!r}") from exc


def _upsert_race(conn: sqlite3.Connection, race: dict[str, Any]) -> int:
    """Inserta o actualiza de forma atómica una carrera por fecha, hipódromo y número.

    ``distance`` y ``surface`` solo se actualizan si llegan con valor.
    """
    key = _race_key(race)
    conn.execute(
        """
        INSERT INTO races (date, track, distance, surface, race_number)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date, track, race_number) DO UPDATE SET
            distance = COALESCE(excluded.distance, races.distance),
            surface = COALESCE(excluded.surface, races.surface)
        """,
        (key[0], key[1], race.get("distance"), race.get("surface"), key[2]),
    )
    row = conn.execute(
        "SELECT id FROM races WHERE date = ? AND track = ? AND race_number = ?", key
    ).fetchone()
    return int(row["id"])


def upsert_race(race: dict[str, Any], db_path: str | None = None) -> int:
    """Inserta o actualiza una carrera.

    Args:
        race: diccionario con ``date``, ``track``, ``race_number``
            (obligatorios) y, opcionalmente, ``distance`` y ``surface``.

    Returns:
        El ``id`` de la carrera.

    Raises:
        ValueError: si falta fecha, hipódromo o número de carrera.
    """
    with get_connection(db_path) as conn:
        return _upsert_race(conn, race)


def save_entries(
    race: dict[str, Any],
    entries: list[dict[str, Any]],
    db_path: str | None = None,
) -> int:
    """Guarda los participantes de una carrera en una sola transacción.

    Crea la carrera y los caballos si no existen. Si un caballo ya estaba
    inscrito en esa carrera, actualiza su inscripción. Las entradas sin
    ``horse_name`` se omiten con un warning.

    Args:
        race: datos de la carrera (ver :func:`upsert_race`).
        entries: lista de diccionarios con ``horse_name`` y, opcionalmente,
            ``jockey``, ``trainer``, ``weight``, ``odds``, ``post_position``
            y ``result_position``.

    Returns:
        Número de inscripciones guardadas.

    Raises:
        ValueError: si la carrera no tiene clave completa (no se guarda nada).
    """
    saved = 0
    with get_connection(db_path) as conn:
        race_id = _upsert_race(conn, race)
        for entry in entries:
            name = (entry.get("horse_name") or "").strip()
            if not name:
                logger.warning("Entrada sin nombre de caballo omitida: %s", entry)
                continue
            horse_id = _upsert_horse(
                conn, name, **{f: entry.get(f) for f in _HORSE_FIELDS}
            )
            values = [entry.get(f) for f in _ENTRY_FIELDS]
            conn.execute(
                """
                INSERT INTO entries (race_id, horse_id, jockey, trainer, weight,
                                     odds, post_position, result_position)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(race_id, horse_id) DO UPDATE SET
                    jockey = COALESCE(excluded.jockey, entries.jockey),
                    trainer = COALESCE(excluded.trainer, entries.trainer),
                    weight = COALESCE(excluded.weight, entries.weight),
                    odds = COALESCE(excluded.odds, entries.odds),
                    post_position = COALESCE(excluded.post_position, entries.post_position),
                    result_position = COALESCE(excluded.result_position, entries.result_position)
                """,
                (race_id, horse_id, *values),
            )
            saved += 1
    return saved


def save_enrichment(
    horse_id: int,
    source: str,
    data: dict[str, Any],
    db_path: str | None = None,
) -> int:
    """Guarda datos externos de un caballo como JSON.

    Returns:
        El ``id`` del registro de enriquecimiento.
    """
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO enrichment (horse_id, source, data_json, fetched_at)
            VALUES (?, ?, ?, ?)
            """,
            (horse_id, source, json.dumps(data, ensure_ascii=False), _now()),
        )
        return int(cur.lastrowid)


def get_horse(name: str, db_path: str | None = None) -> dict[str, Any] | None:
    """Devuelve los datos de un caballo por nombre, o ``None`` si no existe."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM horses WHERE name_key = ?", (name_key(name),)
        ).fetchone()
    return dict(row) if row else None


def get_horse_history(name: str, db_path: str | None = None) -> dict[str, Any]:
    """Devuelve el historial completo de un caballo.

    Returns:
        Diccionario con:

        - ``horse``: datos del caballo o ``None`` si no existe.
        - ``entries``: carreras en las que participó (más recientes primero),
          con los datos de la carrera incluidos.
        - ``enrichment``: registros externos con ``data`` ya decodificado.
    """
    horse = get_horse(name, db_path)
    if horse is None:
        return {"horse": None, "entries": [], "enrichment": []}

    with get_connection(db_path) as conn:
        entries = conn.execute(
            """
            SELECT r.date, r.track, r.distance, r.surface, r.race_number,
                   e.jockey, e.trainer, e.weight, e.odds, e.post_position,
                   e.result_position
            FROM entries e
            JOIN races r ON r.id = e.race_id
            WHERE e.horse_id = ?
            ORDER BY r.date DESC, r.race_number DESC
            """,
            (horse["id"],),
        ).fetchall()
        enrichment = conn.execute(
            """
            SELECT source, data_json, fetched_at
            FROM enrichment
            WHERE horse_id = ?
            ORDER BY fetched_at DESC, id DESC
            """,
            (horse["id"],),
        ).fetchall()

    return {
        "horse": horse,
        "entries": [dict(r) for r in entries],
        "enrichment": [
            {
                "source": r["source"],
                "data": json.loads(r["data_json"]),
                "fetched_at": r["fetched_at"],
            }
            for r in enrichment
        ],
    }
