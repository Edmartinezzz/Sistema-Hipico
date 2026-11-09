"""Enriquecimiento de caballos con datos históricos gratuitos.

Orden de búsqueda de :func:`enrich_horse`:

1. **SQLite** (caché local, tabla ``enrichment``).
2. **CSV local** (por ejemplo, un dataset de Kaggle descargado a mano), indicado
   con ``csv_path`` o con la variable de entorno ``HORSE_CSV_PATH``.
3. **Fuente HTTP** opcional (solo si ``offline=False``), configurada con la
   variable ``HORSE_DATA_URL``: una plantilla de URL con ``{name}`` que
   devuelva JSON, por ejemplo ``https://mi-servidor/caballos?nombre={name}``.

Si nada funciona, devuelve ``{"found": False, "source": None}``; nunca lanza
excepciones, para no romper el pipeline. Las fuentes y sus condiciones de uso
están documentadas en ``docs/fuentes_datos.md``.
"""

from __future__ import annotations

import csv
import logging
import os
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urljoin, urlsplit

import requests

from src import database

logger = logging.getLogger(__name__)

USER_AGENT = (
    "horse-analytics/0.1 (proyecto educativo; +https://github.com/Edmartinezzz/Sistema-Hipico)"
)
MIN_INTERVAL_SECONDS = 1.0
MAX_RETRIES = 3
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = 10.0
RETRY_STATUS = {429, 500, 502, 503, 504}

_last_request_at: dict[str, float] = {}
_rate_lock = threading.Lock()

# Alias de columnas aceptados en los CSV (sin acentos, en minúsculas).
_CSV_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "horse", "horse_name", "caballo", "ejemplar", "nombre"),
    "birth_year": ("birth_year", "year_of_birth", "foaled", "ano_nacimiento", "nacimiento"),
    "sex": ("sex", "sexo", "gender"),
    "sire": ("sire", "padre"),
    "dam": ("dam", "madre"),
}

Fetcher = Callable[[str], "dict[str, Any] | None"]


# --------------------------------------------------------------------------- HTTP


def _domain(url: str) -> str:
    return urlsplit(url).netloc.lower()


def _wait_for_slot(domain: str, min_interval: float) -> None:
    """Respeta un máximo de una petición cada ``min_interval`` s por dominio."""
    with _rate_lock:
        last = _last_request_at.get(domain)
        now = time.monotonic()
        if last is not None:
            pending = min_interval - (now - last)
            if pending > 0:
                time.sleep(pending)
        _last_request_at[domain] = time.monotonic()


