"""Pruebas del pipeline extractor → enriquecimiento → modelo."""

import pytest

from src import database, pipeline
from src.sample_data import create_empty_pdf, create_sample_gaveta


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def gaveta(tmp_path):
    return create_sample_gaveta(tmp_path / "gaveta.pdf")


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [
        ("12-4-3-2", {"starts": 12, "wins": 4, "places": 3, "shows": 2}),
        ("0-0-0-0", {"starts": 0, "wins": 0, "places": 0, "shows": 0}),
        ("4-3-2", None),
        ("3-2-2-2", None),
        (None, None),
        ("—", None),
    ],
)
def test_parse_record(raw, esperado):
    assert pipeline.parse_record(raw) == esperado


def test_form_from_enrichment():
    assert pipeline.form_from_enrichment({"starts": 10, "wins": 3}) == {"starts": 10, "wins": 3}
    assert pipeline.form_from_enrichment({"carreras": 8, "victorias": 2.0}) == {
        "starts": 8,
        "wins": 2,
    }
    for invalido in (None, {}, {"starts": 3}, {"starts": 2, "wins": 5}, {"starts": "x", "wins": 1}):
        assert pipeline.form_from_enrichment(invalido) is None


def _caballo(nombre, cuota, record=None):
    return {"horse_name": nombre, "odds": cuota, "odds_raw": str(cuota), "record": record}


def test_analyze_race_probabilidades_suman_1():
    filas = pipeline.analyze_race(
        [_caballo("A", 2.0, "10-5-2-1"), _caballo("B", 4.0), _caballo("C", 5.0, "8-0-1-1")]
    )
    assert sum(f["market_prob"] for f in filas) == pytest.approx(1.0)
    assert sum(f["model_prob"] for f in filas) == pytest.approx(1.0)
    assert sum(f["edge"] for f in filas) == pytest.approx(0.0, abs=1e-12)
    assert sum(f["top3_prob"] for f in filas) == pytest.approx(3.0)
    assert [f["form_source"] for f in filas] == ["gaveta", None, "gaveta"]


def test_analyze_race_sin_historial_modelo_igual_a_mercado():
    # Cuotas con overround: sin historial no hay ventaja sobre el pago real.
    filas = pipeline.analyze_race([_caballo("A", 1.8), _caballo("B", 2.2)])
    for fila in filas:
        assert fila["model_prob"] == pytest.approx(fila["market_prob"])
        assert fila["value_bet"] is False
        assert fila["kelly"] == 0.0


def test_analyze_race_detecta_value_bet_por_historial():
    filas = pipeline.analyze_race(
        [_caballo("Favorito", 1.5, "10-1-1-1"), _caballo("Batacazo", 10.0, "20-12-3-2")],
        threshold=0.05,
    )
    favorito, batacazo = filas
    assert batacazo["value_bet"] is True and batacazo["edge"] > 0.05
    assert batacazo["kelly"] > 0
    assert favorito["value_bet"] is False


def test_analyze_race_enriquecimiento_tiene_prioridad_sobre_la_gaveta():
    enriquecimiento = {"A": {"found": True, "source": "csv", "data": {"starts": 30, "wins": 15}}}
    fila = pipeline.analyze_race([_caballo("A", 3.0, "4-0-0-0"), _caballo("B", 2.0)],
                                 enriquecimiento)[0]
    assert (fila["starts"], fila["wins"], fila["form_source"]) == (30, 15, "historial")
    assert fila["enrichment_found"] is True and fila["enrichment_source"] == "csv"


def test_analyze_race_caballo_retirado_queda_sin_probabilidades():
    filas = pipeline.analyze_race([_caballo("A", 2.0), _caballo("Retirado", None)])
    assert filas[1]["market_prob"] is None and filas[1]["model_prob"] is None
    assert filas[1]["value_bet"] is False
    assert filas[0]["market_prob"] == pytest.approx(1.0)


def test_analyze_race_todos_retirados():
    filas = pipeline.analyze_race([_caballo("A", None)])
    assert filas[0]["model_prob"] is None


def test_analyze_pdf_gaveta_de_ejemplo(gaveta, db):
    resultado = pipeline.analyze_pdf(gaveta, db_path=db)
    assert [r["race_number"] for r in resultado["races"]] == [1, 2]
    assert [len(r["rows"]) for r in resultado["races"]] == [6, 12]
    assert resultado["warnings"] == []
    carrera1 = resultado["races"][0]
    assert carrera1["distance"] == "1200 m" and carrera1["track"]
    assert sum(f["model_prob"] or 0 for f in carrera1["rows"]) == pytest.approx(1.0)
    # Las inscripciones quedan guardadas en SQLite.
    historial = database.get_horse_history("Caribeño", db)
    assert historial["entries"][0]["race_number"] == 2
    assert historial["entries"][0]["odds"] == pytest.approx(3.0)


def test_analyze_pdf_con_csv_de_historial(gaveta, db, tmp_path):
    csv_path = tmp_path / "historial.csv"
    csv_path.write_text("name,starts,wins\nOrquídea,10,7\n", encoding="utf-8")
    resultado = pipeline.analyze_pdf(gaveta, db_path=db, csv_path=csv_path)
    orquidea = next(f for f in resultado["races"][1]["rows"] if f["horse_name"] == "Orquídea")
    assert orquidea["form_source"] == "historial"
    assert orquidea["value_bet"] is True
    assert resultado["enrichment"]["Orquídea"]["found"] is True
    assert resultado["enrichment"]["Caribeño"]["found"] is False


def test_analyze_pdf_sin_tablas(tmp_path, db):
    resultado = pipeline.analyze_pdf(create_empty_pdf(tmp_path / "vacio.pdf"), db_path=db)
    assert resultado["races"] == []
    assert any("No se encontraron" in w for w in resultado["warnings"])


def test_analyze_pdf_sin_fecha_no_guarda_pero_analiza(tmp_path, db):
    pdf = create_sample_gaveta(tmp_path / "sin_fecha.pdf", track=None, date=None)
    resultado = pipeline.analyze_pdf(pdf, db_path=db)
    assert len(resultado["races"]) == 2
    assert any("no se guarda" in w for w in resultado["warnings"])


def test_analyze_race_sin_victorias_y_peso_cero_usa_el_mercado():
    filas = pipeline.analyze_race(
        [_caballo("A", 2.0, "5-0-1-1"), _caballo("B", 3.0, "8-0-2-2")], prior_weight=0.0
    )
    assert sum(f["model_prob"] for f in filas) == pytest.approx(1.0)
    for fila in filas:
        assert fila["model_prob"] == pytest.approx(fila["market_prob"])
