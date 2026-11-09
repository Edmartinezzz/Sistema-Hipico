"""Módulo 1 — Extracción de datos estructurados desde un PDF de gaveta.

Convierte el programa de carreras (gaveta) en una lista de diccionarios
con un registro por caballo participante. Usa ``pdfplumber`` como
extractor principal; tolera tablas partidas en varias páginas y varios
nombres de columna ("Jinete"/"Jockey"/"J.", "Cuota"/"Odds"/"ML", etc.).

Si el PDF es una imagen escaneada (sin texto extraíble), se registra un
warning: la ruta OCR requiere ``pytesseract`` + ``pdf2image`` y el
binario Tesseract del sistema operativo, que no se instala por defecto
(ver README, sección "PDFs escaneados").
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pdfplumber

from src.harville_model import fractional_to_decimal

logger = logging.getLogger(__name__)

# Alias tolerados por columna lógica (minúsculas, sin acentos ya limpiados).
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "race_number": ("carrera", "race", "race no", "race #", "no.", "#", "r."),
    "horse_name": (
        "caballo", "horse", "horse name", "nombre", "ejemplar", "name",
        "prog", "program", "no prog",
    ),
    "jockey": ("jinete", "jockey", "j.", "jk", "monta"),
    "trainer": ("entrenador", "trainer", "e.", "tr", "preparador"),
    "weight": ("peso", "weight", "wt", "kg", "lbs", "lb", "carga"),
    "odds": (
        "cuota", "odds", "m/l", "m-l", "ml", "m.l.", "morning line", "linea",
    ),
    "post_position": (
        "pp", "post", "post position", "puesto", "partidor", "gate",
        "draw", "salida",
    ),
    "record": (
        "record", "récord", "w-p-s", "wps", "w/p/s", "historial", "stats",
    ),
}

_ACCENTS = str.maketrans("áéíóúñü", "aeiounu")


def _clean(text: Any) -> str:
    """Normaliza texto de celda: minúsculas, sin acentos, espacios simples."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text).strip().lower().translate(_ACCENTS))


def detect_columns(table: list[list[str]]) -> dict[str, int]:
    """Mapea nombres de columna lógicos a índices de la tabla.

    Busca en las primeras 3 filas la que mejor coincida con los alias
    conocidos; devuelve ``{nombre_lógico: índice}`` solo para las
    columnas detectadas. Si ninguna fila parece encabezado, devuelve
    ``{}``.
    """
    mejor: dict[str, int] = {}
    for fila in table[:3]:
        candidatos: dict[str, int] = {}
        for idx, celda in enumerate(fila):
            texto = _clean(celda)
            if not texto:
                continue
            for logico, aliases in _COLUMN_ALIASES.items():
                if logico in candidatos:
                    continue
                for alias in aliases:
                    if texto == alias or texto.startswith(alias + " ") or (
                        len(alias) > 2 and alias in texto
                    ):
                        candidatos[logico] = idx
                        break
        if len(candidatos) > len(mejor):
            mejor = candidatos
    return mejor


def normalize_odds(raw: str) -> float | None:
    """Convierte una cuota cruda a cuota decimal.

    Formatos soportados: fraccionarios UK ("7-2", "5/1"), decimales
    ("3.5", "9/2"), pares ("EVS"). Devuelve ``None`` si no es parseable
    ("NADA", "SCRATCHED", vacío).
    """
    return fractional_to_decimal(raw)


