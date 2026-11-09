"""Componentes visuales del dashboard (HTML/CSS y gráficos Altair).

Funciones puras que devuelven HTML o gráficos, sin llamar a Streamlit,
para poder probarlas. ``app.py`` las renderiza con
``st.markdown(..., unsafe_allow_html=True)`` y ``st.altair_chart``.
Todo el texto dinámico se escapa con ``html.escape``.
"""

from __future__ import annotations

import re
from datetime import date
from html import escape
from typing import Any

import altair as alt
import pandas as pd

DORADO = "#D4AF37"
VERDE = "#3FA37C"
CREMA = "#E8E1CF"

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
DIAS_LARGOS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

# Colores estándar de mantilla (fondo, texto) por número de programa.
MANTILLAS = {
    1: ("#D7263D", "#FFFFFF"), 2: ("#FFFFFF", "#111111"), 3: ("#1E5AA8", "#FFFFFF"),
    4: ("#F2D024", "#111111"), 5: ("#1F8A4C", "#FFFFFF"), 6: ("#111111", "#F2D024"),
    7: ("#F28C28", "#111111"), 8: ("#F4A6C1", "#111111"), 9: ("#3CC6C0", "#111111"),
    10: ("#6A3FA0", "#FFFFFF"), 11: ("#9AA0A6", "#D7263D"), 12: ("#A4D65E", "#111111"),
    13: ("#7B4A2D", "#FFFFFF"), 14: ("#7A1F2B", "#F2D024"), 15: ("#C8B88A", "#111111"),
    16: ("#8EC9F0", "#D7263D"),
}

