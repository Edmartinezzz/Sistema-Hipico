"""Módulo 7 — Análisis por carrera (lógica pura, sin Streamlit).

Combina la forma de cada caballo (modelo) con las cuotas opcionales que
introduce el usuario (mercado):

- Prob. modelo: Harville sobre ``form_strength`` (victorias del año +
  cuerpos perdidos en las últimas actuaciones).
- Prob. mercado: ``1 / cuota`` normalizada, solo si TODOS los caballos
  de la carrera tienen cuota (si no, la normalización sería engañosa).
- Edge = modelo − mercado; value bet si edge > umbral.
"""

from __future__ import annotations

from typing import Any

from src.harville_model import (
    detect_value_bets,
    fill_missing_strengths,
    form_strength,
    harville_win_probabilities,
    implied_probability,
    kelly_fraction,
    normalize_probabilities,
)


def _a_entero(valor: Any) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def datos_forma(registro: dict[str, Any]) -> tuple[int | None, int | None, list]:
    """Devuelve ``(wins, starts, lengths_behind)`` de un registro.

    Usa los campos de la gaceta web (``year_wins``/``year_starts``/
    ``lengths_behind``) y, si faltan, los del enriquecimiento CSV
    (columnas ``wins``/``starts``).
    """
    wins, starts = registro.get("year_wins"), registro.get("year_starts")
    if wins is None or starts is None:
        datos = (registro.get("enrichment") or {}).get("data") or {}
        wins, starts = _a_entero(datos.get("wins")), _a_entero(datos.get("starts"))
    return wins, starts, registro.get("lengths_behind") or []


def probabilidades_modelo(caballos: list[dict[str, Any]], predictor: Any = None) -> list[float]:
    """Probabilidad de victoria: modelo entrenado (``modelo.Predictor``) si
    está disponible y hay datos de la gaceta web; si no, forma (Harville)."""
    if predictor is not None and predictor.aplica(caballos):
        return predictor.probabilidades(caballos)
    fuerzas = [form_strength(*datos_forma(c)) for c in caballos]
    return harville_win_probabilities(fill_missing_strengths(fuerzas))


def probabilidades_mercado(cuotas: list[float | None]) -> list[float] | None:
    """Probabilidad justa de mercado, o ``None`` si falta alguna cuota."""
    if not cuotas or any(c is None or c <= 1 for c in cuotas):
        return None
    return normalize_probabilities([implied_probability(c) for c in cuotas])


def analizar_carrera(
    caballos: list[dict[str, Any]],
    cuotas: list[float | None],
    umbral: float = 0.05,
    predictor: Any = None,
) -> list[dict[str, Any]]:
    """Filas de resultado de una carrera, ordenadas por prob. del modelo."""
    modelo = probabilidades_modelo(caballos, predictor)
    mercado = probabilidades_mercado(cuotas)
    value_bets = (
        {v["index"] for v in detect_value_bets(modelo, mercado, threshold=umbral)}
        if mercado
        else set()
    )
    filas = []
    for i, caballo in enumerate(caballos):
        cuota = cuotas[i]
        filas.append(
            {
                "N°": caballo.get("dorsal") or caballo.get("post_position"),
                "Caballo": caballo.get("horse_name"),
                "Jinete": caballo.get("jockey"),
                "Entrenador": caballo.get("trainer"),
                "Récord": caballo.get("record"),
                "Cuota": cuota,
                "Prob. modelo": modelo[i],
                "Prob. mercado": mercado[i] if mercado else None,
                "Edge": modelo[i] - mercado[i] if mercado else None,
                "Kelly": kelly_fraction(modelo[i], cuota) if cuota and cuota > 1 else None,
                "Value bet": i in value_bets,
                "Llegada": caballo.get("finish_position"),
            }
        )
    return sorted(filas, key=lambda f: f["Prob. modelo"], reverse=True)


def agrupar_por_carrera(registros: list[dict[str, Any]]) -> dict[int, list[dict]]:
    """Agrupa registros por número de carrera (0 si se desconoce)."""
    carreras: dict[int, list[dict]] = {}
    for r in registros:
        carreras.setdefault(r.get("race_number") or 0, []).append(r)
    return dict(sorted(carreras.items()))


def efectividad_modelo(registros: list[dict[str, Any]], predictor: Any = None) -> dict[str, int]:
    """Cuántas veces el modelo acertó en las carreras ya corridas.

    Devuelve ``{"corridas", "aciertos_1", "aciertos_top3"}``: carreras con
    ganador conocido, veces que el 1er pick ganó y veces que el ganador
    estuvo entre los 3 primeros picks. Solo usa la forma (sin cuotas).
    """
    corridas = aciertos_1 = aciertos_top3 = 0
    for caballos in agrupar_por_carrera(registros).values():
        ganador = next(
            (c["horse_name"] for c in caballos if c.get("finish_position") == 1), None
        )
        if ganador is None:
            continue
        orden = [
            f["Caballo"]
            for f in analizar_carrera(caballos, [None] * len(caballos), predictor=predictor)
        ]
        corridas += 1
        aciertos_1 += orden[0] == ganador
        aciertos_top3 += ganador in orden[:3]
    return {"corridas": corridas, "aciertos_1": aciertos_1, "aciertos_top3": aciertos_top3}


