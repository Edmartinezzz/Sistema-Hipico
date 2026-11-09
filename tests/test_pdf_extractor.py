"""Tests del Módulo 1 — extracción de PDFs de gaveta."""

from src.pdf_extractor import detect_columns, extract_races, normalize_odds


def test_extract_races_caballos(pdf_gaveta):
    registros = extract_races(str(pdf_gaveta))
    nombres = [r["horse_name"] for r in registros]
    assert nombres == ["Relampago", "Trueno", "Cometa", "Vendaval", "Brisa"]


def test_extract_races_campos(pdf_gaveta):
    registros = extract_races(str(pdf_gaveta))
    relampago = next(r for r in registros if r["horse_name"] == "Relampago")
    assert relampago["race_number"] == 1
    assert relampago["jockey"] == "J. Perez"
    assert relampago["trainer"] == "M. Lopez"
    assert relampago["weight"] == 55.0
    assert relampago["odds"] == 4.5
    assert relampago["post_position"] == 1
    assert relampago["record"] == "3-2-1"
    assert relampago["morning_line_favorite"] is False


def test_extract_races_tabla_continuada(pdf_gaveta):
    """La tabla sin encabezado de la página 2 se asocia a la Carrera 1."""
    registros = extract_races(str(pdf_gaveta))
    cometa = next(r for r in registros if r["horse_name"] == "Cometa")
    assert cometa["race_number"] == 1
    assert cometa["odds"] == 3.5


def test_extract_races_alias_alternativos(pdf_gaveta):
    """La Carrera 2 usa encabezados en inglés (Horse/Jockey/ML/Post/WPS)."""
    registros = extract_races(str(pdf_gaveta))
    vendaval = next(r for r in registros if r["horse_name"] == "Vendaval")
    assert vendaval["race_number"] == 2
    assert vendaval["jockey"] == "C. Mora"
    assert vendaval["trainer"] == "J. Ortiz"
    assert vendaval["odds"] == 5.0
    assert vendaval["post_position"] == 4
    assert vendaval["record"] == "0-1-1"


def test_extract_races_pdf_sin_tablas(tmp_path):
    """Un PDF de solo texto devuelve [] sin romper el pipeline."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    ruta = tmp_path / "sin_tablas.pdf"
    doc = SimpleDocTemplate(str(ruta), pagesize=letter)
    doc.build([Paragraph("Solo texto, sin tablas.", getSampleStyleSheet()["Normal"])])
    assert extract_races(str(ruta)) == []


def test_detect_columns():
    tabla = [
        ["Caballo", "Jinete", "Entrenador", "Peso", "Cuota", "PP", "Record"],
        ["Relampago", "J. Perez", "M. Lopez", "55", "7-2", "1", "3-2-1"],
    ]
    columnas = detect_columns(tabla)
    assert columnas["horse_name"] == 0
    assert columnas["jockey"] == 1
    assert columnas["trainer"] == 2
    assert columnas["weight"] == 3
    assert columnas["odds"] == 4
    assert columnas["post_position"] == 5
    assert columnas["record"] == 6


def test_detect_columns_variaciones():
    """Tolera variaciones: Jockey/J./Entrenador/M-L."""
    tabla = [["No.", "Horse", "J.", "Entrenador", "M-L", "Post"]]
    columnas = detect_columns(tabla)
    assert columnas["jockey"] == 2
    assert columnas["odds"] == 4
    assert columnas["post_position"] == 5


def test_normalize_odds():
    assert normalize_odds("7-2") == 4.5
    assert normalize_odds("5/1") == 6.0
    assert normalize_odds("3.5") == 3.5
    assert normalize_odds("EVS") == 2.0
    assert normalize_odds("NADA") is None
    assert normalize_odds("") is None
    assert normalize_odds("SCR") is None
