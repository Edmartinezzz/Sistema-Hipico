"""Módulo 6 — Gaceta hípica desde la web (sin PDF).

Fuente: Desafío Hípico (https://www.desafiohipico.com), que publica
gratis los datos oficiales del INH/HINAVA de La Rinconada y del
Hipódromo Nacional de Valencia. Su ``robots.txt`` permite
``/retrospectos`` y ``/revista/``.

Flujo:
1. ``list_meetings()`` lee ``/retrospectos`` y extrae las reuniones del
   bloque JSON-LD (``SportsEvent`` con fecha y URL).
2. ``meetings_for_week()`` filtra las reuniones de la semana (lunes a
   domingo) que contiene la fecha elegida.
3. ``fetch_meeting()`` descarga ``/revista/<id>`` y extrae el JSON
   ``initialData`` incrustado por Next.js (carreras, inscritos,
   historial y traqueos). Se cachea en ``data/cache/`` porque cada
   página pesa varios MB.
4. ``meeting_to_records()`` convierte la reunión al mismo formato de
   registros que ``pdf_extractor.extract_races`` más campos de forma.

Las peticiones pasan por ``scraper.rate_limited_get`` (1 req/s,
User-Agent identificable, reintentos). Si el sitio cambia su estructura
se lanza ``GacetaWebError`` con un mensaje claro; nunca se inventan
datos.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.scraper import rate_limited_get

logger = logging.getLogger(__name__)

BASE_URL = "https://www.desafiohipico.com"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
# Reuniones aún por correr: refrescar la caché cada hora (retirados, etc.).
CACHE_TTL_PENDIENTE = 3600

_LD_JSON_RE = re.compile(
    r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)
_RSC_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
_MEETING_ID_RE = re.compile(r"/revista/([0-9a-f]+)")
_NOMBRE_REUNION_RE = re.compile(r"Reuni[óo]n\s+H[íi]pica\s+(\d+)\s*·\s*(.+)")


class GacetaWebError(RuntimeError):
    """La web no respondió o su estructura cambió."""


def _get_html(url: str) -> str:
    try:
        respuesta = rate_limited_get(url)
    except Exception as exc:  # noqa: BLE001 - se reexpone con mensaje claro
        raise GacetaWebError(f"No se pudo conectar con {url}: {exc}") from exc
    if respuesta.status_code != 200:
        raise GacetaWebError(f"HTTP {respuesta.status_code} en {url}")
    respuesta.encoding = "utf-8"
    return respuesta.text


def parse_meetings(html: str) -> list[dict[str, Any]]:
    """Extrae las reuniones (``SportsEvent``) del JSON-LD de la página."""
    reuniones = []
    for bloque in _LD_JSON_RE.findall(html):
        try:
            datos = json.loads(bloque)
        except json.JSONDecodeError:
            continue
        for evento in datos.get("hasPart", []) if isinstance(datos, dict) else []:
            if evento.get("@type") != "SportsEvent":
                continue
            id_match = _MEETING_ID_RE.search(evento.get("url", ""))
            nombre_match = _NOMBRE_REUNION_RE.search(evento.get("name", ""))
            try:
                fecha = datetime.fromisoformat(
                    evento["startDate"].replace("Z", "+00:00")
                ).date()
            except (KeyError, ValueError):
                continue
            if not id_match:
                continue
            reuniones.append(
                {
                    "id": id_match.group(1),
                    "number": int(nombre_match.group(1)) if nombre_match else None,
                    "track": nombre_match.group(2).strip() if nombre_match else None,
                    "date": fecha,
                    "url": f"{BASE_URL}/revista/{id_match.group(1)}",
                }
            )
    return sorted(reuniones, key=lambda r: r["date"], reverse=True)


def list_meetings() -> list[dict[str, Any]]:
    """Reuniones publicadas (las más recientes primero)."""
    reuniones = parse_meetings(_get_html(f"{BASE_URL}/retrospectos"))
    if not reuniones:
        raise GacetaWebError(
            "No se encontraron reuniones en /retrospectos; "
            "es posible que el sitio haya cambiado su estructura."
        )
    return reuniones


def week_range(dia: date) -> tuple[date, date]:
    """Lunes y domingo de la semana que contiene ``dia``."""
    lunes = dia - timedelta(days=dia.weekday())
    return lunes, lunes + timedelta(days=6)


def meetings_for_week(
    dia: date, reuniones: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Reuniones cuya fecha cae en la semana (lunes-domingo) de ``dia``."""
    lunes, domingo = week_range(dia)
    return sorted(
        (r for r in reuniones if lunes <= r["date"] <= domingo),
        key=lambda r: r["date"],
    )


def parse_meeting_html(html: str) -> dict[str, Any]:
    """Extrae el objeto ``initialData`` del payload Next.js de la página."""
    payload = []
    for trozo in _RSC_RE.findall(html):
        try:
            payload.append(json.loads(f'"{trozo}"'))
        except json.JSONDecodeError:
            continue
    texto = "".join(payload)
    marca = '"initialData":'
    inicio = texto.find(marca)
    if inicio < 0:
        raise GacetaWebError(
            "La página de la reunión no contiene 'initialData'; "
            "es posible que el sitio haya cambiado su estructura."
        )
    try:
        datos, _ = json.JSONDecoder().raw_decode(texto, inicio + len(marca))
    except json.JSONDecodeError as exc:
        raise GacetaWebError(f"JSON de la reunión inválido: {exc}") from exc
    if "races" not in datos:
        raise GacetaWebError("La reunión no trae la lista de carreras")
    return datos


