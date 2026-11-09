"""Módulo 12 — Cuotas ML desde una gaceta escaneada (OCR).

Las gacetas que circulan por WhatsApp suelen ser fotos (CamScanner) sin
texto extraíble. En vez de intentar leer toda la página, este módulo solo
extrae lo que la web no publica: la **cuota de la línea de la mañana
(ML)** de cada caballo, además de la fecha y el número de carrera para
cruzarla con la reunión de la web/archivo.

OCR: ``rapidocr_onnxruntime`` (open source, se instala con pip, no
necesita Tesseract). Es opcional: si no está instalado, la app lo indica.

Por página se leen dos recortes:
- Cabecera (arriba-izquierda): "Segunda Carrera", "08/11/26".
- Franja izquierda: nombres de los ejemplares y cuotas "30/1", "3/2"...
Cada cuota se asigna al último nombre (de la reunión web) leído encima.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

ORDINALES = {
    "PRIMERA": 1, "SEGUNDA": 2, "TERCERA": 3, "CUARTA": 4, "QUINTA": 5,
    "SEXTA": 6, "SEPTIMA": 7, "OCTAVA": 8, "NOVENA": 9, "DECIMA": 10,
    "UNDECIMA": 11, "DUODECIMA": 12, "DECIMAPRIMERA": 11, "DECIMASEGUNDA": 12,
    "DECIMATERCERA": 13, "DECIMACUARTA": 14, "DECIMAQUINTA": 15,
}
_CUOTA_RE = re.compile(r"(?<![\d/])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])")
_FECHA_RE = re.compile(r"(?<!\d)(\d{2})/(\d{2})/(\d{2})(?!\d)")
_CARRERA_RE = re.compile(r"(\d{1,2})\s*[AªO°]?\s*CARRERA")

_motor = None


def disponible() -> bool:
    """``True`` si el motor de OCR está instalado."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _ocr():
    global _motor
    if _motor is None:
        from rapidocr_onnxruntime import RapidOCR

        _motor = RapidOCR()
    return _motor


def compacto(texto: Any) -> str:
    """Mayúsculas sin acentos ni espacios/símbolos: ``"The King Zeus"`` -> ``"THEKINGZEUS"``."""
    sin_acentos = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", sin_acentos.upper())


def numero_carrera(textos: list[str]) -> int | None:
    """Detecta "Segunda Carrera", "Décima Primera Carrera" o "2a Carrera"."""
    for texto in textos:
        plano = compacto(texto)
        match = re.search(r"([A-Z]+)CARRERA", plano)
        if match:
            prefijo = match.group(1)
            for nombre in sorted(ORDINALES, key=len, reverse=True):
                if prefijo.endswith(nombre):
                    return ORDINALES[nombre]
        match = _CARRERA_RE.search(unicodedata.normalize("NFKD", texto).upper())
        if match:
            return int(match.group(1))
    return None


def fecha_pagina(textos: list[str]) -> date | None:
    for texto in textos:
        match = _FECHA_RE.search(texto)
        if match:
            dia, mes, anio = (int(g) for g in match.groups())
            try:
                return date(2000 + anio, mes, dia)
            except ValueError:
                continue
    return None


def cuota_decimal(numerador: int, denominador: int) -> float | None:
    """Cuota fraccionaria ML -> decimal (``3/2`` -> 2.5)."""
    if denominador == 0 or numerador == 0:
        return None
    return round(numerador / denominador + 1, 3)


def clave_nombre(nombre: Any) -> str:
    """Nombre comparable: sin país de origen ``(USA)``/``(ARG)`` ni símbolos."""
    return compacto(re.sub(r"\([^)]*\)", "", str(nombre or "")))


def _reconocer(plano: str, claves: dict[str, str]) -> str | None:
    """Nombre de la web contenido en la línea, o muy parecido (OCR con errores)."""
    for clave in sorted(claves, key=len, reverse=True):
        if clave in plano:
            return claves[clave]
    # Tolerancia a 1-2 letras mal leídas: la línea entera ~ nombre.
    if len(plano) >= 5:
        parecido = difflib.get_close_matches(plano, list(claves), n=1, cutoff=0.82)
        if parecido:
            return claves[parecido[0]]
    return None


def asignar_cuotas(
    lineas: list[tuple[float, str]], nombres: list[str]
) -> dict[str, float]:
    """Asigna cada cuota al último nombre conocido leído por encima.

    ``lineas``: ``[(y, texto)]`` de la franja izquierda; ``nombres``:
    ejemplares de esa carrera según la web. Solo se acepta la primera
    cuota tras cada nombre.
    """
    claves = {clave_nombre(n): n for n in nombres if len(clave_nombre(n)) >= 3}
    actual: str | None = None
    cuotas: dict[str, float] = {}
    for _, texto in sorted(lineas):
        plano = compacto(texto)
        candidato = _reconocer(plano, claves)
        if candidato:
            actual = candidato
            continue
        match = _CUOTA_RE.search(texto)
        if match and actual and actual not in cuotas:
            decimal = cuota_decimal(int(match.group(1)), int(match.group(2)))
            if decimal:
                cuotas[actual] = decimal
    return cuotas