CSS = """
<style>
.block-container {padding-top: 1.2rem; max-width: 1200px;}
.hero {
  background: radial-gradient(circle at 85% 20%, rgba(212,175,55,.25), transparent 45%),
              linear-gradient(135deg, #0F3B2B 0%, #0B1F17 70%);
  border: 1px solid #2A5A44; border-radius: 1rem; padding: 1.3rem 1.5rem;
  margin-bottom: 1rem; position: relative; overflow: hidden;
}
.hero::after {
  content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 4px;
  background: repeating-linear-gradient(90deg, #D4AF37 0 24px, transparent 24px 36px);
  opacity: .55;
}
.hero .kicker {color: #D4AF37; letter-spacing: .18em; font-size: .75rem;
  text-transform: uppercase; font-weight: 700;}
.hero h1 {font-family: Georgia, serif; font-size: 2.1rem; margin: .2rem 0 .1rem;
  color: #F2EBD9; line-height: 1.15;}
.hero .sub {color: #C9C2AE; font-size: 1rem; margin-bottom: .6rem;}
.chip {display: inline-block; padding: .15rem .6rem; border-radius: 999px;
  font-size: .75rem; font-weight: 700; margin: 0 .3rem .3rem 0; letter-spacing: .02em;
  border: 1px solid transparent; white-space: nowrap;}
.chip-por_correr {background: rgba(63,163,124,.18); color: #7FE0B4; border-color: #3FA37C;}
.chip-finalizada {background: rgba(255,255,255,.06); color: #B8B2A2; border-color: #4A5A52;}
.chip-en_curso {background: rgba(192,57,43,.2); color: #FF8A7A; border-color: #C0392B;}
.chip-value {background: rgba(212,175,55,.2); color: #F5D776; border-color: #D4AF37;}
.chip-acierto {background: rgba(63,163,124,.25); color: #9BF0C8; border-color: #3FA37C;}
.chip-info {background: rgba(232,225,207,.08); color: #E8E1CF; border-color: #4A5A52;}
.saddle {display: inline-flex; align-items: center; justify-content: center;
  width: 2.3rem; height: 2.3rem; border-radius: .55rem; font-weight: 800;
  font-size: 1.05rem; box-shadow: 0 2px 6px rgba(0,0,0,.35); flex-shrink: 0;
  border: 1px solid rgba(0,0,0,.25);}
.saddle.sm {width: 1.7rem; height: 1.7rem; font-size: .85rem; border-radius: .4rem;}
.race-card {background: #13362A; border: 1px solid #2A5A44; border-radius: .9rem;
  padding: .9rem 1rem; height: 100%; margin-bottom: .8rem;}
.race-card .head {display: flex; justify-content: space-between; align-items: baseline;}
.race-card .num {font-family: Georgia, serif; font-size: 1.5rem; color: #D4AF37; font-weight: 700;}
.race-card .dist {color: #C9C2AE; font-size: .85rem;}
.podium-row {display: flex; align-items: center; gap: .5rem; margin: .35rem 0;}
.podium-row .pos {width: 1.3rem; color: #8FB9A8; font-weight: 700; font-size: .8rem;}
.podium-row .name {flex: 1; font-weight: 600; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;}
.podium-row .pct {color: #D4AF37; font-weight: 700; font-size: .9rem;}
.race-card .foot {margin-top: .5rem; font-size: .8rem; color: #C9C2AE;}
.horse-card {display: flex; gap: .8rem; align-items: center; background: #13362A;
  border: 1px solid #2A5A44; border-radius: .9rem; padding: .7rem .9rem; margin-bottom: .2rem;}
.horse-card.value {border-color: #D4AF37; box-shadow: 0 0 0 1px rgba(212,175,55,.35),
  0 0 18px -6px rgba(212,175,55,.6);}
.horse-card .body {flex: 1; min-width: 0;}
.horse-card .name {font-weight: 800; font-size: 1.05rem; letter-spacing: .01em;}
.horse-card .meta {color: #C9C2AE; font-size: .8rem; margin: .1rem 0 .35rem;}
.bar {background: rgba(255,255,255,.08); border-radius: 999px; height: .55rem; overflow: hidden;}
.bar > span {display: block; height: 100%; border-radius: 999px;
  background: linear-gradient(90deg, #3FA37C, #D4AF37);}
.horse-card .prob {text-align: right; min-width: 4.2rem;}
.horse-card .prob .big {font-family: Georgia, serif; font-size: 1.35rem; color: #D4AF37;
  font-weight: 700; line-height: 1;}
.horse-card .prob .small {font-size: .72rem; color: #C9C2AE;}
.rank {color: #8FB9A8; font-weight: 800; font-size: .8rem; width: 1.4rem; text-align: center;}
.live-dot {display: inline-block; width: .6rem; height: .6rem; border-radius: 50%;
  background: #E74C3C; margin-right: .4rem; animation: pulse 1.4s infinite;}
@keyframes pulse {0% {box-shadow: 0 0 0 0 rgba(231,76,60,.7);}
  70% {box-shadow: 0 0 0 10px rgba(231,76,60,0);} 100% {box-shadow: 0 0 0 0 rgba(231,76,60,0);}}
div[data-testid="stMetric"] {background: #13362A; border-radius: .9rem;}
div[data-testid="stMetricValue"] {color: #D4AF37; font-family: Georgia, serif;}
/* Tarjeta de caballo + botón "Ficha" en la misma fila. Solo la fila interna
   (la que no contiene otras columnas), no la de tarjetas + gráfico. */
div[data-testid="stHorizontalBlock"]:has(.horse-card):not(:has(div[data-testid="stHorizontalBlock"])) {
  flex-wrap: nowrap !important; gap: .4rem;}
div[data-testid="stHorizontalBlock"]:has(.horse-card):not(:has(div[data-testid="stHorizontalBlock"]))
  > div[data-testid="stColumn"] {min-width: 0 !important;}
div[data-testid="stHorizontalBlock"]:has(.horse-card):not(:has(div[data-testid="stHorizontalBlock"]))
  > div[data-testid="stColumn"]:last-child {flex: 0 0 auto !important; width: auto !important;}
@media (max-width: 640px) {
  .block-container {padding: .6rem .7rem 3rem;}
  .hero {padding: 1rem 1.05rem;}
  .hero h1 {font-size: 1.5rem;}
  .hero .sub {font-size: .9rem;}
  .horse-card {padding: .55rem .6rem; gap: .5rem;}
  .horse-card .name {font-size: .95rem;}
  .horse-card .meta {font-size: .72rem;}
  .horse-card .prob {min-width: 3.2rem;}
  .horse-card .prob .big {font-size: 1.1rem;}
  .saddle {width: 2rem; height: 2rem; font-size: .95rem;}
  .rank {display: none;}
  div[data-testid="stHorizontalBlock"]:has(.horse-card) button {padding: .25rem .55rem;}
  button[data-baseweb="tab"] {padding-left: .5rem; padding-right: .5rem;}
}
</style>
"""


