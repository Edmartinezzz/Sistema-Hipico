"""Tests de los componentes visuales (HTML y gráficos)."""

from datetime import date

from src import ui

FILA = {
    "N°": 3, "Caballo": "QUEEN <b>X</b>", "Jinete": "FUNEZ", "Récord": "7-0",
    "Cuota": 4.0, "Prob. modelo": 0.42, "Prob. mercado": 0.25, "Edge": 0.17,
    "Kelly": 0.2, "Value bet": True, "Llegada": 1,
}


def test_fecha_larga():
    assert ui.fecha_larga(date(2026, 11, 8)) == "domingo 8 de noviembre de 2026"


def test_pct():
    assert ui.pct(0.42) == "42%"
    assert ui.pct(0.034) == "3.4%"
    assert ui.pct(None) == "-"


def test_saddle_colores():
    assert "background:#D7263D" in ui.saddle(1)
    assert "background:#2A5A44" in ui.saddle(99)  # sin color estándar
    assert ">-<" in ui.saddle(None)


def test_horse_card_escapa_html_y_marca_value_bet():
    html = ui.horse_card(FILA, 1, 0.42, {"weight": 57.0})
    assert "<b>X</b>" not in html and "&lt;b&gt;" in html
    assert "horse-card value" in html
    assert "Value bet +17%" in html
    assert "Llegó 1°" in html
    assert "57 kg" in html
    assert "width:100.0%" in html


def test_race_card_acierto():
    podio = [dict(FILA, Caballo="A"), dict(FILA, Caballo="B")]
    html = ui.race_card(1, 1200, "finalizada", podio, ganador="A", value_bets=["A"])
    assert "Acierto 1er pick" in html
    assert "Ganó: <b>A</b>" in html
    assert "1200 m" in html
    assert "Acierto" not in ui.race_card(1, 1200, "finalizada", podio, ganador="B")


def test_graficos():
    sin_mercado = [dict(FILA, **{"Prob. mercado": None})]
    assert ui.grafico_probabilidades(sin_mercado).to_dict()
    assert ui.grafico_probabilidades([FILA]).to_dict()
    historial = [
        {"Fecha": "2026-10-01", "Llegada": 3, "Ganador": "X"},
        {"Fecha": "2026-10-20", "Llegada": 1, "Ganador": "Y"},
    ]
    assert ui.grafico_forma(historial).to_dict()
    assert ui.grafico_forma(historial[:1]) is None


def test_es_movil():
    iphone = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
    android = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Mobile Safari/537.36"
    tablet = "Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 Safari/537.36"
    ipad = "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
    pc = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
    assert ui.es_movil(iphone)
    assert ui.es_movil(android)
    assert not ui.es_movil(ipad)  # tablet: vista PC
    assert not ui.es_movil(tablet)  # tablet Android sin "Mobile": vista PC
    assert not ui.es_movil(pc)
    assert not ui.es_movil(None)  # sin User-Agent: vista PC (respaldo responsivo)


def test_tiles_y_barra():
    html = ui.tiles([("Carreras", 13, "detalle"), ("X", 1, None)])
    assert 'class="tile"' in html and "Carreras" in html and "detalle" in html
    assert "m-top" in ui.barra_superior("Sistema Hípico", "sub <b>")
    assert "&lt;b&gt;" in ui.barra_superior("Sistema Hípico", "sub <b>")
