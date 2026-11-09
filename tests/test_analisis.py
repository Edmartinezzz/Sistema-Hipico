"""Tests del Módulo 7 — análisis por carrera."""

import pytest

from src.analisis import (
    analizar_carrera,
    datos_forma,
    efectividad_modelo,
    probabilidades_mercado,
    resumen_reunion,
)

CABALLOS = [
    {"race_number": 1, "horse_name": "A", "year_wins": 4, "year_starts": 6,
     "lengths_behind": [0, 1], "finish_position": 2},
    {"race_number": 1, "horse_name": "B", "year_wins": 0, "year_starts": 8,
     "lengths_behind": [10, 12], "finish_position": 1},
    {"race_number": 1, "horse_name": "C"},  # sin datos -> mediana
]


def test_datos_forma_web_y_csv():
    assert datos_forma(CABALLOS[0]) == (4, 6, [0, 1])
    csv = {"enrichment": {"data": {"wins": "2", "starts": "5"}}}
    assert datos_forma(csv) == (2, 5, [])
    assert datos_forma({}) == (None, None, [])


def test_analizar_carrera_sin_cuotas():
    filas = analizar_carrera(CABALLOS, [None, None, None])
    assert sum(f["Prob. modelo"] for f in filas) == pytest.approx(1.0)
    # El caballo en mejor forma queda primero.
    assert filas[0]["Caballo"] == "A"
    assert all(f["Prob. mercado"] is None and not f["Value bet"] for f in filas)


def test_analizar_carrera_con_cuotas_value_bet():
    # El mercado da a "A" como el menos probable -> value bet.
    filas = analizar_carrera(CABALLOS, [8.0, 2.0, 3.0], umbral=0.05)
    a = next(f for f in filas if f["Caballo"] == "A")
    assert a["Value bet"] is True
    assert a["Edge"] > 0.05
    assert a["Kelly"] > 0


def test_probabilidades_mercado_incompleto():
    assert probabilidades_mercado([2.0, None]) is None
    assert probabilidades_mercado([2.0, 2.0]) == pytest.approx([0.5, 0.5])


def test_efectividad_modelo():
    # Ganó "B" (último pick del modelo): corrida sin acierto 1° pero en top 3.
    assert efectividad_modelo(CABALLOS) == {
        "corridas": 1, "aciertos_1": 0, "aciertos_top3": 1,
    }
    sin_correr = [{**c, "finish_position": None} for c in CABALLOS]
    assert efectividad_modelo(sin_correr)["corridas"] == 0


def test_resumen_reunion():
    resumen = resumen_reunion(CABALLOS, {(1, "A"): 8.0, (1, "B"): 2.0, (1, "C"): 3.0})
    assert len(resumen) == 1
    assert resumen[0]["1er pick"] == "A"
    assert resumen[0]["Ganador real"] == "B"
    assert "A" in resumen[0]["Value bets"]


def test_confianza_top():
    from src.analisis import confianza_top

    assert confianza_top(0.40, 0.20) == "Alta"
    assert confianza_top(0.40, 0.35) == "Media"  # margen chico
    assert confianza_top(0.30, 0.10) == "Media"
    assert confianza_top(0.10) == "Baja"


def test_harville_lugar_top3_pequeno_campo():
    from src.analisis import _harville_lugar_top3

    assert _harville_lugar_top3([0.5, 0.5]) == [1.0, 1.0]
    assert _harville_lugar_top3([0.4, 0.3, 0.3]) == [1.0, 1.0, 1.0]


def test_harville_lugar_top3_suma_coherente():
    from src.analisis import _harville_lugar_top3

    p = [0.4, 0.25, 0.15, 0.1, 0.1]
    lugar = _harville_lugar_top3(p)
    # La suma de P(top-3) sobre todos debe ser 3 (siempre hay 3 caballos).
    assert sum(lugar) == pytest.approx(3.0, abs=1e-6)
    # El más probable queda más arriba que el peor.
    assert lugar[0] > lugar[-1]


def test_cobertura_5y6():
    from src.analisis import cobertura_5y6

    p = [0.4, 0.25, 0.15, 0.1, 0.05, 0.05]
    combo = cobertura_5y6(p, objetivo=0.30)
    assert combo["indices"] == [0, 1]  # 0.4 y 0.25 ya cubren ~62%
    assert combo["cobertura"] >= 0.30
    # Sin objetivo imposible: devuelve el grupo completo.
    combo_full = cobertura_5y6(p, objetivo=0.99)
    assert combo_full["indices"] == list(range(6))


def test_exactas_top():
    from src.analisis import exactas_top

    combos = exactas_top([0.5, 0.3, 0.2], ["A", "B", "C"], top=3)
    assert len(combos) == 3
    assert combos[0]["1°"] == "A"
    assert combos[0]["2°"] == "B"
    assert combos[0]["Prob."] > combos[1]["Prob."]


def test_pronostico_carrera():
    from src.analisis import pronostico_carrera

    filas = analizar_carrera(CABALLOS, [None] * 3)
    pron = pronostico_carrera(filas)
    assert pron["top3"] == filas[:3]
    assert pron["confianza"] in {"Alta", "Media", "Baja"}
    assert pron["combo_nombres"]
    assert all("Prob. top3" in f for f in filas)
    # Las probabilidades top-3 suman ~3.
    assert sum(f["Prob. top3"] for f in filas) == pytest.approx(3.0, abs=1e-6)