_MOVIL_RE = re.compile(
    r"Mobi|Android|iPhone|iPod|Windows Phone|IEMobile|Opera Mini|BlackBerry", re.I
)


def es_movil(user_agent: str | None) -> bool:
    """``True`` si el navegador es de un teléfono (según su User-Agent).

    Las tabletas Android sin "Mobile" y los iPad (que se presentan como
    Mac) reciben la vista de PC, que aprovecha su pantalla.
    """
    ua = user_agent or ""
    if "Android" in ua and "Mobile" not in ua:
        return False
    return bool(_MOVIL_RE.search(ua))


CSS_MOVIL = """
<style>
/* Sin barra de Streamlit ni menú lateral ni sellos de la plataforma. */
header[data-testid="stHeader"], div[data-testid="stToolbar"],
div[data-testid="stSidebarCollapsedControl"], section[data-testid="stSidebar"],
div[data-testid="stDecoration"], div[data-testid="stStatusWidget"],
div[data-testid="stManageAppButton"], div[data-testid="stAppDeployButton"],
div[data-testid="stDeployButton"], div[data-testid="stAppViewerBadge"],
#stDecoration, #manage-app-button,
.stAppDeployButton, [class*="viewerBadge"], [class*="deployButton"],
a[href*="share.streamlit.io"][class*="badge"],
a[href*="share.streamlit.io"][data-testid] {display: none !important;}
.block-container {padding: .6rem .75rem 1rem !important; max-width: 100% !important;}
.stMainBlockContainer {padding-top: .6rem !important;}

/* Botón ☰ fijo arriba a la izquierda: abre/cierra el menú lateral. */
.st-key-m_hamb {position: fixed; left: .45rem; top: .45rem; z-index: 1001;}
.st-key-m_hamb button {width: 2.9rem; height: 2.9rem; border-radius: .8rem;
  background: #0A1A12 !important; border: 1px solid #2A5A44 !important;
  padding: 0 !important; box-shadow: 0 4px 14px rgba(0,0,0,.45);}
.st-key-m_hamb button p {font-size: 1.4rem !important; margin: 0 !important;
  color: #D4AF37 !important;}

/* Barra superior */
.m-top {display: flex; align-items: center; gap: .6rem;
  margin: .1rem 0 .5rem 3.4rem;}
.m-logo {width: 2.2rem; height: 2.2rem; border-radius: .6rem; display: flex;
  align-items: center; justify-content: center; font-family: Georgia, serif; font-weight: 800;
  background: linear-gradient(135deg, #D4AF37, #8C6D12); color: #0B1F17; flex-shrink: 0;}
.m-top .t {font-weight: 800; font-size: 1.02rem; line-height: 1.1;}
.m-top .s {color: #C9C2AE; font-size: .78rem; line-height: 1.2;}

/* Hero compacto */
.hero {padding: .9rem 1rem !important; margin-bottom: .7rem !important; border-radius: .9rem !important;}
.hero h1 {font-size: 1.45rem !important; margin: .1rem 0 0 !important;}
.hero .sub {font-size: .85rem !important; margin-bottom: .45rem !important;}

/* Mosaico 2x2 de indicadores */
.tiles {display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; margin-bottom: .8rem;}
.tile {background: #13362A; border: 1px solid #2A5A44; border-radius: .8rem; padding: .55rem .75rem;}
.tile .l {color: #C9C2AE; font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;}
.tile .v {font-family: Georgia, serif; color: #D4AF37; font-size: 1.45rem; font-weight: 700; line-height: 1.15;}
.tile .x {color: #8FB9A8; font-size: .72rem;}
.m-h {font-family: Georgia, serif; font-size: 1.15rem; font-weight: 700; margin: .6rem 0 .4rem;}

/* Herramientas (sección Config): popovers/inputs ya quedan en pantalla. */

/* Lista de carreras: cada botón es una fila-tarjeta */
.st-key-m_lista button {width: 100%; justify-content: flex-start !important; text-align: left;
  background: #13362A !important; border: 1px solid #2A5A44 !important; border-radius: .85rem !important;
  padding: .7rem .85rem !important; min-height: 3.1rem;}
.st-key-m_lista button p {font-size: .92rem; white-space: normal; text-align: left;}
.st-key-m_lista [data-testid="stVerticalBlock"] {gap: .45rem !important;}

/* Botones de carrera 1..13 deslizables en una sola fila */
.st-key-m_pills [data-testid="stButtonGroup"] > div {flex-wrap: nowrap !important; overflow-x: auto;
  scrollbar-width: none; padding-bottom: .2rem;}
.st-key-m_pills [data-testid="stButtonGroup"] > div::-webkit-scrollbar {display: none;}
.st-key-m_pills button {flex-shrink: 0; min-width: 2.6rem;}

/* Tarjetas de caballo a todo el ancho + enlace "Ver ficha" pegado debajo */
.horse-card {margin-bottom: 0 !important;}
.horse-card .rank {display: none;}
div[class*="st-key-m_ficha_"] {margin-top: -.55rem; display: flex; justify-content: flex-end;}
div[class*="st-key-m_ficha_"] button {padding: 0 .4rem !important; min-height: 1.8rem !important;
  font-size: .8rem; color: #E8C766 !important;}

/* Indicadores de Streamlit más compactos (Laboratorio) */
div[data-testid="stMetric"] {padding: .5rem .7rem !important;}
div[data-testid="stMetricValue"] {font-size: 1.5rem !important;}

/* Menú lateral desplegable (se abre con ☰): iconos en vertical,
   flota sobre el contenido como cajón — el resto del tiempo no ocupa
   espacio. Empieza debajo del botón ☰ para poder cerrarlo igual. */
.st-key-m_nav {position: fixed; left: 0; top: 0; bottom: 0; z-index: 1000;
  width: 4.1rem; background: #0A1A12; border-right: 1px solid #2A5A44;
  padding: 3.6rem .35rem .5rem; box-shadow: 8px 0 24px rgba(0,0,0,.55);}
.st-key-m_nav > div, .st-key-m_nav [data-testid="stVerticalBlock"] {height: 100%;}
.st-key-m_nav [data-testid="stVerticalBlock"] {justify-content: center;
  gap: .35rem !important;}
.st-key-m_nav button {width: 100%; min-height: 2.9rem !important;
  border-radius: .7rem !important; background: transparent !important;
  border: 1px solid transparent !important; padding: .15rem 0 !important;}
.st-key-m_nav button p {font-size: 1.4rem !important; margin: 0 !important;
  line-height: 1.2 !important;}
.st-key-m_nav button[kind="primary"] {
  background: rgba(212, 175, 55, .22) !important;
  border: 1px solid #D4AF37 !important;}

/* El campo del chat no queda tapado por el sello (esquina inferior der.). */
div[data-testid="stBottomBlockContainer"] {padding-right: 4.4rem !important;
  bottom: 0 !important;}
div[data-testid="stBottomBlockContainer"] > div {background: transparent !important;
  border-top: none !important;}
</style>
"""


