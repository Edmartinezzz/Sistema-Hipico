"""Tests de humo del Módulo 5 — la app Streamlit arranca y analiza.

Se inyectan reuniones sintéticas en la sesión para no usar la red.
"""

from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.gaceta_web import meeting_to_records, parse_meetings
from tests.test_gaceta_web import LISTA_HTML, REUNION

APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")


def _app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["reuniones"] = parse_meetings(LISTA_HTML)
    # Semana sin reuniones sintéticas: no se dispara ninguna descarga.
    at.session_state["semana"] = date(2026, 12, 2)
    return at


def test_app_arranca_sin_excepciones():
    at = _app().run()
    assert not at.exception
    assert [t.label for t in at.tabs] == [
        "Domingo", "Reunión", "Carrera", "En vivo", "Laboratorio", "Chat IA"
    ]
    assert any(m.label == "Al azar · 1er pick" for m in at.metric)
    assert at.date_input[0].label == "Semana"
    # Botón para saltar a la última reunión publicada.
    assert any("ir a la última" in b.label for b in at.button)


def test_app_tras_ocr_muestra_reunion_sin_recargar():
    """Tras leer una gaceta escaneada: salta a su semana/reunión y conserva las cuotas."""
    registros = meeting_to_records(REUNION)
    at = _app()
    at.session_state["registros"] = registros
    at.session_state["origen"] = "web_bb22"
    at.session_state["meta"] = {"kicker": "Reunión 28", "track": "NACIONAL DE VALENCIA",
                                "date": date(2026, 11, 7), "number": 28, "retirados": []}
    at.session_state["cuotas"] = {(1, "QUEEN VISION"): 4.0, (1, "SALOME"): 2.5}
    at.session_state["_semana_pendiente"] = date(2026, 11, 7)
    at.session_state["_reunion_pendiente"] = "bb22"
    at.session_state["_aviso_ocr"] = ("Gaceta escaneada leída: 2 cuotas ML", {})
    at.run()
    assert not at.exception
    assert at.date_input[0].value == date(2026, 11, 7)
    assert at.selectbox[0].value == "bb22"
    assert at.session_state["cuotas"][(1, "SALOME")] == 2.5
    assert any("Gaceta escaneada leída" in s.value for s in at.success)
    # Con todas las cuotas puestas hay probabilidad de mercado (sin aviso de cuotas).
    assert not any("Escribe las cuotas" in c.value for c in at.caption)


def _app_movil() -> AppTest:
    at = _app()
    at.session_state["_vista_forzada"] = "movil"
    return at


def test_app_movil_resumen_y_carrera():
    """Vista móvil: sin pestañas, navegación abajo y secciones por botón."""
    registros = meeting_to_records(REUNION)
    at = _app_movil()
    at.session_state["registros"] = registros
    at.session_state["origen"] = "test"
    at.session_state["meta"] = {
        "kicker": "Reunión 44", "track": "LA RINCONADA", "date": date(2026, 11, 8),
        "number": 44, "retirados": [],
    }
    at.session_state["cuotas"] = {(1, r["horse_name"]): None for r in registros}
    at.run()
    assert not at.exception
    assert not at.tabs  # la vista móvil no usa pestañas
    # Barra superior + riel lateral de iconos (las herramientas son Config).
    assert len(at.get("popover")) == 0
    assert not at.segmented_control
    assert at.session_state["m_sec"] == "Resumen"
    nav = {b.key: b for b in at.button if b.key.startswith("m_nav_")}
    assert set(nav) == {f"m_nav_{s}" for s in (
        "Resumen", "Domingo", "Carrera", "En vivo", "Lab", "Chat", "Config")}
    # Lista de carreras como botones grandes.
    assert any(b.label.startswith("C1") for b in at.button)
    # Entrar a la sección Carrera desde el resumen.
    at.button(key="m_carr_test_1").click().run()
    assert not at.exception
    assert at.session_state["m_sec"] == "Carrera"
    assert at.pills[0].value == 1
    assert sum(b.label == "Ver ficha" for b in at.button) == len(registros)
    # Sección Domingo accesible desde el riel lateral.
    at.button(key="m_nav_Domingo").click().run()
    assert not at.exception
    assert any("Pronóstico del domingo" in m.value for m in at.markdown)


def test_app_movil_sin_reunion():
    at = _app_movil().run()
    assert not at.exception
    assert at.session_state["m_sec"] == "Resumen"
    assert any("elige la semana" in m.value for m in at.markdown)
    # La sección Config está accesible sin reunión cargada.
    at.button(key="m_nav_Config").click().run()
    assert not at.exception
    assert at.date_input[0].label == "Semana"


def test_app_muestra_reunion_cargada():
    registros = meeting_to_records(REUNION)
    at = _app()
    at.session_state["registros"] = registros
    at.session_state["origen"] = "test"
    at.session_state["meta"] = {
        "kicker": "Reunión 44", "track": "LA RINCONADA", "date": date(2026, 11, 8),
        "number": 44, "retirados": [{"race_number": 1, "horse_name": "RETIRADA"}],
    }
    at.session_state["cuotas"] = {(1, r["horse_name"]): None for r in registros}
    at.run()
    assert not at.exception
    assert at.metric[0].value == "2"  # inscritos
    assert at.metric[1].value == "1"  # retirados
    assert at.pills[0].value == 1
    # Una tarjeta "Ficha" por caballo.
    assert sum(b.label == "Ficha" for b in at.button) == 2
    # Pestaña Domingo: pronóstico o aviso de reuniones ya corridas.
    assert any("Pronóstico del domingo" in m.value for m in at.markdown)
    # Pestaña Chat IA: con API key muestra el chat; sin ella, instrucciones.
    assert at.chat_input or any("API gratuita" in i.value for i in at.info)
