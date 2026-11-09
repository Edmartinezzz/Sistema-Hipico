"""Módulo 2 — Enriquecimiento de datos de caballos con fuentes gratuitas.

Estrategia (documentada en ``docs/fuentes_datos.md``):
1. Caché local en SQLite (tabla ``enrichment``).
2. CSV locales exportados manualmente (p. ej. datasets de Kaggle).
3. Scraping respetuoso de fuentes gratuitas (inspirado en la estructura
   de ``rpscrape``): ``rate_limited_get`` aplica 1 s entre peticiones,
   User-Agent identificable y reintentos exponenciales (máx 3).

Reglas:
- Nunca inventar datos: si una fuente falla o el caballo no existe, se
  registra un warning y se devuelve ``{"found": False, "source": None}``.
- ``offline=True`` usa solo SQLite + CSV, sin red (útil para tests).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from src.database import (
    get_connection,
    save_enrichment,
    upsert_horse,
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "SistemaHipico/0.1 (+analisis estadistico de carreras; "
    "contacto: usuario local)"
)
_REQUEST_GAP = 1.0  # segundos entre peticiones al mismo dominio
_MAX_RETRIES = 3
_timeout = 15
_last_request_at = 0.0


def rate_limited_get(url: str, **kwargs: Any) -> requests.Response:
    """GET con rate limiting, User-Agent y reintentos exponenciales.

    Aplica ``time.sleep`` para no superar 1 req/segundo, un User-Agent
    identificable y hasta 3 intentos con espera 1s, 2s, 4s ante errores
    HTTP 5xx o de conexión. Lanza la última excepción si todo falla.
    """
    global _last_request_at
    kwargs.setdefault("timeout", _timeout)
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("User-Agent", USER_AGENT)
    kwargs["headers"] = headers

    ultimo_error: Exception | None = None
    for intento in range(_MAX_RETRIES):
        espera = _REQUEST_GAP - (time.monotonic() - _last_request_at)
        if espera > 0:
            time.sleep(espera)
        _last_request_at = time.monotonic()
        try:
            respuesta = requests.get(url, **kwargs)
            if respuesta.status_code < 500:
                return respuesta
            ultimo_error = requests.HTTPError(
                f"HTTP {respuesta.status_code} en {url}"
            )
        except requests.RequestException as exc:
            ultimo_error = exc
        backoff = 2 ** intento
        logger.warning(
            "Intento %d/%d falló (%s); reintentando en %ds",
            intento + 1, _MAX_RETRIES, ultimo_error, backoff,
        )
        time.sleep(backoff)
    assert ultimo_error is not None
    raise ultimo_error


def _buscar_en_cache(horse_name: str, db_path: str) -> dict[str, Any] | None:
    """Lee el último registro de enriquecimiento cacheado, si existe."""
    with get_connection(db_path) as conn:
        horse = conn.execute(
            "SELECT id FROM horses WHERE name = ?", (horse_name,)
        ).fetchone()
        if horse is None:
            return None
        fila = conn.execute(
            """SELECT source, data_json, fetched_at FROM enrichment
               WHERE horse_id = ? ORDER BY fetched_at DESC LIMIT 1""",
            (horse["id"],),
        ).fetchone()
        if fila is None:
            return None
        return {
            "found": True,
            "source": fila["source"],
            "fetched_at": fila["fetched_at"],
            "data": json.loads(fila["data_json"] or "null"),
        }


def _buscar_en_csv(horse_name: str, csv_dir: str | Path) -> dict[str, Any] | None:
    """Busca el caballo en CSVs locales (descargas manuales de Kaggle).

    Cada ``*.csv`` del directorio se escanea buscando una columna de
    nombre ("horse", "horse_name", "nombre", "caballo", "name").
    """
    csv_dir = Path(csv_dir)
    if not csv_dir.is_dir():
        return None
    nombre_objetivo = horse_name.strip().lower()
    for csv_file in sorted(csv_dir.glob("*.csv")):
        try:
            with csv_file.open(newline="", encoding="utf-8", errors="replace") as fh:
                for fila in csv.DictReader(fh):
                    claves_nombre = {
                        "horse", "horse_name", "nombre", "caballo", "name",
                    }
                    for clave, valor in fila.items():
                        if clave and clave.strip().lower() in claves_nombre and (
                            valor and valor.strip().lower() == nombre_objetivo
                        ):
                            return {
                                "found": True,
                                "source": f"csv:{csv_file.name}",
                                "data": dict(fila),
                            }
        except OSError as exc:
            logger.warning("No se pudo leer %s: %s", csv_file, exc)
    return None


def _scrape_fuente(horse_name: str) -> dict[str, Any] | None:
    """Intenta enriquecer desde fuentes web gratuitas.

    Degrada elegantemente: cualquier error de red, cambio de sitio o
    bloqueo devuelve ``None`` con un warning, nunca rompe el pipeline.
    Las credenciales opcionales (p. ej. Brisnet) se leen de variables de
    entorno, nunca hardcodeadas.
    """
    brisnet_user = os.getenv("BRISNET_USER")
    brisnet_pass = os.getenv("BRISNET_PASS")
    if not (brisnet_user and brisnet_pass):
        logger.info(
            "Sin credenciales Brisnet (BRISNET_USER/BRISNET_PASS); "
            "se omite el scraping para %s", horse_name,
        )
        return None
    try:
        # Punto de extensión: autenticación + parseo de la fuente real.
        # Se mantiene aislado para que un cambio del sitio no rompa el
        # pipeline completo.
        return None
    except Exception as exc:  # noqa: BLE001 - degradación elegante
        logger.warning("El scraping falló para %s: %s", horse_name, exc)
        return None


def enrich_horse(
    horse_name: str,
    db_path: str,
    offline: bool = False,
    csv_dir: str | Path = "data/enrichment",
) -> dict[str, Any]:
    """Enriquece un caballo: caché SQLite -> CSV -> scraper.

    Devuelve ``{"found": bool, "source": str|None, ...}``. En modo
    ``offline=True`` no hace peticiones de red.
    """
    cacheado = _buscar_en_cache(horse_name, db_path)
    if cacheado:
        return cacheado

    encontrado = _buscar_en_csv(horse_name, csv_dir)
    if encontrado:
        return encontrado

    if offline:
        return {"found": False, "source": None}

    scrapeado = _scrape_fuente(horse_name)
    if scrapeado:
        horse_id = upsert_horse(db_path, horse_name)
        save_enrichment(
            db_path, horse_id, scrapeado.get("source", "web"), scrapeado
        )
        return scrapeado

    return {"found": False, "source": None}


def cache_to_db(records: list[dict], db_path: str) -> int:
    """Hace upsert de registros de enriquecimiento en SQLite.

    Cada registro debe tener ``horse_name`` y ``source``; el resto se
    serializa como JSON. Devuelve cuántos registros se guardaron.
    """
    guardados = 0
    for registro in records:
        nombre = registro.get("horse_name")
        if not nombre:
            logger.warning("Registro sin horse_name ignorado: %s", registro)
            continue
        horse_id = upsert_horse(db_path, nombre)
        save_enrichment(
            db_path,
            horse_id,
            registro.get("source", "desconocida"),
            {k: v for k, v in registro.items() if k not in {"horse_name", "source"}},
        )
        guardados += 1
    return guardados
