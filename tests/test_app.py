"""Pruebas de humo del dashboard con ``streamlit.testing``."""

from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")


@pytest.fixture(autouse=True)
def db_temporal(tmp_path, monkeypatch):
    monkeypatch.setenv("HORSE_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.delenv("HORSE_CSV_PATH", raising=False)


def test_app_arranca_sin_errores():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert not at.error
    assert at.title[0].value == "Análisis estadístico de carreras"
    assert at.button(key="analizar").disabled


def test_app_analiza_la_gaveta_de_ejemplo():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.button(key="ejemplo").click().run()
    assert not at.exception
    assert not at.error
    assert len(at.dataframe) >= 2
    tabla = at.dataframe[0].value
    for columna in ("Caballo", "Jinete", "Cuota", "Prob. modelo", "Prob. mercado", "Edge"):
        assert columna in tabla.columns
    assert [m.value for m in at.metric][:2] == ["2", "18"]
    assert at.selectbox(key="detalle").options
    retirado = tabla[tabla["Caballo"] == "Viento Sur"].iloc[0]
    assert retirado["Cuota"] == "NADA"
    assert retirado["Prob. modelo"] == "—"
    assert tabla["Prob. mercado"].iloc[0].endswith("%")

    # Cambiar el caballo del detalle no borra los resultados.
    at.selectbox(key="detalle").select_index(7).run()
    assert not at.exception
    assert len(at.dataframe) >= 2


def test_app_busca_la_gaceta_en_internet(monkeypatch):
    import responses

    from src import gaceta_online, scraper
    from tests.test_gaceta_online import REVISTA_URL, lista_html, revista_html

    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    monkeypatch.setattr(gaceta_online, "today_in_venezuela", lambda: date(2026, 11, 8))
    with responses.RequestsMock() as mock:
        mock.get(gaceta_online.DESAFIO_LIST_URL, body=lista_html(
            [(44, "LA RINCONADA", "2026-11-08T12:00:00.000Z", REVISTA_URL)]
        ))
        mock.get(REVISTA_URL, body=revista_html())
        at = AppTest.from_file(APP, default_timeout=60).run()
        at.button(key="buscar").click().run()
    assert not at.exception
    assert not at.error
    assert len(at.dataframe) >= 2
    tabla = at.dataframe[0].value
    assert tabla["Caballo"].iloc[0] == "CABALLO UNO"
    assert tabla["Prob. modelo"].iloc[0].endswith("%")
    assert tabla["Prob. mercado"].iloc[0] == "—"


def test_app_avisa_si_no_encuentra_la_gaceta(monkeypatch):
    import responses

    from src import gaceta_online, scraper

    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    with responses.RequestsMock() as mock:
        mock.get(gaceta_online.DESAFIO_LIST_URL, status=404)
        mock.get(gaceta_online.POLLAMACACO_URLS["LA RINCONADA"], status=404)
        at = AppTest.from_file(APP, default_timeout=60).run()
        at.button(key="buscar").click().run()
    assert not at.exception
    assert "No se encontró la gaceta" in at.error[0].value
