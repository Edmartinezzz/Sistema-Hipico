"""Extracción de datos estructurados desde una gaveta (programa de carreras) en PDF.

Usa ``pdfplumber`` para localizar las tablas de cada página. Para cada tabla
busca, en el texto que tiene justo encima, el título «Carrera N» (y, si
aparecen, distancia y superficie). Si una tabla no trae fila de encabezado y
tiene el mismo número de columnas que la anterior, se trata como continuación
de la carrera anterior (tablas partidas entre páginas).

El hipódromo y la fecha se leen de líneas «Hipódromo: ...» y «Fecha: ...».
Cualquier dato que no se encuentre queda en ``None``: nunca se inventa.

Los PDF escaneados (imagen) no tienen texto; en ese caso se devuelve ``[]`` con
un warning. El OCR con ``pytesseract`` queda fuera de este sprint.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

import pdfplumber

logger = logging.getLogger(__name__)

# Campo canónico -> textos de encabezado aceptados (ya normalizados con _norm).
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "post_position": (
        "#", "n", "no", "nro", "num", "numero", "pp", "post", "puesto", "programa", "pos",
    ),
    "horse_name": ("caballo", "ejemplar", "horse", "nombre", "caballos", "ejemplares"),
    "jockey": ("jinete", "jockey", "j", "jock", "jinetes"),
    "trainer": ("entrenador", "trainer", "e", "entr", "preparador", "trn"),
    "weight": ("peso", "weight", "kg", "kgs", "lbs", "wgt", "wt"),
    "odds": ("cuota", "odds", "ml", "morning line", "linea", "dividendo", "momio"),
    "record": ("record", "w p s", "wps", "campana", "historial"),
}

_SCRATCHED = {"", "-", "--", "NADA", "SCR", "RET", "RETIRADO", "N/A", "NA"}
_FRACTION_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*[-/:]\s*(\d+(?:[.,]\d+)?)$")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_RACE_RE = re.compile(r"\b(?:carrera|race)\s*(?:n\s*[º°o.]*\s*)?(\d{1,2})\b", re.IGNORECASE)
_TRACK_RE = re.compile(r"hip[óo]dromo\s*:\s*(.+)", re.IGNORECASE)
_DATE_RE = re.compile(
    r"fecha\s*:\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4})", re.IGNORECASE
)
_DISTANCE_RE = re.compile(r"\b(\d{3,4})\s*(m|mts|metros|y|yds|yardas)\b", re.IGNORECASE)
_SURFACE_RE = re.compile(
    r"\b(arena|grama|c[ée]sped|tierra|dirt|turf|sint[ée]tica)\b", re.IGNORECASE
)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _norm(header: Any) -> str:
    """Normaliza un encabezado: sin acentos, minúsculas y solo letras/dígitos/«#»."""
    text = _strip_accents(str(header or "")).lower()
    text = re.sub(r"[^a-z0-9#]+", " ", text)
    return " ".join(text.split())


def _clean(cell: Any) -> str | None:
    """Limpia una celda: une saltos de línea y devuelve ``None`` si queda vacía."""
    if cell is None:
        return None
    text = " ".join(str(cell).split())
    return text or None


def _match_field(header: str) -> str | None:
    if not header:
        return None
    for field, aliases in COLUMN_ALIASES.items():
        if header in aliases:
            return field
    for field, aliases in COLUMN_ALIASES.items():
        if any(len(a) >= 2 and header.startswith(a + " ") for a in aliases):
            return field
    return None


