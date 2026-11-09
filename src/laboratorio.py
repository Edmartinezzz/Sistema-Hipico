"""Módulo 11 — Laboratorio: evaluación honesta del modelo.

Validación cronológica (*walk-forward*): para predecir la reunión ``k``
el modelo se entrena **solo** con las reuniones anteriores, y las
estadísticas de jinetes/entrenadores usan fechas previas. Así los
aciertos medidos son los que se habrían obtenido de verdad ese domingo.

Compara el modelo entrenado con el modelo de forma original y con el
azar, y calcula la calibración (si dice 30%, ¿gana ~30% de las veces?).
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from src.harville_model import fill_missing_strengths, form_strength, harville_win_probabilities
from src.modelo import (
    CARACTERISTICAS,
    L2_DEFECTO,
    EstadisticasPersonas,
    _softmax,
    carreras_entrenables,
    entrenar,
    matriz_carrera,
    preparar_ejemplos,
)


def _prob_forma(caballos: list[dict[str, Any]]) -> list[float]:
    fuerzas = [
        form_strength(c.get("year_wins"), c.get("year_starts"), c.get("lengths_behind"))
        for c in caballos
    ]
    return harville_win_probabilities(fill_missing_strengths(fuerzas))


def _metricas(probs: list[float], ganador: int) -> tuple[int, int, float]:
    orden = sorted(range(len(probs)), key=lambda i: -probs[i])
    return (
        int(orden[0] == ganador),
        int(ganador in orden[:3]),
        -math.log(max(probs[ganador], 1e-9)),
    )


def evaluar(
    reuniones: list[dict[str, Any]],
    min_entreno: int = 3,
    l2: float = L2_DEFECTO,
) -> dict[str, Any]:
    """Evalúa por reunión. ``reuniones``: ``[{"meta": {...}, "registros": [...]}]``
    en orden cronológico (``meta`` con ``date``, ``track``, ``number``)."""
    filas = []
    calibracion: list[tuple[float, int]] = []
    tot = {k: 0.0 for k in ("carreras", "nuevo_1", "nuevo_3", "nuevo_ll",
                            "actual_1", "actual_3", "actual_ll", "azar_1", "azar_3")}
    w_final = np.zeros(len(CARACTERISTICAS))
    for k in range(min_entreno, len(reuniones)):
        previas = [r["registros"] for r in reuniones[:k]]
        stats = EstadisticasPersonas.desde_registros(previas + [reuniones[k]["registros"]])
        w = entrenar(preparar_ejemplos(previas, stats), l2=l2)
        w_final = w
        fila = {"Fecha": reuniones[k]["meta"]["date"], "Hipódromo": reuniones[k]["meta"]["track"],
                "Reunión": reuniones[k]["meta"].get("number"), "Carreras": 0,
                "Nuevo 1er": 0, "Nuevo top3": 0, "Actual 1er": 0, "Actual top3": 0}
        for caballos, ganador in carreras_entrenables(reuniones[k]["registros"]):
            nuevo = list(_softmax(matriz_carrera(caballos, stats) @ w))
            actual = _prob_forma(caballos)
            n1, n3, nll = _metricas(nuevo, ganador)
            a1, a3, all_ = _metricas(actual, ganador)
            fila["Carreras"] += 1
            fila["Nuevo 1er"] += n1
            fila["Nuevo top3"] += n3
            fila["Actual 1er"] += a1
            fila["Actual top3"] += a3
            tot["nuevo_ll"] += nll
            tot["actual_ll"] += all_
            tot["azar_1"] += 1 / len(caballos)
            tot["azar_3"] += min(3, len(caballos)) / len(caballos)
            calibracion += [(p, int(i == ganador)) for i, p in enumerate(nuevo)]
        tot["carreras"] += fila["Carreras"]
        tot["nuevo_1"] += fila["Nuevo 1er"]
        tot["nuevo_3"] += fila["Nuevo top3"]
        tot["actual_1"] += fila["Actual 1er"]
        tot["actual_3"] += fila["Actual top3"]
        filas.append(fila)

    return {
        "reuniones": filas,
        "totales": tot,
        "calibracion": tabla_calibracion(calibracion),
        "pesos_ultimo": {c: float(v) for c, v in zip(CARACTERISTICAS, w_final)},
    }


LABORATORIO_PATH = Path(__file__).resolve().parent.parent / "data" / "laboratorio.json"


def evaluar_archivo() -> dict[str, Any]:
    """Evalúa con todo el archivo histórico (orden cronológico)."""
    from src.archivo import leer, listar
    from src.gaceta_web import meeting_to_records

    reuniones = [
        {"meta": r, "registros": meeting_to_records(leer(r["ruta"]))}
        for r in reversed(listar())
    ]
    resultado = evaluar(reuniones)
    resultado["n_reuniones"] = len(reuniones)
    resultado["rango"] = (
        [reuniones[0]["meta"]["date"], reuniones[-1]["meta"]["date"]] if reuniones else None
    )
    return resultado


def guardar(resultado: dict[str, Any], ruta: str | Path = LABORATORIO_PATH) -> None:
    """Guarda el resultado en JSON (lo genera la tarea semanal)."""
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    Path(ruta).write_text(
        json.dumps(resultado, default=lambda o: o.isoformat() if isinstance(o, date) else float(o),
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def cargar(ruta: str | Path = LABORATORIO_PATH) -> dict[str, Any] | None:
    """Lee el resultado guardado (fechas como ``date``) o ``None``."""
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for fila in datos["reuniones"]:
        fila["Fecha"] = date.fromisoformat(fila["Fecha"])
    if datos.get("rango"):
        datos["rango"] = [date.fromisoformat(d) for d in datos["rango"]]
    return datos


def tabla_calibracion(
    pares: list[tuple[float, int]], cortes: tuple[float, ...] = (0, .05, .1, .2, .3, .45, 1.01)
) -> list[dict[str, Any]]:
    """Agrupa ``(probabilidad, ganó)`` en tramos: prob. media vs. frecuencia real."""
    tabla = []
    for bajo, alto in zip(cortes, cortes[1:]):
        tramo = [(p, g) for p, g in pares if bajo <= p < alto]
        if tramo:
            tabla.append({
                "Tramo": f"{bajo:.0%}–{min(alto, 1):.0%}",
                "Prob. modelo": sum(p for p, _ in tramo) / len(tramo),
                "Ganó de verdad": sum(g for _, g in tramo) / len(tramo),
                "Caballos": len(tramo),
            })
    return tabla