def rate_limited_get(url: str, **kwargs: Any) -> requests.Response:
    """``GET`` respetuoso: User-Agent propio, 1 petición/s por dominio y reintentos.

    Reintenta hasta ``MAX_RETRIES`` veces ante errores de conexión o respuestas
    429/5xx, esperando :math:`2^{intento}` segundos (1 s, 2 s, 4 s).

    Args:
        url: URL a descargar.
        **kwargs: se pasan a :func:`requests.get`. Extras opcionales:
            ``min_interval`` (s entre peticiones al mismo dominio) y
            ``max_retries``.

    Raises:
        requests.RequestException: si se agotan los reintentos.
    """
    min_interval = float(kwargs.pop("min_interval", MIN_INTERVAL_SECONDS))
    max_retries = int(kwargs.pop("max_retries", MAX_RETRIES))
    headers = {"User-Agent": USER_AGENT, **(kwargs.pop("headers", None) or {})}
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)

    def throttle_redirect(response: requests.Response, *args: Any, **kw: Any) -> None:
        # requests sigue la redirección justo después de este hook.
        if response.is_redirect:
            target = urljoin(response.url, response.headers["Location"])
            _wait_for_slot(_domain(target), min_interval)

    hooks = dict(kwargs.pop("hooks", None) or {})
    if kwargs.get("allow_redirects", True):
        response_hooks = hooks.get("response") or []
        if callable(response_hooks):
            response_hooks = [response_hooks]
        hooks["response"] = [*response_hooks, throttle_redirect]

    attempt = 0
    while True:
        _wait_for_slot(_domain(url), min_interval)
        try:
            with requests.Session() as session:
                session.max_redirects = MAX_REDIRECTS
                response = session.get(url, headers=headers, hooks=hooks, **kwargs)
            if response.status_code not in RETRY_STATUS:
                response.raise_for_status()
                return response
            error: requests.RequestException = requests.HTTPError(
                f"HTTP {response.status_code} en {url}", response=response
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            error = exc
        if attempt >= max_retries:
            raise error
        backoff = 2.0**attempt
        logger.warning("Fallo en %s (%s); reintento en %.0f s", url, error, backoff)
        time.sleep(backoff)
        attempt += 1


def http_json_fetcher(url_template: str) -> Fetcher:
    """Crea una fuente que pide ``url_template.format(name=...)`` y lee JSON.

    El JSON puede ser un objeto con los datos del caballo o una lista de
    objetos (se toma el primero). Una respuesta vacía o 404 equivale a
    «no encontrado».
    """

    def fetch(horse_name: str) -> dict[str, Any] | None:
        url = url_template.format(name=quote(horse_name))
        try:
            response = rate_limited_get(url)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
        payload = response.json()
        if isinstance(payload, list):
            payload = payload[0] if payload else None
        if not isinstance(payload, dict) or not payload:
            return None
        return payload

    fetch.source_name = _domain(url_template) or "http"  # type: ignore[attr-defined]
    return fetch


def default_fetchers() -> list[Fetcher]:
    """Fuentes HTTP configuradas por entorno (``HORSE_DATA_URL``)."""
    template = os.getenv("HORSE_DATA_URL")
    return [http_json_fetcher(template)] if template else []


# --------------------------------------------------------------------------- CSV


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "_".join(stripped.strip().lower().replace("-", " ").split())


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.upper() in {"NA", "N/A", "NULL", "NONE", "NAN"}:
        return None
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            continue
    return text


def load_csv(csv_path: str | Path) -> list[dict[str, Any]]:
    """Lee un CSV de historial y lo convierte en registros para :func:`cache_to_db`.

    Las columnas reconocidas (``name``/``caballo``, ``birth_year``, ``sex``,
    ``sire``/``padre``, ``dam``/``madre``) se renombran a su nombre canónico;
    el resto se conserva tal cual. Las filas sin nombre se omiten. Detecta
    separador ``,`` o ``;`` y acepta UTF-8 con o sin BOM.
    """
    path = Path(csv_path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        alias_lookup = {
            alias: canonical for canonical, aliases in _CSV_ALIASES.items() for alias in aliases
        }
        records = []
        for row in reader:
            record: dict[str, Any] = {}
            for column, value in row.items():
                if column is None:
                    continue
                key = alias_lookup.get(_plain(column), _plain(column))
                record[key] = _clean_value(value)
            if record.get("name") is None:
                continue
            record["name"] = str(record["name"])
            records.append(record)
    return records


def _find_in_csv(horse_name: str, csv_path: str | Path) -> dict[str, Any] | None:
    key = database.name_key(horse_name)
    for record in load_csv(csv_path):
        if database.name_key(record["name"]) == key:
            return record
    return None


# --------------------------------------------------------------------------- SQLite


_HORSE_FIELDS = ("birth_year", "sex", "sire", "dam")


def _as_year(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value)


def cache_to_db(records: Iterable[dict[str, Any]], db_path: str | None = None) -> int:
    """Guarda registros de enriquecimiento en SQLite (upsert del caballo).

    Cada registro necesita ``name``. ``birth_year``, ``sex``, ``sire`` y ``dam``
    actualizan la tabla ``horses``; el registro completo se guarda como JSON
    en ``enrichment`` con la fuente ``record["source"]`` (``"csv"`` por defecto).

    Returns:
        Número de registros guardados (se omiten los que no tienen nombre).
    """
    database.init_db(db_path)
    saved = 0
    for record in records:
        name = record.get("name")
        if not name or not str(name).strip():
            logger.warning("Registro sin nombre de caballo; se omite: %r", record)
            continue
        fields = {f: record.get(f) for f in _HORSE_FIELDS}
        fields["birth_year"] = _as_year(fields["birth_year"])
        for text_field in ("sex", "sire", "dam"):
            if fields[text_field] is not None:
                fields[text_field] = str(fields[text_field])
        horse_id = database.upsert_horse(str(name), db_path=db_path, **fields)
        data = {k: v for k, v in record.items() if k != "source"}
        database.save_enrichment(horse_id, str(record.get("source") or "csv"), data, db_path)
        saved += 1
    return saved


def _from_db(horse_name: str, db_path: str | None) -> dict[str, Any] | None:
    history = database.get_horse_history(horse_name, db_path)
    if history["horse"] is None or not history["enrichment"]:
        return None
    latest = history["enrichment"][0]
    return {
        "found": True,
        "source": latest["source"],
        "cached": True,
        "horse": history["horse"],
        "data": latest["data"],
        "history": history["entries"],
    }


# --------------------------------------------------------------------------- API


def enrich_horse(
    horse_name: str,
    db_path: str | None = None,
    offline: bool = False,
    csv_path: str | Path | None = None,
    fetchers: list[Fetcher] | None = None,
) -> dict[str, Any]:
    """Busca datos históricos de un caballo: CSV local → SQLite → fuentes HTTP.

    Lo que se encuentre en el CSV o en internet se guarda en SQLite para no
    volver a pedirlo.

    Args:
        horse_name: nombre del caballo tal como aparece en la gaveta.
        db_path: base SQLite (por defecto ``HORSE_DB_PATH``).
        offline: si es ``True`` no se hace ninguna petición de red.
        csv_path: CSV local; por defecto la variable ``HORSE_CSV_PATH``.
        fetchers: fuentes HTTP; por defecto :func:`default_fetchers`.

    Returns:
        ``{"found": True, "source": ..., "data": {...}, "horse": {...},
        "history": [...], "cached": bool}`` o ``{"found": False, "source": None}``.
    """
    not_found: dict[str, Any] = {"found": False, "source": None}
    if not horse_name or not str(horse_name).strip():
        return not_found
    cached = None
    try:
        database.init_db(db_path)
        cached = _from_db(horse_name, db_path)
    except Exception:  # noqa: BLE001 - degradar sin romper el pipeline
        logger.exception("No se pudo consultar SQLite para %r", horse_name)

    csv_path = csv_path or os.getenv("HORSE_CSV_PATH")
    if csv_path:
        try:
            record = _find_in_csv(horse_name, csv_path)
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            logger.warning("No se pudo leer el CSV %s: %s", csv_path, exc)
            record = None
        if record:
            source = record.get("source") or "csv"
            data = {k: v for k, v in record.items() if k != "source"}
            if cached and cached["source"] == source and cached["data"] == data:
                return cached
            return _store_and_return(record, "csv", db_path)
    if cached:
        return cached

    if offline:
        return not_found

    for fetch in default_fetchers() if fetchers is None else fetchers:
        source = getattr(fetch, "source_name", getattr(fetch, "__name__", "http"))
        try:
            record = fetch(horse_name)
        except Exception as exc:  # noqa: BLE001 - una fuente caída no rompe el pipeline
            logger.warning("La fuente %s falló para %r: %s", source, horse_name, exc)
            continue
        if record:
            return _store_and_return({**record, "name": horse_name}, source, db_path)
    return not_found


def _store_and_return(record: dict[str, Any], source: str, db_path: str | None) -> dict[str, Any]:
    record = {**record, "source": record.get("source") or source}
    try:
        cache_to_db([record], db_path)
        stored = _from_db(record["name"], db_path)
        if stored:
            return {**stored, "cached": False}
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo guardar en SQLite el registro de %r", record.get("name"))
    data = {k: v for k, v in record.items() if k != "source"}
    return {
        "found": True,
        "source": record["source"],
        "cached": False,
        "horse": None,
        "data": data,
        "history": [],
    }
