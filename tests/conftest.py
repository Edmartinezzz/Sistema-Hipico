"""Fixtures compartidas: PDFs de gaveta sintéticos generados con reportlab."""

from pathlib import Path

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ENCABEZADO = ["Caballo", "Jinete", "Entrenador", "Peso", "Cuota", "PP", "Record"]

FILAS_PAGINA_1 = [
    ["Relampago", "J. Perez", "M. Lopez", "55", "7-2", "1", "3-2-1"],
    ["Trueno", "A. Diaz", "M. Lopez", "54", "5/1", "2", "2-1-0"],
]

# Tabla continuada en página 2 sin encabezado (misma cantidad de columnas).
FILAS_PAGINA_2 = [
    ["Cometa", "L. Ruiz", "S. Gil", "52", "3.5", "3", "1-0-0"],
]

# Segunda carrera con alias alternativos de encabezado.
ENCABEZADO_ALT = ["Race", "Horse", "Jockey", "Trainer", "ML", "Post", "WPS"]
FILAS_CARRERA_2 = [
    ["2", "Vendaval", "C. Mora", "J. Ortiz", "4-1", "4", "0-1-1"],
    ["2", "Brisa", "R. Soto", "J. Ortiz", "9-2", "5", "5-1-0"],
]


def _tabla(filas: list[list[str]]) -> Table:
    t = Table(filas)
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
            ]
        )
    )
    return t


def crear_pdf_gaveta(path: Path) -> Path:
    """Genera un PDF de gaveta sintético de 3 páginas.

    Página 1: "Carrera 1" + tabla con encabezado y 2 caballos.
    Página 2: tabla continuada sin encabezado (1 caballo más).
    Página 3: "Carrera 2" + tabla con alias alternativos (1 caballo).
    """
    estilos = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    story = [
        Paragraph("Carrera 1", estilos["Title"]),
        Spacer(1, 12),
        _tabla([ENCABEZADO, *FILAS_PAGINA_1]),
        PageBreak(),
        _tabla(FILAS_PAGINA_2),
        PageBreak(),
        Paragraph("Carrera 2", estilos["Title"]),
        Spacer(1, 12),
        _tabla([ENCABEZADO_ALT, *FILAS_CARRERA_2]),
    ]
    doc.build(story)
    return path


@pytest.fixture()
def pdf_gaveta(tmp_path: Path) -> Path:
    """PDF de gaveta sintético en un directorio temporal."""
    return crear_pdf_gaveta(tmp_path / "gaveta.pdf")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """Ruta a una base de datos SQLite temporal."""
    return tmp_path / "hipico.db"
