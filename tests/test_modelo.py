"""Tests del Módulo 10 — modelo entrenado y Módulo 11 — laboratorio."""

import random
from datetime import date

import numpy as np
import pytest

from src import laboratorio
from src.modelo import (
    CARACTERISTICAS,
    EstadisticasPersonas,
    Modelo,
    Predictor,
    ajustar,
    caracteristicas,
    matriz_carrera,
    normalizar_nombre,
    tiempo_a_segundos,
)


def _caballo(nombre, fecha="2026-11-08", llegadas=(), perdida=0.0, jinete="J", **extra):
    historial = [
        {"Fecha": f"2026-08-{10 + i:02d}", "Llegada": l, "Dist.": 1200, "Kg": "55",
         "Tiempo": f"{74 + int(perdida)}.0", "Tiempo ganador": "74.0", "Jinete": jinete}
        for i, l in enumerate(llegadas)
    ]
    return {"horse_name": nombre, "date": fecha, "jockey": jinete, "trainer": "T",
            "history": historial, "year_wins": extra.get("wins"), "year_starts": extra.get("starts"),
            "lengths_behind": [], "distance": 1200, "weight": 55.0, "post_position": 1,
            "finish_position": extra.get("finish"), "race_number": extra.get("race", 1)}


def test_tiempo_a_segundos_en_quintos():
    assert tiempo_a_segundos("74.3") == pytest.approx(74.6)
    assert tiempo_a_segundos("81") == 81
    assert tiempo_a_segundos("—") is None


def test_normalizar_nombre():
    assert normalizar_nombre("Funez Jr. Luis Al.") == "FUNEZ JR LUIS AL"


def test_estadisticas_solo_usan_fechas_previas():
    stats = EstadisticasPersonas()
    stats.agregar("jinete", "ANA", date(2026, 10, 1), True, "a")
    stats.agregar("jinete", "ANA", date(2026, 10, 8), False, "b")
    stats.agregar("jinete", "ANA", date(2026, 10, 8), False, "b")  # duplicado
    assert stats.tasa("jinete", "ANA", date(2026, 10, 1)) is None
    assert stats.tasa("jinete", "ana", date(2026, 10, 2)) == pytest.approx(2 / 11)
    assert stats.tasa("jinete", "ANA", date(2026, 12, 1)) == pytest.approx(2 / 12)


def test_caracteristicas_ignoran_historial_futuro():
    c = _caballo("A", llegadas=(1, 2))
    c["history"].append({"Fecha": "2026-11-08", "Llegada": 1})  # mismo día: excluido
    f = caracteristicas(c, 10, None)
    assert f["llegada"] == pytest.approx(-1.5)
    assert f["debut"] == 0.0
    assert caracteristicas(_caballo("B"), 10, None)["debut"] == 1.0


def test_matriz_estandarizada():
    caballos = [_caballo("A", llegadas=(1,)), _caballo("B", llegadas=(5,)), _caballo("C")]
    x = matriz_carrera(caballos, None)
    assert x.shape == (3, len(CARACTERISTICAS))
    col = CARACTERISTICAS.index("llegada")
    assert x[0, col] > 0 > x[1, col]
    assert x[2, col] == 0.0  # sin dato -> promedio


def _reuniones_sinteticas(n_reuniones=6, seed=1):
    """El caballo con menos segundos perdidos gana casi siempre."""
    rnd = random.Random(seed)
    reuniones = []
    for k in range(n_reuniones):
        fecha = f"2026-{9 + k // 4:02d}-{1 + 7 * (k % 4):02d}"
        registros = []
        for carrera in range(1, 7):
            perdidas = rnd.sample(range(0, 8), 5)
            ganador = perdidas.index(min(perdidas)) if rnd.random() < 0.8 else rnd.randrange(5)
            for i, p in enumerate(perdidas):
                registros.append(_caballo(
                    f"C{k}{carrera}{i}", fecha=fecha, llegadas=(3,), perdida=p,
                    jinete=f"J{i}", race=carrera, finish=1 if i == ganador else 2 + i,
                ))
        reuniones.append({"meta": {"date": date.fromisoformat(fecha), "track": "X", "number": k},
                          "registros": registros})
    return reuniones


def test_ajustar_aprende_factor_tiempo():
    reuniones = _reuniones_sinteticas()
    modelo = ajustar([r["registros"] for r in reuniones], l2=0.1)
    assert modelo.n_carreras == 36
    assert modelo.pesos["tiempo"] > 0.5
    assert modelo.hasta == max(r["meta"]["date"] for r in reuniones).isoformat()


def test_modelo_guardar_cargar(tmp_path):
    m = Modelo(pesos={"forma": 0.5}, n_carreras=3, entrenado="x", hasta="2026-11-08")
    m.guardar(tmp_path / "m.json")
    assert Modelo.cargar(tmp_path / "m.json") == m
    assert Modelo.cargar(tmp_path / "no.json") is None


def test_predictor_probabilidades_y_explicacion():
    caballos = [_caballo("A", llegadas=(1,), perdida=0), _caballo("B", llegadas=(6,), perdida=6)]
    pred = Predictor(Modelo(pesos={"tiempo": 1.0, "llegada": 0.5}), EstadisticasPersonas())
    probs = pred.probabilidades(caballos)
    assert sum(probs) == pytest.approx(1.0)
    assert probs[0] > probs[1]
    aportes = dict(pred.explicar(caballos, 0))
    assert aportes["Tiempo vs. ganador"] > 0
    assert pred.aplica(caballos)
    assert not pred.aplica([{"horse_name": "PDF"}])


def test_laboratorio_walk_forward_y_guardado(tmp_path):
    res = laboratorio.evaluar(_reuniones_sinteticas(), min_entreno=3, l2=0.1)
    t = res["totales"]
    assert t["carreras"] == 18  # 3 reuniones evaluadas x 6 carreras
    assert t["nuevo_1"] / t["carreras"] > t["azar_1"] / t["carreras"]
    assert sum(f["Caballos"] for f in res["calibracion"]) == 18 * 5
    res["rango"] = [date(2026, 9, 1), date(2026, 10, 22)]
    laboratorio.guardar(res, tmp_path / "lab.json")
    cargado = laboratorio.cargar(tmp_path / "lab.json")
    assert cargado["reuniones"][0]["Fecha"] == res["reuniones"][0]["Fecha"]
    assert cargado["rango"][0] == date(2026, 9, 1)


def test_calibracion_tramos():
    tabla = laboratorio.tabla_calibracion([(0.02, 0), (0.04, 1), (0.5, 1)])
    assert tabla[0]["Caballos"] == 2 and tabla[0]["Ganó de verdad"] == 0.5
    assert tabla[-1]["Tramo"] == "45%–100%"
    assert np.isclose(tabla[-1]["Prob. modelo"], 0.5)