def tiles(items: list[tuple[str, Any, str | None]]) -> str:
    """Mosaico de indicadores: ``[(etiqueta, valor, detalle)]``."""
    celdas = "".join(
        f'<div class="tile"><div class="l">{escape(str(l))}</div><div class="v">{escape(str(v))}</div>'
        + (f'<div class="x">{escape(str(x))}</div>' if x else "")
        + "</div>"
        for l, v, x in items
    )
    return f'<div class="tiles">{celdas}</div>'


def barra_superior(titulo: str, subtitulo: str) -> str:
    return (
        f'<div class="m-top"><div class="m-logo">SH</div><div><div class="t">{escape(titulo)}</div>'
        f'<div class="s">{escape(subtitulo)}</div></div></div>'
    )


def fecha_larga(d: date) -> str:
    """``domingo 8 de noviembre de 2026``."""
    return f"{DIAS_LARGOS[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def pct(valor: float | None) -> str:
    return "-" if valor is None else f"{valor:.0%}" if valor >= 0.095 else f"{valor:.1%}"


def chip(texto: str, tipo: str = "info") -> str:
    """Etiqueta de color. Tipos: por_correr, finalizada, en_curso, value, acierto, info."""
    return f'<span class="chip chip-{escape(tipo)}">{escape(str(texto))}</span>'