def _harville_lugar_top3(p: list[float]) -> list[float]:
    """P(top-3) exacta bajo Harville: suma las permutaciones ordenadas
    (i, j, k) en las que el caballo aparece en alguna de las 3 posiciones.
    O(n^3); con ~14 caballos son ~2.700 operaciones, trivial."""
    n = len(p)
    if n <= 3:
        return [1.0] * n  # con 3 o menos caballos todos entran al top-3
    lugar = [0.0] * n
    for i in range(n):
        rem1 = 1.0 - p[i]
        if rem1 <= 0:
            continue
        for j in range(n):
            if j == i:
                continue
            pij = p[i] * p[j] / rem1
            rem2 = rem1 - p[j]
            if rem2 <= 0:
                continue
            for k in range(n):
                if k == i or k == j:
                    continue
                trio = pij * p[k] / rem2
                lugar[i] += trio
                lugar[j] += trio
                lugar[k] += trio
    return lugar


def confianza_top(prob: float, segundo: float | None = None) -> str:
    """Nivel de confianza del 1er pick según su probabilidad y margen."""
    if prob >= 0.35 and (segundo is None or prob - segundo >= 0.10):
        return "Alta"
    if prob >= 0.22:
        return "Media"
    return "Baja"


def cobertura_5y6(p: list[float], objetivo: float = 0.55) -> dict[str, Any]:
    """Menor grupo de caballos (por orden de probabilidad) que cubre al
    ganador Y al segundo en cualquier orden — la apuesta «5y6».

    P(ambos en el grupo) = Σ_{i≠j ∈ S} p_i · p_j / (1 − p_i), exacta bajo
    Harville. Devuelve ``{"indices", "cobertura", "objetivo"}``; si ni con
    todos los caballos se llega al objetivo, devuelve el grupo completo.
    """
    orden = sorted(range(len(p)), key=lambda i: p[i], reverse=True)
    mejor = {"indices": orden, "cobertura": 0.0, "objetivo": objetivo}
    for k in range(1, len(orden) + 1):
        grupo = orden[:k]
        dentro = set(grupo)
        cob = 0.0
        for i in grupo:
            rem = 1.0 - p[i]
            if rem <= 0:
                continue
            for j in grupo:
                if j != i:
                    cob += p[i] * p[j] / rem
        mejor = {"indices": grupo, "cobertura": cob, "objetivo": objetivo}
        if cob >= objetivo:
            break
    return mejor


def exactas_top(p: list[float], nombres: list[str], top: int = 3) -> list[dict[str, Any]]:
    """Las ``top`` exactas más probables (P(i 1° y j 2°) bajo Harville)."""
    combos = []
    for i, pi in enumerate(p):
        rem = 1.0 - pi
        if rem <= 0:
            continue
        for j, pj in enumerate(p):
            if i != j:
                combos.append({"1°": nombres[i], "2°": nombres[j], "Prob.": pi * pj / rem})
    combos.sort(key=lambda c: c["Prob."], reverse=True)
    return combos[:top]


def pronostico_carrera(filas: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumen de pronóstico de una carrera a partir de ``analizar_carrera``
    (filas ya ordenadas por probabilidad descendente)."""
    p = [f["Prob. modelo"] for f in filas]
    nombres = [f["Caballo"] for f in filas]
    lugar3 = _harville_lugar_top3(p)
    for f, pl in zip(filas, lugar3):
        f["Prob. top3"] = pl
    segundo = p[1] if len(p) > 1 else None
    combo = cobertura_5y6(p)
    return {
        "top3": filas[:3],
        "confianza": confianza_top(p[0], segundo),
        "combo_5y6": combo,
        "combo_nombres": [nombres[i] for i in combo["indices"]],
        "exactas": exactas_top(p, nombres),
    }


def resumen_reunion(
    registros: list[dict[str, Any]],
    cuotas: dict[tuple[int, str], float | None],
    umbral: float = 0.05,
    predictor: Any = None,
) -> list[dict[str, Any]]:
    """Una fila por carrera: picks del modelo, value bets y ganador real."""
    filas = []
    for numero, caballos in agrupar_por_carrera(registros).items():
        resultado = analizar_carrera(
            caballos,
            [cuotas.get((numero, c["horse_name"])) for c in caballos],
            umbral,
            predictor,
        )
        ganador = next(
            (c["horse_name"] for c in caballos if c.get("finish_position") == 1),
            None,
        )
        filas.append(
            {
                "Carrera": numero or "-",
                "Dist.": caballos[0].get("distance"),
                "Inscritos": len(caballos),
                "1er pick": resultado[0]["Caballo"],
                "Prob. 1er pick": resultado[0]["Prob. modelo"],
                "2do pick": resultado[1]["Caballo"] if len(resultado) > 1 else None,
                "Value bets": ", ".join(f["Caballo"] for f in resultado if f["Value bet"])
                or None,
                "Ganador real": ganador,
            }
        )
    return filas
