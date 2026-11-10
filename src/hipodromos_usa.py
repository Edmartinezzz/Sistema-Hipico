"""Módulo — Hipódromos de EE.UU. (Equibase, sin login).

Fuente: mirror estático ``tvg.equibase.com``, que publica los mismos
entries que ``www.equibase.com`` pero sin la protección anti-bot de
Imperva (que en ``www`` responde 200 con una página de "Pardon Our
Interruption" en lugar de datos). Es la misma empresa (TVG es de
Equibase/Flutter); los datos son los oficiales de los hipódromos
norteamericanos.

Flujo:
1. ``list_meetings()`` lee ``/static/entry/index.html`` y extrae la
   tabla ``#tracks``: para cada hipódromo enlaza tarjetas
   ``RaceCardIndex{TRK}{MMDDYY}{PAIS}-EQB.html`` en las columnas
   Today / Tomorrow / Future / Past.
2. ``fetch_meeting()`` descarga el RaceCardIndex del día (tabla
   ``#entryRaces``: número de carrera, bolsa, tipo, distancia,
   superficie, participantes, hora) y luego cada página de carrera
   ``{TRK}{MMDDYY}{PAIS}{N}-EQB.html`` con la tabla de inscritos
   (P#, PP, caballo, edad/sexo, jinete, peso, entrenador, M/L).
3. ``meeting_to_records()`` normaliza al mismo formato de registros
   que ``gaceta_web.meeting_to_records`` para reutilizar todo el
   análisis (probabilidades, Harville, value bets).

Las peticiones pasan por ``scraper.rate_limited_get`` (1 req/s). Las
reuniones ya corridas se cachean indefinidamente en ``data/cache/``;
las del día se refrescan cada ``CACHE_TTL_PENDIENTE`` segundos.
Nunca se inventan datos: si la estructura cambia se lanza
``HipodromosUsaError``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.harville_model import fractional_to_decimal
from src.scraper import rate_limited_get

logger = logging.getLogger(__name__)

BASE_URL = "https://tvg.equibase.com"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
# Tarjetas aún por correr: refrescar la caché cada hora (retirados, etc.).
CACHE_TTL_PENDIENTE = 3600

INDEX_URL = f"{BASE_URL}/static/entry/index.html"

_CARD_RE = re.compile(
    r"RaceCardIndex([A-Z]{2,5})(\d{2})(\d{2})(\d{2})([A-Z]{3})-EQB\.html",
    re.I,
)
_RACE_LINK_RE = re.compile(
    r"/static/entry[\\/]([A-Z]{2,5}\d{6}[A-Z]{3})(\d+)-EQB\.html", re.I
)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_TRACK_NAME_RE = re.compile(
    r'/static/entry[\\/][A-Z]{2,5}-calendar\.html[^>]*>\s*([^<]+?)\s*<', re.I
)
_TABLE_TRACKS_RE = re.compile(
    r'<table id="tracks".*?</table>', re.S | re.I
)
_TABLE_RACES_RE = re.compile(
    r'<table[^>]*id="entryRaces".*?</table>', re.S | re.I
)
_ENTRIES_TABLE_RE = re.compile(
    r"<table class=\"fullwidth\">(.*?)</table>", re.S | re.I
)
_SADDLE_RE = re.compile(r"saddlecloth-(\d+)")
_HORSE_LINK_RE = re.compile(
    r'<a href="[^"]*type=Horse[^"]*"[^>]*title="\s*\((.*?)\)\s*"[^>]*>\s*'
    r"(.*?)\s*</a>",
    re.S,
)
_PERSON_LINK_RE = re.compile(r'<a href="[^"]*"[^>]*>\s*([^<]+?)\s*</a>')
_POST_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*[AP]M\s*[A-Z]{2})")
_RACE_TITLE_RE = re.compile(r"<strong>([^<]+)</strong>\s*([^<]+?)\s*</p>")
_DATE_MOBILE_RE = re.compile(r"\|\s*([A-Z][a-z]+ \d{1,2}, \d{4})")
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

# Columnas del índice: 0 hipódromo, 1 hoy, 2 mañana, 3 futuro, 4 pasado.
_SLOTS = ("today", "tomorrow", "future", "past")


class HipodromosUsaError(RuntimeError):
    """Equibase no respondió o su estructura cambió."""


def _get_html(url: str) -> str:
    try:
        respuesta = rate_limited_get(url)
    except Exception as exc:  # noqa: BLE001 - se reexpone con mensaje claro
        raise HipodromosUsaError(f"No se pudo conectar con {url}: {exc}") from exc
    if respuesta.status_code == 404:
        raise HipodromosUsaError(f"La página no existe: {url}")
    if respuesta.status_code != 200:
        raise HipodromosUsaError(f"HTTP {respuesta.status_code} en {url}")
    respuesta.encoding = "utf-8"
    if "Pardon Our Interruption" in respuesta.text:
        raise HipodromosUsaError(
            f"{url} respondió con el anti-bot de Imperva, no con datos"
        )
    return respuesta.text


def _texto(html: str) -> str:
    """Texto plano de un fragmento HTML (espacios normalizados)."""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html)).strip()


def _fecha_desde_codigo(mes: str, dia: str, anio: str) -> date:
    """MMDDYY de Equibase a ``date`` (año 2000 + YY)."""
    return date(2000 + int(anio), int(mes), int(dia))


def parse_meetings(html: str) -> list[dict[str, Any]]:
    """Extrae las tarjetas del índice de entries de Equibase.

    Devuelve ``[{track_code, track_name, country, date, slot, url}]``
    donde ``slot`` es ``'today' | 'tomorrow' | 'future' | 'past'`` según
    la columna de la tabla ``#tracks``. Las tablas "Featured Tracks" y
    "All Tracks" se deduplican por (hipódromo, fecha).
    """
    reuniones: dict[tuple[str, date], dict[str, Any]] = {}
    for tabla in _TABLE_TRACKS_RE.findall(html):
        for fila in _ROW_RE.findall(tabla):
            nombre_match = _TRACK_NAME_RE.search(fila)
            if not nombre_match:
                continue
            celdas = _CELL_RE.findall(fila)
            for idx, celda in enumerate(celdas[1:], start=1):
                slot = _SLOTS[idx - 1] if idx <= len(_SLOTS) else "future"
                for enlace in _CARD_RE.finditer(celda):
                    trk, mes, dia, anio, pais = enlace.groups()
                    clave = (trk.upper(), _fecha_desde_codigo(mes, dia, anio))
                    reuniones.setdefault(
                        clave,
                        {
                            "track_code": trk.upper(),
                            "track_name": nombre_match.group(1).strip(),
                            "country": pais.upper(),
                            "date": clave[1],
                            "slot": slot,
                            "url": (
                                f"{BASE_URL}/static/entry/"
                                f"RaceCardIndex{trk.upper()}{mes}{dia}{anio}"
                                f"{pais.upper()}-EQB.html"
                            ),
                        },
                    )
    return sorted(
        reuniones.values(),
        key=lambda r: (r["slot"] != "today", r["date"], r["track_name"]),
        reverse=False,
    )


def list_meetings() -> list[dict[str, Any]]:
    """Tarjetas publicadas (hoy/mañana/futuro/pasado) de todos los tracks."""
    reuniones = parse_meetings(_get_html(INDEX_URL))
    if not reuniones:
        raise HipodromosUsaError(
            "No se encontraron tarjetas en el índice de Equibase; "
            "es posible que el sitio haya cambiado su estructura."
        )
    return reuniones


def parse_card_index(html: str) -> list[dict[str, Any]]:
    """Resumen de carreras del día desde la tabla ``#entryRaces``.

    Devuelve ``[{race_number, purse, race_type, distance, surface,
    starters, post_time, url}]``; ``url`` apunta a la página de esa
    carrera con la tabla de inscritos.
    """
    tabla_match = _TABLE_RACES_RE.search(html)
    if not tabla_match:
        raise HipodromosUsaError(
            "La tarjeta no contiene la tabla de carreras (#entryRaces)"
        )
    carreras = []
    for fila in _ROW_RE.findall(tabla_match.group(0))[1:]:
        celdas = _CELL_RE.findall(fila)
        if len(celdas) < 7:
            continue
        enlace = _RACE_LINK_RE.search(fila)
        numero = _entero(_texto(celdas[0]))
        if numero is None or enlace is None:
            continue
        post = _POST_TIME_RE.search(_texto(celdas[6]))
        carreras.append(
            {
                "race_number": numero,
                "purse": _texto(celdas[1]) or None,
                "race_type": _texto(celdas[2]) or None,
                "distance": _texto(celdas[3]) or None,
                "surface": _texto(celdas[4]) or None,
                "starters": _entero(_texto(celdas[5])),
                "post_time": post.group(1) if post else _texto(celdas[6]),
                "url": f"{BASE_URL}/static/entry/{enlace.group(1)}"
                f"{enlace.group(2)}-EQB.html",
            }
        )
    if not carreras:
        raise HipodromosUsaError(
            "La tabla de carreras está vacía; la estructura pudo cambiar"
        )
    return carreras


def _entero(texto: str) -> int | None:
    match = re.search(r"\d+", texto.replace(",", ""))
    return int(match.group()) if match else None


def _numero(texto: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", texto.replace(",", ""))
    return float(match.group()) if match else None


def _edad_sexo(texto: str) -> tuple[int | None, str | None]:
    """'2/F' -> (2, 'F'); '5/H' -> (5, 'H')."""
    match = re.match(r"\s*(\d+)\s*/\s*([A-Z])", texto)
    if not match:
        return None, None
    return int(match.group(1)), match.group(2)


def parse_race_page(html: str, race_number: int) -> dict[str, Any]:
    """Extrae la tabla de inscritos de una página de carrera.

    Devuelve ``{race_number, race_name, wagers, conditions,
    entries: [{program, post_position, horse_name, bred, pedigree,
    age, sex, medication, claiming_price, jockey, weight, trainer,
    morning_line, scratched}]}``. Los inscritos retirados se marcan
    con ``scratched=True`` pero no se excluyen aquí.
    """
    info_match = re.search(
        r'<div class="race-info">(.*?)(?:<div class="entries-race-conditions">|'
        r"<table)",
        html,
        re.S,
    )
    wagers = titulo = ""
    if info_match:
        parrafos = re.findall(r"<p[^>]*>(.*?)</p>", info_match.group(1), re.S)
        if parrafos:
            wagers = _texto(parrafos[0])
        if len(parrafos) > 1:
            titulo = _texto(parrafos[1])
    cond_match = re.search(
        r'<div class="conditions-text">(.*?)</div>', html, re.S
    )
    condiciones = _texto(cond_match.group(1)) if cond_match else None

    tabla_match = _ENTRIES_TABLE_RE.search(html)
    if not tabla_match:
        raise HipodromosUsaError(
            f"La carrera {race_number} no contiene la tabla de inscritos"
        )
    inscritos = []
    for fila in _ROW_RE.findall(tabla_match.group(1))[1:]:
        retirado = "scratch" in fila.lower()
        celdas = _CELL_RE.findall(fila)
        if len(celdas) < 10:
            continue
        dorsal = _SADDLE_RE.search(celdas[0])
        caballo_match = _HORSE_LINK_RE.search(celdas[2])
        nombre = _texto(caballo_match.group(2)) if caballo_match else _texto(
            celdas[2]
        )
        if not nombre:
            continue
        origen = re.search(r"\(([A-Z]{2,4})\)\s*$", nombre)
        edad, sexo = _edad_sexo(_texto(celdas[4]))
        jockey_link = _PERSON_LINK_RE.search(celdas[7])
        trainer_link = _PERSON_LINK_RE.search(celdas[9])
        inscritos.append(
            {
                "program": _entero(dorsal.group(1)) if dorsal else _entero(
                    _texto(celdas[0])
                ),
                "post_position": _entero(_texto(celdas[1])),
                "horse_name": nombre,
                "bred": origen.group(1) if origen else None,
                "pedigree": (
                    caballo_match.group(1).strip() if caballo_match else None
                ),
                "age": edad,
                "sex": sexo,
                "medication": _texto(celdas[5]) or None,
                "claiming_price": _numero(_texto(celdas[6])),
                "jockey": (
                    re.sub(r"\s+", " ", jockey_link.group(1)).strip()
                    if jockey_link
                    else _texto(celdas[7]) or None
                ),
                "weight": _numero(_texto(celdas[8])),
                "trainer": (
                    re.sub(r"\s+", " ", trainer_link.group(1)).strip()
                    if trainer_link
                    else _texto(celdas[9]) or None
                ),
                "morning_line": _texto(celdas[10]) or None,
                "scratched": retirado,
            }
        )
    if not inscritos:
        raise HipodromosUsaError(
            f"La carrera {race_number} no tiene inscritos; "
            "la estructura pudo cambiar"
        )
    return {
        "race_number": race_number,
        "race_name": titulo or None,
        "wagers": wagers or None,
        "conditions": condiciones,
        "entries": inscritos,
    }


_MOBILE_BASE = "https://mobile.equibase.com"
_MOBILE_DAY_RE = re.compile(
    r"/html/entries([A-Z]{2,5})(\d{8})(\d{2})\.html", re.I
)
_MOBILE_ENTRY_RE = re.compile(
    r"Program:\s*(\d+)\s+Post:\s*(\d+)\s+Odds:\s*([^<]*)<br>\s*"
    r"<b>([^<]+)</b>\s*<br>\s*Jockey:\s*([^<]*)<br>\s*Trainer:\s*([^<]*)",
    re.I,
)


def fetch_meeting_mobile(reunion: dict[str, Any]) -> dict[str, Any]:
    """Respaldo ligero: sitio móvil de Equibase (``mobile.equibase.com``).

    Sirve los mismos datos oficiales en HTML simple (~3 KB por carrera)
    sin anti-bot. Tiene menos campos que la fuente principal (sin peso,
    bolsa ni condiciones), pero incluye programa, puesto, cuota M/L,
    caballo, jinete y entrenador.
    """
    trk = reunion["track_code"]
    pais = reunion.get("country", "USA")
    fecha = reunion["date"]
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha[:10])
    dia = _get_html(f"{_MOBILE_BASE}/html/entries{trk}{fecha:%Y%m%d}.html")
    enlaces = _MOBILE_DAY_RE.findall(dia)
    if not enlaces:
        raise HipodromosUsaError(
            f"El sitio móvil no tiene carreras para {trk} {fecha:%Y-%m-%d}"
        )
    carreras = []
    for trk_e, fecha_e, num_e in enlaces:
        html = _get_html(
            f"{_MOBILE_BASE}/html/entries{trk_e}{fecha_e}{num_e}.html"
        )
        post = re.search(r"Post Time:\s*([^<]+)", html)
        tipo = re.search(
            r"Post Time:[^<]*<br>\s*<br>([^<]+)<br>", html
        )
        inscritos = [
            {
                "program": int(m.group(1)),
                "post_position": int(m.group(2)),
                "horse_name": re.sub(r"\s+", " ", m.group(4)).strip(),
                "bred": None,
                "pedigree": None,
                "age": None,
                "sex": None,
                "medication": None,
                "claiming_price": None,
                "jockey": re.sub(r"\s+", " ", m.group(5)).strip() or None,
                "weight": None,
                "trainer": re.sub(r"\s+", " ", m.group(6)).strip() or None,
                "morning_line": m.group(3).strip() or None,
                "scratched": "scratch" in m.group(0).lower(),
            }
            for m in _MOBILE_ENTRY_RE.finditer(html)
        ]
        carreras.append(
            {
                "race_number": int(num_e),
                "race_name": None,
                "wagers": None,
                "conditions": tipo.group(1).strip() if tipo else None,
                "purse": None,
                "race_type": tipo.group(1).strip() if tipo else None,
                "distance": None,
                "surface": None,
                "post_time": post.group(1).strip() if post else None,
                "entries": inscritos,
            }
        )
    return {
        "meeting": {
            "track_code": trk,
            "trackName": reunion.get("track_name"),
            "country": pais,
            "date": fecha.isoformat(),
        },
        "slot": reunion.get("slot"),
        "races": carreras,
    }


def fetch_meeting(
    reunion: dict[str, Any],
    cache_dir: str | Path = CACHE_DIR,
    usar_cache: bool = True,
    usar_respaldo: bool = True,
) -> dict[str, Any]:
    """Descarga una tarjeta completa (índice + todas las carreras).

    ``reunion`` es un dict de ``list_meetings()`` (o equivalente con
    ``track_code``, ``country``, ``date``). Resultado cacheado como
    ``data/cache/usa_{TRK}_{PAIS}_{YYYYMMDD}.json``; las tarjetas del
    día se refrescan cada hora. Si la fuente principal (tvg.equibase)
    falla, intenta el sitio móvil como respaldo (``usar_respaldo``).
    """
    trk = reunion["track_code"]
    pais = reunion.get("country", "USA")
    fecha = reunion["date"]
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha[:10])
    cache = Path(cache_dir) / f"usa_{trk}_{pais}_{fecha:%Y%m%d}.json"
    if usar_cache and cache.exists():
        datos = json.loads(cache.read_text(encoding="utf-8"))
        pendiente = datos.get("slot") in ("today", "tomorrow", "future")
        edad = time.time() - cache.stat().st_mtime
        if not pendiente or edad < CACHE_TTL_PENDIENTE:
            logger.info("Tarjeta %s %s leída de la caché", trk, fecha)
            return datos
    try:
        html = _get_html(reunion["url"])
        resumen = parse_card_index(html)
        carreras = []
        for c in resumen:
            datos_carrera = parse_race_page(
                _get_html(c["url"]), c["race_number"]
            )
            datos_carrera.update(
                {
                    "purse": c.get("purse"),
                    "race_type": c.get("race_type"),
                    "distance": c.get("distance"),
                    "surface": c.get("surface"),
                    "post_time": c.get("post_time"),
                }
            )
            carreras.append(datos_carrera)
        datos = {
            "meeting": {
                "track_code": trk,
                "trackName": reunion.get("track_name"),
                "country": pais,
                "date": fecha.isoformat(),
            },
            "slot": reunion.get("slot"),
            "races": carreras,
            "source": "equibase",
        }
    except HipodromosUsaError:
        if not usar_respaldo:
            raise
        logger.warning(
            "Fuente principal falló para %s %s; usando sitio móvil",
            trk, fecha,
        )
        datos = fetch_meeting_mobile(reunion)
        datos["source"] = "equibase_mobile"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos


def scratched(datos: dict[str, Any]) -> list[dict[str, Any]]:
    """Ejemplares retirados de la tarjeta: ``[{race_number, horse_name}]``."""
    return [
        {"race_number": c.get("race_number"), "horse_name": e.get("horse_name")}
        for c in datos.get("races", [])
        for e in c.get("entries", [])
        if e.get("scratched")
    ]


def meeting_to_records(datos: dict[str, Any]) -> list[dict[str, Any]]:
    """Convierte una tarjeta USA en registros (uno por inscrito no retirado).

    Mismo formato que ``gaceta_web.meeting_to_records``: la línea
    matutina (M/L) pasa a ``odds`` en cuota decimal vía
    ``fractional_to_decimal`` y el favorito de la M/L se marca con
    ``morning_line_favorite``. El peso de Equibase es en libras (lbs),
    campo ``weight_lbs=True`` para distinguirlo del kg venezolano.
    """
    reunion = datos.get("meeting", {})
    # El favorito M/L es el de menor cuota en cada carrera.
    registros = []
    for carrera in datos["races"]:
        activos = [e for e in carrera.get("entries", []) if not e.get("scratched")]
        cuotas = [
            fractional_to_decimal(e.get("morning_line") or "")
            for e in activos
        ]
        cuota_min = min((c for c in cuotas if c), default=None)
        for inscrito, cuota in zip(activos, cuotas):
            if inscrito.get("scratched"):
                continue
            registros.append(
                {
                    "race_number": carrera.get("race_number"),
                    "horse_name": inscrito.get("horse_name"),
                    "jockey": inscrito.get("jockey") or None,
                    "trainer": inscrito.get("trainer") or None,
                    "weight": inscrito.get("weight"),
                    "weight_lbs": True,
                    "odds": cuota,
                    "post_position": inscrito.get("post_position"),
                    "record": None,
                    "morning_line": inscrito.get("morning_line"),
                    "morning_line_favorite": bool(
                        cuota is not None and cuota == cuota_min
                    ),
                    "dorsal": inscrito.get("program"),
                    "stud": inscrito.get("bred"),
                    "distance": carrera.get("distance"),
                    "surface": carrera.get("surface"),
                    "race_status": "pending",
                    "finish_position": None,
                    "track": reunion.get("trackName"),
                    "track_code": reunion.get("track_code"),
                    "meeting_number": None,
                    "date": (reunion.get("date") or "")[:10] or None,
                    "race_video": None,
                    "conditions": carrera.get("conditions"),
                    "race_name": carrera.get("race_name"),
                    "purse": carrera.get("purse"),
                    "race_type": carrera.get("race_type"),
                    "post_time": carrera.get("post_time"),
                    "wagers": carrera.get("wagers"),
                    "age": inscrito.get("age"),
                    "sex": inscrito.get("sex"),
                    "medication": inscrito.get("medication"),
                    "claiming_price": inscrito.get("claiming_price"),
                    "pedigree": inscrito.get("pedigree"),
                    "year_starts": None,
                    "year_wins": None,
                    "lengths_behind": [],
                    "history": [],
                    "workouts": [],
                    "source": "equibase",
                }
            )
    return registros


def meetings_for_day(
    reuniones: list[dict[str, Any]], slot: str = "today"
) -> list[dict[str, Any]]:
    """Filtra las tarjetas de un slot ('today', 'tomorrow', ...)."""
    return [r for r in reuniones if r.get("slot") == slot]
