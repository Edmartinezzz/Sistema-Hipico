"""Pruebas del modelo de Harville."""

import math

import pytest

from src.harville_model import (
    detect_value_bets,
    fractional_to_decimal,
    harville_exacta_probability,
    harville_place_probabilities,
    harville_win_probabilities,
    implied_probability,
    kelly_fraction,
    normalize_probabilities,
    overround,
)


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [("7-2", 4.5), ("5/1", 6.0), ("9:2", 5.5), ("1-2", 1.5), ("EVEN", 2.0),
     ("evs", 2.0), (" 11 - 4 ", 3.75), ("2,5-1", 3.5)],
)
def test_fractional_to_decimal(raw, esperado):
    assert fractional_to_decimal(raw) == pytest.approx(esperado)


@pytest.mark.parametrize("raw", [None, "", "NADA", "3.5", "5/0", "abc", "7-"])
def test_fractional_to_decimal_invalido(raw):
    assert fractional_to_decimal(raw) is None


def test_cuota_2_implica_probabilidad_0_5():
    assert implied_probability(2.0) == pytest.approx(0.5)
    assert implied_probability(4.5) == pytest.approx(1 / 4.5)


@pytest.mark.parametrize("cuota", [1.0, 0.5, 0, -3, float("nan"), float("inf"), True, "2"])
def test_implied_probability_rechaza_cuotas_invalidas(cuota):
    with pytest.raises(ValueError):
        implied_probability(cuota)


def test_normalize_probabilities_suma_1_y_elimina_overround():
    mercado = [implied_probability(d) for d in (2.0, 3.0, 4.0, 6.0)]
    assert overround(mercado) > 0
    normalizadas = normalize_probabilities(mercado)
    assert sum(normalizadas) == pytest.approx(1.0)
    assert overround(normalizadas) == pytest.approx(0.0, abs=1e-12)
    # Conserva el orden relativo.
    assert normalizadas == sorted(normalizadas, reverse=True)
    assert normalizadas[0] / normalizadas[1] == pytest.approx(mercado[0] / mercado[1])


def test_normalize_probabilities_casos_borde():
    assert normalize_probabilities([]) == []
    assert normalize_probabilities([0.2, 0, 0.2]) == [0.5, 0.0, 0.5]
    for invalido in ([0, 0], [-0.1, 0.5], [float("nan"), 0.3]):
        with pytest.raises(ValueError):
            normalize_probabilities(invalido)


def test_harville_win_probabilities():
    probs = harville_win_probabilities([3, 1, 1])
    assert probs == pytest.approx([0.6, 0.2, 0.2])
    assert sum(probs) == pytest.approx(1.0)


def test_harville_exacta_conocida():
    # p = [0.5, 0.3, 0.2] → P(0 gana, 1 segundo) = 0.5 * 0.3 / 0.5 = 0.3
    fuerzas = [0.5, 0.3, 0.2]
    assert harville_exacta_probability(fuerzas, 0, 1) == pytest.approx(0.3)
    assert harville_exacta_probability(fuerzas, 1, 1) == 0.0
    total = sum(
        harville_exacta_probability(fuerzas, i, j)
        for i in range(3) for j in range(3) if i != j
    )
    assert total == pytest.approx(1.0)


def test_harville_place_probabilities():
    fuerzas = [0.5, 0.3, 0.2]
    assert harville_place_probabilities(fuerzas, places=1) == pytest.approx([0.5, 0.3, 0.2])
    top2 = harville_place_probabilities(fuerzas, places=2)
    # P(0 en top2) = 0.5 + 0.3*0.5/0.7 + 0.2*0.5/0.8
    assert top2[0] == pytest.approx(0.5 + 0.15 / 0.7 + 0.1 / 0.8)
    assert sum(top2) == pytest.approx(2.0)
    # Con 3 caballos todos terminan entre los 3 primeros.
    assert harville_place_probabilities(fuerzas, places=3) == pytest.approx([1.0, 1.0, 1.0])
    assert sum(harville_place_probabilities([4, 3, 2, 1, 1], places=3)) == pytest.approx(3.0)


def test_harville_place_con_caballo_sin_opciones():
    probs = harville_place_probabilities([1, 1, 0], places=2)
    assert probs == pytest.approx([1.0, 1.0, 0.0])
    assert harville_place_probabilities([1, 1, 0], places=3) == pytest.approx([1.0, 1.0, 1.0])
    assert harville_place_probabilities([2, 0, 0], places=2) == pytest.approx([1.0, 0.5, 0.5])


def test_exacta_con_fuerza_cero_en_segundo_lugar():
    assert harville_exacta_probability([1, 0], 0, 1) == pytest.approx(1.0)
    assert harville_exacta_probability([1, 0], 1, 0) == 0.0
    assert harville_exacta_probability([1, 0, 0], 0, 2) == pytest.approx(0.5)


def test_detect_value_bets():
    modelo = [0.40, 0.30, 0.20, 0.10]
    mercado = [0.45, 0.20, 0.19, None]
    apuestas = detect_value_bets(modelo, mercado, threshold=0.05)
    assert [a["index"] for a in apuestas] == [1]
    assert apuestas[0]["edge"] == pytest.approx(0.10)
    assert apuestas[0]["fair_odds"] == pytest.approx(1 / 0.30)
    # Umbral 0 incluye también el caballo 2, ordenado por edge.
    indices = [a["index"] for a in detect_value_bets(modelo, mercado, threshold=0.0)]
    assert indices == [1, 2]


def test_detect_value_bets_longitudes_distintas():
    with pytest.raises(ValueError):
        detect_value_bets([0.5], [0.5, 0.5])


def test_kelly_fraction():
    # p = 0.5, d = 3 → b = 2 → f = (2*0.5 - 0.5)/2 = 0.25
    assert kelly_fraction(0.5, 3.0) == pytest.approx(0.25)
    # Sin ventaja (apuesta justa o negativa) → 0.
    assert kelly_fraction(0.5, 2.0) == pytest.approx(0.0)
    assert kelly_fraction(0.2, 3.0) == 0.0
    assert math.isclose(kelly_fraction(1.0, 2.0), 1.0)
    for prob, cuota in ((1.5, 2.0), (-0.1, 2.0), (0.5, 1.0), (0.5, float("nan"))):
        with pytest.raises(ValueError):
            kelly_fraction(prob, cuota)


@pytest.mark.parametrize(("first", "second"), [(-1, 0), (0, -1), (3, 0)])
def test_exacta_rechaza_indices_fuera_de_rango(first, second):
    with pytest.raises(IndexError):
        harville_exacta_probability([0.5, 0.3, 0.2], first, second)