def _fila_a_registro(
    fila: list[str],
    columnas: dict[str, int],
    race_number: int | None,
) -> dict[str, Any] | None:
    """Convierte una fila de tabla en un registro de caballo.

    Devuelve ``None`` si la fila no contiene nombre de caballo (filas
    vacías, notas al pie, encabezados repetidos).
    """

    def celda(clave: str) -> str:
        idx = columnas.get(clave)
        if idx is None or idx >= len(fila):
            return ""
        return str(fila[idx] or "").strip()

    nombre = celda("horse_name")
    if not nombre or _clean(nombre) in _COLUMN_ALIASES["horse_name"]:
        return None

    registro: dict[str, Any] = {
        "race_number": race_number,
        "horse_name": nombre,
        "jockey": celda("jockey") or None,
        "trainer": celda("trainer") or None,
        "weight": _parse_float(celda("weight")),
        "odds": normalize_odds(celda("odds")),
        "post_position": _parse_int(celda("post_position")),
        "record": celda("record") or None,
        "morning_line_favorite": _es_favorito(celda("odds"), celda("record")),
    }
    # Conservar cualquier columna extra detectada como "extra_<idx>".
    usados = set(columnas.values())
    for idx, valor in enumerate(fila):
        if idx not in usados and valor and str(valor).strip():
            registro[f"extra_{idx}"] = str(valor).strip()
    return registro


def _parse_float(texto: str) -> float | None:
    try:
        return float(re.sub(r"[^\d.\-]", "", texto))
    except ValueError:
        return None


def _parse_int(texto: str) -> int | None:
    valor = _parse_float(texto)
    return int(valor) if valor is not None else None


def _es_favorito(odds_texto: str, record_texto: str) -> bool:
    """Heurística de favorito de la línea matutina ("*", "F", favorito)."""
    conjunto = f"{odds_texto} {record_texto}".lower()
    return any(marca in conjunto for marca in ("*", "fav", "favorite"))


def _numero_carrera_desde_texto(texto: str) -> int | None:
    """Detecta "Carrera 3" / "Race 5" en el texto de una página."""
    match = re.search(
        r"(?:carrera|race)\s*(?:no\.?|#|n[úu]mero)?\s*(\d+)",
        texto.lower(),
    )
    return int(match.group(1)) if match else None


def extract_races(pdf_path: str) -> list[dict]:
    """Extrae todos los caballos del PDF de gaveta.

    Devuelve una lista de dicts (uno por caballo por carrera) con las
    claves mínimas ``race_number``, ``horse_name``, ``jockey``,
    ``trainer``, ``weight``, ``odds``, ``post_position``, ``record`` y
    ``morning_line_favorite``. Columnas no reconocidas se conservan como
    ``extra_<idx>``. Devuelve ``[]`` con warning si el PDF no contiene
    tablas o es una imagen escaneada.
    """
    registros: list[dict] = []
    race_number: int | None = None
    columnas_activas: dict[str, int] = {}

    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                logger.warning("El PDF no tiene páginas: %s", pdf_path)
                return []
            for pagina in pdf.pages:
                texto = pagina.extract_text() or ""
                if not texto.strip() and not pagina.extract_tables():
                    logger.warning(
                        "Página %d sin texto extraíble (¿PDF escaneado?). "
                        "Instala Tesseract para la ruta OCR (ver README).",
                        pagina.page_number,
                    )
                    continue
                n = _numero_carrera_desde_texto(texto)
                if n is not None:
                    race_number = n
                    columnas_activas = {}

                for tabla in pagina.extract_tables() or []:
                    columnas = detect_columns(tabla)
                    if columnas:
                        columnas_activas = columnas
                        inicio = _fila_encabezado(tabla, columnas)
                    elif columnas_activas and tabla and len(tabla[0]) == max(
                        columnas_activas.values()
                    ) + 1:
                        # Tabla continuada de la página anterior (sin encabezado).
                        columnas, inicio = columnas_activas, 0
                    else:
                        continue
                    for fila in tabla[inicio:]:
                        registro = _fila_a_registro(fila, columnas, race_number)
                        if registro:
                            registros.append(registro)
    except Exception:
        logger.exception("Error procesando el PDF %s", pdf_path)
        return []

    if not registros:
        logger.warning("No se encontraron caballos en el PDF %s", pdf_path)
    return registros


def _fila_encabezado(tabla: list[list[str]], columnas: dict[str, int]) -> int:
    """Índice de la primera fila de datos (tras el encabezado)."""
    for i, fila in enumerate(tabla[:3]):
        limpia = {_clean(c) for c in fila if c}
        aliases = {
            a for aliases in _COLUMN_ALIASES.values() for a in aliases
        }
        if limpia & aliases:
            return i + 1
    return 0
