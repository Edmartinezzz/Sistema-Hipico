"""Generador de gavetas sintéticas en PDF (para pruebas y demostración).

Todos los nombres son ficticios. El PDF imita un programa de carreras real:
encabezado con hipódromo y fecha, un título «Carrera N» por carrera y una
tabla con bordes por carrera. Por defecto la última carrera empieza al final de
la página 1 para que su tabla se parta entre dos páginas (sin repetir el
encabezado), como ocurre en muchas gavetas.

Uso desde la terminal::

    python -m src.sample_data data/samples/gaveta_ejemplo.pdf
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)

DEFAULT_TRACK = "Hipódromo Sintético de Prueba"
DEFAULT_DATE = "2026-01-15"

DEFAULT_HEADERS: dict[str, str] = {
    "post_position": "#",
    "horse_name": "Caballo",
    "jockey": "Jinete",
    "trainer": "Entrenador",
    "weight": "Peso",
    "record": "Récord",
    "odds": "Cuota",
}


def _horse(post, name, jockey, trainer, weight, record, odds) -> dict[str, Any]:
    return {
        "post_position": post,
        "horse_name": name,
        "jockey": jockey,
        "trainer": trainer,
        "weight": weight,
        "record": record,
        "odds": odds,
    }


DEFAULT_RACES: list[dict[str, Any]] = [
    {
        "race_number": 1,
        "distance": "1200 m",
        "surface": "Arena",
        "horses": [
            _horse(1, "Relámpago Azul", "J. Pérez", "M. Rojas", "54", "12-4-3-2", "5-2"),
            _horse(2, "Brisa del Ávila", "L. Gómez", "A. Díaz", "52", "8-1-2-2", "7/2"),
            _horse(3, "Tormenta Criolla", "R. Silva", "M. Rojas", "56", "15-5-2-3", "3.5"),
            _horse(4, "Pólvora Fina", "C. Mora", "P. León", "53", "6-0-1-1", "10-1"),
            _horse(5, "Lucero Real", "E. Vera", "A. Díaz", "54", "10-2-3-1", "6-1"),
            _horse(6, "Viento Sur", "F. Ruiz", "J. Castro", "55", "4-0-0-1", "NADA"),
        ],
    },
    {
        "race_number": 2,
        "distance": "1600 m",
        "surface": "Grama",
        "horses": [
            _horse(1, "Caribeño", "J. Pérez", "J. Castro", "56", "20-6-4-3", "2-1"),
            _horse(2, "Niña Bonita", "L. Gómez", "M. Rojas", "52", "9-2-1-2", "9-2"),
            _horse(3, "Sol de Oriente", "R. Silva", "P. León", "54", "14-3-3-3", "4-1"),
            _horse(4, "Gran Sabana", "C. Mora", "A. Díaz", "55", "7-1-1-0", "12-1"),
            _horse(5, "Médanos", "E. Vera", "J. Castro", "53", "11-2-2-2", "8-1"),
            _horse(6, "Araguaney", "F. Ruiz", "M. Rojas", "54", "5-0-1-0", "20-1"),
            _horse(7, "Chubasco", "D. Paz", "P. León", "56", "16-4-2-4", "5-1"),
            _horse(8, "Cumbre Andina", "H. Luna", "A. Díaz", "52", "3-0-0-0", "30-1"),
            _horse(9, "Faro del Norte", "I. Sosa", "J. Castro", "55", "13-3-1-2", "6-1"),
            _horse(10, "Mar de Plata", "K. Rey", "M. Rojas", "53", "8-1-2-1", "15-1"),
            _horse(11, "Ñandú Veloz", "N. Toro", "P. León", "54", "10-2-1-3", "10-1"),
            _horse(12, "Orquídea", "O. Lara", "A. Díaz", "51", "6-1-0-2", "25-1"),
        ],
    },
]


def create_sample_gaveta(
    path: str | Path,
    races: list[dict[str, Any]] | None = None,
    track: str | None = DEFAULT_TRACK,
    date: str | None = DEFAULT_DATE,
    headers: dict[str, str] | None = None,
    gap_before_last_race_cm: float = 10.0,
) -> Path:
    """Crea una gaveta sintética en PDF y devuelve su ruta.

    Args:
        path: archivo PDF de salida (se crean las carpetas necesarias).
        races: lista de carreras con ``race_number``, ``distance``, ``surface``
            y ``horses`` (diccionarios con las claves de ``headers``).
        track: nombre del hipódromo; ``None`` omite la línea.
        date: fecha ISO; ``None`` omite la línea.
        headers: mapeo campo → texto de columna. Define el orden de columnas.
        gap_before_last_race_cm: espacio antes de la última carrera para que su
            tabla se parta entre páginas. Usar ``0`` para no forzarlo.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    races = DEFAULT_RACES if races is None else races
    headers = headers or DEFAULT_HEADERS
    styles = getSampleStyleSheet()

    story: list[Any] = [Paragraph("Programa Oficial de Carreras (sintético)", styles["Title"])]
    if track:
        story.append(Paragraph(f"Hipódromo: {track}", styles["Normal"]))
    if date:
        story.append(Paragraph(f"Fecha: {date}", styles["Normal"]))
    story.append(Spacer(1, 0.4 * cm))

    for index, race in enumerate(races):
        if index == len(races) - 1 and index > 0 and gap_before_last_race_cm > 0:
            story.append(Spacer(1, gap_before_last_race_cm * cm))
        details = " — ".join(
            str(race[k]) for k in ("distance", "surface") if race.get(k)
        )
        title = f"Carrera {race['race_number']}" + (f" — {details}" if details else "")
        story.append(Paragraph(title, styles["Heading2"]))

        rows = [list(headers.values())]
        for horse in race["horses"]:
            rows.append(["" if horse.get(k) is None else str(horse.get(k)) for k in headers])
        table = Table(rows, repeatRows=0)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 0.5 * cm))

    SimpleDocTemplate(str(path), pagesize=A4).build(story)
    logger.info("Gaveta sintética creada en %s", path)
    return path


def create_empty_pdf(path: str | Path, text: str = "Documento sin tablas") -> Path:
    """Crea un PDF que solo contiene texto (útil para probar el caso sin tablas)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    SimpleDocTemplate(str(path), pagesize=A4).build([Paragraph(text, styles["Normal"])])
    return path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    destino = sys.argv[1] if len(sys.argv) > 1 else "data/samples/gaveta_ejemplo.pdf"
    create_sample_gaveta(destino)
