"""Pipeline completo: gaveta PDF → enriquecimiento → modelo → resultados.

Lo usa ``src/app.py`` y no depende de Streamlit, así se puede probar aparte.

Modelo usado para la "Prob. modelo"
-----------------------------------
El mercado aporta una probabilidad base :math:`m_i` (implícita y sin
overround). Si se conoce el historial del caballo (``starts`` y ``wins``, del
récord de la gaveta o del enriquecimiento), se combina con su tasa de
victorias mediante un promedio bayesiano:

.. math::

    s_i = \\frac{wins_i + k \\cdot m_i}{starts_i + k}

donde :math:`k` (``prior_weight``) indica cuántas carreras "vale" la opinión
del mercado. Las fuerzas :math:`s_i` se convierten en probabilidades de
victoria con Harville (:math:`s_i / \\sum s_j`). Sin historial, :math:`s_i = m_i`.

Es una heurística transparente y sencilla, no una predicción garantizada.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from src import database, harville_model, pdf_extractor, scraper

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.05
DEFAULT_PRIOR_WEIGHT = 5.0
SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "samples" / "historial_ejemplo.csv"

_STARTS_KEYS = ("starts", "runs", "races", "carreras", "salidas", "corridas")
_WINS_KEYS = ("wins", "victorias", "ganadas", "primeros")


def parse_record(raw: Any) -> dict[str, int] | None:
    """Interpreta un récord ``carreras-1.º-2.º-3.º`` (por ejemplo ``"12-4-3-2"``).

    Devuelve ``None`` si no tiene exactamente cuatro números o si es
    incoherente (más llegadas en el podio que carreras).
    """
    if raw is None:
        return None
    numbers = [int(n) for n in re.findall(r"\d+", str(raw))]
    if len(numbers) != 4:
        return None
    starts, wins, places, shows = numbers
    if wins + places + shows > starts:
        return None
    return {"starts": starts, "wins": wins, "places": places, "shows": shows}


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def form_from_enrichment(data: dict[str, Any] | None) -> dict[str, int] | None:
    """Extrae ``starts`` y ``wins`` de los datos de enriquecimiento, si existen."""
    if not data:
        return None
    starts = next((_as_int(data.get(k)) for k in _STARTS_KEYS if k in data), None)
    wins = next((_as_int(data.get(k)) for k in _WINS_KEYS if k in data), None)
    if starts is None or wins is None or starts < 0 or not 0 <= wins <= starts:
        return None
    return {"starts": starts, "wins": wins}


def analyze_race(
    horses: list[dict[str, Any]],
    enrichments: dict[str, dict[str, Any]] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
) -> list[dict[str, Any]]:
    """Calcula probabilidades de mercado y del modelo, edge y value bets.

    Args:
        horses: caballos de una misma carrera (salida de ``extract_races``).
        enrichments: resultado de ``enrich_horse`` por nombre de caballo.
        threshold: edge mínimo para marcar un value bet.
        prior_weight: peso :math:`k` del mercado frente al historial.

    Returns:
        Una fila por caballo con ``market_prob``, ``model_prob``, ``edge``,
        ``value_bet``, ``kelly``, ``top3_prob`` y los datos de la gaveta.
        Los caballos sin cuota (retirados) quedan con probabilidades ``None``.
    """
    enrichments = enrichments or {}
    priced = [i for i, h in enumerate(horses) if h.get("odds") and h["odds"] > 1]
    market = harville_model.normalize_probabilities(
        [harville_model.implied_probability(horses[i]["odds"]) for i in priced]
    )

    rows: list[dict[str, Any]] = []
    strengths: list[float] = []
    for horse in horses:
        enrichment = enrichments.get(horse.get("horse_name") or "") or {}
        form = form_from_enrichment(enrichment.get("data"))
        form_source = "historial" if form else None
        if form is None:
            form = parse_record(horse.get("record"))
            form_source = "gaveta" if form else None
        rows.append(
            {
                **horse,
                "starts": form["starts"] if form else None,
                "wins": form["wins"] if form else None,
                "form_source": form_source,
                "enrichment_found": bool(enrichment.get("found")),
                "enrichment_source": enrichment.get("source"),
                "market_prob": None,
                "model_prob": None,
                "edge": None,
                "value_bet": False,
                "kelly": None,
                "top3_prob": None,
            }
        )

    for position, index in enumerate(priced):
        row, m = rows[index], market[position]
        row["market_prob"] = m
        if row["starts"]:
            strengths.append((row["wins"] + prior_weight * m) / (row["starts"] + prior_weight))
        else:
            strengths.append(m)

    if priced and sum(strengths) <= 0:
        strengths = list(market)
    if priced:
        model = harville_model.harville_win_probabilities(strengths)
        top3 = harville_model.harville_place_probabilities(strengths, places=3)
        bets = {
            bet["index"]
            for bet in harville_model.detect_value_bets(model, market, threshold)
        }
        for position, index in enumerate(priced):
            row = rows[index]
            row["model_prob"] = model[position]
            row["edge"] = model[position] - market[position]
            row["value_bet"] = position in bets
            row["kelly"] = harville_model.kelly_fraction(model[position], row["odds"])
            row["top3_prob"] = top3[position]
    return rows


class _WarningCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def _collect_warnings() -> Iterator[list[str]]:
    collector = _WarningCollector()
    root = logging.getLogger("src")
    root.addHandler(collector)
    try:
        yield collector.messages
    finally:
        root.removeHandler(collector)


def _group_by_race(horses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    races: dict[Any, dict[str, Any]] = {}
    for horse in horses:
        number = horse.get("race_number")
        race = races.setdefault(
            number,
            {
                "race_number": number,
                "date": horse.get("date"),
                "track": horse.get("track"),
                "distance": horse.get("distance"),
                "surface": horse.get("surface"),
                "horses": [],
            },
        )
        race["horses"].append(horse)
    return list(races.values())


def analyze_pdf(
    pdf_path: str | Path,
    db_path: str | None = None,
    offline: bool = True,
    csv_path: str | Path | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    prior_weight: float = DEFAULT_PRIOR_WEIGHT,
    save: bool = True,
) -> dict[str, Any]:
    """Ejecuta el pipeline completo sobre una gaveta PDF.

    1. Extrae los caballos con :func:`pdf_extractor.extract_races`.
    2. Enriquece cada caballo con :func:`scraper.enrich_horse`.
    3. Guarda la carrera y las inscripciones en SQLite (si ``save``).
    4. Calcula probabilidades y value bets por carrera.

    Returns:
        ``{"races": [...], "enrichment": {nombre: dict}, "warnings": [str]}``.
        Cada carrera trae sus metadatos y ``rows`` (ver :func:`analyze_race`).
    """
    with _collect_warnings() as warnings:
        horses = pdf_extractor.extract_races(str(pdf_path))
        if not horses:
            warnings.append("No se encontraron tablas de caballos en el PDF.")
            return {"races": [], "enrichment": {}, "warnings": warnings}

        database.init_db(db_path)
        enrichment: dict[str, dict[str, Any]] = {}
        for name in dict.fromkeys(h["horse_name"] for h in horses if h.get("horse_name")):
            enrichment[name] = scraper.enrich_horse(
                name, db_path, offline=offline, csv_path=csv_path
            )

        races = _group_by_race(horses)
        for race in races:
            if save:
                _save_race(race, db_path, warnings)
            race["rows"] = analyze_race(race.pop("horses"), enrichment, threshold, prior_weight)
    return {"races": races, "enrichment": enrichment, "warnings": warnings}


def _save_race(race: dict[str, Any], db_path: str | None, warnings: list[str]) -> None:
    if not (race.get("date") and race.get("track") and race.get("race_number") is not None):
        warnings.append(
            f"Carrera {race.get('race_number')}: falta fecha u hipódromo; no se guarda en SQLite."
        )
        return
    try:
        database.save_entries(race, race["horses"], db_path)
    except Exception as exc:  # noqa: BLE001 - guardar es opcional, el análisis sigue
        warnings.append(f"Carrera {race.get('race_number')}: no se pudo guardar ({exc}).")


def horse_detail(name: str, db_path: str | None = None) -> dict[str, Any]:
    """Historial guardado de un caballo (carreras y enriquecimiento)."""
    return database.get_horse_history(name, db_path)
