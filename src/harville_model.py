"""Modelo de Harville: cuotas → probabilidades, value bets y fracción de Kelly.

Convenciones:

* Cuota decimal :math:`d`: pago total por unidad apostada (incluye la unidad).
  Una cuota fraccionaria UK ``a-b`` equivale a :math:`d = a / b + 1`.
* Probabilidad implícita del mercado: :math:`p = 1 / d`. La suma de las
  probabilidades implícitas de una carrera suele ser mayor que 1; ese exceso
  es el *overround* (margen de la casa o del pool).

Este módulo no depende del extractor, del scraper ni de Streamlit.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Sequence

logger = logging.getLogger(__name__)

_FRACTIONAL_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*[-/:]\s*(\d+(?:[.,]\d+)?)\s*$")
_EVEN_WORDS = {"EVEN", "EVENS", "EVS", "PAR"}


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


def fractional_to_decimal(raw: Any) -> float | None:
    """Convierte una cuota fraccionaria UK a cuota decimal.

    Fórmula: ``a-b`` → :math:`d = a / b + 1`. Ejemplos: ``"7-2"`` → 4.5,
    ``"5/1"`` → 6.0, ``"EVEN"`` → 2.0.

    Acepta los separadores ``-``, ``/`` y ``:``. Devuelve ``None`` si el
    texto no es una fracción válida (incluye denominador cero).
    """
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if text in _EVEN_WORDS:
        return 2.0
    match = _FRACTIONAL_RE.match(text)
    if not match:
        return None
    numerator, denominator = _to_float(match.group(1)), _to_float(match.group(2))
    if denominator <= 0 or numerator < 0:
        return None
    return numerator / denominator + 1.0


def implied_probability(odds_decimal: float) -> float:
    """Probabilidad implícita de una cuota decimal, sin quitar el margen.

    Fórmula: :math:`p = 1 / d`. Una cuota 2.0 implica p = 0.5.

    Raises:
        ValueError: si la cuota no es un número finito mayor que 1.
    """
    if (
        isinstance(odds_decimal, bool)
        or not isinstance(odds_decimal, (int, float))
        or not math.isfinite(odds_decimal)
        or odds_decimal <= 1.0
    ):
        raise ValueError(f"Cuota decimal inválida (debe ser > 1): {odds_decimal!r}")
    return 1.0 / float(odds_decimal)


def overround(probs: Sequence[float]) -> float:
    """Margen del mercado: :math:`\\sum_i p_i - 1` (0 en un mercado justo)."""
    return float(sum(probs)) - 1.0


def normalize_probabilities(probs: Sequence[float]) -> list[float]:
    """Reescala las probabilidades para que sumen 1 (elimina el overround).

    Fórmula: :math:`q_i = p_i / \\sum_j p_j`.

    Raises:
        ValueError: si hay valores negativos o no finitos, o si la suma es 0.
    """
    values = [float(p) for p in probs]
    if not values:
        return []
    if any(not math.isfinite(p) or p < 0 for p in values):
        raise ValueError("Las probabilidades deben ser números finitos >= 0")
    total = sum(values)
    if total <= 0:
        raise ValueError("La suma de las probabilidades debe ser mayor que 0")
    return [p / total for p in values]


def harville_win_probabilities(strengths: Sequence[float]) -> list[float]:
    """Probabilidad de victoria de cada caballo según Harville (1973).

    Si los tiempos de cada caballo son exponenciales con tasa
    :math:`s_i` (su "fuerza"), entonces
    :math:`P(i \\text{ gana}) = s_i / \\sum_j s_j`.

    Las fuerzas pueden ser, por ejemplo, las probabilidades implícitas del
    mercado. Una fuerza 0 corresponde a un caballo sin opciones.
    """
    return normalize_probabilities(strengths)


def harville_exacta_probability(strengths: Sequence[float], first: int, second: int) -> float:
    """Probabilidad de que ``first`` gane y ``second`` llegue segundo.

    Fórmula de Harville:
    :math:`P(i, j) = p_i \\cdot p_j / (1 - p_i)`, con :math:`p` = probabilidades
    de victoria normalizadas.
    """
    if first == second:
        return 0.0
    p = harville_win_probabilities(strengths)
    if p[first] >= 1.0:
        return 0.0
    return p[first] * p[second] / (1.0 - p[first])


def harville_place_probabilities(strengths: Sequence[float], places: int = 3) -> list[float]:
    """Probabilidad de que cada caballo termine entre los ``places`` primeros.

    Aplica Harville de forma recursiva: tras retirar a los caballos ya
    colocados, la probabilidad de que :math:`k` ocupe el siguiente puesto es
    :math:`p_k / (1 - \\sum_{c \\in \\text{colocados}} p_c)`.

    Con ``places=1`` coincide con :func:`harville_win_probabilities`.
    Costo :math:`O(n^{places})`; pensado para ``places <= 3``.
    """
    p = harville_win_probabilities(strengths)
    n = len(p)
    places = max(0, min(places, n))
    result = [0.0] * n

    def recurse(placed: tuple[int, ...], prob: float, used: float) -> None:
        remaining = 1.0 - used
        if remaining <= 1e-15:
            return
        for k in range(n):
            if k in placed or p[k] == 0:
                continue
            prob_k = prob * p[k] / remaining
            result[k] += prob_k
            if len(placed) + 1 < places:
                recurse(placed + (k,), prob_k, used + p[k])

    if places:
        recurse((), 1.0, 0.0)
    return result


def detect_value_bets(
    model_probs: Sequence[float],
    market_probs: Sequence[float],
    threshold: float = 0.05,
) -> list[dict]:
    """Detecta caballos cuyo modelo supera al mercado por más de ``threshold``.

    Edge: :math:`e_i = p^{modelo}_i - p^{mercado}_i`. Se reporta el caballo
    ``i`` si :math:`e_i > \\text{threshold}`. Los valores ``None`` se ignoran.

    Returns:
        Lista ordenada por edge descendente de dicts con ``index``,
        ``model_prob``, ``market_prob``, ``edge`` y ``fair_odds``
        (:math:`1 / p^{modelo}`).
    """
    if len(model_probs) != len(market_probs):
        raise ValueError("model_probs y market_probs deben tener la misma longitud")
    bets = []
    for index, (model, market) in enumerate(zip(model_probs, market_probs)):
        if model is None or market is None:
            continue
        edge = float(model) - float(market)
        if edge > threshold:
            bets.append(
                {
                    "index": index,
                    "model_prob": float(model),
                    "market_prob": float(market),
                    "edge": edge,
                    "fair_odds": 1.0 / model if model > 0 else None,
                }
            )
    bets.sort(key=lambda bet: bet["edge"], reverse=True)
    return bets


def kelly_fraction(prob: float, odds_decimal: float) -> float:
    """Fracción de Kelly del bankroll a apostar (solo informativo).

    Fórmula: :math:`f^* = (b \\cdot p - q) / b`, donde :math:`b = d - 1` es la
    ganancia neta por unidad, :math:`p` la probabilidad de ganar y
    :math:`q = 1 - p`. Si :math:`f^* \\le 0` no hay ventaja y se devuelve 0.

    Advertencia: es una referencia matemática, no una recomendación de apuesta.
    """
    if not 0.0 <= prob <= 1.0:
        raise ValueError(f"Probabilidad fuera de [0, 1]: {prob!r}")
    if odds_decimal is None or not math.isfinite(odds_decimal) or odds_decimal <= 1.0:
        raise ValueError(f"Cuota decimal inválida (debe ser > 1): {odds_decimal!r}")
    b = odds_decimal - 1.0
    fraction = (b * prob - (1.0 - prob)) / b
    return max(0.0, fraction)
