"""Dashboard Streamlit: sube una gaveta PDF y analiza probabilidades y value bets.

Ejecutar desde la raíz del repositorio::

    streamlit run src/app.py
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # `streamlit run src/app.py` solo agrega src/ al path
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import database, pipeline, sample_data  # noqa: E402

logger = logging.getLogger(__name__)

COLUMNS = {
    "post_position": "#",
    "horse_name": "Caballo",
    "jockey": "Jinete",
    "odds_raw": "Cuota",
    "model_prob": "Prob. modelo",
    "market_prob": "Prob. mercado",
    "edge": "Edge",
    "value_bet": "Value bet",
    "top3_prob": "Prob. top 3",
    "kelly": "Kelly",
    "record": "Récord",
    "form_source": "Forma desde",
}
PERCENT_COLUMNS = ["Prob. modelo", "Prob. mercado", "Edge", "Prob. top 3", "Kelly"]
VALUE_BET_STYLE = "background-color: #c8f7c5; color: #0b3d0b"


def _db_path() -> str:
    return os.getenv("HORSE_DB_PATH", database.DEFAULT_DB_PATH)


def race_table(rows: list[dict]) -> pd.DataFrame:
    """Tabla de resultados de una carrera con los nombres de columna en español."""
    frame = pd.DataFrame(rows)
    for column in COLUMNS:
        if column not in frame:
            frame[column] = None
    frame = frame[list(COLUMNS)].rename(columns=COLUMNS)
    frame["Value bet"] = frame["Value bet"].map({True: "Sí", False: ""})
    for column in PERCENT_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    text_columns = [c for c in frame.columns if c not in PERCENT_COLUMNS and c != "#"]
    frame[text_columns] = frame[text_columns].astype(object).where(
        frame[text_columns].notna(), "—"
    )
    return frame


def _style(frame: pd.DataFrame):
    def highlight(row: pd.Series) -> list[str]:
        return [VALUE_BET_STYLE if row["Value bet"] == "Sí" else ""] * len(row)

    return frame.style.apply(highlight, axis=1).format(
        {c: "{:.1%}" for c in PERCENT_COLUMNS}, na_rep="—"
    )


def _save_upload(uploaded) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="gaveta_", suffix=".pdf", delete=False)
    with handle:
        handle.write(uploaded.getvalue())
    return Path(handle.name)


def _save_csv_upload(uploaded) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="historial_", suffix=".csv", delete=False)
    with handle:
        handle.write(uploaded.getvalue())
    return Path(handle.name)


def _run_analysis(pdf_path: Path, label: str, options: dict) -> None:
    with st.spinner(f"Analizando {label}…"):
        result = pipeline.analyze_pdf(pdf_path, db_path=_db_path(), **options)
    st.session_state["result"] = result
    st.session_state["label"] = label


def _sidebar() -> dict:
    st.sidebar.header("Opciones")
    threshold = st.sidebar.slider(
        "Edge mínimo para value bet",
        min_value=0.0,
        max_value=0.20,
        value=pipeline.DEFAULT_THRESHOLD,
        step=0.01,
        format="%.2f",
        help="Diferencia mínima entre la prob. del modelo y la del mercado.",
    )
    prior_weight = st.sidebar.slider(
        "Peso del mercado (k)",
        min_value=0.0,
        max_value=30.0,
        value=pipeline.DEFAULT_PRIOR_WEIGHT,
        step=1.0,
        help="Cuántas carreras 'vale' la opinión del mercado frente al historial del caballo.",
    )
    offline = st.sidebar.checkbox(
        "Modo offline (sin internet)",
        value=True,
        help="Solo usa SQLite y el CSV local. Desmárcalo para usar HORSE_DATA_URL.",
    )
    csv_upload = st.sidebar.file_uploader("Historial CSV (opcional)", type=["csv"])
    csv_path = _save_csv_upload(csv_upload) if csv_upload else os.getenv("HORSE_CSV_PATH")
    st.sidebar.caption(f"Base de datos: `{_db_path()}`")
    return {
        "threshold": threshold,
        "prior_weight": prior_weight,
        "offline": offline,
        "csv_path": csv_path,
    }


def _show_results(result: dict) -> None:
    for message in result["warnings"]:
        st.warning(message)
    if not result["races"]:
        st.error("No se encontraron caballos en el PDF. ¿Tiene tablas con texto (no escaneado)?")
        return

    bets = [
        (race["race_number"], row)
        for race in result["races"]
        for row in race["rows"]
        if row["value_bet"]
    ]
    total = sum(len(race["rows"]) for race in result["races"])
    col1, col2, col3 = st.columns(3)
    col1.metric("Carreras", len(result["races"]))
    col2.metric("Caballos", total)
    col3.metric("Value bets", len(bets))
    if bets:
        st.success(
            "Value bets: "
            + "; ".join(f"C{n} {row['horse_name']} (edge {row['edge']:+.1%})" for n, row in bets)
        )
    else:
        st.info("Ningún caballo supera el edge mínimo. Prueba bajar el umbral en la barra lateral.")

    for race in result["races"]:
        details = " · ".join(
            str(v) for v in (race.get("distance"), race.get("surface"), race.get("track"),
                             race.get("date")) if v
        )
        st.subheader(f"Carrera {race['race_number']}" + (f" — {details}" if details else ""))
        table = race_table(race["rows"])
        st.dataframe(_style(table), hide_index=True, height=36 * (len(table) + 1) + 3)

    _show_detail(result)


def _show_detail(result: dict) -> None:
    st.header("Detalle por caballo")
    options = {
        f"Carrera {race['race_number']} — {row['horse_name']}": row
        for race in result["races"]
        for row in race["rows"]
    }
    choice = st.selectbox("Caballo", list(options), key="detalle")
    row = options[choice]
    name = row["horse_name"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Cuota", row.get("odds_raw") or "—")
    col2.metric("Prob. modelo", f"{row['model_prob']:.1%}" if row["model_prob"] else "—")
    col3.metric("Prob. mercado", f"{row['market_prob']:.1%}" if row["market_prob"] else "—")
    col4.metric("Edge", f"{row['edge']:+.1%}" if row["edge"] is not None else "—")
    st.write(
        f"**Jinete:** {row.get('jockey') or '—'} · **Entrenador:** {row.get('trainer') or '—'}"
        f" · **Peso:** {row.get('weight') or '—'} · **Récord:** {row.get('record') or '—'}"
    )

    enrichment = result["enrichment"].get(name) or {}
    if enrichment.get("found"):
        st.markdown(f"**Datos enriquecidos** (fuente: `{enrichment.get('source')}`)")
        st.json(enrichment.get("data") or {})
    else:
        st.caption("Sin datos enriquecidos para este caballo (no está en SQLite ni en el CSV).")

    history = pipeline.horse_detail(name, _db_path())
    if history["entries"]:
        st.markdown("**Carreras guardadas en SQLite**")
        st.dataframe(pd.DataFrame(history["entries"]), hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Análisis de caballos", page_icon="🏇", layout="wide")
    st.title("Análisis estadístico de carreras")
    st.caption(
        "Herramienta educativa: las probabilidades son estimaciones, no garantías. "
        "La fracción de Kelly es solo informativa."
    )
    options = _sidebar()

    uploaded = st.file_uploader("Gaveta en PDF", type=["pdf"])
    col1, col2 = st.columns(2)
    analyze = col1.button("Analizar", type="primary", disabled=uploaded is None, key="analizar")
    sample = col2.button("Usar gaveta de ejemplo", key="ejemplo")

    try:
        if analyze and uploaded is not None:
            _run_analysis(_save_upload(uploaded), uploaded.name, options)
        elif sample:
            path = Path(tempfile.gettempdir()) / "gaveta_ejemplo.pdf"
            sample_data.create_sample_gaveta(path)
            if not options["csv_path"] and pipeline.SAMPLE_CSV.exists():
                options = {**options, "csv_path": pipeline.SAMPLE_CSV}
            _run_analysis(path, "gaveta de ejemplo", options)
    except Exception as exc:  # noqa: BLE001 - nunca dejar la app en blanco
        logger.exception("Error al analizar")
        st.error(f"No se pudo analizar el PDF: {exc}")
        st.session_state.pop("result", None)

    result = st.session_state.get("result")
    if result is None:
        st.info("Sube una gaveta en PDF y pulsa **Analizar**, o prueba con la gaveta de ejemplo.")
        return
    st.caption(f"Resultados de: {st.session_state.get('label')}")
    try:
        _show_results(result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error al mostrar resultados")
        st.error(f"No se pudieron mostrar los resultados: {exc}")


main()
