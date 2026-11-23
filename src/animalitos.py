"""Animalitos de Venezuela — historial de sorteos y estadísticas.

Fuente: ResultadosVenezuela (https://resultadosvenezuela.com), que
publica gratis los resultados oficiales de las loterías de animalitos
(Lotto Activo, La Granjita, Ruleta Activa, Guácharo Activo, etc.).
Cada página ``/lottery/<slug>?date=AAAA-MM-DD`` trae las tarjetas
``.result-card`` con hora, número y nombre del animalito ganador.

Flujo:
1. ``sorteos_dia()`` descarga y cachea los sorteos de una fecha; un
   día pasado solo se da por definitivo si se descargó después de
   terminar, y el día de hoy se revalida cada ``CACHE_TTL_HOY``
   segundos (sorteos en curso).
2. ``actualizar_archivo()`` guarda los días ya terminados en
   ``data/animalitos/<slug>.json.gz`` (versionado en git; lo actualiza
   cada día la tarea de GitHub Actions) para que la app cargue meses
   de historial sin pedir nada a la red.
3. ``historial()`` junta varias semanas de sorteos: archivo, luego
   caché local y, solo si ``red=True``, la fuente.
4. Las funciones ``tabla_dia()``, ``pronostico_horas()``,
   ``aciertos()``, ``enjaulados()`` y ``calientes()`` son puras:
   reciben la lista de sorteos y devuelven estadísticas.

Las probabilidades mostradas son frecuencias históricas con suavizado
de Laplace; los sorteos son aleatorios y el historial no garantiza
resultados futuros. Nunca se inventan datos.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from src.scraper import rate_limited_get

logger = logging.getLogger(__name__)

BASE_URL = "https://resultadosvenezuela.com"
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "animalitos"
ARCHIVO_DIR = Path(__file__).resolve().parent.parent / "data" / "animalitos"
# El día en curso publica sorteos cada hora: revalidar la caché seguido.
CACHE_TTL_HOY = 900
# Días que guarda el archivo (la fuente conserva ~6 meses).
DIAS_ARCHIVO = 182
DIAS_ARCHIVO_MAX = 400
# Un día vacío reciente puede ser un fallo pasajero: no se archiva.
DIAS_GRACIA_VACIO = 3
# La fuente usa estos textos cuando no conoce el nombre del animalito.
NOMBRES_GENERICOS = {"", "-", "resultado", "pendiente", "sin nombre"}

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


# Los sorteos son en hora de Venezuela (UTC-4 todo el año); el servidor
# en la nube corre en UTC y después de las 8 PM ya sería "mañana".
ZONA_VE = timezone(timedelta(hours=-4))


def hoy_ve() -> date:
    """Fecha actual en Venezuela."""
    return datetime.now(ZONA_VE).date()


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
        if not numero:
            continue
        if nombre.lower() in NOMBRES_GENERICOS:
            nombre = f"N.º {numero}"
        hora_txt = hora_el.get_text(strip=True) if hora_el else ""
        try:
            num = int(numero)
        except ValueError:
            num = None
        img_el = tarjeta.find("img")
        imagen = img_el.get("src", "") if img_el else ""
        if imagen and imagen.startswith("/"):
            imagen = f"{BASE_URL}{imagen}"
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
                "imagen": imagen or None,
            }
        )
    return sorteos


def _generico(nombre: str | None) -> bool:
    """``True`` si el nombre es un relleno (``N.º 96``) y no el animal."""
    return not nombre or nombre.startswith("N.º ")


def _limpiar(sorteos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normaliza nombres genéricos de cachés guardadas antes del arreglo."""
    for s in sorteos:
        if (s.get("nombre") or "").lower() in NOMBRES_GENERICOS:
            s["nombre"] = f"N.º {s['numero']}"
    return sorteos


def _cache_path(slug: str, fecha: date, cache_dir: str | Path) -> Path:
    return Path(cache_dir) / f"{slug}_{fecha.isoformat()}.json"