def detect_columns(table: list[list[str]]) -> dict[str, int]:
    """Mapea los nombres de columna de la primera fila a sus índices.

    Tolera variaciones como «Jinete»/«Jockey»/«J.» o «Peso (kg)». Las columnas
    conocidas se devuelven con su nombre canónico (``horse_name``, ``jockey``,
    ``trainer``, ``weight``, ``odds``, ``post_position``, ``record``); las demás
    con su encabezado normalizado (p. ej. ``edad``).

    Returns:
        Diccionario ``{campo: índice}``. Vacío si la primera fila no parece un
        encabezado (no tiene columna de caballo).
    """
    if not table or not table[0]:
        return {}
    mapping: dict[str, int] = {}
    extras: dict[str, int] = {}
    for index, cell in enumerate(table[0]):
        header = _norm(cell)
        field = _match_field(header)
        if field and field not in mapping:
            mapping[field] = index
        elif header:
            extras.setdefault(header.replace(" ", "_"), index)
    if "horse_name" not in mapping:
        return {}
    for key, index in extras.items():
        mapping.setdefault(key, index)
    return mapping


def odds_to_decimal(raw: Any) -> float | None:
    """Convierte una cuota a formato decimal (europeo).

    - Fraccionaria «7-2», «5/1», «9:2» → ``a / b + 1`` (7-2 → 4.5).
    - «EVEN»/«EVS» → 2.0.
    - Número simple «3.5» o «3,5» → se interpreta como cuota decimal (debe ser > 1).
    - «NADA», «SCR», «RET», vacío o texto no reconocido → ``None``.
    """
    text = " ".join(str(raw or "").split()).upper()
    if text in _SCRATCHED:
        return None
    if text in {"EVEN", "EVS", "EVN"}:
        return 2.0
    match = _FRACTION_RE.match(text)
    if match:
        num, den = (float(g.replace(",", ".")) for g in match.groups())
        return num / den + 1 if den > 0 else None
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        value = float(text.replace(",", "."))
        return value if value > 1 else None
    return None


def normalize_odds(raw: str) -> float | None:
    """Convierte una cuota en texto a probabilidad implícita (``1 / cuota_decimal``).

    Ejemplos: «7-2» → 1/4.5 ≈ 0.222; «5/1» → 1/6 ≈ 0.167; «3.5» → 1/3.5 ≈ 0.286;
    «NADA» → ``None``. Ver :func:`odds_to_decimal` para los formatos aceptados.
    """
    decimal = odds_to_decimal(raw)
    return None if decimal is None else 1 / decimal


def _parse_number(raw: Any) -> float | None:
    match = _NUMBER_RE.search(str(raw or ""))
    return float(match.group().replace(",", ".")) if match else None


def _parse_post(raw: Any) -> int | None:
    match = re.match(r"\s*(\d+)", str(raw or ""))
    return int(match.group(1)) if match else None


def _parse_date(raw: str) -> str:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    day, month, year = re.split(r"[/-]", raw)
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _document_meta(text: str) -> dict[str, str | None]:
    track = _TRACK_RE.search(text)
    date = _DATE_RE.search(text)
    return {
        "track": _clean(track.group(1)) if track else None,
        "date": _parse_date(date.group(1)) if date else None,
    }


def _race_header(text: str) -> dict[str, Any] | None:
    """Busca el último «Carrera N» del texto y la distancia/superficie de esa línea."""
    matches = list(_RACE_RE.finditer(text or ""))
    if not matches:
        return None
    last = matches[-1]
    line = text[last.start():].splitlines()[0]
    distance = _DISTANCE_RE.search(line)
    surface = _SURFACE_RE.search(line)
    return {
        "race_number": int(last.group(1)),
        "distance": f"{distance.group(1)} {distance.group(2).lower()}" if distance else None,
        "surface": surface.group(1).capitalize() if surface else None,
    }


def _row_to_horse(row: list[Any], mapping: dict[str, int]) -> dict[str, Any] | None:
    def cell(field: str) -> str | None:
        index = mapping.get(field)
        return _clean(row[index]) if index is not None and index < len(row) else None

    name = cell("horse_name")
    if not name:
        return None
    odds_raw = cell("odds")
    horse: dict[str, Any] = {
        "horse_name": name,
        "jockey": cell("jockey"),
        "trainer": cell("trainer"),
        "weight": _parse_number(cell("weight")),
        "odds_raw": odds_raw,
        "odds": odds_to_decimal(odds_raw),
        "implied_probability": normalize_odds(odds_raw) if odds_raw else None,
        "post_position": _parse_post(cell("post_position")),
        "record": cell("record"),
    }
    for field in mapping:
        if field not in COLUMN_ALIASES:
            horse[field] = cell(field)
    return horse