def _imagen(pagina, dpi: int):
    import numpy as np

    return np.array(pagina.to_image(resolution=dpi).original.convert("RGB"))


def leer_cabecera(imagen) -> dict[str, Any]:
    """OCR rápido de la cabecera: número de carrera y fecha (o ``None``)."""
    alto, ancho = imagen.shape[:2]
    cabecera, _ = _ocr()(imagen[: int(alto * 0.17), : int(ancho * 0.6)])
    textos = [t for _, t, _ in cabecera or []]
    return {"carrera": numero_carrera(textos), "fecha": fecha_pagina(textos)}


def leer_franja(imagen) -> list[tuple[float, str]]:
    """OCR de la franja izquierda (nombres y cuotas ML): ``[(y, texto)]``."""
    ancho = imagen.shape[1]
    franja, _ = _ocr()(imagen[:, : int(ancho * 0.30)])
    return [(caja[0][1], texto) for caja, texto, conf in franja or [] if conf >= 0.5]


def leer_gaceta(
    pdf_path: str,
    nombres_por_carrera: Callable[[date | None], dict[int, list[str]]] | None = None,
    progreso: Callable[[str, int, int], None] | None = None,
    dpi_cabecera: int = 72,
    dpi_franja: int = 120,
) -> dict[str, Any]:
    """Lee las cuotas ML de un PDF escaneado.

    1ª pasada (rápida): cabeceras para saber qué páginas son carreras.
    2ª pasada: franja izquierda solo de esas páginas.

    ``nombres_por_carrera(fecha)`` devuelve los ejemplares de cada carrera
    de la reunión de esa fecha (para reconocer nombres). Devuelve
    ``{"fecha", "cuotas": {(carrera, nombre): cuota}, "paginas", "carreras"}``.
    """
    import pdfplumber

    paginas = []
    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        for i, pagina in enumerate(pdf.pages, start=1):
            if progreso:
                progreso("Buscando carreras", i, total)
            datos = leer_cabecera(_imagen(pagina, dpi_cabecera))
            if datos["carrera"]:
                paginas.append({**datos, "indice": i - 1})
        for n, datos in enumerate(paginas, start=1):
            if progreso:
                progreso(f"Leyendo cuotas de la carrera {datos['carrera']}", n, len(paginas))
            datos["lineas"] = leer_franja(_imagen(pdf.pages[datos["indice"]], dpi_franja))

    fechas = [p["fecha"] for p in paginas if p["fecha"]]
    fecha = max(set(fechas), key=fechas.count) if fechas else None
    nombres = nombres_por_carrera(fecha) if nombres_por_carrera else {}
    cuotas: dict[tuple[int, str], float] = {}
    for p in paginas:
        for nombre, cuota in asignar_cuotas(p["lineas"], nombres.get(p["carrera"], [])).items():
            cuotas[(p["carrera"], nombre)] = cuota
    return {
        "fecha": fecha,
        "cuotas": cuotas,
        "paginas": len(paginas),
        "carreras": sorted({p["carrera"] for p in paginas}),
    }


# ------------------------------------------------------------- caché por PDF

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "ocr_cache"


def _ruta_cache(pdf_bytes: bytes) -> Path:
    return CACHE_DIR / f"{hashlib.sha256(pdf_bytes).hexdigest()}.json"


def leer_cache(pdf_bytes: bytes) -> dict[str, Any] | None:
    """Resultado de ``leer_gaceta`` guardado para este PDF exacto, o None."""
    try:
        datos = json.loads(_ruta_cache(pdf_bytes).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cuotas = {}
    for clave, cuota in (datos.get("cuotas") or {}).items():
        n_txt, _, nombre = str(clave).partition("|")
        cuotas[(int(n_txt), nombre)] = cuota
    fecha_txt = datos.get("fecha")
    return {
        "fecha": date.fromisoformat(fecha_txt) if fecha_txt else None,
        "cuotas": cuotas,
        "paginas": datos.get("paginas"),
        "carreras": datos.get("carreras") or [],
    }


def guardar_cache(pdf_bytes: bytes, resultado: dict[str, Any]) -> None:
    """Guarda el resultado del OCR para no repetirlo si se sube el mismo PDF."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _ruta_cache(pdf_bytes).write_text(
            json.dumps(
                {
                    "fecha": resultado["fecha"].isoformat()
                    if resultado.get("fecha")
                    else None,
                    "cuotas": {
                        f"{n}|{nombre}": c
                        for (n, nombre), c in resultado["cuotas"].items()
                    },
                    "paginas": resultado.get("paginas"),
                    "carreras": resultado.get("carreras") or [],
                }
            ),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("No se pudo guardar la caché del OCR: %s", exc)