def sorteos_dia(
    slug: str,
    fecha: date,
    cache_dir: str | Path = CACHE_DIR,
    usar_cache: bool = True,
    red: bool = True,
) -> list[dict[str, Any]]:
    """Sorteos de una lotería en una fecha (con caché en disco).

    Un día pasado solo se toma de la caché si se descargó cuando ya había
    terminado (si se guardó a media jornada, faltan sorteos). Con
    ``red=False`` nunca se pide la fuente: se devuelve lo que haya.
    """
    cache = _cache_path(slug, fecha, cache_dir)
    if cache.exists() and (usar_cache or not red):
        mtime = cache.stat().st_mtime
        definitivo = datetime.fromtimestamp(mtime, ZONA_VE).date() > fecha
        if not red or definitivo or time.time() - mtime < CACHE_TTL_HOY:
            logger.info("Sorteos %s %s leídos de la caché", slug, fecha)
            return _limpiar(json.loads(cache.read_text(encoding="utf-8")))
    if not red:
        return []
    html = _get_html(f"{BASE_URL}/lottery/{slug}?date={fecha.isoformat()}")
    sorteos = parse_dia(html, slug, fecha)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(sorteos, ensure_ascii=False), encoding="utf-8")
    return sorteos


# ------------------------------------------------------------------ archivo


def _archivo_path(slug: str, archivo_dir: str | Path) -> Path:
    return Path(archivo_dir) / f"{slug}.json.gz"


def _compactar(sorteos: list[dict[str, Any]]) -> list[list[Any]]:
    """Solo lo que no se deriva de la fecha: ``[hora, número, nombre, imagen]``."""
    return [[s["hora"], s["numero"], s["nombre"], s.get("imagen")] for s in sorteos]


def _expandir(slug: str, fecha: date, filas: list[list[Any]]) -> list[dict[str, Any]]:
    return [
        {
            "loteria": slug,
            "fecha": fecha.isoformat(),
            "dia_semana": DIAS[fecha.weekday()],
            "hora": hora,
            "hora24": _hora24(hora),
            "numero": numero,
            "num": int(numero) if str(numero).isdigit() else None,
            "nombre": nombre,
            "imagen": imagen,
        }
        for hora, numero, nombre, imagen in filas
    ]


def _leer_archivo_crudo(slug: str, archivo_dir: str | Path) -> dict[str, list]:
    ruta = _archivo_path(slug, archivo_dir)
    if not ruta.exists():
        return {}
    try:
        with gzip.open(ruta, "rt", encoding="utf-8") as fh:
            return json.load(fh).get("dias", {})
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Archivo de animalitos dañado (%s): %s", ruta, exc)
        return {}


def leer_archivo(
    slug: str, archivo_dir: str | Path = ARCHIVO_DIR
) -> dict[str, list[dict[str, Any]]]:
    """Días archivados de una lotería: ``{"AAAA-MM-DD": [sorteos]}``."""
    return {
        f: _expandir(slug, date.fromisoformat(f), filas)
        for f, filas in _leer_archivo_crudo(slug, archivo_dir).items()
    }


def actualizar_archivo(
    slug: str,
    dias: int = DIAS_ARCHIVO,
    archivo_dir: str | Path = ARCHIVO_DIR,
    cache_dir: str | Path = CACHE_DIR,
    hoy: date | None = None,
) -> dict[str, int]:
    """Añade al archivo los días terminados que falten (hoy no se archiva).

    Reutiliza la caché local válida; lo demás se pide a la fuente
    respetando el límite de 1 petición/segundo de ``rate_limited_get``.
    """
    if slug not in LOTERIAS:
        raise AnimalitosError(f"Lotería desconocida: {slug}")
    hoy = hoy or hoy_ve()
    crudo = _leer_archivo_crudo(slug, archivo_dir)
    nuevos = errores = 0
    for i in range(dias, 0, -1):
        fecha = hoy - timedelta(days=i)
        if fecha.isoformat() in crudo:
            continue
        try:
            sorteos = sorteos_dia(slug, fecha, cache_dir)
        except AnimalitosError as exc:
            logger.warning("Sin datos de %s en %s: %s", slug, fecha, exc)
            errores += 1
            continue
        if not sorteos and i <= DIAS_GRACIA_VACIO:
            continue
        crudo[fecha.isoformat()] = _compactar(sorteos)
        nuevos += 1
    corte = (hoy - timedelta(days=DIAS_ARCHIVO_MAX)).isoformat()
    crudo = {f: v for f, v in sorted(crudo.items()) if f >= corte}
    if nuevos:
        ruta = _archivo_path(slug, archivo_dir)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # mtime=0: el .gz no cambia si los datos no cambian (diff limpio en git).
        with open(ruta, "wb") as crudo_fh, gzip.GzipFile(
            fileobj=crudo_fh, mode="wb", mtime=0
        ) as gz:
            gz.write(
                json.dumps(
                    {"loteria": slug, "dias": crudo},
                    ensure_ascii=False, separators=(",", ":"),
                ).encode("utf-8")
            )
    return {"nuevos": nuevos, "errores": errores, "dias": len(crudo)}


