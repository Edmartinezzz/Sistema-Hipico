"""Módulo 9 — Archivo histórico propio de reuniones.

La web solo conserva unos 2 meses de reuniones. Este módulo guarda cada
reunión (recortada a los campos que usa el sistema) en
``data/archivo/<fecha>_<hipódromo>_<id>.json.gz`` para que el histórico
crezca cada semana y el modelo aprenda con más carreras.

El archivo se versiona en git: en la nube (Streamlit Community Cloud) la
tarea semanal de GitHub Actions (``scripts/archivar.py``) añade las
reuniones nuevas y la app las lee del repositorio.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from src.gaceta_web import GacetaWebError, fetch_meeting, list_meetings

logger = logging.getLogger(__name__)

ARCHIVO_DIR = Path(__file__).resolve().parent.parent / "data" / "archivo"

_CAMPOS_REUNION = ("id", "meetingNumber", "date", "trackName", "trackCode", "status")
_CAMPOS_CARRERA = ("raceNumber", "distance", "conditions", "status", "videoUrl", "scheduledTime")
_CAMPOS_INSCRITO = (
    "dorsalNumber", "postPosition", "horseName", "jockeyName", "trainerName",
    "studName", "weightDeclared", "isScratched", "finishPosition", "yearStats",
)
_CAMPOS_HISTORIAL = (
    "date", "trackName", "meetingNumber", "raceNumber", "distance", "weight",
    "jockeyName", "finishPosition", "officialTime", "winnerTime", "diffVsFirst",
    "winnerName", "videoUrl",
)
_CAMPOS_TRAQUEO = ("workoutDate", "workoutType", "splits", "comment", "jockeyName", "rm")


def _sub(d: dict[str, Any], campos: tuple[str, ...]) -> dict[str, Any]:
    return {k: d[k] for k in campos if k in d}


def recortar(datos: dict[str, Any]) -> dict[str, Any]:
    """Conserva solo los campos que usa el sistema (reduce ~10x el tamaño)."""
    return {
        "meeting": _sub(datos.get("meeting", {}), _CAMPOS_REUNION),
        "races": [
            {
                **_sub(c, _CAMPOS_CARRERA),
                "entries": [
                    {
                        **_sub(e, _CAMPOS_INSCRITO),
                        "raceHistory": [_sub(a, _CAMPOS_HISTORIAL) for a in e.get("raceHistory") or []],
                        "workouts": [_sub(t, _CAMPOS_TRAQUEO) for t in e.get("workouts") or []],
                    }
                    for e in c.get("entries", [])
                ],
            }
            for c in datos.get("races", [])
        ],
    }


def terminada(datos: dict[str, Any], hoy: date | None = None) -> bool:
    """``True`` si la reunión ya no va a cambiar.

    Todas sus carreras terminaron, o su fecha ya pasó (hay reuniones con
    carreras suspendidas que nunca pasan a ``finished``).
    """
    carreras = datos.get("races") or []
    if carreras and all(c.get("status") == "finished" for c in carreras):
        return True
    fecha = str(datos.get("meeting", {}).get("date", ""))[:10]
    try:
        return date.fromisoformat(fecha) < (hoy or date.today())
    except ValueError:
        return False


def _nombre_archivo(datos: dict[str, Any]) -> str:
    m = datos["meeting"]
    pista = re.sub(r"[^A-Z0-9]+", "_", str(m.get("trackName") or "X").upper()).strip("_")
    return f"{str(m.get('date', ''))[:10]}_{pista}_{m['id']}.json.gz"


def guardar_reunion(datos: dict[str, Any], directorio: str | Path = ARCHIVO_DIR) -> Path:
    """Guarda (o reemplaza) una reunión en el archivo. Devuelve la ruta."""
    recortada = recortar(datos)
    ruta = Path(directorio) / _nombre_archivo(recortada)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = json.dumps(recortada, ensure_ascii=False, separators=(",", ":"))
    # mtime=0 -> mismo contenido produce el mismo archivo (sin commits vacíos).
    with gzip.GzipFile(ruta, "wb", mtime=0) as fh:
        fh.write(contenido.encode("utf-8"))
    return ruta


def leer(ruta: str | Path) -> dict[str, Any]:
    with gzip.open(ruta, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def listar(directorio: str | Path = ARCHIVO_DIR) -> list[dict[str, Any]]:
    """Reuniones archivadas (más recientes primero), mismo formato que
    ``gaceta_web.parse_meetings`` más la ``ruta`` del archivo."""
    reuniones = []
    for ruta in Path(directorio).glob("*.json.gz"):
        match = re.match(r"(\d{4}-\d{2}-\d{2})_(.+)_([0-9a-f]+)\.json\.gz$", ruta.name)
        if not match:
            continue
        datos_min = leer(ruta)["meeting"]
        reuniones.append(
            {
                "id": match.group(3),
                "number": datos_min.get("meetingNumber"),
                "track": datos_min.get("trackName"),
                "date": date.fromisoformat(match.group(1)),
                "ruta": ruta,
            }
        )
    return sorted(reuniones, key=lambda r: r["date"], reverse=True)


def cargar_todas(directorio: str | Path = ARCHIVO_DIR) -> list[dict[str, Any]]:
    """Todas las reuniones archivadas, en orden cronológico."""
    return [leer(r["ruta"]) for r in reversed(listar(directorio))]


def buscar(meeting_id: str, directorio: str | Path = ARCHIVO_DIR) -> dict[str, Any] | None:
    """Reunión archivada por id, o ``None``."""
    for ruta in Path(directorio).glob(f"*_{meeting_id}.json.gz"):
        return leer(ruta)
    return None


def unir_con_web(
    web: list[dict[str, Any]], archivadas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Lista de reuniones de la web + las archivadas que la web ya no muestra."""
    ids = {r["id"] for r in web}
    extra = [{k: v for k, v in r.items() if k != "ruta"} for r in archivadas if r["id"] not in ids]
    return sorted([*web, *extra], key=lambda r: r["date"], reverse=True)


def sincronizar(directorio: str | Path = ARCHIVO_DIR) -> dict[str, int]:
    """Descarga y archiva las reuniones terminadas que aún no están guardadas.

    Devuelve ``{"nuevas", "ya_archivadas", "pendientes", "errores"}``.
    """
    resumen = {"nuevas": 0, "ya_archivadas": 0, "pendientes": 0, "errores": 0}
    guardadas = {r["id"] for r in listar(directorio)}
    for reunion in list_meetings():
        if reunion["id"] in guardadas:
            resumen["ya_archivadas"] += 1
            continue
        try:
            datos = fetch_meeting(reunion["id"])
        except GacetaWebError as exc:
            logger.warning("No se pudo archivar %s: %s", reunion["id"], exc)
            resumen["errores"] += 1
            continue
        if not terminada(datos):
            resumen["pendientes"] += 1
            continue
        guardar_reunion(datos, directorio)
        resumen["nuevas"] += 1
    return resumen
