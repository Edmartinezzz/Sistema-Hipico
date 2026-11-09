"""Módulo 5 — Dashboard Streamlit del Sistema Hípico.

Ejecutar con:  streamlit run src/app.py

Arriba se elige la semana en el calendario y la reunión (se carga sola);
un PDF de gaveta sirve como respaldo. Tres pestañas:

- **Reunión**: cabecera, indicadores, efectividad del modelo y tarjetas
  con el podio del modelo en cada carrera.
- **Carrera**: botones por carrera, tarjetas de caballos con mantilla y
  barra de probabilidad, gráfico modelo vs. mercado, cuotas editables,
  video de la carrera y ficha de cada caballo en una ventana.
- **En vivo**: próxima carrera con sus picks y la señal en vivo.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import quote

# ``streamlit run src/app.py`` agrega ``src/`` al path, no la raíz del repo.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from src import archivo, chat_ia, laboratorio, ocr_gaceta, telegram, ui  # noqa: E402
from src.modelo import MODELO_PATH, NOMBRES, Predictor, entrenar_desde_archivo  # noqa: E402
from src.analisis import (  # noqa: E402
    agrupar_por_carrera,
    analizar_carrera,
    efectividad_modelo,
    pronostico_carrera,
    resumen_reunion,
)
from src.database import (  # noqa: E402
    delete_race_video,
    get_race_video,
    get_setting,
    init_db,
    save_race_video,
    set_setting,
)
from src.gaceta_web import (  # noqa: E402
    GacetaWebError,
    fetch_meeting,
    list_meetings,
    meeting_to_records,
    meetings_for_week,
    scratched,
    week_range,
)
from src.pdf_extractor import extract_races  # noqa: E402
from src.scraper import enrich_horse  # noqa: E402
from src.videos import (  # noqa: E402
    EXTENSIONES_VIDEO,
    SENALES_OFICIALES,
    busqueda_youtube,
    ruta_video_subido,
    tipo_video,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = str(RAIZ / "data" / "hipico.db")
CSV_DIR = str(RAIZ / "data" / "enrichment")
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
ESTADOS = {"finished": "finalizada", "scheduled": "por_correr", "active": "en_curso"}
FORMATO = {
    "Cuota": "{:.2f}",
    "Prob. modelo": "{:.1%}",
    "Prob. mercado": "{:.1%}",
    "Edge": "{:+.1%}",
    "Kelly": "{:.3f}",
    "Prob. 1er pick": "{:.1%}",
    "Llegada": "{:.0f}",
}


# ---------------------------------------------------------------- utilidades


@st.cache_data(ttl=900, show_spinner=False)
def _reuniones_publicadas() -> list[dict]:
    return list_meetings()


def _firma_archivo() -> tuple:
    """Cambia cuando hay reuniones archivadas nuevas o un modelo nuevo."""
    rutas = sorted(p.name for p in archivo.ARCHIVO_DIR.glob("*.json.gz"))
    mtime = MODELO_PATH.stat().st_mtime if MODELO_PATH.exists() else 0
    return (tuple(rutas), mtime)


@st.cache_resource(show_spinner=False)
def _predictor_cache(firma: tuple) -> Predictor | None:
    return Predictor.desde_archivo()


def _predictor() -> Predictor | None:
    """Modelo entrenado + estadísticas, con el historial de la reunión cargada."""
    predictor = _predictor_cache(_firma_archivo())
    if predictor is not None and st.session_state.get("registros"):
        predictor.incorporar(st.session_state["registros"])
    return predictor


@st.cache_data(show_spinner=False)
def _laboratorio_cache(firma: tuple) -> dict | None:
    return laboratorio.cargar()


def _laboratorio() -> dict | None:
    """Resultado precalculado del laboratorio (``data/laboratorio.json``)."""
    mtime = laboratorio.LABORATORIO_PATH.stat().st_mtime if laboratorio.LABORATORIO_PATH.exists() else 0
    return _laboratorio_cache((mtime,))


def _fecha_corta(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d:%d/%m}"


def _html(fragmento: str) -> None:
    st.markdown(fragmento, unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def _fondo_data_uri() -> str:
    """Foto de fondo en base64 (Streamlit no sirve estáticos del proyecto)."""
    import base64

    ruta = RAIZ / "src" / "fondo.jpg"
    if not ruta.exists():
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(ruta.read_bytes()).decode()


def _inyectar_css() -> None:
    """CSS del tema + foto de fondo con velo oscuro para leer el texto."""
    css = ui.CSS
    fondo = _fondo_data_uri()
    if fondo:
        css += (
            "<style>.stApp{background:linear-gradient(rgba(5,14,10,.68),"
            f"rgba(5,14,10,.68)),url('{fondo}') center/cover fixed no-repeat"
            " !important;}</style>"
        )
    _html(css)


def _estado(caballos: list[dict]) -> str | None:
    crudo = caballos[0].get("race_status")
    return ESTADOS.get(crudo, crudo) if crudo else None


def _cuotas_carrera(numero: int, caballos: list[dict]) -> list[float | None]:
    cuotas = st.session_state["cuotas"]
    return [cuotas.get((numero, c["horse_name"])) for c in caballos]


def _cargar_registros(registros: list[dict], origen: str, meta: dict) -> None:
    """Guarda una nueva gaceta en la sesión y reinicia las cuotas."""
    st.session_state["registros"] = registros
    st.session_state["origen"] = origen
    st.session_state["meta"] = meta
    st.session_state["cuotas"] = {
        (r.get("race_number") or 0, r["horse_name"]): r.get("odds") for r in registros
    }
    st.session_state.pop("carrera_sel", None)
    st.session_state.pop("m_carrera", None)


def _ir_a_carrera(numero: int) -> None:
    """Desde la lista de carreras del resumen, abre la sección Carrera."""
    st.session_state["m_sec"] = "Carrera"
    st.session_state["m_carrera"] = numero


def _tabla(filas: list[dict]) -> None:
    df = pd.DataFrame(filas)
    formato = {k: v for k, v in FORMATO.items() if k in df.columns}

    def resaltar(fila: pd.Series) -> list[str]:
        color = "background-color: rgba(212,175,55,.25)" if fila.get("Value bet") else ""
        return [color] * len(fila)

    st.dataframe(df.style.apply(resaltar, axis=1).format(formato, na_rep="-"), hide_index=True)


# ------------------------------------------------------------ carga de datos


def _obtener_reuniones() -> list[dict]:
    """Reuniones de la web + archivo propio; guarda el error para no
    reintentar en cada clic."""
    if "reuniones" not in st.session_state:
        try:
            with st.spinner("Consultando reuniones publicadas..."):
                web = _reuniones_publicadas()
            st.session_state.pop("reuniones_error", None)
        except GacetaWebError as exc:
            web = []
            st.session_state["reuniones_error"] = str(exc)
        st.session_state["reuniones"] = archivo.unir_con_web(web, archivo.listar())
    return st.session_state["reuniones"]


def _ir_a_ultima(fecha: date) -> None:
    st.session_state["semana"] = fecha


def _reintentar() -> None:
    _reuniones_publicadas.clear()
    st.session_state.pop("reuniones", None)


def _cargar_reunion_web(reunion: dict) -> None:
    datos = archivo.buscar(reunion["id"])
    if datos is None:
        try:
            with st.spinner("Descargando inscritos, historial y traqueos..."):
                datos = fetch_meeting(reunion["id"])
        except GacetaWebError as exc:
            st.error(f"No se pudo cargar la reunión: {exc}")
            return
        if archivo.terminada(datos):
            try:
                archivo.guardar_reunion(datos)
            except OSError as exc:
                logger.warning("No se pudo archivar la reunión: %s", exc)
    _cargar_registros(
        meeting_to_records(datos),
        f"web_{reunion['id']}",
        {
            "kicker": f"Reunión {reunion['number']}",
            "track": reunion["track"],
            "date": reunion["date"],
            "number": reunion["number"],
            "retirados": scratched(datos),
            "reunion_id": reunion["id"],
        },
    )


def _preparar_selector() -> list[dict]:
    """Reuniones disponibles + estado inicial del calendario (sin dibujar widgets)."""
    reuniones = _obtener_reuniones()
    if st.session_state.get("reuniones_error"):
        st.warning(
            "No se pudo leer la gaceta web; se muestran las reuniones del archivo. "
            f"Detalle: {st.session_state['reuniones_error']}"
        )
        st.button("Reintentar", on_click=_reintentar)

    # Tras leer una gaceta escaneada: mostrar su reunión sin volver a cargarla.
    if "_semana_pendiente" in st.session_state:
        st.session_state["semana"] = st.session_state.pop("_semana_pendiente")
        pendiente = st.session_state.pop("_reunion_pendiente")
        st.session_state["reunion_sel"] = pendiente
        st.session_state["_reunion_prev"] = pendiente

    if "semana" not in st.session_state:
        hoy = date.today()
        st.session_state["semana"] = (
            hoy if meetings_for_week(hoy, reuniones) or not reuniones
            else reuniones[0]["date"]
        )
    return reuniones


def _aviso_ocr() -> None:
    aviso = st.session_state.get("_aviso_ocr")
    if aviso and st.session_state.get("registros"):
        texto, faltan = aviso
        st.success(texto)
        if faltan:
            detalle = "; ".join(f"C{n}: {', '.join(f)}" for n, f in sorted(faltan.items()))
            st.caption(f"Sin cuota (escríbelas a mano en la carrera): {detalle}")
        if st.button("Ocultar aviso"):
            st.session_state.pop("_aviso_ocr")
            st.rerun()


def _selector_gaceta(offline: bool) -> None:
    """Vista PC: calendario + reunión (carga automática) + PDF, en una fila."""
    reuniones = _preparar_selector()
    col_fecha, col_reunion, col_pdf = st.columns([1.1, 2.2, 0.9], vertical_alignment="bottom")
    with col_fecha:
        dia = st.date_input("Semana", key="semana", format="DD/MM/YYYY")
    with col_reunion:
        semana = _selector_reunion(dia, reuniones)
    with col_pdf.popover("Subir PDF", width="stretch"):
        _cargar_pdf(offline)
    _aviso_ocr()
    _nota_semana(dia, reuniones, semana)


def _nota_semana(dia: date, reuniones: list[dict], semana: list[dict]) -> None:
    if reuniones and not semana:
        lunes, domingo = week_range(dia)
        fechas = [r["date"] for r in reuniones]
        st.caption(
            f"Semana del {_fecha_corta(lunes)} al {_fecha_corta(domingo)}. La web "
            f"conserva reuniones del {min(fechas):%d/%m/%Y} al {max(fechas):%d/%m/%Y}."
        )


def _selector_reunion(dia: date, reuniones: list[dict]) -> list[dict]:
    """Selector de reunión de la semana con carga automática al cambiar."""
    semana = meetings_for_week(dia, reuniones)
    if semana:
        opciones = {r["id"]: r for r in semana}
        if st.session_state.get("reunion_sel") not in opciones:
            st.session_state["reunion_sel"] = semana[-1]["id"]
        sel = st.selectbox(
            "Reunión",
            list(opciones),
            key="reunion_sel",
            format_func=lambda i: (
                f"{_fecha_corta(opciones[i]['date'])} · {opciones[i]['track']} · "
                f"Reunión {opciones[i]['number']}"
            ),
        )
        # Carga automática al cambiar de reunión (sin pisar un PDF cargado).
        if sel != st.session_state.get("_reunion_prev"):
            st.session_state["_reunion_prev"] = sel
            _cargar_reunion_web(opciones[sel])
    elif reuniones:
        st.button(
            f"Sin reuniones esa semana · ir a la última ({reuniones[0]['date']:%d/%m})",
            on_click=_ir_a_ultima,
            args=(reuniones[0]["date"],),
        )
    return semana


def _nombres_reunion(fecha: date | None) -> tuple[dict | None, dict[int, list[str]]]:
    """Reunión (web/archivo) de esa fecha y sus ejemplares por carrera."""
    reunion = next(
        (r for r in st.session_state.get("reuniones", []) if r["date"] == fecha), None
    )
    if reunion is None:
        return None, {}
    _cargar_reunion_web(reunion)
    nombres: dict[int, list[str]] = {}
    for r in st.session_state.get("registros") or []:
        nombres.setdefault(r["race_number"], []).append(r["horse_name"])
    return reunion, nombres


def _leer_cuotas_escaneadas(tmp_path: str) -> None:
    """PDF escaneado: OCR de las cuotas ML + reunión de la web de esa fecha."""
    if not ocr_gaceta.disponible():
        st.warning(
            "El PDF es una imagen escaneada. Para leer sus cuotas instala el OCR: "
            "`pip install rapidocr_onnxruntime==1.4.4`."
        )
        return
    reunion_usada: dict = {}

    def nombres(fecha: date | None) -> dict[int, list[str]]:
        reunion, por_carrera = _nombres_reunion(fecha)
        reunion_usada.update(reunion or {})
        return por_carrera

    pdf_bytes = Path(tmp_path).read_bytes()
    resultado = ocr_gaceta.leer_cache(pdf_bytes)
    if resultado is not None:
        nombres(resultado.get("fecha"))
        st.caption("Este PDF ya fue leído antes: se usan las cuotas guardadas.")
    else:
        barra = st.progress(0.0, text="Preparando OCR (la primera vez tarda un poco)...")

        def progreso(etapa: str, i: int, n: int) -> None:
            barra.progress(i / n, text=f"{etapa}: {i}/{n}")

        resultado = ocr_gaceta.leer_gaceta(tmp_path, nombres, progreso)
        barra.empty()
        ocr_gaceta.guardar_cache(pdf_bytes, resultado)
    if not reunion_usada:
        fecha = resultado["fecha"]
        st.warning(
            "Se leyó la gaceta pero no hay una reunión de la web/archivo con la "
            f"fecha {fecha:%d/%m/%Y}." if fecha else
            "No se pudo leer la fecha de la gaceta escaneada."
        )
        return
    st.session_state["cuotas"].update(resultado["cuotas"])
    st.session_state["_semana_pendiente"] = reunion_usada["date"]
    st.session_state["_reunion_pendiente"] = reunion_usada["id"]
    carreras = agrupar_por_carrera(st.session_state["registros"])
    faltan = {
        n: [c["horse_name"] for c in cab if (n, c["horse_name"]) not in resultado["cuotas"]]
        for n, cab in carreras.items()
    }
    st.session_state["_aviso_ocr"] = (
        f"Gaceta escaneada leída: {len(resultado['cuotas'])} cuotas ML en "
        f"{len(resultado['carreras'])} carreras de la reunión del "
        f"{reunion_usada['date']:%d/%m/%Y}. Ya están puestas en cada carrera.",
        {n: f for n, f in faltan.items() if f},
    )
    st.rerun()


def _cargar_pdf(offline: bool) -> None:
    pdf_subido = st.file_uploader("PDF de gaveta", type=["pdf"])
    st.caption("Si la gaceta es escaneada, se leen sus cuotas ML (tarda unos minutos).")
    if pdf_subido is None or not st.button("Analizar PDF", type="primary"):
        return
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_subido.getbuffer())
        tmp_path = tmp.name
    try:
        with st.spinner("Extrayendo caballos..."):
            registros = extract_races(tmp_path)
            for r in registros:
                r["enrichment"] = enrich_horse(
                    r["horse_name"], DB_PATH, offline=offline, csv_dir=CSV_DIR
                )
        if not registros:
            _leer_cuotas_escaneadas(tmp_path)
            return
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ in {"RerunException", "StopException"}:
            raise
        logger.exception("Fallo al procesar el PDF")
        st.error(f"No se pudo procesar el PDF: {exc}")
        return
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    _cargar_registros(
        registros,
        f"pdf_{pdf_subido.name}",
        {"kicker": "Gaceta PDF", "track": pdf_subido.name, "date": None,
         "number": None, "retirados": []},
    )


# -------------------------------------------------------------------- videos


def _panel_video(
    track: str | None,
    fecha_iso: str | None,
    carrera: int | None,
    reunion: int | None,
    web_url: str | None,
    clave: str,
    en_dialogo: bool = False,
    por_correr: bool = False,
) -> None:
    """Reproductor de la carrera + formulario para guardar un video."""
    if not (track and fecha_iso and carrera):
        st.caption("Videos disponibles para reuniones cargadas desde la web.")
        return
    alcance = "fragment" if en_dialogo else "app"
    guardado = get_race_video(DB_PATH, track, fecha_iso, carrera)
    fuente = web_url or guardado
    tipo = tipo_video(fuente)

    if tipo in {"youtube", "archivo"}:
        inicio = st.number_input(
            "Empezar en (segundos)", min_value=0, step=5, key=f"{clave}_inicio"
        )
        st.video(fuente, start_time=int(inicio))
    elif tipo == "enlace":
        st.link_button("Abrir video de la carrera", fuente, type="primary")
    elif por_correr:
        st.info("Esta carrera aún no se corre: mírala en la pestaña **En vivo**.")
    else:
        st.caption("Aún no hay video para esta carrera.")

    if guardado and st.button("Quitar video guardado", key=f"{clave}_quitar"):
        delete_race_video(DB_PATH, track, fecha_iso, carrera)
        st.rerun(scope=alcance)

    fecha_txt = f"{date.fromisoformat(fecha_iso):%d/%m/%Y}"
    st.link_button(
        "Buscar la carrera en YouTube",
        busqueda_youtube(track, fecha_txt, carrera, reunion),
    )
    with st.expander("Agregar o cambiar video", expanded=False):
        with st.form(f"{clave}_form", clear_on_submit=True, border=False):
            enlace = st.text_input("Enlace (YouTube, MP4, Facebook...)")
            subido = st.file_uploader(
                "o sube un archivo de video",
                type=[e.lstrip(".") for e in EXTENSIONES_VIDEO],
            )
            if st.form_submit_button("Guardar video", type="primary"):
                if subido is not None:
                    destino = ruta_video_subido(track, fecha_iso, carrera, subido.name)
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    destino.write_bytes(subido.getbuffer())
                    save_race_video(DB_PATH, track, fecha_iso, carrera, str(destino))
                    st.rerun(scope=alcance)
                elif tipo_video(enlace):
                    save_race_video(DB_PATH, track, fecha_iso, carrera, enlace.strip())
                    st.rerun(scope=alcance)
                else:
                    st.error("Escribe un enlace válido (http/https) o sube un archivo.")


# --------------------------------------------------------------- pestañas


def _tab_reunion(umbral: float) -> None:
    registros = st.session_state["registros"]
    meta = st.session_state["meta"]
    carreras = agrupar_por_carrera(registros)
    estados = [_estado(c) for c in carreras.values()]
    chips = [ui.chip(f"{len(carreras)} carreras", "info")]
    if estados.count("por_correr"):
        chips.append(ui.chip(f"{estados.count('por_correr')} por correr", "por_correr"))
    if estados.count("finalizada"):
        chips.append(ui.chip(f"{estados.count('finalizada')} finalizadas", "finalizada"))
    subtitulo = ui.fecha_larga(meta["date"]).capitalize() if meta.get("date") else "Gaceta cargada desde PDF"
    _html(ui.hero(meta["kicker"], str(meta["track"]).title(), subtitulo, chips))

    predictor = _predictor()
    resumen = resumen_reunion(registros, st.session_state["cuotas"], umbral, predictor)
    n_value = sum(len(r["Value bets"].split(", ")) for r in resumen if r["Value bets"])
    efect = _efectividad_honesta(registros, meta, predictor)
    cols = st.columns(4)
    cols[0].metric("Inscritos", len(registros), border=True)
    cols[1].metric("Retirados", len(meta.get("retirados") or []), border=True)
    cols[2].metric("Value bets", n_value, border=True, help="Requiere escribir cuotas en la pestaña Carrera.")
    if efect["corridas"]:
        cols[3].metric(
            "1er pick ganó",
            f"{efect['aciertos_1']}/{efect['corridas']}",
            f"Top 3: {efect['aciertos_top3']}/{efect['corridas']}",
            delta_color="off",
            border=True,
            help="Carreras ya corridas en que el favorito del modelo ganó; "
                 "abajo, cuántas veces el ganador estuvo entre sus 3 picks. "
                 + efect["nota"],
        )
    else:
        cols[3].metric("Carreras", len(carreras), border=True)

    st.subheader("Podio del modelo por carrera")
    st.caption("Abre la pestaña **Carrera** para ver cada caballo, el gráfico y el video.")
    grid = st.columns(3)
    for i, (numero, caballos) in enumerate(carreras.items()):
        filas = analizar_carrera(caballos, _cuotas_carrera(numero, caballos), umbral, predictor)
        ganador = next((c["horse_name"] for c in caballos if c.get("finish_position") == 1), None)
        with grid[i % 3]:
            _html(ui.race_card(
                numero or "-",
                caballos[0].get("distance"),
                _estado(caballos),
                filas,
                ganador,
                [f["Caballo"] for f in filas if f["Value bet"]],
            ))

    if meta.get("retirados"):
        with st.expander(f"Retirados ({len(meta['retirados'])})"):
            for r in meta["retirados"]:
                st.write(f"Carrera {r['race_number']}: {r['horse_name']}")
    with st.expander("Tabla resumen"):
        _tabla(resumen)


def _efectividad_honesta(registros: list[dict], meta: dict, predictor: Predictor | None) -> dict:
    """Aciertos del modelo en la reunión sin "hacer trampa".

    Si la reunión se usó para entrenar el modelo, se toma el resultado de
    la validación cronológica del laboratorio (modelo entrenado solo con
    reuniones anteriores). Si es nueva, se calcula en vivo.
    """
    fecha = meta.get("date")
    hasta = predictor.modelo.hasta if predictor else ""
    if predictor and fecha and fecha.isoformat() <= hasta:
        for fila in (_laboratorio() or {}).get("reuniones", []):
            if fila["Fecha"] == fecha and fila["Hipódromo"] == meta.get("track"):
                return {"corridas": fila["Carreras"], "aciertos_1": fila["Nuevo 1er"],
                        "aciertos_top3": fila["Nuevo top3"],
                        "nota": "Medido sin que el modelo conociera esta reunión."}
        efect = efectividad_modelo(registros)
        return {**efect, "nota": "Modelo de forma (la reunión se usó para entrenar)."}
    return {**efectividad_modelo(registros, predictor), "nota": "Modelo entrenado."}


@st.dialog("Ficha del caballo", width="large")
def _ficha(info: dict, fila: dict, caballos: list[dict] | None = None) -> None:
    chips = []
    if fila.get("Value bet"):
        chips.append(ui.chip(f"Value bet {fila['Edge']:+.0%}", "value"))
    if info.get("finish_position"):
        chips.append(ui.chip(f"Llegó {info['finish_position']}°", "acierto" if info["finish_position"] == 1 else "finalizada"))
    _html(
        f'<div style="display:flex;gap:.8rem;align-items:center;margin-bottom:.6rem">'
        f'{ui.saddle(fila.get("N°"))}<div><div style="font-size:1.4rem;font-weight:800">'
        f'{ui.escape(info["horse_name"])}</div>{"".join(chips)}</div></div>'
    )
    cols = st.columns(4)
    cols[0].metric("Prob. modelo", ui.pct(fila["Prob. modelo"]), border=True)
    cols[1].metric("Kg", info.get("weight") or "-", border=True)
    cols[2].metric("Puesto (PP)", info.get("post_position") or "-", border=True)
    cols[3].metric("Récord año", info.get("record") or "-", border=True, help="carreras-ganadas")
    st.caption(
        f"Jinete: {info.get('jockey') or '-'} · Entrenador: {info.get('trainer') or '-'}"
        f" · Stud: {info.get('stud') or '-'}"
    )

    predictor = _predictor()
    if predictor and caballos and predictor.aplica(caballos):
        aportes = predictor.explicar(caballos, caballos.index(info))
        if aportes:
            st.markdown("**Por qué el modelo le da esta probabilidad**")
            favor = [n for n, v in aportes if v > 0][:4]
            contra = [n for n, v in aportes if v < 0][:4]
            c1, c2 = st.columns(2)
            c1.markdown("A favor: " + (", ".join(favor) or "-"))
            c2.markdown("En contra: " + (", ".join(contra) or "-"))

    historial = info.get("history") or []
    grafico = ui.grafico_forma(historial)
    if grafico is not None:
        st.markdown("**Forma reciente** (1° arriba)")
        st.altair_chart(grafico, width="stretch")
    if historial:
        st.markdown("**Últimas actuaciones**")
        df = pd.DataFrame(historial)
        st.dataframe(df.drop(columns=["Video"], errors="ignore"), hide_index=True)

        st.markdown("**Video de una actuación anterior**")
        indices = list(range(len(historial)))
        elegido = st.selectbox(
            "Actuación",
            indices,
            format_func=lambda i: (
                f"{historial[i]['Fecha']} · {str(historial[i].get('Hipódromo') or '').title()} · "
                f"C{historial[i].get('Carrera') or '?'} · llegó {historial[i].get('Llegada') or '?'}°"
            ),
            key=f"ficha_act_{info['horse_name']}",
        )
        h = historial[elegido]
        _panel_video(
            h.get("Hipódromo"), h.get("Fecha") or None, h.get("Carrera"), h.get("Reunión"),
            h.get("Video"), f"vh_{info['horse_name']}_{elegido}", en_dialogo=True,
        )
    if info.get("workouts"):
        st.markdown("**Traqueos**")
        st.dataframe(pd.DataFrame(info["workouts"]), hide_index=True)
    datos = (info.get("enrichment") or {}).get("data")
    if datos:
        st.markdown("**Datos enriquecidos**")
        st.json(datos)
    if not (historial or info.get("workouts") or datos):
        st.caption("Sin historial disponible para este caballo.")


def _editor_cuotas(numero: int, caballos: list[dict]) -> list[float | None]:
    """Tabla editable para escribir las cuotas decimales de una carrera."""
    cuotas = st.session_state["cuotas"]
    df = pd.DataFrame(
        {
            "N°": [c.get("dorsal") or c.get("post_position") for c in caballos],
            "Caballo": [c["horse_name"] for c in caballos],
            "Cuota": _cuotas_carrera(numero, caballos),
        }
    )
    editado = st.data_editor(
        df,
        key=f"editor_{st.session_state['origen']}_{numero}",
        hide_index=True,
        disabled=["N°", "Caballo"],
        column_config={
            "Cuota": st.column_config.NumberColumn(
                "Cuota (decimal)", min_value=1.01, step=0.1, format="%.2f",
                help="3.5 significa que pagan 3.5 por cada 1 apostado.",
            )
        },
    )
    valores = [None if pd.isna(v) else float(v) for v in editado["Cuota"]]
    for c, v in zip(caballos, valores):
        cuotas[(numero, c["horse_name"])] = v
    return valores


def _tab_carrera(umbral: float) -> None:
    carreras = agrupar_por_carrera(st.session_state["registros"])
    meta = st.session_state["meta"]
    numeros = list(carreras)
    numero = st.pills(
        "Carrera", numeros, default=numeros[0], required=True, key="carrera_sel",
        format_func=lambda n: f"{n}" if n else "-",
    ) or numeros[0]
    caballos = carreras[numero]
    estado = _estado(caballos)

    chips = [ui.chip(estado.replace("_", " ").capitalize(), estado)] if estado else []
    if caballos[0].get("distance"):
        chips.append(ui.chip(f"{caballos[0]['distance']} m", "info"))
    chips.append(ui.chip(f"{len(caballos)} inscritos", "info"))
    _html(f'<h2 style="font-family:Georgia,serif;margin:.2rem 0">Carrera {numero}</h2>{"".join(chips)}')
    if caballos[0].get("conditions"):
        st.caption(caballos[0]["conditions"])

    with st.expander("Escribir cuotas para detectar value bets", expanded=False):
        st.caption("Escribe la cuota de **todos** los caballos para calcular el mercado.")
        cuotas = _editor_cuotas(numero, caballos)
    filas = analizar_carrera(caballos, cuotas, umbral, _predictor())
    por_nombre = {c["horse_name"]: c for c in caballos}

    value_bets = [f["Caballo"] for f in filas if f["Value bet"]]
    if value_bets:
        st.success(f"Value bets (edge > {umbral:.0%}): " + ", ".join(value_bets))

    col_cards, col_graf = st.columns([3, 2])
    with col_cards:
        prob_max = max(f["Prob. modelo"] for f in filas)
        for i, fila in enumerate(filas, start=1):
            info = por_nombre[fila["Caballo"]]
            c1, c2 = st.columns([6, 1], vertical_alignment="center")
            with c1:
                _html(ui.horse_card(fila, i, prob_max, info))
            if c2.button("Ficha", key=f"ficha_{st.session_state['origen']}_{numero}_{i}"):
                _ficha(info, fila, caballos)
    with col_graf:
        st.markdown("**Probabilidad de ganar**")
        st.altair_chart(ui.grafico_probabilidades(filas), width="stretch")
        if filas[0]["Prob. mercado"] is None:
            st.caption("Escribe las cuotas para comparar modelo y mercado.")

        st.markdown("**Video de la carrera**")
        _panel_video(
            meta.get("track"),
            meta["date"].isoformat() if meta.get("date") else None,
            numero,
            meta.get("number"),
            caballos[0].get("race_video"),
            f"vc_{st.session_state['origen']}_{numero}",
            por_correr=estado in {"por_correr", "en_curso"},
        )

    with st.expander("Tabla detallada"):
        _tabla(filas)


def _tab_en_vivo() -> None:
    _html('<h2 style="font-family:Georgia,serif;margin:.2rem 0">'
          '<span class="live-dot"></span>En vivo</h2>')

    registros = st.session_state.get("registros")
    if registros:
        carreras = agrupar_por_carrera(registros)
        proxima = next(
            ((n, c) for n, c in carreras.items() if _estado(c) in {"por_correr", "en_curso"}),
            None,
        )
        if proxima:
            numero, caballos = proxima
            filas = analizar_carrera(
                caballos, _cuotas_carrera(numero, caballos), predictor=_predictor()
            )
            st.markdown("**Próxima carrera de la reunión cargada**")
            _html(ui.race_card(numero, caballos[0].get("distance"), _estado(caballos), filas))
        else:
            st.caption("Todas las carreras de la reunión cargada ya se corrieron.")

    col_video, col_links = st.columns([3, 1.3])
    with col_video:
        senal = get_setting(DB_PATH, "url_en_vivo")
        tipo = tipo_video(senal)
        if tipo in {"youtube", "archivo"}:
            st.video(senal, autoplay=True, muted=True)
        elif tipo == "enlace":
            st.link_button("Abrir señal en vivo", senal, type="primary")
        else:
            st.info(
                "Pega abajo el enlace de la transmisión (por ejemplo un YouTube "
                "Live del INH o de un canal hípico) y se reproducirá aquí."
            )
        with st.form("form_en_vivo", border=False):
            nuevo = st.text_input("Enlace de la señal en vivo", value=senal or "")
            if st.form_submit_button("Guardar señal"):
                if not nuevo.strip() or tipo_video(nuevo):
                    set_setting(DB_PATH, "url_en_vivo", nuevo.strip() or None)
                    st.rerun()
                else:
                    st.error("Enlace no válido (debe empezar por http:// o https://).")
    with col_links:
        st.markdown("**Señales oficiales**")
        for nombre, url in SENALES_OFICIALES:
            st.link_button(nombre, url, width="stretch")
        st.link_button(
            "Buscar en YouTube",
            "https://www.youtube.com/results?search_query=INH+en+vivo+La+Rinconada",
            width="stretch",
        )
        st.caption(
            "La transmisión es propiedad del INH. El sistema solo enlaza o "
            "reproduce la señal desde su origen."
        )


def _actualizar_y_reentrenar() -> None:
    try:
        with st.spinner("Archivando reuniones nuevas, reentrenando y evaluando..."):
            resumen = archivo.sincronizar()
            modelo = entrenar_desde_archivo()
            laboratorio.guardar(laboratorio.evaluar_archivo())
    except Exception as exc:  # noqa: BLE001
        logger.exception("Fallo al reentrenar")
        st.error(f"No se pudo actualizar: {exc}")
        return
    st.session_state.pop("reuniones", None)
    st.success(
        f"{resumen['nuevas']} reuniones nuevas archivadas · modelo reentrenado "
        f"con {modelo.n_carreras} carreras."
    )


def _tab_laboratorio() -> None:
    st.markdown("### Laboratorio del modelo")
    st.caption(
        "Validación cronológica: para cada reunión el modelo se entrena **solo "
        "con las reuniones anteriores**, como si fuera ese domingo. Estos son "
        "los aciertos que se habrían obtenido de verdad."
    )
    if not archivo.listar():
        st.info("El archivo histórico está vacío. Pulsa el botón para crearlo.")
        if st.button("Crear archivo y entrenar", type="primary"):
            _actualizar_y_reentrenar()
        return

    lab = _laboratorio()
    if lab is None:
        st.info("Aún no hay evaluación guardada. Pulsa el botón para calcularla.")
        if st.button("Evaluar y entrenar", type="primary"):
            _actualizar_y_reentrenar()
        return
    t = lab["totales"]
    n = t["carreras"]
    desde, hasta = lab["rango"]
    st.caption(
        f"Archivo: {lab['n_reuniones']} reuniones del {desde:%d/%m/%Y} al "
        f"{hasta:%d/%m/%Y}. Evaluadas: {n:.0f} carreras (las 3 primeras "
        "reuniones solo sirven para entrenar)."
    )
    if not n:
        st.info("Hacen falta al menos 4 reuniones archivadas para evaluar.")
        return

    cols = st.columns(3)
    cols[0].metric("Modelo entrenado · 1er pick", f"{t['nuevo_1'] / n:.0%}",
                   f"Top 3: {t['nuevo_3'] / n:.0%}", delta_color="off", border=True)
    cols[1].metric("Modelo de forma · 1er pick", f"{t['actual_1'] / n:.0%}",
                   f"Top 3: {t['actual_3'] / n:.0%}", delta_color="off", border=True)
    cols[2].metric("Al azar · 1er pick", f"{t['azar_1'] / n:.0%}",
                   f"Top 3: {t['azar_3'] / n:.0%}", delta_color="off", border=True)
    st.caption(
        f"Log-loss (menor es mejor): entrenado {t['nuevo_ll'] / n:.3f} · forma "
        f"{t['actual_ll'] / n:.3f}. Con pocas carreras, diferencias de 2-3 puntos "
        "pueden ser casualidad: el archivo crece cada semana."
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Calibración** · si dice X%, ¿gana X%?")
        st.altair_chart(ui.grafico_calibracion(lab["calibracion"]), width="stretch")
    with c2:
        st.markdown("**Qué pesa en el modelo actual**")
        st.altair_chart(
            ui.grafico_pesos({NOMBRES[k]: v for k, v in lab["pesos_ultimo"].items()}),
            width="stretch",
        )

    st.markdown("**Resultados por reunión**")
    df = pd.DataFrame(lab["reuniones"])
    df["Fecha"] = pd.to_datetime(df["Fecha"]).dt.strftime("%d/%m/%Y")
    st.dataframe(df, hide_index=True)

    st.divider()
    st.caption(
        "El archivo y el modelo se actualizan solos cada semana en la nube "
        "(GitHub Actions). Aquí puedes forzarlo a mano."
    )
    if st.button("Actualizar archivo y reentrenar"):
        _actualizar_y_reentrenar()


# ------------------------------------------------------------------ domingo


def _pronosticos() -> list[dict]:
    """Pronóstico por carrera pendiente de la reunión cargada."""
    registros = st.session_state.get("registros")
    if not registros:
        return []
    predictor = _predictor()
    salida = []
    for numero, caballos in agrupar_por_carrera(registros).items():
        estado = _estado(caballos)
        if estado == "finalizada":
            continue
        filas = analizar_carrera(
            caballos, _cuotas_carrera(numero, caballos), 0.05, predictor
        )
        salida.append(
            {
                "numero": numero,
                "caballos": caballos,
                "estado": estado,
                "dist": caballos[0].get("distance"),
                "filas": filas,
                **pronostico_carrera(filas),
            }
        )
    return salida


def _texto_pronostico(prons: list[dict], meta: dict) -> str:
    """Texto plano del pronóstico, listo para WhatsApp/Telegram."""
    fecha = meta.get("date")
    titulo = f"PRONÓSTICO {str(meta.get('track', '')).title()}"
    titulo += f" {fecha:%d/%m/%Y}" if fecha else ""
    lineas = [titulo, ""]
    for x in prons:
        top = " · ".join(
            f"{f['Caballo']} {ui.pct(f['Prob. modelo'])}" for f in x["top3"]
        )
        lineas.append(
            f"C{x['numero']} ({x['dist'] or '?'}m · {x['confianza']}): {top}"
        )
        lineas.append(f"   5y6: {', '.join(x['combo_nombres'])}")
    lineas += ["", "Estimaciones del modelo — uso informativo, no garantía."]
    return "\n".join(lineas)


def _recargar_reunion() -> None:
    """Vuelve a descargar la reunión web: refresca retirados y estado."""
    meta = st.session_state.get("meta") or {}
    reunion_id = meta.get("reunion_id")
    if not reunion_id:
        st.warning("Solo se pueden refrescar reuniones cargadas desde la web.")
        return
    reuniones = _obtener_reuniones()
    reunion = next((r for r in reuniones if r["id"] == reunion_id), None)
    if reunion is None:
        st.error("La reunión ya no aparece en el archivo/web.")
        return
    try:
        with st.spinner("Descargando datos actualizados..."):
            datos = fetch_meeting(reunion_id)
    except GacetaWebError as exc:
        st.error(f"No se pudo actualizar: {exc}")
        return
    _cargar_registros(
        meeting_to_records(datos),
        f"web_{reunion_id}",
        {
            "kicker": f"Reunión {reunion['number']}",
            "track": reunion["track"],
            "date": reunion["date"],
            "number": reunion["number"],
            "retirados": scratched(datos),
            "reunion_id": reunion_id,
        },
    )
    st.success("Reunión actualizada: retirados y estado al día.")


def _tab_domingo() -> None:
    st.markdown("### Pronóstico del domingo")
    st.caption(
        "Favoritos del modelo por carrera pendiente, nivel de confianza, "
        "combinación sugerida para el 5y6 y exacta más probable."
    )
    if not st.session_state.get("registros"):
        st.info("Carga una reunión para ver el pronóstico.")
        return
    prons = _pronosticos()
    if not prons:
        st.info("Todas las carreras de esta reunión ya se corrieron.")
        return
    meta = st.session_state["meta"]

    c1, c2, c3 = st.columns(3)
    if c1.button("Actualizar retirados", width="stretch"):
        _recargar_reunion()
    texto = _texto_pronostico(prons, meta)
    c2.link_button(
        "Compartir por WhatsApp",
        f"https://wa.me/?text={quote(texto)}",
        width="stretch",
    )
    if telegram.configurado():
        if c3.button("Enviar por Telegram", width="stretch"):
            with st.spinner("Enviando pronóstico..."):
                try:
                    telegram.enviar(texto)
                    st.success("Pronóstico enviado por Telegram.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"No se pudo enviar: {exc}")
    else:
        c3.caption("Telegram sin configurar (ver Ajustes/secrets).")

    st.divider()
    for x in prons:
        with st.container(border=True):
            estado_txt = (x["estado"] or "").replace("_", " ").capitalize()
            color = {"Alta": "acierto", "Media": "info", "Baja": "finalizada"}[
                x["confianza"]
            ]
            _html(
                f"<div class='race-head'>"
                f"<strong>Carrera {x['numero']}</strong> · "
                f"{x['dist'] or '?'} m · {estado_txt} "
                f"{ui.chip(x['confianza'], color)}"
                f"</div>"
            )
            top = " · ".join(
                f"{f['Caballo']} <b>{ui.pct(f['Prob. modelo'])}</b>"
                for f in x["top3"]
            )
            st.markdown(f"**Top 3:** {top}")
            st.caption(
                "Prob. de quedar 3° o mejor — "
                + " · ".join(
                    f"{f['Caballo']} {ui.pct(f.get('Prob. top3'))}"
                    for f in x["filas"][:3]
                )
            )
            combo = x["combo_5y6"]
            st.markdown(
                f"**5y6 sugerido** "
                f"({combo['cobertura']:.0%} cobertura estimada): "
                + ", ".join(f"**{n}**" for n in x["combo_nombres"])
            )
            if x["exactas"]:
                ex = x["exactas"][0]
                st.caption(
                    f"Exacta probable: {ex['1°']} → {ex['2°']} "
                    f"({ui.pct(ex['Prob.'])})"
                )


# ------------------------------------------------------------------- chat IA


def _contexto_chat() -> str:
    """Resumen compacto del sistema para el prompt del chat.

    Incluye la reunión cargada (top caballos por carrera, cuotas,
    value bets, ganador real) y los totales del laboratorio. Se mantiene
    corto para no gastar el límite de tokens/minuto del nivel gratuito.
    """
    lab = _laboratorio()
    totales = ""
    if lab and lab.get("totales"):
        t = lab["totales"]
        if t["carreras"]:
            totales = (
                f"LABORATORIO ({t['carreras']:.0f} carreras evaluadas, modelo "
                "reentrenado solo con reuniones anteriores): el 1er pick "
                f"acierta {t['nuevo_1'] / t['carreras']:.0%} y el top-3 "
                f"{t['nuevo_3'] / t['carreras']:.0%} (al azar: "
                f"{t['azar_1'] / t['carreras']:.0%} / "
                f"{t['azar_3'] / t['carreras']:.0%})."
            )
    registros = st.session_state.get("registros")
    if not registros:
        return totales or "No hay ninguna reunión cargada en la app."

    meta = st.session_state["meta"]
    lineas = [
        f"REUNIÓN CARGADA: {meta.get('kicker', '')} · "
        f"{str(meta.get('track', '')).title()} · {meta.get('date', '')}".rstrip(" ·")
    ]
    predictor = _predictor()
    for numero, caballos in sorted(agrupar_por_carrera(registros).items()):
        filas = analizar_carrera(
            caballos, _cuotas_carrera(numero, caballos), 0.05, predictor
        )
        dist = caballos[0].get("distance") or "?"
        estado = _estado(caballos) or "?"
        ganador = next(
            (c["horse_name"] for c in caballos if c.get("finish_position") == 1), None
        )
        top = []
        for f in filas[:3]:
            partes = [f["Caballo"], ui.pct(f["Prob. modelo"])]
            if f.get("Cuota"):
                partes.append(f"cuota {f['Cuota']:.1f}")
            if f["Value bet"]:
                partes.append("VALUE BET")
            if f.get("Llegada") == 1:
                partes.append("GANÓ")
            top.append(" ".join(partes))
        lineas.append(
            f"Carrera {numero} ({dist} m, {estado})"
            + (f", ganó: {ganador}" if ganador else "")
            + " -> " + " | ".join(top)
        )
    if totales:
        lineas.append(totales)
    return "\n".join(lineas)[:12000]


def _tab_chat() -> None:
    """Chat con IA (API gratuita) sobre la reunión y el sistema."""
    st.markdown("### Chat con IA")
    prov = chat_ia.proveedor()
    if prov is None:
        st.caption(
            "Modo Pollinations (gratis, sin key; puede ser lento). Para un "
            "servicio más rápido añade una key gratuita en secrets o "
            "variables de entorno: `GEMINI_API_KEY` (aistudio.google.com, "
            "~1.500 preguntas/día), `GITHUB_TOKEN`, `OPENROUTER_API_KEY` "
            "o `GROQ_API_KEY`. Si un proveedor llega a su límite, el chat "
            "salta solo al siguiente."
        )
    else:
        st.caption(
            f"Proveedor: {chat_ia.NOMBRES.get(prov, prov)} "
            "(gratis; salta solo al siguiente si llega al límite)."
        )

    contexto = _contexto_chat()
    historial = st.session_state.setdefault("chat_historial", [])
    for m in historial:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    c_limpiar, _ = st.columns([1, 5])
    if c_limpiar.button("Limpiar conversación", width="stretch"):
        historial.clear()
        st.rerun()

    if not st.session_state.get("registros"):
        st.caption("Carga una reunión (botón Semana/PDF) para que el chat tenga datos de los caballos.")

    pregunta = st.chat_input("Pregunta sobre las carreras, los caballos o los pronósticos...")
    if not pregunta:
        return
    historial.append({"role": "user", "content": pregunta})
    with st.chat_message("user"):
        st.markdown(pregunta)
    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                respuesta = chat_ia.chatear(pregunta, historial[:-1], contexto)
            except chat_ia.ChatError as exc:
                respuesta = f"No pude responder: {exc}"
            except Exception as exc:  # noqa: BLE001
                logger.exception("Fallo el chat con IA")
                respuesta = f"Error inesperado del chat: {exc}"
        st.markdown(respuesta)
    historial.append({"role": "assistant", "content": respuesta})


# -------------------------------------------------------------- vista móvil

SECCIONES_MOVIL = ["Resumen", "Domingo", "Carrera", "En vivo", "Lab", "Chat"]


def _vista() -> str:
    """``"movil"`` o ``"pc"`` según dónde se abre la app.

    Orden: forzada en sesión (tests), ``?vista=movil|pc``, User-Agent del
    navegador. Si no se puede saber, se usa la vista PC (la CSS ya es
    responsiva como respaldo).
    """
    forzada = st.session_state.get("_vista_forzada")
    if forzada in {"movil", "pc"}:
        return forzada
    try:
        pedido = str(st.query_params.get("vista", "") or "")
    except Exception:  # noqa: BLE001
        pedido = ""
    if pedido in {"movil", "pc"}:
        return pedido
    try:
        ua = st.context.headers.get("User-Agent") or ""
    except Exception:  # noqa: BLE001  (AppTest, ejecución sin navegador)
        ua = ""
    return "movil" if ui.es_movil(ua) else "pc"


def _vista_movil() -> None:
    """Layout pensado para el teléfono: barra superior, navegación fija
    abajo y una sección a la vez (sin pestañas ni tablas anchas)."""
    reuniones = _preparar_selector()
    meta = st.session_state.get("meta") or {}
    if meta.get("date"):
        sub = f"{str(meta.get('track') or '').title()} · {meta['date']:%d/%m/%Y}"
    else:
        sub = str(meta.get("track") or "Análisis estadístico hípico")
    _html(ui.barra_superior("Sistema Hípico", sub))

    umbral = 0.05
    _aviso_ocr()

    # Barra flotante inferior: herramientas (Semana/PDF/Ajustes) + navegación.
    with st.container(key="m_nav"):
        with st.container(key="m_tools"):
            c_semana, c_pdf, c_ajustes = st.columns(3)
            with c_semana.popover("Semana"):
                dia = st.date_input("Semana", key="semana", format="DD/MM/YYYY")
                semana = _selector_reunion(dia, reuniones)
                _nota_semana(dia, reuniones, semana)
            with c_pdf.popover("PDF"):
                offline = st.toggle("Enriquecimiento offline", value=True)
                _cargar_pdf(offline)
            with c_ajustes.popover("Ajustes"):
                umbral = st.slider("Umbral de value bet", 0.0, 0.20, 0.05, 0.01)
                st.caption("Uso informativo: no constituye recomendación de apuesta.")
        seccion = st.segmented_control(
            "Sección", SECCIONES_MOVIL, required=True, key="m_sec",
            default="Resumen", label_visibility="collapsed", width="stretch",
        ) or "Resumen"

    if not st.session_state.get("registros"):
        _html(ui.hero(
            "Sistema Hípico", "Análisis Estadístico de Caballos",
            "Abre «Semana» y elige la reunión para cargar la gaceta.",
        ))
        return
    if seccion == "Domingo":
        _tab_domingo()
    elif seccion == "Carrera":
        _movil_carrera(umbral)
    elif seccion == "En vivo":
        _tab_en_vivo()
    elif seccion == "Lab":
        _tab_laboratorio()
    elif seccion == "Chat":
        _tab_chat()
    else:
        _movil_resumen(umbral)


def _movil_resumen(umbral: float) -> None:
    """Inicio del teléfono: indicadores y lista táctil de carreras."""
    registros = st.session_state["registros"]
    meta = st.session_state["meta"]
    carreras = agrupar_por_carrera(registros)
    estados = [_estado(c) for c in carreras.values()]
    chips = []
    if estados.count("por_correr"):
        chips.append(ui.chip(f"{estados.count('por_correr')} por correr", "por_correr"))
    if estados.count("finalizada"):
        chips.append(ui.chip(f"{estados.count('finalizada')} finalizadas", "finalizada"))
    subtitulo = (
        ui.fecha_larga(meta["date"]).capitalize()
        if meta.get("date") else "Gaceta cargada desde PDF"
    )
    _html(ui.hero(meta["kicker"], str(meta["track"]).title(), subtitulo, chips))

    predictor = _predictor()
    resumen = resumen_reunion(registros, st.session_state["cuotas"], umbral, predictor)
    n_value = sum(len(r["Value bets"].split(", ")) for r in resumen if r["Value bets"])
    efect = _efectividad_honesta(registros, meta, predictor)
    _html(ui.tiles([
        ("Carreras", len(carreras), None),
        ("Inscritos", len(registros),
         f"{len(meta.get('retirados') or [])} retirados" if meta.get("retirados") else None),
        ("Value bets", n_value, None if n_value else "escribe cuotas en Carrera"),
        ("1er pick ganó", f"{efect['aciertos_1']}/{efect['corridas']}",
         f"Top 3: {efect['aciertos_top3']}/{efect['corridas']}"
         if efect["corridas"] else "sin carreras corridas"),
    ]))

    _html('<div class="m-h">Carreras</div>')
    with st.container(key="m_lista"):
        for numero, caballos in carreras.items():
            filas = analizar_carrera(
                caballos, _cuotas_carrera(numero, caballos), umbral, predictor
            )
            dist = caballos[0].get("distance")
            dist_txt = f"{dist} m · " if dist else ""
            ganador = next(
                (c["horse_name"] for c in caballos if c.get("finish_position") == 1), None
            )
            if ganador:
                etiqueta = f"C{numero or '-'} · {dist_txt}ganó {ganador}"
            else:
                etiqueta = (
                    f"C{numero or '-'} · {dist_txt}{filas[0]['Caballo']} · "
                    f"{ui.pct(filas[0]['Prob. modelo'])}"
                )
            st.button(
                etiqueta,
                key=f"m_carr_{st.session_state['origen']}_{numero}",
                on_click=_ir_a_carrera, args=(numero,), width="stretch",
            )

    if meta.get("retirados"):
        with st.expander(f"Retirados ({len(meta['retirados'])})"):
            for r in meta["retirados"]:
                st.write(f"Carrera {r['race_number']}: {r['horse_name']}")
    with st.expander("Tabla resumen"):
        _tabla(resumen)


def _editor_cuotas_movil(numero: int, caballos: list[dict]) -> list[float | None]:
    """Cuotas en campos apilados (la tabla ancha del PC no sirve en el teléfono)."""
    cuotas = st.session_state["cuotas"]
    for i, c in enumerate(caballos):
        nombre = c["horse_name"]
        dorsal = c.get("dorsal") or c.get("post_position") or "?"
        valor = st.number_input(
            f"{dorsal} · {nombre}",
            min_value=1.01, step=0.05,
            value=cuotas.get((numero, nombre)),
            key=f"q_{st.session_state['origen']}_{numero}_{i}",
            format="%.2f", placeholder="sin cuota",
        )
        cuotas[(numero, nombre)] = valor
    return [cuotas.get((numero, c["horse_name"])) for c in caballos]


def _movil_carrera(umbral: float) -> None:
    """Una carrera a la vez: pills deslizables, tarjetas y ficha."""
    carreras = agrupar_por_carrera(st.session_state["registros"])
    meta = st.session_state["meta"]
    numeros = list(carreras)
    with st.container(key="m_pills"):
        numero = st.pills(
            "Carrera", numeros, default=numeros[0], required=True,
            key="m_carrera", format_func=lambda n: f"{n}" if n else "-",
            label_visibility="collapsed",
        ) or numeros[0]
    caballos = carreras[numero]
    estado = _estado(caballos)

    chips = [ui.chip(estado.replace("_", " ").capitalize(), estado)] if estado else []
    if caballos[0].get("distance"):
        chips.append(ui.chip(f"{caballos[0]['distance']} m", "info"))
    chips.append(ui.chip(f"{len(caballos)} inscritos", "info"))
    _html(f'<h2 style="font-family:Georgia,serif;margin:.2rem 0">Carrera {numero}</h2>{"".join(chips)}')
    if caballos[0].get("conditions"):
        st.caption(caballos[0]["conditions"])

    with st.expander("Escribir cuotas para detectar value bets", expanded=False):
        cuotas = _editor_cuotas_movil(numero, caballos)
    filas = analizar_carrera(caballos, cuotas, umbral, _predictor())
    por_nombre = {c["horse_name"]: c for c in caballos}

    value_bets = [f["Caballo"] for f in filas if f["Value bet"]]
    if value_bets:
        st.success(f"Value bets (edge > {umbral:.0%}): " + ", ".join(value_bets))

    prob_max = max(f["Prob. modelo"] for f in filas)
    for i, fila in enumerate(filas, start=1):
        info = por_nombre[fila["Caballo"]]
        _html(ui.horse_card(fila, i, prob_max, info))
        if st.button(
            "Ver ficha", key=f"m_ficha_{st.session_state['origen']}_{numero}_{i}",
            type="tertiary", width="content",
        ):
            _ficha(info, fila, caballos)

    with st.expander("Gráfico de probabilidades"):
        st.altair_chart(ui.grafico_probabilidades(filas), width="stretch")
        if filas[0]["Prob. mercado"] is None:
            st.caption("Escribe las cuotas para comparar modelo y mercado.")
    with st.expander("Video de la carrera"):
        _panel_video(
            meta.get("track"),
            meta["date"].isoformat() if meta.get("date") else None,
            numero, meta.get("number"), caballos[0].get("race_video"),
            f"vm_{st.session_state['origen']}_{numero}",
            por_correr=estado in {"por_correr", "en_curso"},
        )
    with st.expander("Tabla detallada"):
        _tabla(filas)


# ---------------------------------------------------------------------- main


def main() -> None:
    st.set_page_config(
        page_title="Sistema Hípico", layout="wide", initial_sidebar_state="collapsed"
    )
    _inyectar_css()

    try:
        init_db(DB_PATH)
    except Exception as exc:  # noqa: BLE001
        st.error(f"No se pudo inicializar la base de datos: {exc}")
        return

    if _vista() == "movil":
        _html(ui.CSS_MOVIL)
        _vista_movil()
        return

    with st.sidebar:
        st.markdown("### Sistema Hípico")
        st.caption("Análisis estadístico de carreras · La Rinconada y Valencia")
        umbral = st.slider("Umbral de value bet", 0.0, 0.20, 0.05, 0.01)
        offline = st.toggle(
            "Enriquecimiento offline (PDF)", value=True,
            help="Para PDFs: solo usa SQLite y CSVs locales al enriquecer.",
        )
        st.caption("Uso informativo: no constituye recomendación de apuesta.")

    _selector_gaceta(offline)

    tab_domingo, tab_reunion, tab_carrera, tab_vivo, tab_lab, tab_chat = st.tabs(
        ["Domingo", "Reunión", "Carrera", "En vivo", "Laboratorio", "Chat IA"]
    )
    try:
        if st.session_state.get("registros"):
            with tab_domingo:
                _tab_domingo()
            with tab_reunion:
                _tab_reunion(umbral)
            with tab_carrera:
                _tab_carrera(umbral)
        else:
            with tab_domingo:
                st.info("Carga una reunión para ver el pronóstico del domingo.")
            with tab_reunion:
                _html(ui.hero(
                    "Sistema Hípico", "Análisis Estadístico de Caballos",
                    "Elige una semana en el calendario para cargar la gaceta.",
                ))
            with tab_carrera:
                st.info("Carga una reunión para ver el análisis por carrera.")
        with tab_vivo:
            _tab_en_vivo()
        with tab_lab:
            _tab_laboratorio()
        with tab_chat:
            _tab_chat()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Fallo mostrando resultados")
        st.error(f"Error mostrando el análisis: {exc}")


main()