def _mark_favorites(horses: list[dict[str, Any]]) -> None:
    """Marca como favorito de la línea matinal al caballo de menor cuota en cada carrera."""
    by_race: dict[Any, list[dict[str, Any]]] = {}
    for horse in horses:
        by_race.setdefault(horse["race_number"], []).append(horse)
    for race_horses in by_race.values():
        odds = [h["odds"] for h in race_horses if h["odds"] is not None]
        best = min(odds) if odds else None
        for horse in race_horses:
            horse["morning_line_favorite"] = best is not None and horse["odds"] == best


def extract_races(pdf_path: str) -> list[dict]:
    """Convierte una gaveta en PDF en una lista de caballos (un dict por caballo y carrera).

    Cada diccionario contiene: ``race_number``, ``horse_name``, ``jockey``,
    ``trainer``, ``weight`` (número), ``odds`` (cuota decimal), ``odds_raw``
    (texto original), ``implied_probability``, ``post_position``, ``record``,
    ``morning_line_favorite`` (bool), ``date``, ``track``, ``distance``,
    ``surface``, ``page`` y cualquier columna extra detectada.

    Returns:
        La lista de caballos, o ``[]`` con un warning si el PDF no tiene tablas
        reconocibles.

    Raises:
        FileNotFoundError: si el archivo no existe.
    """
    if not Path(pdf_path).is_file():
        raise FileNotFoundError(f"No existe el PDF: {pdf_path}")

    horses: list[dict[str, Any]] = []
    meta: dict[str, str | None] = {"track": None, "date": None}
    race: dict[str, Any] | None = None
    mapping: dict[str, int] | None = None
    columns: int | None = None
    any_text = False

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            any_text = any_text or bool(page_text.strip())
            if meta["track"] is None or meta["date"] is None:
                page_meta = _document_meta(page_text)
                meta = {k: meta[k] or page_meta.get(k) for k in meta}

            top = 0.0
            for table in page.find_tables():
                x0, table_top, x1, bottom = table.bbox
                above = ""
                if table_top > top:
                    above = page.crop((0, top, page.width, table_top)).extract_text() or ""
                top = bottom
                rows = table.extract()
                if not rows:
                    continue

                header = _race_header(above)
                same_race = header is None or (
                    race is not None and header["race_number"] == race["race_number"]
                )
                if header and same_race and race is not None:
                    race = {**race, **{k: v for k, v in header.items() if v is not None}}
                elif header:
                    race = header

                detected = detect_columns(rows)
                if detected:
                    mapping, columns, data_rows = detected, len(rows[0]), rows[1:]
                elif mapping is not None and len(rows[0]) == columns and same_race:
                    data_rows = rows
                    logger.debug("Tabla de la página %s tratada como continuación", page_number)
                else:
                    logger.warning(
                        "Tabla sin encabezado reconocible en la página %s; se omite", page_number
                    )
                    continue

                if race is None:
                    logger.warning(
                        "Tabla de la página %s sin título «Carrera N»: race_number=None",
                        page_number,
                    )
                for row in data_rows:
                    horse = _row_to_horse(row, mapping)
                    if horse is None:
                        continue
                    horse.update(
                        race_number=race["race_number"] if race else None,
                        distance=race["distance"] if race else None,
                        surface=race["surface"] if race else None,
                        track=meta["track"],
                        date=meta["date"],
                        page=page_number,
                    )
                    horses.append(horse)

    if not horses:
        if not any_text:
            logger.warning("El PDF %s no tiene texto (¿es una imagen escaneada?)", pdf_path)
        logger.warning("No se encontraron tablas de caballos en %s", pdf_path)
        return []

    for horse in horses:
        horse["track"] = horse["track"] or meta["track"]
        horse["date"] = horse["date"] or meta["date"]
    _mark_favorites(horses)
    return horses
