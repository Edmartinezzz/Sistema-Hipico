"""Pruebas del extractor de gavetas (src/pdf_extractor.py) con PDF sintéticos."""

import pytest

from src import pdf_extractor
from src.sample_data import DEFAULT_RACES, create_empty_pdf, create_sample_gaveta


@pytest.fixture(scope="module")
def gaveta(tmp_path_factory):
    path = tmp_path_factory.mktemp("pdf") / "gaveta.pdf"
    create_sample_gaveta(path)
    return pdf_extractor.extract_races(str(path))


def test_extrae_todos_los_caballos(gaveta):
    esperados = [(r["race_number"], h["horse_name"]) for r in DEFAULT_RACES for h in r["horses"]]
    assert [(h["race_number"], h["horse_name"]) for h in gaveta] == esperados


def test_tabla_partida_entre_paginas_sigue_en_la_misma_carrera(gaveta):
    carrera2 = [h for h in gaveta if h["race_number"] == 2]
    paginas = {h["page"] for h in carrera2}
    assert paginas == {1, 2}
    assert len(carrera2) == 12
    assert carrera2[-1]["horse_name"] == "Orquídea"


def test_campos_parseados(gaveta):
    primero = gaveta[0]
    assert primero["post_position"] == 1
    assert primero["jockey"] == "J. Pérez"
    assert primero["trainer"] == "M. Rojas"
    assert primero["weight"] == 54.0
    assert primero["record"] == "12-4-3-2"
    assert primero["odds_raw"] == "5-2"
    assert primero["odds"] == pytest.approx(3.5)
    assert primero["implied_probability"] == pytest.approx(1 / 3.5)


def test_metadatos_de_carrera_y_documento(gaveta):
    primero, ultimo = gaveta[0], gaveta[-1]
    assert primero["track"] == "Hipódromo Sintético de Prueba"
    assert primero["date"] == "2026-01-15"
    assert (primero["distance"], primero["surface"]) == ("1200 m", "Arena")
    assert (ultimo["distance"], ultimo["surface"]) == ("1600 m", "Grama")


def test_cuota_nada_queda_en_none(gaveta):
    viento = next(h for h in gaveta if h["horse_name"] == "Viento Sur")
    assert viento["odds"] is None
    assert viento["implied_probability"] is None
    assert viento["morning_line_favorite"] is False


def test_favorito_de_la_linea_matinal(gaveta):
    favoritos = {h["race_number"]: h["horse_name"] for h in gaveta if h["morning_line_favorite"]}
    assert favoritos == {1: "Tormenta Criolla", 2: "Caribeño"}


def test_encabezados_alternativos_y_columnas_extra(tmp_path):
    headers = {
        "post_position": "Nº",
        "horse_name": "Ejemplar",
        "jockey": "J.",
        "weight": "Peso (kg)",
        "odds": "ML",
        "edad": "Edad",
    }
    races = [{
        "race_number": 7,
        "horses": [
            {"post_position": "1A", "horse_name": "Uno", "jockey": "A", "weight": "54,5",
             "odds": "9:2", "edad": "4"},
            {"post_position": 2, "horse_name": "Dos", "jockey": "B", "weight": "55",
             "odds": "EVEN", "edad": "5"},
        ],
    }]
    path = create_sample_gaveta(tmp_path / "alt.pdf", races=races, track=None, date=None,
                                headers=headers)
    horses = pdf_extractor.extract_races(str(path))
    assert [h["horse_name"] for h in horses] == ["Uno", "Dos"]
    uno = horses[0]
    assert uno["race_number"] == 7
    assert uno["post_position"] == 1
    assert uno["weight"] == 54.5
    assert uno["odds"] == pytest.approx(5.5)
    assert uno["edad"] == "4"
    assert uno["trainer"] is None and uno["record"] is None
    assert uno["track"] is None and uno["date"] is None
    assert horses[1]["morning_line_favorite"] is True


def test_pdf_sin_tablas_devuelve_lista_vacia(tmp_path, caplog):
    path = create_empty_pdf(tmp_path / "vacio.pdf")
    with caplog.at_level("WARNING"):
        assert pdf_extractor.extract_races(str(path)) == []
    assert "No se encontraron tablas" in caplog.text


def test_pdf_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        pdf_extractor.extract_races(str(tmp_path / "no.pdf"))


@pytest.mark.parametrize(
    "raw, esperado",
    [
        ("7-2", 1 / 4.5),
        ("5/1", 1 / 6),
        ("9:2", 1 / 5.5),
        ("3.5", 1 / 3.5),
        ("3,5", 1 / 3.5),
        (" 2 - 1 ", 1 / 3),
        ("EVEN", 0.5),
        ("NADA", None),
        ("SCR", None),
        ("", None),
        (None, None),
        ("abc", None),
        ("1", None),
        ("5-0", None),
    ],
)
def test_normalize_odds(raw, esperado):
    resultado = pdf_extractor.normalize_odds(raw)
    if esperado is None:
        assert resultado is None
    else:
        assert resultado == pytest.approx(esperado)