def fetch_meeting(
    meeting_id: str,
    cache_dir: str | Path = CACHE_DIR,
    usar_cache: bool = True,
) -> dict[str, Any]:
    """Descarga una reunión, usando la caché local si es válida.

    Las reuniones terminadas se cachean indefinidamente; las que tienen
    carreras por correr se refrescan cada ``CACHE_TTL_PENDIENTE`` segundos.
    """
    cache = Path(cache_dir) / f"reunion_{meeting_id}.json"
    if usar_cache and cache.exists():
        datos = json.loads(cache.read_text(encoding="utf-8"))
        pendiente = any(r.get("status") != "finished" for r in datos["races"])
        edad = time.time() - cache.stat().st_mtime
        if not pendiente or edad < CACHE_TTL_PENDIENTE:
            logger.info("Reunión %s leída de la caché", meeting_id)
            return datos
    datos = parse_meeting_html(_get_html(f"{BASE_URL}/revista/{meeting_id}"))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos


def _parse_numero(texto: Any) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", str(texto or ""))
    return float(match.group().replace(",", ".")) if match else None


def _cuerpos_detras(actuacion: dict[str, Any]) -> float | None:
    """Cuerpos de desventaja frente al ganador (0 si ganó)."""
    if actuacion.get("finishPosition") == 1:
        return 0.0
    return _parse_numero(actuacion.get("diffVsFirst"))


def scratched(datos: dict[str, Any]) -> list[dict[str, Any]]:
    """Ejemplares retirados de la reunión: ``[{race_number, horse_name}]``."""
    return [
        {"race_number": c.get("raceNumber"), "horse_name": e.get("horseName")}
        for c in datos.get("races", [])
        for e in c.get("entries", [])
        if e.get("isScratched")
    ]


def meeting_to_records(datos: dict[str, Any]) -> list[dict[str, Any]]:
    """Convierte una reunión en registros (uno por inscrito no retirado).

    Incluye las claves de ``pdf_extractor.extract_races`` (``odds`` queda
    en ``None``: la web no publica cuotas) más campos de forma:
    ``year_starts``, ``year_wins``, ``lengths_behind``, ``history`` y
    ``workouts``.
    """
    reunion = datos.get("meeting", {})
    registros = []
    for carrera in datos["races"]:
        for inscrito in carrera.get("entries", []):
            if inscrito.get("isScratched"):
                logger.info(
                    "Retirado: %s (carrera %s)",
                    inscrito.get("horseName"), carrera.get("raceNumber"),
                )
                continue
            stats = inscrito.get("yearStats") or {}
            historial = inscrito.get("raceHistory") or []
            registros.append(
                {
                    "race_number": carrera.get("raceNumber"),
                    "horse_name": inscrito.get("horseName"),
                    "jockey": inscrito.get("jockeyName") or None,
                    "trainer": inscrito.get("trainerName") or None,
                    "weight": _parse_numero(inscrito.get("weightDeclared")),
                    "odds": None,
                    "post_position": inscrito.get("postPosition"),
                    "record": (
                        f"{stats['starts']}-{stats['wins']}"
                        if "starts" in stats and "wins" in stats
                        else None
                    ),
                    "morning_line_favorite": False,
                    "dorsal": inscrito.get("dorsalNumber"),
                    "stud": inscrito.get("studName") or None,
                    "distance": carrera.get("distance"),
                    "race_status": carrera.get("status"),
                    "finish_position": inscrito.get("finishPosition"),
                    "track": reunion.get("trackName"),
                    "meeting_number": reunion.get("meetingNumber"),
                    "date": (reunion.get("date") or "")[:10] or None,
                    "race_video": carrera.get("videoUrl"),
                    "conditions": carrera.get("conditions") or None,
                    "year_starts": stats.get("starts"),
                    "year_wins": stats.get("wins"),
                    "lengths_behind": [_cuerpos_detras(a) for a in historial],
                    "history": [
                        {
                            "Fecha": (a.get("date") or "")[:10],
                            "Hipódromo": a.get("trackName"),
                            "Reunión": a.get("meetingNumber"),
                            "Carrera": a.get("raceNumber"),
                            "Dist.": a.get("distance"),
                            "Llegada": a.get("finishPosition"),
                            "Cuerpos": a.get("diffVsFirst"),
                            "Jinete": a.get("jockeyName"),
                            "Kg": a.get("weight"),
                            "Tiempo": a.get("officialTime"),
                            "Tiempo ganador": a.get("winnerTime"),
                            "Ganador": a.get("winnerName"),
                            "Video": a.get("videoUrl"),
                        }
                        for a in historial
                    ],
                    "workouts": [
                        {
                            "Fecha": (t.get("workoutDate") or "")[:10],
                            "Tipo": t.get("workoutType"),
                            "Parciales": t.get("splits"),
                            "Comentario": t.get("comment"),
                            "Jinete": t.get("jockeyName"),
                        }
                        for t in inscrito.get("workouts") or []
                    ],
                    "source": "desafiohipico",
                }
            )
    return registros