def historial(
    slug: str,
    dias: int,
    cache_dir: str | Path = CACHE_DIR,
    progreso: Any = None,
    red: bool = True,
    archivo_dir: str | Path = ARCHIVO_DIR,
) -> list[dict[str, Any]]:
    """Sorteos de los últimos ``dias`` días (hoy inclusive).

    Primero el archivo versionado, luego la caché local y, si ``red``,
    la fuente para los días que falten. ``progreso`` es opcional: un
    callable ``f(i, dias)`` para barras de progreso en la UI.
    """
    if slug not in LOTERIAS:
        raise AnimalitosError(f"Lotería desconocida: {slug}")
    hoy = hoy_ve()
    archivo = leer_archivo(slug, archivo_dir)
    todos: list[dict[str, Any]] = []
    for i in range(dias):
        fecha = hoy - timedelta(days=dias - 1 - i)
        if fecha.isoformat() in archivo:
            todos.extend(archivo[fecha.isoformat()])
        else:
            try:
                todos.extend(sorteos_dia(slug, fecha, cache_dir, red=red))
            except AnimalitosError:
                logger.warning("Sin datos de %s en %s", slug, fecha)
        if progreso:
            progreso(i + 1, dias)
    return todos


def animales(sorteos: list[dict[str, Any]]) -> dict[str, str]:
    """Mapa número → nombre visto en el historial (el real gana al genérico)."""
    mapa: dict[str, str] = {}
    for s in sorteos:
        if s["numero"] not in mapa or (_generico(mapa[s["numero"]]) and not _generico(s["nombre"])):
            mapa[s["numero"]] = s["nombre"]
    return mapa


def _mapa_path(slug: str, cache_dir: str | Path) -> Path:
    return Path(cache_dir) / f"{slug}_mapa.json"


