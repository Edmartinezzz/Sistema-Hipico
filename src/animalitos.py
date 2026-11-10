"""Animalitos de Venezuela — historial de sorteos y estadísticas.

Fuente: ResultadosVenezuela (https://resultadosvenezuela.com), que
publica gratis los resultados oficiales de las loterías de animalitos
(Lotto Activo, La Granjita, Ruleta Activa, Guácharo Activo, etc.).
Cada página ``/lottery/<slug>?date=AAAA-MM-DD`` trae las tarjetas
``.result-card`` con hora, número y nombre del animalito ganador.

Flujo:
1. ``sorteos_dia()`` descarga y cachea los sorteos de una fecha; los
   días pasados se cachean indefinidamente y el día de hoy se
   revalida cada ``CACHE_TTL_HOY`` segundos (sorteos en curso).
2. ``historial()`` junta varias semanas de sorteos para análisis.
3. Las funciones ``tabla_dia()``, ``enjaulados()`` y ``calientes()``
   son puras: reciben la lista de sorteos y devuelven estadísticas
   por día de semana, ausencias y rachas recientes.

Las probabilidades mostradas son frecuencias históricas con suavizado
de Laplace; los sorteos son aleatorios y el historial no garantiza
resultados futuros. Nunca se inventan datos.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.scraper import rate_limited_get

logger = logging.getLogger(__name__)

BASE_URL = "https://resultadosvenezuela.com"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "animalitos"
# El día en curso publica sorteos cada hora: revalidar la caché seguido.
CACHE_TTL_HOY = 900
PAUSA_ENTRE_DIAS = 0.35

# Loterías de animalitos verificadas en la fuente (slug → nombre visible).
LOTERIAS = {
    "lotto-activo": "Lotto Activo",
    "la-granjita": "La Granjita",
    "ruleta-activa": "Ruleta Activa",
    "guacharo-activo": "Guácharo Activo",
    "selva-plus": "Selva Plus",
    "lotto-activo-rd": "Lotto Activo RD Internacional",
    "la-ricachona-animalito": "La Ricachona",
    "granjazo": "El Granjazo",
    "chance-animalitos": "Chance con Animalitos",
}

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


class AnimalitosError(RuntimeError):
    """La fuente no respondió o su estructura cambió."""


def _get_html(url: str) -> str:
    try:
        respuesta = rate_limited_get(url)
    except Exception as exc:  # noqa: BLE001 - se reexpone con mensaje claro
        raise AnimalitosError(f"No se pudo conectar con {url}: {exc}") from exc
    if respuesta.status_code != 200:
        raise AnimalitosError(f"HTTP {respuesta.status_code} en {url}")
    respuesta.encoding = "utf-8"
    return respuesta.text


def _hora24(texto: str) -> int | None:
    """'07:30 PM' -> 19 (hora en 24h); ``None`` si no se reconoce."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])", texto or "")
    if not m:
        return None
    hora = int(m.group(1)) % 12
    if m.group(3).upper() == "PM":
        hora += 12
    return hora


def parse_dia(html: str, slug: str, fecha: date) -> list[dict[str, Any]]:
    """Extrae los sorteos de una página de resultados diarios.

    Cada tarjeta ``.result-card`` trae ``.card-time`` (hora),
    ``.card-number`` (número), ``.card-name`` (animal) y ``.card-date``.
    """
    from bs4 import BeautifulSoup

    sopa = BeautifulSoup(html, "html.parser")
    sorteos = []
    for tarjeta in sopa.select(".result-card"):
        numero_el = tarjeta.select_one(".card-number")
        nombre_el = tarjeta.select_one(".card-name")
        hora_el = tarjeta.select_one(".card-time")
        if not numero_el or not nombre_el:
            continue
        numero = numero_el.get_text(strip=True)
        nombre = nombre_el.get_text(strip=True)
        if not numero or not nombre:
            continue
        hora_txt = hora_el.get_text(strip=True) if hora_el else ""
        try:
            num = int(numero)
        except ValueError:
            num = None
        sorteos.append(
            {
                "loteria": slug,
                "fecha": fecha.isoformat(),
                "dia_semana": DIAS[fecha.weekday()],
                "hora": hora_txt,
                "hora24": _hora24(hora_txt),
                "numero": numero,
                "num": num,
                "nombre": nombre,
            }
        )
    return sorteos


def _cache_path(slug: str, fecha: date, cache_dir: str | Path) -> Path:
    return Path(cache_dir) / f"{slug}_{fecha.isoformat()}.json"


def sorteos_dia(
    slug: str,
    fecha: date,
    cache_dir: str | Path = CACHE_DIR,
    usar_cache: bool = True,
) -> list[dict[str, Any]]:
    """Sorteos de una lotería en una fecha (con caché en disco)."""
    cache = _cache_path(slug, fecha, cache_dir)
    if usar_cache and cache.exists():
        edad = time.time() - cache.stat().st_mtime
        if fecha < date.today() or edad < CACHE_TTL_HOY:
            logger.info("Sorteos %s %s leídos de la caché", slug, fecha)
            return json.loads(cache.read_text(encoding="utf-8"))
    html = _get_html(f"{BASE_URL}/lottery/{slug}?date={fecha.isoformat()}")
    sorteos = parse_dia(html, slug, fecha)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(sorteos, ensure_ascii=False), encoding="utf-8")
    return sorteos


