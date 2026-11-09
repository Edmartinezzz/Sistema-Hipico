"""Módulo 8 — Videos de carreras (repeticiones y señal en vivo).

La fuente web trae un campo ``videoUrl`` por carrera, pero hoy viene
vacío. Por eso el sistema permite:

- Mostrar el video automáticamente si la web lo publica.
- Guardar un enlace (YouTube, MP4/WebM directo) por carrera en SQLite.
- Subir un archivo de video propio (se guarda en ``data/videos/``).
- Buscar la carrera en YouTube con un clic.
- Configurar el enlace de la señal en vivo.

No se descarga ni retransmite contenido de terceros: los enlaces se
reproducen desde su origen.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

VIDEOS_DIR = Path(__file__).resolve().parent.parent / "data" / "videos"
EXTENSIONES_VIDEO = (".mp4", ".webm", ".ogg", ".mov", ".m4v")

# Enlaces verificados a señales oficiales/agregadores (abrir en el navegador).
SENALES_OFICIALES = [
    ("Señal INH en Desafío Hípico", "https://www.desafiohipico.com/en-vivo"),
    ("Canal oficial INH en Telegram", "https://t.me/s/INHOficial"),
]

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def es_url(texto: str | None) -> bool:
    """``True`` si es una URL http(s) bien formada."""
    if not texto:
        return False
    partes = urlparse(texto.strip())
    return partes.scheme in {"http", "https"} and bool(partes.netloc)


def youtube_id(url: str | None) -> str | None:
    """Extrae el id de un video de YouTube (watch, youtu.be, live, shorts, embed)."""
    if not es_url(url):
        return None
    partes = urlparse(url.strip())
    host = partes.netloc.lower().removeprefix("www.").removeprefix("m.")
    candidato = None
    if host == "youtu.be":
        candidato = partes.path.lstrip("/").split("/")[0]
    elif host in {"youtube.com", "youtube-nocookie.com", "music.youtube.com"}:
        if partes.path == "/watch":
            candidato = parse_qs(partes.query).get("v", [None])[0]
        else:
            trozos = partes.path.strip("/").split("/")
            if len(trozos) >= 2 and trozos[0] in {"live", "shorts", "embed", "v"}:
                candidato = trozos[1]
    return candidato if candidato and _YT_ID_RE.match(candidato) else None


def tipo_video(fuente: str | None) -> str | None:
    """Clasifica una fuente de video.

    - ``"youtube"``: reproducible con ``st.video``.
    - ``"archivo"``: archivo directo (URL o ruta local .mp4/.webm/...).
    - ``"enlace"``: otra página web (Facebook, Periscope...): se abre aparte.
    - ``None``: vacío o inválido.
    """
    if not fuente:
        return None
    fuente = fuente.strip()
    if youtube_id(fuente):
        return "youtube"
    ruta = urlparse(fuente).path if es_url(fuente) else fuente
    if ruta.lower().endswith(EXTENSIONES_VIDEO):
        return "archivo" if es_url(fuente) or Path(fuente).exists() else None
    return "enlace" if es_url(fuente) else None


def busqueda_youtube(
    hipodromo: str | None,
    fecha_ddmmyyyy: str | None,
    carrera: int | None,
    reunion: int | None = None,
) -> str:
    """URL de búsqueda en YouTube para encontrar la repetición de una carrera."""
    partes = [
        (hipodromo or "").title(),
        f"reunión {reunion}" if reunion else "",
        f"carrera {carrera}" if carrera else "",
        fecha_ddmmyyyy or "",
    ]
    consulta = " ".join(p for p in partes if p)
    return f"https://www.youtube.com/results?search_query={quote_plus(consulta)}"


def ruta_video_subido(hipodromo: str, fecha_iso: str, carrera: int, nombre: str) -> Path:
    """Ruta segura en ``data/videos/`` para un archivo subido por el usuario."""
    extension = Path(nombre).suffix.lower()
    if extension not in EXTENSIONES_VIDEO:
        raise ValueError(f"Formato no soportado: {extension or 'sin extensión'}")
    base = re.sub(r"[^A-Za-z0-9]+", "_", f"{hipodromo}_{fecha_iso}_c{carrera}").strip("_")
    return VIDEOS_DIR / f"{base}{extension}"
