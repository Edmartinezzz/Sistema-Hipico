"""Módulo 3 — Modelo estadístico de Harville y detección de value bets.

El modelo de Harville asume que cada caballo tiene una "fuerza"
(``strength_i``) y que su tiempo de carrera sigue una distribución
exponencial. Bajo esa suposición, la probabilidad de victoria es:

    P(caballo i gana) = strength_i / Σ_j strength_j

Cuando las fuerzas se derivan de las cuotas del mercado, el modelo
permite comparar la probabilidad estimada con la probabilidad implícita
de la cuota para detectar "value bets" (apuestas con valor esperado
positivo). Toda la información es informativa; el sistema no realiza
apuestas reales.
"""

from __future__ import annotations

import math
import re
from statistics import median
from typing import Any

FRACTION_RE = re.compile(r"^\s*(\d+)\s*[-/]\s*(\d+)\s*$")


def fractional_to_decimal(fractional: str) -> float | None:
    """Convierte una cuota fraccionaria UK a cuota decimal.

    Ejemplos:
        "7-2"  -> 4.5   (7/2 + 1)
        "5/1"  -> 6.0   (5/1 + 1)
        "evs"  -> 2.0   (cuota par)
        "NADA" -> None  (no parseable)
    """
    if fractional is None:
        return None
    texto = str(fractional).strip().lower()
    if texto in {"evs", "ev", "even", "even money", "1-1", "1/1"}:
        return 2.0
    match = FRACTION_RE.match(texto)
    if match:
        numerador, denominador = int(match.group(1)), int(match.group(2))
        if denominador == 0:
            return None
        return numerador / denominador + 1.0
    try:
        valor = float(texto)
        return valor if valor > 0 else None
    except ValueError:
        return None


def implied_probability(odds_decimal: float) -> float:
    """Probabilidad implícita de una cuota decimal: ``1 / odds_decimal``.

    La cuota 2.0 implica probabilidad 0.5. El valor incluye el margen
    de la casa (overround), por lo que las probabilidades de todos los
    competidores suelen sumar más de 1.0; usar
    ``normalize_probabilities`` para eliminar el margen.
    """
    if odds_decimal is None or odds_decimal <= 0:
        raise ValueError(f"Cuota decimal inválida: {odds_decimal}")
    return 1.0 / odds_decimal


def normalize_probabilities(probs: list[float]) -> list[float]:
    """Reescala probabilidades para que sumen 1.0 (elimina el overround).

    La suma de probabilidades implícitas del mercado supera 1.0 por el
    margen de la casa. Dividir cada una entre la suma produce un
    estimado de probabilidad "justa" de mercado.
    """
    total = sum(probs)
    if total <= 0:
        raise ValueError("La suma de probabilidades debe ser positiva")
    return [p / total for p in probs]


def harville_win_probabilities(strengths: list[float]) -> list[float]:
    """Probabilidad de victoria de cada caballo según Harville.

    Fórmula: P(i gana) = strength_i / Σ strengths, derivada de tiempos
    de carrera exponenciales independientes con tasas proporcionales a
    las fuerzas. Devuelve una lista de la misma longitud que
    ``strengths`` cuya suma es 1.0.
    """
    if not strengths:
        return []
    if any(s < 0 for s in strengths):
        raise ValueError("Las fuerzas no pueden ser negativas")
    total = sum(strengths)
    if total <= 0:
        raise ValueError("Al menos una fuerza debe ser positiva")
    return [s / total for s in strengths]


def form_strength(
    wins: int | None,
    starts: int | None,
    lengths_behind: list[float] | None = None,
    k: float = 0.1,
) -> float | None:
    """Fuerza de un caballo según su forma reciente.

    Fórmula: fuerza = (wins + 1) / (starts + 2) · exp(−k · L̄)

    - ``(wins + 1) / (starts + 2)`` es la tasa de victorias suavizada
      (Laplace); sin estadística se usa el valor neutro 0.5.
    - ``L̄`` es la media de cuerpos de desventaja frente al ganador en
      las últimas actuaciones (0 si ganó); sin historial el factor es 1.
    - ``k`` penaliza cada cuerpo perdido (0.1 ≈ −10% por cuerpo).

    Devuelve ``None`` si no hay ningún dato de forma (no se inventan
    datos; el llamador decide el valor por defecto).
    """
    tiene_stats = wins is not None and starts is not None
    cuerpos = [c for c in (lengths_behind or []) if c is not None]
    if not tiene_stats and not cuerpos:
        return None
    tasa = (wins + 1) / (starts + 2) if tiene_stats else 0.5
    factor = math.exp(-k * sum(cuerpos) / len(cuerpos)) if cuerpos else 1.0
    return tasa * factor


def fill_missing_strengths(strengths: list[float | None]) -> list[float]:
    """Completa fuerzas desconocidas con la mediana de la carrera.

    Si ningún caballo tiene datos, todos reciben la misma fuerza (1.0),
    lo que equivale a probabilidades uniformes.
    """
    conocidas = [s for s in strengths if s is not None]
    relleno = median(conocidas) if conocidas else 1.0
    return [relleno if s is None else s for s in strengths]


def detect_value_bets(
    model_probs: list[float],
    market_probs: list[float],
    threshold: float = 0.05,
) -> list[dict[str, Any]]:
    """Detecta caballos donde el modelo supera al mercado.

    Devuelve una lista de dicts ``{"index", "model_prob",
    "market_prob", "edge"}`` para cada caballo con
    ``model_prob - market_prob > threshold``. El ``edge`` es la
    diferencia de probabilidad en puntos (0.05 = 5%).
    """
    if len(model_probs) != len(market_probs):
        raise ValueError("Las listas de probabilidades deben tener la misma longitud")
    value_bets = []
    for i, (p_modelo, p_mercado) in enumerate(zip(model_probs, market_probs)):
        edge = p_modelo - p_mercado
        if edge > threshold:
            value_bets.append(
                {
                    "index": i,
                    "model_prob": p_modelo,
                    "market_prob": p_mercado,
                    "edge": edge,
                }
            )
    return value_bets


def kelly_fraction(prob: float, odds_decimal: float) -> float:
    """Fracción de Kelly para dimensionar una apuesta (informativo).

    Fórmula: f* = (b·p − q) / b, donde ``b = odds_decimal − 1`` es el
    beneficio neto por unidad apostada, ``p`` la probabilidad estimada
    y ``q = 1 − p``. Un valor negativo indica que no hay ventaja y la
    fracción óptima es cero.
    """
    if odds_decimal <= 1:
        return 0.0
    b = odds_decimal - 1.0
    q = 1.0 - prob
    fraccion = (b * prob - q) / b
    return max(fraccion, 0.0)
