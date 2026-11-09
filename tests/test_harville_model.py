"""Tests del Módulo 3 — modelo de Harville y value bets."""

import pytest

from src.harville_model import (
    detect_value_bets,
    fill_missing_strengths,
    form_strength,
    fractional_to_decimal,
    harville_win_probabilities,
    implied_probability,
    kelly_fraction,
    normalize_probabilities,
)


def test_implied_probability():
    assert implied_probability(2.0) == pytest.approx(0.5)
    assert implied_probability(4.0) == pytest.approx(0.25)
    with pytest.raises(ValueError):
        implied_probability(0)


def test_normalize_probabilities_elimina_overround():
    # Mercado con overround: suma > 1.
    probs = [0.55, 0.30, 0.20]
    normalizadas = normalize_probabilities(probs)
    assert sum(normalizadas) == pytest.approx(1.0)
    assert normalizadas[0] == pytest.approx(0.55 / 1.05)


def test_harville_suma_uno():
    probs = harville_win_probabilities([0.4, 0.3, 0.2, 0.1])
    assert sum(probs) == pytest.approx(1.0)
    assert probs[0] == pytest.approx(0.4)


def test_harville_fuerzas_proporcionales():
    probs = harville_win_probabilities([2, 1, 1])
    assert probs == pytest.approx([0.5, 0.25, 0.25])


def test_harville_errores():
    assert harville_win_probabilities([]) == []
    with pytest.raises(ValueError):
        harville_win_probabilities([0, 0, 0])
    with pytest.raises(ValueError):
        harville_win_probabilities([0.5, -0.1, 0.6])


def test_detect_value_bets():
    modelo = [0.40, 0.30, 0.30]
    mercado = [0.30, 0.40, 0.30]
    bets = detect_value_bets(modelo, mercado, threshold=0.05)
    assert len(bets) == 1
    assert bets[0]["index"] == 0
    assert bets[0]["edge"] == pytest.approx(0.10)


def test_detect_value_bets_sin_valor():
    modelo = [0.34, 0.33, 0.33]
    mercado = [0.33, 0.34, 0.33]
    assert detect_value_bets(modelo, mercado) == []


def test_detect_value_bets_longitudes_distintas():
    with pytest.raises(ValueError):
        detect_value_bets([0.5], [0.5, 0.5])


def test_kelly_fraction():
    # p=0.5, cuota 3.0 -> f* = (2*0.5 - 0.5)/2 = 0.25
    assert kelly_fraction(0.5, 3.0) == pytest.approx(0.25)
    # Sin ventaja -> 0 (nunca negativo).
    assert kelly_fraction(0.4, 2.0) == 0.0
    # Cuota inválida -> 0.
    assert kelly_fraction(0.9, 1.0) == 0.0


def test_form_strength():
    # Sin datos -> None (no se inventa nada).
    assert form_strength(None, None, []) is None
    # Solo estadística: (2+1)/(8+2) = 0.3.
    assert form_strength(2, 8) == pytest.approx(0.3)
    # Solo historial: 0.5 · exp(-0.1 · 2).
    assert form_strength(None, None, [0, 4]) == pytest.approx(0.5 * 0.8187307)
    # Más cuerpos perdidos -> menos fuerza.
    assert form_strength(1, 5, [1]) > form_strength(1, 5, [10])


def test_fill_missing_strengths():
    assert fill_missing_strengths([0.2, None, 0.4]) == pytest.approx([0.2, 0.3, 0.4])
    assert fill_missing_strengths([None, None]) == [1.0, 1.0]


def test_fractional_to_decimal():
    assert fractional_to_decimal("7-2") == 4.5
    assert fractional_to_decimal("5/1") == 6.0
    assert fractional_to_decimal("evs") == 2.0
    assert fractional_to_decimal("9/4") == 3.25
    assert fractional_to_decimal("NADA") is None
    assert fractional_to_decimal(None) is None
