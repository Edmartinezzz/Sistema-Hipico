"""Búsqueda automática de la gaceta del día en internet.

Fuente principal: la revista de Desafío Hípico (``/retrospectos`` y
``/revista/<id>``), que publica inscritos, historial y traqueos de La Rinconada
y Valencia. Si falla, se descarga la revista en PDF publicada en pollamacaco.com
y se lee con :func:`pdf_extractor.extract_races`.

Ninguna de las dos fuentes publica cuotas (*morning line*): los caballos llegan
con ``odds=None`` y el modelo usa un mercado uniforme (ver ``pipeline``).
Todas las peticiones pasan por :func:`scraper.rate_limited_get` (User-Agent
propio y 1 petición/s por dominio). Solo se leen rutas permitidas por el
``robots.txt`` de cada sitio.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from src import pdf_extractor, scraper

logger = logging.getLogger(__name__)

DESAFIO_BASE = "https://www.desafiohipico.com"
DESAFIO_LIST_URL = f"{DESAFIO_BASE}/retrospectos"
POLLAMACACO_URLS = {"LA RINCONADA": "https://pollamacaco.com/Revistas/LaRinconada.pdf"}
TRACKS = {"LA RINCONADA": "La Rinconada", "VALENCIA": "Valencia"}
MAX_PDF_BYTES = 30 * 1024 * 1024
VENEZUELA_TZ = timezone(timedelta(hours=-4))

_NEXT_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)\s*</script>', re.S)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


class GacetaNoEncontrada(Exception):
    """No se pudo obtener la gaceta de ninguna fuente."""


def today_in_venezuela() -> date:
    """Fecha actual en Venezuela (UTC−4, sin horario de verano)."""
    return datetime.now(VENEZUELA_TZ).date()


def _next_payload(html: str) -> str:
    """Une los fragmentos ``self.__next_f`` que Next.js incrusta en la página."""
    return "".join(json.loads(f'"{chunk}"') for chunk in _NEXT_CHUNK_RE.findall(html))


def _decode_after(text: str, key: str) -> Any:
    index = text.find(key)
    if index < 0:
        return None
    try:
        start = index + len(key)
        start += len(text[start:start + 50]) - len(text[start:start + 50].lstrip())
        value, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    return value


def _track_key(name: str) -> str | None:
    upper = pdf_extractor._strip_accents(name or "").upper()
    return next((key for key in TRACKS if key in upper), None)


def parse_meeting_list(html: str) -> list[dict[str, Any]]:
    """Lee las reuniones de ``/retrospectos``.

    Returns:
        Lista de ``{"track", "date", "url", "name"}`` (``track`` es una clave de
        :data:`TRACKS` y ``date`` un :class:`datetime.date`).
    """
    events = _decode_after(_next_payload(html) or html, '"hasPart":') or []
    meetings = []
    for event in events:
        if not isinstance(event, dict):
            continue
        track = _track_key(event.get("name", ""))
        try:
            day = date.fromisoformat(str(event.get("startDate", ""))[:10])
        except ValueError:
            continue
        if track and event.get("url"):
            meetings.append(
                {"track": track, "date": day, "url": event["url"], "name": event.get("name")}
            )
    return meetings


def pick_meeting(
    meetings: list[dict[str, Any]], track: str, today: date
) -> dict[str, Any] | None:
    """Elige la próxima reunión del hipódromo (o la de hoy); si no hay, la más reciente."""
    own = [m for m in meetings if m["track"] == track]
    upcoming = sorted((m for m in own if m["date"] >= today), key=lambda m: m["date"])
    if upcoming:
        return upcoming[0]
    past = sorted(own, key=lambda m: m["date"], reverse=True)
    return past[0] if past else None


def _weight(raw: Any) -> float | None:
    match = _NUMBER_RE.search(str(raw or ""))
    return float(match.group().replace(",", ".")) if match else None


def _entry_to_horse(entry: dict[str, Any], race: dict[str, Any], meeting: dict[str, Any]):
    stats = entry.get("yearStats") or {}
    scratched = bool(entry.get("isScratched"))
    distance = race.get("distance")
    return {
        "horse_name": (entry.get("horseName") or "").strip() or None,
        "jockey": entry.get("jockeyName") or None,
        "trainer": entry.get("trainerName") or None,
        "weight": _weight(entry.get("weightDeclared")),
        "odds_raw": "RET" if scratched else None,
        "odds": None,
        "implied_probability": None,
        "odds_published": False,
        "post_position": entry.get("postPosition") or entry.get("dorsalNumber"),
        "record": None,
        "starts": stats.get("starts"),
        "wins": stats.get("wins"),
        "scratched": scratched,
        "race_number": race.get("raceNumber"),
        "distance": f"{distance} m" if distance else None,
        "surface": None,
        "track": TRACKS.get(_track_key(meeting.get("trackName", "")) or "")
        or meeting.get("trackName"),
        "date": str(meeting.get("date", ""))[:10] or None,
        "morning_line_favorite": False,
    }


def parse_desafio_revista(html: str) -> list[dict[str, Any]]:
    """Convierte la página ``/revista/<id>`` en caballos con el formato de ``extract_races``.

    ``starts`` y ``wins`` son las estadísticas del año (``yearStats``).
    """
    data = _decode_after(_next_payload(html) or html, '"initialData":')
    if not isinstance(data, dict) or not data.get("races"):
        return []
    meeting = data.get("meeting") or {}
    horses = []
    for race in data["races"]:
        for entry in race.get("entries") or []:
            horse = _entry_to_horse(entry, race, meeting)
            if horse["horse_name"]:
                horses.append(horse)
    return horses


def fetch_desafio(track: str, today: date) -> tuple[list[dict[str, Any]], str]:
    """Descarga la reunión de Desafío Hípico. Devuelve ``(caballos, descripción)``."""
    listing = scraper.rate_limited_get(DESAFIO_LIST_URL)
    meeting = pick_meeting(parse_meeting_list(listing.text), track, today)
    if meeting is None:
        raise GacetaNoEncontrada(f"Desafío Hípico no tiene reuniones de {TRACKS[track]}")
    page = scraper.rate_limited_get(meeting["url"])
    horses = parse_desafio_revista(page.text)
    if not horses:
        raise GacetaNoEncontrada(f"La revista {meeting['url']} no trae inscritos legibles")
    if meeting["date"] < today:
        logger.warning(
            "Aún no hay reunión publicada desde hoy; se muestra la del %s", meeting["date"]
        )
    return horses, f"Desafío Hípico · {meeting['name']} · {meeting['date']}"


def fetch_pollamacaco(track: str, today: date) -> tuple[list[dict[str, Any]], str]:
    """Descarga la revista PDF de pollamacaco.com y la lee con el extractor."""
    url = POLLAMACACO_URLS.get(track)
    if url is None:
        raise GacetaNoEncontrada(f"pollamacaco.com no publica revista de {TRACKS[track]}")
    response = scraper.rate_limited_get(url, timeout=60)
    content = response.content
    if not content.startswith(b"%PDF") or len(content) > MAX_PDF_BYTES:
        raise GacetaNoEncontrada(f"{url} no devolvió un PDF válido")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(content)
    path = Path(handle.name)
    try:
        horses = pdf_extractor.extract_races(str(path))
    finally:
        path.unlink(missing_ok=True)
    if not horses:
        raise GacetaNoEncontrada(f"{url} no trae tablas de caballos legibles")
    day = horses[0].get("date")
    if day and day != today.isoformat():
        logger.warning("La revista de pollamacaco.com es del %s, no de hoy", day)
    return horses, f"pollamacaco.com · revista {TRACKS[track]} · {day or 'sin fecha'}"


def fetch_gaceta(
    track: str = "LA RINCONADA", today: date | None = None
) -> tuple[list[dict[str, Any]], str]:
    """Busca la gaceta del día: primero Desafío Hípico y, si falla, pollamacaco.com.

    Args:
        track: clave de :data:`TRACKS` (``"LA RINCONADA"`` o ``"VALENCIA"``).
        today: fecha de referencia (por defecto, hoy en Venezuela).

    Returns:
        ``(caballos, descripción de la fuente)``.

    Raises:
        GacetaNoEncontrada: si ninguna fuente funcionó.
    """
    if track not in TRACKS:
        raise ValueError(f"Hipódromo desconocido: {track}")
    today = today or today_in_venezuela()
    errors = []
    for fetch in (fetch_desafio, fetch_pollamacaco):
        try:
            return fetch(track, today)
        except (requests.RequestException, GacetaNoEncontrada, ValueError) as exc:
            logger.warning("Fuente %s falló: %s", fetch.__name__.removeprefix("fetch_"), exc)
            errors.append(str(exc))
    raise GacetaNoEncontrada("No se encontró la gaceta: " + "; ".join(errors))