def saddle(numero: Any, pequeno: bool = False) -> str:
    """Número de programa con el color estándar de su mantilla."""
    try:
        n = int(numero)
    except (TypeError, ValueError):
        n = None
    fondo, texto = MANTILLAS.get(n, ("#2A5A44", "#F2EBD9"))
    clase = "saddle sm" if pequeno else "saddle"
    etiqueta = escape(str(numero)) if numero is not None else "-"
    return f'<span class="{clase}" style="background:{fondo};color:{texto}">{etiqueta}</span>'


def hero(kicker: str, titulo: str, subtitulo: str, chips: list[str] | None = None) -> str:
    """Cabecera principal de la reunión."""
    return (
        f'<div class="hero"><div class="kicker">{escape(kicker)}</div>'
        f"<h1>{escape(titulo)}</h1><div class=\"sub\">{escape(subtitulo)}</div>"
        f"{''.join(chips or [])}</div>"
    )


def race_card(
    numero: Any,
    distancia: Any,
    estado: str | None,
    podio: list[dict[str, Any]],
    ganador: str | None = None,
    value_bets: list[str] | None = None,
) -> str:
    """Tarjeta resumen de una carrera con el podio del modelo.

    ``podio`` son filas de ``analisis.analizar_carrera`` (las 3 primeras).
    """
    chips = [chip(estado.replace("_", " ").capitalize(), estado)] if estado else []
    if value_bets:
        chips.append(chip(f"{len(value_bets)} value bet", "value"))
    if ganador and podio and podio[0]["Caballo"] == ganador:
        chips.append(chip("Acierto 1er pick", "acierto"))
    filas = "".join(
        f'<div class="podium-row"><span class="pos">{i}°</span>'
        f'{saddle(f.get("N°"), pequeno=True)}'
        f'<span class="name">{escape(str(f["Caballo"]))}</span>'
        f'<span class="pct">{pct(f["Prob. modelo"])}</span></div>'
        for i, f in enumerate(podio[:3], start=1)
    )
    pie = f'<div class="foot">Ganó: <b>{escape(ganador)}</b></div>' if ganador else ""
    dist = f"{distancia} m" if distancia else ""
    return (
        f'<div class="race-card"><div class="head"><span class="num">Carrera {escape(str(numero))}</span>'
        f'<span class="dist">{escape(dist)}</span></div>{"".join(chips)}{filas}{pie}</div>'
    )


def horse_card(fila: dict[str, Any], rango: int, prob_max: float, extra: dict[str, Any]) -> str:
    """Tarjeta de un caballo: mantilla, datos, barra y probabilidad.

    ``fila`` viene de ``analisis.analizar_carrera``; ``extra`` es el
    registro original (kilos, etc.).
    """
    prob = fila["Prob. modelo"]
    ancho = 100 * prob / prob_max if prob_max else 0
    chips = []
    if fila.get("Value bet"):
        chips.append(chip(f"Value bet {fila['Edge']:+.0%}", "value"))
    if fila.get("Llegada"):
        tipo = "acierto" if fila["Llegada"] == 1 else "finalizada"
        chips.append(chip(f"Llegó {int(fila['Llegada'])}°", tipo))
    meta = " · ".join(
        str(p)
        for p in (
            fila.get("Jinete"),
            f"{extra['weight']:g} kg" if extra.get("weight") else None,
            f"Récord {fila['Récord']}" if fila.get("Récord") else None,
        )
        if p
    )
    mercado = (
        f'<div class="small">Mercado {pct(fila["Prob. mercado"])}</div>'
        if fila.get("Prob. mercado") is not None
        else '<div class="small">modelo</div>'
    )
    clase = "horse-card value" if fila.get("Value bet") else "horse-card"
    return (
        f'<div class="{clase}"><span class="rank">{rango}</span>{saddle(fila.get("N°"))}'
        f'<div class="body"><div class="name">{escape(str(fila["Caballo"]))} {"".join(chips)}</div>'
        f'<div class="meta">{escape(meta)}</div>'
        f'<div class="bar"><span style="width:{ancho:.1f}%"></span></div></div>'
        f'<div class="prob"><div class="big">{pct(prob)}</div>{mercado}</div></div>'
    )


