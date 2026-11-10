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
    assert sorteos[0]["numero"] == "05"
    assert sorteos[0]["nombre"] == "León"
    assert sorteos[0]["dia_semana"] == "Lunes"
    assert sorteos[0]["hora24"] == 9
    assert sorteos[2]["hora24"] == 19


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
    hoy = date.today()
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
