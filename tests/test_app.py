"""Pruebas de humo del dashboard con ``streamlit.testing``."""

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

    # Cambiar el caballo del detalle no borra los resultados.
    at.selectbox(key="detalle").select_index(7).run()
    assert not at.exception
    assert len(at.dataframe) >= 2