def grafico_probabilidades(filas: list[dict[str, Any]]) -> alt.Chart:
    """Barras horizontales: probabilidad del modelo (y del mercado si hay)."""
    datos = []
    for f in filas:
        datos.append({"Caballo": f["Caballo"], "Fuente": "Modelo", "Prob": f["Prob. modelo"]})
        if f.get("Prob. mercado") is not None:
            datos.append({"Caballo": f["Caballo"], "Fuente": "Mercado", "Prob": f["Prob. mercado"]})
    df = pd.DataFrame(datos)
    orden = [f["Caballo"] for f in filas]
    hay_mercado = (df["Fuente"] == "Mercado").any()
    base = alt.Chart(df).encode(
        y=alt.Y("Caballo:N", sort=orden, title=None),
        x=alt.X("Prob:Q", axis=alt.Axis(format="%"), title="Probabilidad de ganar"),
        tooltip=["Caballo", "Fuente", alt.Tooltip("Prob:Q", format=".1%")],
    )
    if hay_mercado:
        barras = base.mark_bar(cornerRadiusEnd=4).encode(
            color=alt.Color(
                "Fuente:N",
                scale=alt.Scale(domain=["Modelo", "Mercado"], range=[DORADO, VERDE]),
                legend=alt.Legend(orient="top", title=None),
            ),
            yOffset="Fuente:N",
        )
    else:
        barras = base.mark_bar(cornerRadiusEnd=4, color=DORADO)
    return barras.properties(height=max(160, 34 * len(filas)))


def grafico_calibracion(tabla: list[dict[str, Any]]) -> alt.Chart:
    """Barras: frecuencia real de victoria por tramo vs. línea de la prob. del modelo."""
    df = pd.DataFrame(tabla)
    base = alt.Chart(df).encode(
        x=alt.X("Tramo:N", sort=None, title="Probabilidad que dio el modelo"),
        tooltip=[
            "Tramo", alt.Tooltip("Prob. modelo:Q", format=".1%"),
            alt.Tooltip("Ganó de verdad:Q", format=".1%"), "Caballos",
        ],
    )
    barras = base.mark_bar(color=VERDE, cornerRadiusEnd=4).encode(
        y=alt.Y("Ganó de verdad:Q", axis=alt.Axis(format="%"), title="Ganó de verdad"),
    )
    linea = base.mark_line(color=DORADO, strokeWidth=3, point=True).encode(y="Prob. modelo:Q")
    return (barras + linea).properties(height=260)


def grafico_pesos(pesos: dict[str, float]) -> alt.Chart:
    """Peso de cada factor en el modelo (dorado = a favor, rojo = en contra)."""
    df = pd.DataFrame({"Factor": list(pesos), "Peso": list(pesos.values())})
    return alt.Chart(df).mark_bar(cornerRadiusEnd=4).encode(
        y=alt.Y("Factor:N", sort="-x", title=None),
        x=alt.X("Peso:Q", title="Peso (más largo = más importante)"),
        color=alt.condition(alt.datum.Peso >= 0, alt.value(DORADO), alt.value("#C0392B")),
        tooltip=["Factor", alt.Tooltip("Peso:Q", format=".2f")],
    ).properties(height=260)


def grafico_forma(historial: list[dict[str, Any]]) -> alt.Chart | None:
    """Línea de llegadas en las últimas actuaciones (1° arriba)."""
    puntos = [
        {"Fecha": h["Fecha"], "Llegada": h["Llegada"], "Ganador": h.get("Ganador")}
        for h in historial
        if h.get("Fecha") and h.get("Llegada")
    ]
    if len(puntos) < 2:
        return None
    df = pd.DataFrame(puntos)
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    peor = int(df["Llegada"].max())
    base = alt.Chart(df).encode(
        x=alt.X("Fecha:T", title=None, axis=alt.Axis(format="%d/%m")),
        y=alt.Y(
            "Llegada:Q",
            scale=alt.Scale(reverse=True, domain=[1, max(peor, 4)]),
            title="Llegada",
            axis=alt.Axis(tickMinStep=1),
        ),
        tooltip=[alt.Tooltip("Fecha:T", format="%d/%m/%Y"), "Llegada", "Ganador"],
    )
    linea = base.mark_line(color=VERDE, strokeWidth=3)
    puntos_chart = base.mark_circle(size=120, color=DORADO)
    return (linea + puntos_chart).properties(height=220)