def historial(
    slug: str,
    dias: int,
    cache_dir: str | Path = CACHE_DIR,
    progreso: Any = None,
) -> list[dict[str, Any]]:
    """Sorteos de los últimos ``dias`` días (hoy inclusive).

    ``progreso`` es opcional: un callable ``f(i, dias)`` para barras de
    progreso en la UI.
    """
    if slug not in LOTERIAS:
        raise AnimalitosError(f"Lotería desconocida: {slug}")
    hoy = date.today()
    todos: list[dict[str, Any]] = []
    for i in range(dias):
        fecha = hoy - timedelta(days=dias - 1 - i)
        try:
            todos.extend(sorteos_dia(slug, fecha, cache_dir))
        except AnimalitosError:
            logger.warning("Sin datos de %s en %s", slug, fecha)
        if progreso:
            progreso(i + 1, dias)
        elif i + 1 < dias:
            time.sleep(PAUSA_ENTRE_DIAS)
    return todos


def animales(sorteos: list[dict[str, Any]]) -> dict[str, str]:
    """Mapa número → nombre visto en el historial."""
    mapa: dict[str, str] = {}
    for s in sorteos:
        mapa.setdefault(s["numero"], s["nombre"])
    return mapa


def tabla_dia(
    sorteos: list[dict[str, Any]],
    dia_semana: int,
    hora: str | None = None,
    suavizado: float = 1.0,
) -> list[dict[str, Any]]:
    """Frecuencias por animalito para un día de la semana (0=lunes).

    ``prob`` es la frecuencia con suavizado de Laplace sobre los sorteos
    de ese día (y de esa ``hora`` si se indica, p. ej. ``"10:00 AM"``).
    ``prob_teorica`` es 1/N con N = animalitos distintos observados.
    """
    mapa = animales(sorteos)
    n = max(len(mapa), 1)
    filtrados = [
        s
        for s in sorteos
        if s.get("dia_semana") == DIAS[dia_semana]
        and (hora is None or s.get("hora") == hora)
    ]
    conteo = Counter(s["numero"] for s in filtrados)
    dias_vistos: dict[str, set] = defaultdict(set)
    for s in filtrados:
        dias_vistos[s["numero"]].add(s["fecha"])
    total = len(filtrados)
    tabla = []
    for numero, nombre in sorted(mapa.items(), key=lambda kv: (kv[0].isdigit(), kv[0])):
        veces = conteo.get(numero, 0)
        tabla.append(
            {
                "numero": numero,
                "nombre": nombre,
                "veces": veces,
                "dias": len(dias_vistos.get(numero, ())),
                "sorteos": total,
                "prob": (veces + suavizado) / (total + suavizado * n) if total else 0.0,
                "prob_teorica": 1.0 / n,
            }
        )
    tabla.sort(key=lambda f: (-f["veces"], -f["dias"], f["numero"]))
    return tabla


def enjaulados(sorteos: list[dict[str, Any]], limite: int = 10) -> list[dict[str, Any]]:
    """Animalitos con más tiempo sin salir (días desde la última vez)."""
    mapa = animales(sorteos)
    ultima: dict[str, date] = {}
    for s in sorteos:
        try:
            f = date.fromisoformat(s["fecha"])
        except ValueError:
            continue
        if s["numero"] not in ultima or f > ultima[s["numero"]]:
            ultima[s["numero"]] = f
    hoy = date.today()
    tabla = [
        {
            "numero": num,
            "nombre": mapa[num],
            "ultima_vez": ultima[num].isoformat(),
            "dias_sin_salir": (hoy - ultima[num]).days,
        }
        for num in ultima
    ]
    tabla.sort(key=lambda f: -f["dias_sin_salir"])
    return tabla[:limite]


def calientes(sorteos: list[dict[str, Any]], dias: int = 7, limite: int = 10) -> list[dict[str, Any]]:
    """Animalitos más repetidos en los últimos ``dias`` días."""
    corte = date.today() - timedelta(days=dias - 1)
    conteo = Counter(
        s["numero"] for s in sorteos if date.fromisoformat(s["fecha"]) >= corte
    )
    mapa = animales(sorteos)
    return [
        {"numero": num, "nombre": mapa.get(num, num), "veces": veces}
        for num, veces in conteo.most_common(limite)
    ]


def horas_disponibles(sorteos: list[dict[str, Any]], dia_semana: int) -> list[str]:
    """Horarios de sorteo vistos para un día de la semana, ordenados."""
    vistos = {
        s["hora"]
        for s in sorteos
        if s.get("dia_semana") == DIAS[dia_semana] and s.get("hora")
    }
    return sorted(vistos, key=lambda h: (_hora24(h) or 0, h))


def resumen(sorteos: list[dict[str, Any]]) -> dict[str, Any]:
    """Totales para el encabezado de la sección."""
    fechas = sorted({s["fecha"] for s in sorteos})
    return {
        "sorteos": len(sorteos),
        "dias": len(fechas),
        "desde": fechas[0] if fechas else None,
        "hasta": fechas[-1] if fechas else None,
        "animales": len(animales(sorteos)),
    }