def mapa_animales(
    slug: str,
    sorteos: list[dict[str, Any]] | None = None,
    cache_dir: str | Path = CACHE_DIR,
    red: bool = True,
) -> dict[str, dict[str, str]]:
    """Mapa persistente número → ``{"nombre", "imagen"}`` de una lotería.

    Se llena con las páginas ya descargadas y, si aún no conoce ninguna
    imagen (caché vieja sin ese campo), pide un día fresco a la fuente
    para sembrarlo. Solo es una petición extra la primera vez. Con
    ``red=False`` solo usa lo que ya conoce.
    """
    ruta = _mapa_path(slug, cache_dir)
    mapa: dict[str, dict[str, str]] = {}
    if ruta.exists():
        try:
            mapa = json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            mapa = {}

    def _sumar(lista: list[dict[str, Any]]) -> None:
        for s in lista:
            entrada = mapa.setdefault(s["numero"], {"nombre": s["nombre"]})
            if not _generico(s["nombre"]) or _generico(entrada.get("nombre")):
                entrada["nombre"] = s["nombre"]
            if s.get("imagen"):
                entrada["imagen"] = s["imagen"]

    _sumar(_limpiar(list(sorteos or [])))

    def _cobertura() -> float:
        if not mapa:
            return 0.0
        return sum(1 for v in mapa.values() if v.get("imagen")) / len(mapa)

    # Sembrado: si la mayoría no tiene dibujo (caché vieja sin ese campo),
    # pedir días recientes frescos hasta cubrir ~90% o probar una semana.
    for retroceso in range(7 if red else 0):
        if _cobertura() >= 0.9:
            break
        fecha = hoy_ve() - timedelta(days=retroceso)
        try:
            fresco = parse_dia(
                _get_html(f"{BASE_URL}/lottery/{slug}?date={fecha.isoformat()}"),
                slug,
                fecha,
            )
        except AnimalitosError:
            continue
        _sumar(fresco)
        if not fresco and retroceso > 2:
            break

    # Último recurso: el dibujo sigue un patrón fijo por lotería
    # (`assets/images/animales/<slug>/<Nombre sin acentos>_1.webp`);
    # verificar que exista para no mostrar una imagen rota.
    for entrada in mapa.values():
        if (
            not red
            or entrada.get("imagen")
            or entrada.get("sin_img")
            or _generico(entrada.get("nombre"))
        ):
            continue
        nombre = "".join(
            c
            for c in unicodedata.normalize("NFD", entrada["nombre"])
            if unicodedata.category(c) != "Mn"
        )
        url = (
            f"{BASE_URL}/assets/images/animales/{slug}/"
            f"{quote(nombre)}_1.webp"
        )
        try:
            respuesta = rate_limited_get(url)
        except Exception:  # noqa: BLE001 - red caída: se reintenta luego
            continue
        if respuesta.status_code == 200 and "image" in (
            respuesta.headers.get("Content-Type") or ""
        ):
            entrada["imagen"] = url
        elif respuesta.status_code == 404:
            entrada["sin_img"] = True
    if mapa:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(mapa, ensure_ascii=False), encoding="utf-8")
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
    hoy = hoy_ve()
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
    corte = hoy_ve() - timedelta(days=dias - 1)
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


def pronostico_horas(
    sorteos: list[dict[str, Any]], dia_semana: int, top: int = 3
) -> list[dict[str, Any]]:
    """Animalitos más frecuentes en cada sorteo (hora) de un día de semana.

    Orden: veces en ese día + hora; empata la frecuencia de esa hora en
    toda la semana (más muestra) y luego el número. Cada hora trae pocos
    sorteos (uno por semana), así que es orientativo.
    """
    por_hora = Counter((s.get("hora"), s["numero"]) for s in sorteos)
    resultado = []
    for hora in horas_disponibles(sorteos, dia_semana):
        tabla = tabla_dia(sorteos, dia_semana, hora)
        tabla.sort(
            key=lambda f: (-f["veces"], -por_hora[(hora, f["numero"])], f["numero"])
        )
        resultado.append(
            {
                "hora": hora,
                "hora24": _hora24(hora),
                "sorteos": tabla[0]["sorteos"] if tabla else 0,
                "top": [f for f in tabla if f["veces"]][:top],
            }
        )
    return resultado


def aciertos(
    sorteos_hoy: list[dict[str, Any]],
    top_dia: list[str],
    top_hora: dict[str, list[str]],
    n_animales: int,
) -> dict[str, Any]:
    """Compara los sorteos de hoy con lo recomendado (números).

    ``esperado`` es lo que acertaría el azar con la misma cantidad de
    números: ``sorteos × len(top_dia) / n_animales``.
    """
    filas = sorted(
        (
            {
                **s,
                "en_top_dia": s["numero"] in top_dia,
                "en_top_hora": s["numero"] in top_hora.get(s.get("hora"), []),
            }
            for s in sorteos_hoy
        ),
        key=lambda s: (s.get("hora24") is None, s.get("hora24") or 0),
    )
    n = len(filas)
    return {
        "filas": filas,
        "sorteos": n,
        "dia": sum(f["en_top_dia"] for f in filas),
        "hora": sum(f["en_top_hora"] for f in filas),
        "esperado": n * len(top_dia) / n_animales if n_animales else 0.0,
    }


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