def test_detect_columns_variantes():
    tabla = [[
        "N°", "CABALLO", "Jockey", "Entrenador", "Peso Kg", "Cuota ML", "Récord W-P-S", "Edad",
    ]]
    assert pdf_extractor.detect_columns(tabla) == {
        "post_position": 0,
        "horse_name": 1,
        "jockey": 2,
        "trainer": 3,
        "weight": 4,
        "odds": 5,
        "record": 6,
        "edad": 7,
    }


def test_detect_columns_sin_columna_de_caballo():
    assert pdf_extractor.detect_columns([["1", "Relámpago", "J. Pérez"]]) == {}
    assert pdf_extractor.detect_columns([]) == {}


def _pdf_continuacion(path, titulo_pagina_2):
    """Página 1: fecha + Carrera 1 con encabezados. Página 2: hipódromo + tabla sin encabezados."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

    estilos = getSampleStyleSheet()
    bordes = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))])
    tabla1 = Table([["#", "Caballo", "Jinete", "Cuota"], ["1", "Alfa", "J. Uno", "2-1"],
                    ["2", "Beta", "J. Dos", "3-1"]])
    tabla2 = Table([["3", "Gamma", "J. Tres", "5-1"], ["4", "Delta", "J. Cuatro", "8-1"]])
    tabla1.setStyle(bordes)
    tabla2.setStyle(bordes)
    historia = [Paragraph("Fecha: 15/01/2026", estilos["Normal"]),
                Paragraph("Carrera 1 — 1200 m", estilos["Heading2"]), tabla1, PageBreak(),
                Paragraph("Hipódromo: Pista de Prueba", estilos["Normal"])]
    if titulo_pagina_2:
        historia.append(Paragraph(titulo_pagina_2, estilos["Heading2"]))
    historia.append(tabla2)
    SimpleDocTemplate(str(path), pagesize=letter).build(historia)
    return str(path)


@pytest.mark.parametrize("titulo", [None, "Carrera 1 (continuación)"])
def test_continuacion_sin_encabezados_con_o_sin_titulo_repetido(tmp_path, titulo):
    caballos = pdf_extractor.extract_races(_pdf_continuacion(tmp_path / "cont.pdf", titulo))
    assert [c["horse_name"] for c in caballos] == ["Alfa", "Beta", "Gamma", "Delta"]
    assert {c["race_number"] for c in caballos} == {1}
    assert {c["page"] for c in caballos} == {1, 2}
    assert caballos[-1]["distance"] == "1200 m"


def test_fecha_e_hipodromo_en_paginas_distintas(tmp_path):
    caballos = pdf_extractor.extract_races(_pdf_continuacion(tmp_path / "meta.pdf", None))
    assert {(c["date"], c["track"]) for c in caballos} == {("2026-01-15", "Pista de Prueba")}


def test_tabla_sin_encabezados_bajo_otra_carrera_se_omite(tmp_path):
    caballos = pdf_extractor.extract_races(_pdf_continuacion(tmp_path / "otra.pdf", "Carrera 2"))
    assert [c["horse_name"] for c in caballos] == ["Alfa", "Beta"]


def test_titulo_repetido_completa_datos_de_la_carrera(tmp_path):
    pdf = _pdf_continuacion(tmp_path / "det.pdf", "Carrera 1 — 1200 m — Arena")
    caballos = pdf_extractor.extract_races(pdf)
    assert len({c["surface"] for c in caballos}) == 1
    assert caballos[0]["surface"] is not None
    assert {c["distance"] for c in caballos} == {"1200 m"}


def test_extract_races_formato_movil_hipismo(tmp_path):
    from src.sample_data import create_sample_movil

    caballos = pdf_extractor.extract_races(str(create_sample_movil(tmp_path / "movil.pdf")))
    assert [c["race_number"] for c in caballos] == [1, 1, 1, 2, 2]
    primero = caballos[0]
    assert primero["horse_name"] == "QUEEN DEMO"
    assert (primero["jockey"], primero["trainer"], primero["weight"]) == (
        "J. Pérez", "M. Rojas", 55.0
    )
    assert (primero["record"], primero["post_position"], primero["stud"]) == (
        "20-5-3-2", 1, "Reina Morena"
    )
    assert (primero["sire"], primero["dam"]) == ("Trueno Real", "Brisa Fina")
    assert (primero["date"], primero["track"], primero["distance"], primero["surface"]) == (
        "2026-11-08", "La Rinconada", "1200 m", "Arena"
    )
    assert caballos[1]["weight"] == 54.5
    assert caballos[3]["horse_name"] == "ÁGUILA SINTÉTICA" and caballos[3]["distance"] == "1600 m"
    assert all(c["odds"] is None and c["odds_published"] is False for c in caballos)
