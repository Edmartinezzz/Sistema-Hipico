"""Tests del módulo de animalitos (src/animalitos.py).

Los fixtures son páginas sintéticas con la estructura real de
resultadosvenezuela.com (tarjetas ``.result-card``) — sin red.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src import animalitos as an


def _pagina(cards: list[tuple[str, str, str, str]]) -> str:
    """HTML sintético con tarjetas (hora, número, nombre, fecha)."""
    cuerpo = "".join(
        f'<div class="result-card"><div class="card-time">{h}</div>'
        f'<div class="card-image-wrapper"><img src="https://resultadosvenezuela.com'
        f'/assets/images/animales/lotto-activo/{a}_1.webp"/></div>'
        f'<div class="card-number">{n}</div>'
        f'<div class="card-name">{a}</div>'
        f'<div class="card-date">{f}</div></div>'
        for h, n, a, f in cards
    )
    return f"<html><body>{cuerpo}</body></html>"


def _sorteo(fecha: date, numero: str, nombre: str, hora: str = "10:00 AM") -> dict:
    return {
        "loteria": "lotto-activo",
        "fecha": fecha.isoformat(),
        "dia_semana": an.DIAS[fecha.weekday()],
        "hora": hora,
        "hora24": an._hora24(hora),
        "numero": numero,
        "num": int(numero),
        "nombre": nombre,
    }


def test_parse_dia_extrae_campos():
    fecha = date(2026, 11, 9)  # lunes
    html = _pagina(
        [
            ("09:00 AM", "05", "León", "09/11/2026"),
            ("10:00 AM", "00", "Ballena", "09/11/2026"),
            ("07:30 PM", "12", "Caballo", "09/11/2026"),
        ]
    )
    sorteos = an.parse_dia(html, "lotto-activo", fecha)
    assert len(sorteos) == 3
    assert sorteos[0]["numero"] == "5"  # "05" se normaliza
    assert sorteos[0]["nombre"] == "León"
    assert sorteos[0]["dia_semana"] == "Lunes"
    assert sorteos[0]["hora24"] == 9
    assert sorteos[2]["hora24"] == 19
    assert sorteos[0]["imagen"].endswith("/animales/lotto-activo/León_1.webp")


def test_parse_dia_ignora_tarjetas_incompletas():
    html = (
        _pagina([("09:00 AM", "05", "León", "09/11/2026")])
        + '<div class="result-card"><div class="card-time">x</div></div>'
    )
    assert len(an.parse_dia(html, "lotto-activo", date(2026, 11, 9))) == 1


def test_hora24():
    assert an._hora24("07:30 PM") == 19
    assert an._hora24("12:00 PM") == 12
    assert an._hora24("12:00 AM") == 0
    assert an._hora24("09:00 AM") == 9
    assert an._hora24("sin hora") is None


def test_sorteos_dia_usa_cache(tmp_path, monkeypatch):
    fecha = date(2026, 11, 1)
    cache = Path(tmp_path) / f"lotto-activo_{fecha.isoformat()}.json"
    cache.write_text(json.dumps([_sorteo(fecha, "05", "León")]), "utf-8")
    monkeypatch.setattr(
        an, "_get_html", lambda u: pytest.fail("no debió pedir la red")
    )
    assert an.sorteos_dia("lotto-activo", fecha, tmp_path)[0]["nombre"] == "León"


def test_tabla_dia_cuenta_por_dia_semana():
    # Lunes 9 y lunes 16 de noviembre de 2026 + un martes.
    lun1, lun2, mar = date(2026, 11, 9), date(2026, 11, 16), date(2026, 11, 10)
    sorteos = [
        _sorteo(lun1, "05", "León"),
        _sorteo(lun1, "07", "Perico", "11:00 AM"),
        _sorteo(lun2, "05", "León"),
        _sorteo(lun2, "05", "León", "11:00 AM"),
        _sorteo(mar, "09", "Águila"),
    ]
    tabla = an.tabla_dia(sorteos, 0)  # lunes
    assert tabla[0]["numero"] == "05"
    assert tabla[0]["veces"] == 3
    assert tabla[0]["dias"] == 2
    assert tabla[0]["sorteos"] == 4
    assert tabla[0]["prob"] > tabla[0]["prob_teorica"]
    # El martes no suma al lunes.
    assert all(f["numero"] != "09" or f["veces"] == 0 for f in tabla)


def test_tabla_dia_filtra_por_hora():
    lun = date(2026, 11, 9)
    sorteos = [
        _sorteo(lun, "05", "León", "09:00 AM"),
        _sorteo(lun, "07", "Perico", "10:00 AM"),
    ]
    tabla = an.tabla_dia(sorteos, 0, hora="09:00 AM")
    assert tabla[0]["numero"] == "05"
    assert tabla[0]["sorteos"] == 1


def test_enjaulados_y_calientes():
    hoy = an.hoy_ve()
    viejo = hoy - timedelta(days=10)
    sorteos = [
        _sorteo(hoy, "05", "León"),
        _sorteo(hoy, "05", "León", "11:00 AM"),
        _sorteo(viejo, "07", "Perico"),
    ]
    enj = an.enjaulados(sorteos)
    assert enj[0]["numero"] == "07"
    assert enj[0]["dias_sin_salir"] == 10
    cal = an.calientes(sorteos, dias=7)
    assert cal[0]["numero"] == "05"
    assert cal[0]["veces"] == 2


def test_horas_disponibles_ordenadas():
    lun = date(2026, 11, 9)
    sorteos = [
        _sorteo(lun, "05", "León", "04:00 PM"),
        _sorteo(lun, "07", "Perico", "09:00 AM"),
        _sorteo(lun, "09", "Águila", "12:00 PM"),
    ]
    assert an.horas_disponibles(sorteos, 0) == [
        "09:00 AM", "12:00 PM", "04:00 PM",
    ]


def test_historial_loteria_desconocida():
    with pytest.raises(an.AnimalitosError):
        an.historial("no-existe", 3)


class _Resp:
    """Respuesta falsa para rate_limited_get."""

    def __init__(self, status: int, tipo: str = "image/webp"):
        self.status_code = status
        self.headers = {"Content-Type": tipo}


def test_mapa_animales_guarda_y_completa(tmp_path, monkeypatch):
    fecha = date(2026, 11, 9)
    s = _sorteo(fecha, "05", "León")
    s["imagen"] = "https://img.test/leon.webp"
    monkeypatch.setattr(an, "rate_limited_get", lambda u: _Resp(404))
    mapa = an.mapa_animales("lotto-activo", [s], tmp_path)
    assert mapa["5"] == {"nombre": "León", "imagen": "https://img.test/leon.webp"}
    # Persiste en disco aunque la siguiente llamada no traiga imagen.
    s2 = _sorteo(fecha, "07", "Perico")
    monkeypatch.setattr(
        an, "_get_html",
        lambda u: _pagina([("09:00 AM", "05", "León", "09/11/2026")]),
    )
    mapa = an.mapa_animales("lotto-activo", [s2], tmp_path)
    assert mapa["5"]["imagen"].endswith("_1.webp")  # la fuente real gana
    assert mapa["7"]["nombre"] == "Perico"
    assert not mapa["7"].get("imagen")
    assert mapa["7"]["sin_img"]  # la URL construida dio 404: no reintentar


def test_mapa_animales_siembra_si_no_hay_imagenes(tmp_path, monkeypatch):
    # Sin mapa previo ni imágenes: pide un día fresco a la fuente.
    fecha = date(2026, 11, 9)
    html = _pagina([("09:00 AM", "05", "León", "09/11/2026")])
    monkeypatch.setattr(an, "_get_html", lambda u: html)
    monkeypatch.setattr(an, "rate_limited_get", lambda u: _Resp(200))
    mapa = an.mapa_animales("lotto-activo", [_sorteo(fecha, "07", "Perico")], tmp_path)
    assert mapa["5"]["imagen"].endswith("León_1.webp")
    # Perico no salió en la página: su dibujo se resolvió por URL patrón.
    assert "Perico_1.webp" in mapa["7"]["imagen"]


def test_tira_animalitos_con_y_sin_imagen():
    from src import ui

    items = [
        {"numero": "05", "nombre": "León", "veces": 6, "sorteos": 89,
         "prob": 0.055, "imagen": "https://img.test/leon.webp"},
        {"numero": "07", "nombre": "Perico", "veces": 4, "sorteos": 89,
         "prob": 0.04, "imagen": None},
    ]
    html = ui.tira_animalitos(items)
    assert 'class="an-tira"' in html
    assert 'src="https://img.test/leon.webp"' in html
    assert 'class="an-img an-num">07<' in html
    assert "an-item top" in html  # el primero se destaca


def test_parse_dia_nombre_generico_y_animales_prefiere_real():
    # La fuente pone "Resultado" cuando no conoce el animal (Selva Plus 96).
    fecha = date(2026, 11, 22)
    html = _pagina([("08:15 PM", "96", "Resultado", "22/11/2026")])
    s = an.parse_dia(html, "selva-plus", fecha)
    assert s[0]["nombre"] == "N.º 96"
    otro = _sorteo(fecha, "96", "Tucán")
    assert an.animales(s + [otro])["96"] == "Tucán"
    assert an.animales([otro] + s)["96"] == "Tucán"


def test_hoy_ve_es_hora_de_venezuela():
    from datetime import datetime, timezone

    assert an.hoy_ve() == (datetime.now(timezone.utc) - timedelta(hours=4)).date()


def test_sorteos_dia_rechaza_cache_parcial(tmp_path, monkeypatch):
    # Un día guardado a media jornada (mtime = ese mismo día) no es definitivo.
    import os
    from datetime import datetime

    fecha = date(2026, 11, 10)
    cache = Path(tmp_path) / f"lotto-activo_{fecha.isoformat()}.json"
    cache.write_text(json.dumps([_sorteo(fecha, "05", "León")]), "utf-8")
    media_jornada = datetime(2026, 11, 10, 12, 0, tzinfo=an.ZONA_VE).timestamp()
    os.utime(cache, (media_jornada, media_jornada))
    html = _pagina([("09:00 AM", "05", "León", ""), ("10:00 AM", "07", "Perico", "")])
    monkeypatch.setattr(an, "_get_html", lambda u: html)
    assert len(an.sorteos_dia("lotto-activo", fecha, tmp_path)) == 2
    # Ahora el archivo se reescribió hoy (después de ese día): definitivo.
    monkeypatch.setattr(an, "_get_html", lambda u: pytest.fail("no debió pedir la red"))
    assert len(an.sorteos_dia("lotto-activo", fecha, tmp_path)) == 2


def test_sorteos_dia_sin_red(tmp_path, monkeypatch):
    monkeypatch.setattr(an, "_get_html", lambda u: pytest.fail("no debió pedir la red"))
    assert an.sorteos_dia("lotto-activo", date(2026, 11, 1), tmp_path, red=False) == []


def test_actualizar_archivo_y_historial_sin_red(tmp_path, monkeypatch):
    hoy = date(2026, 11, 23)
    archivo, cache = tmp_path / "archivo", tmp_path / "cache"
    pedidas = []

    def falso(url):
        fecha = url.rsplit("=", 1)[1]
        pedidas.append(fecha)
        if fecha == "2026-11-22":  # ayer vacío: posible fallo pasajero
            return "<html></html>"
        return _pagina([("09:00 AM", "05", "León", ""), ("10:00 AM", "96", "Resultado", "")])

    monkeypatch.setattr(an, "_get_html", falso)
    res = an.actualizar_archivo("lotto-activo", 5, archivo, cache, hoy=hoy)
    assert pedidas == ["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"]
    assert res == {"nuevos": 4, "errores": 0, "dias": 4}
    ruta = archivo / "lotto-activo.json.gz"
    contenido = ruta.read_bytes()

    dias = an.leer_archivo("lotto-activo", archivo)
    assert sorted(dias) == ["2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"]
    s = dias["2026-11-18"][1]
    assert s["dia_semana"] == "Miércoles" and s["hora24"] == 10
    assert s["num"] == 96 and s["nombre"] == "N.º 96"

    # Segunda pasada: solo reintenta el día vacío y el .gz no cambia.
    pedidas.clear()
    for f in cache.glob("*2026-11-22*"):
        f.unlink()  # la caché de un día vacío también se ignora
    assert an.actualizar_archivo("lotto-activo", 5, archivo, cache, hoy=hoy)["nuevos"] == 0
    assert pedidas == ["2026-11-22"]
    assert ruta.read_bytes() == contenido

    # historial lee el archivo sin tocar la red.
    monkeypatch.setattr(an, "_get_html", lambda u: pytest.fail("no debió pedir la red"))
    monkeypatch.setattr(an, "hoy_ve", lambda: date(2026, 11, 21))
    todos = an.historial("lotto-activo", 4, cache, red=False, archivo_dir=archivo)
    assert len(todos) == 8


def test_pronostico_horas():
    lun1, lun2, mar = date(2026, 11, 9), date(2026, 11, 16), date(2026, 11, 10)
    sorteos = [
        _sorteo(lun1, "05", "León", "09:00 AM"),
        _sorteo(lun2, "05", "León", "09:00 AM"),
        _sorteo(lun2, "07", "Perico", "10:00 AM"),
        _sorteo(lun1, "09", "Águila", "10:00 AM"),
        # El martes no cuenta como "veces" pero desempata la hora 10.
        _sorteo(mar, "07", "Perico", "10:00 AM"),
    ]
    horas = an.pronostico_horas(sorteos, 0, top=2)
    assert [h["hora"] for h in horas] == ["09:00 AM", "10:00 AM"]
    assert horas[0]["top"][0]["numero"] == "05" and horas[0]["top"][0]["veces"] == 2
    assert len(horas[0]["top"]) == 1  # solo los que salieron
    assert [f["numero"] for f in horas[1]["top"]] == ["07", "09"]
    assert horas[1]["sorteos"] == 2


def test_aciertos():
    hoy = date(2026, 11, 23)
    sorteos_hoy = [
        _sorteo(hoy, "07", "Perico", "10:00 AM"),
        _sorteo(hoy, "05", "León", "09:00 AM"),
        _sorteo(hoy, "11", "Gato", "11:00 AM"),
    ]
    res = an.aciertos(sorteos_hoy, ["05", "07"], {"09:00 AM": ["05"]}, 38)
    assert [f["hora"] for f in res["filas"]] == ["09:00 AM", "10:00 AM", "11:00 AM"]
    assert res["sorteos"] == 3 and res["dia"] == 2 and res["hora"] == 1
    assert res["filas"][0]["en_top_hora"] and not res["filas"][1]["en_top_hora"]
    assert res["esperado"] == pytest.approx(3 * 2 / 38)


def test_ui_resultados_hoy_y_pronostico_horas():
    from src import ui

    filas = [
        {"hora": "09:00 AM", "numero": "05", "nombre": "León", "imagen": None,
         "en_top_dia": True, "en_top_hora": True},
        {"hora": "10:00 AM", "numero": "07", "nombre": "<b>", "imagen": None,
         "en_top_dia": True, "en_top_hora": False},
    ]
    html = ui.resultados_hoy(filas, ["11:00 AM"])
    assert "an-item ok-hora" in html and "TOP HORA" in html
    assert "an-item ok" in html and "TOP DÍA" in html
    assert "&lt;b&gt;" in html  # texto escapado
    assert "an-item pend" in html and "11:00 AM" in html

    horas = [{"hora": "09:00 AM", "sorteos": 4, "top": [
        {"numero": "05", "nombre": "León", "veces": 2, "sorteos": 4}]},
        {"hora": "10:00 AM", "sorteos": 0, "top": []}]
    html = ui.pronostico_horas(horas, {"05": {"imagen": "https://img.test/l.webp"}})
    assert 'src="https://img.test/l.webp"' in html and "<b>2/4</b>" in html
    assert "Sin datos" in html


def test_normalizar_numero_unifica_formatos():
    # La fuente pasó de "08" a "8" a mitad de año; 0 y 00 son distintos.
    assert [an.normalizar_numero(x) for x in ["08", "8", "0", "00", "10", " 36 "]] == [
        "8", "8", "0", "00", "10", "36",
    ]
    html = _pagina([("09:00 AM", "08", "Ratón", ""), ("10:00 AM", "00", "Ballena", "")])
    s = an.parse_dia(html, "la-granjita", date(2026, 6, 1))
    assert [x["numero"] for x in s] == ["8", "00"]
    viejo = [_sorteo(date(2026, 6, 1), "8", "Ratón") | {"numero": "08"},
             _sorteo(date(2026, 8, 3), "8", "Ratón")]
    assert an.tabla_dia(an._limpiar(viejo), 0)[0]["veces"] == 2


def test_efectividad_dia_walk_forward():
    # Cada lunes sale el 05 y los demás días el 07: el top-1 del lunes
    # acierta todos los lunes evaluados y nunca usa el día que predice.
    inicio = date(2026, 6, 1)  # lunes
    sorteos = []
    for i in range(28):
        f = inicio + timedelta(days=i)
        sorteos.append(_sorteo(f, "05" if f.weekday() == 0 else "07", "X"))
    ef = an.efectividad_dia(sorteos, top=1, min_dias=14)
    assert ef["dias"] == 14 and ef["sorteos"] == 14
    assert ef["aciertos"] == 14 and ef["tasa"] == 1.0
    assert ef["azar"] == pytest.approx(0.5)
    assert an.efectividad_dia(sorteos, min_dias=100)["tasa"] is None
