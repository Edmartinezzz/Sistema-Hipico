"""Chat con IA para preguntar sobre las carreras (APIs gratuitas).

Presupuesto cero: encadena varios proveedores gratuitos compatibles con
la API de OpenAI y salta al siguiente si uno falla o llega a su límite:

1. **Google Gemini** — ``GEMINI_API_KEY`` (aistudio.google.com, ~1.500
   preguntas/día gratis; el más generoso).
2. **GitHub Models** — ``GITHUB_TOKEN`` (PAT de GitHub, gratis).
3. **NVIDIA NIM** — ``NVIDIA_API_KEY`` (build.nvidia.com, gratis).
4. **OpenRouter** — ``OPENROUTER_API_KEY`` (modelos ``:free``, ~50/día).
5. **Groq** — ``GROQ_API_KEY`` (console.groq.com).
6. **Pollinations** — sin key, siempre disponible como último recurso
   (comunitario: puede ser lento o fallar a veces).

Las keys se leen de secrets de Streamlit o variables de entorno, nunca
del código. Si un modelo se retira, se prueba el siguiente de la lista.
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

TIMEOUT = 45

NOMBRES = {
    "gemini": "Google Gemini",
    "github": "GitHub Models",
    "nvidia": "NVIDIA",
    "openrouter": "OpenRouter",
    "groq": "Groq",
    "pollinations": "Pollinations",
}

OR_MODELOS_URL = "https://openrouter.ai/api/v1/models"
# ``openrouter/free`` es un router que elige solo entre los modelos :free
# vigentes: nunca queda obsoleto aunque OpenRouter rote el catálogo.
OR_MODELOS_FIJOS = [
    "openrouter/free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "qwen/qwen3-32b:free",
]

# Cada proveedor: id, variable de entorno con la key (None = sin key),
# endpoint OpenAI-compatible, modelos en orden de preferencia.
PROVEEDORES = [
    {
        "id": "gemini",
        "env": "GEMINI_API_KEY",
        "env_modelo": "GEMINI_MODEL",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "modelos": [
            "gemini-3.8-flash", "gemini-3.1-flash-lite",
            "gemini-3.1-flash", "gemini-2.5-flash",
        ],
        "headers_extra": {},
    },
    {
        "id": "github",
        "env": "GITHUB_TOKEN",
        "env_modelo": "GITHUB_MODEL",
        "url": "https://models.github.ai/inference/chat/completions",
        "modelos": [
            "openai/gpt-4o-mini", "openai/gpt-4.1-mini",
            "deepseek/DeepSeek-V3-0324", "openai/gpt-4o",
        ],
        "headers_extra": {},
    },
    {
        "id": "nvidia",
        "env": "NVIDIA_API_KEY",
        "env_modelo": "NVIDIA_MODEL",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "modelos": [
            "meta/llama-3.3-70b-instruct", "openai/gpt-oss-120b",
            "deepseek-ai/deepseek-v3.1",
        ],
        "headers_extra": {},
    },
    {
        "id": "openrouter",
        "env": "OPENROUTER_API_KEY",
        "env_modelo": "OPENROUTER_MODEL",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "modelos": "__openrouter__",  # se calcula con descubrimiento
        "headers_extra": {
            "HTTP-Referer": "https://sistema-hipico.local",
            "X-Title": "Sistema Hípico",
        },
    },
    {
        "id": "groq",
        "env": "GROQ_API_KEY",
        "env_modelo": "GROQ_MODEL",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "modelos": [
            "openai/gpt-oss-120b", "meta-llama/llama-4-scout-17b-16e-instruct",
            "openai/gpt-oss-20b", "qwen/qwen3.6-27b",
        ],
        "headers_extra": {},
    },
    {
        "id": "pollinations",
        "env": None,  # no pide key
        "env_modelo": "POLLINATIONS_MODEL",
        "url": "https://text.pollinations.ai/openai/chat/completions",
        "modelos": ["openai"],
        "headers_extra": {},
    },
]

PROMPT_SISTEMA = """\
Eres el asistente del «Sistema Hípico», una herramienta de análisis \
estadístico de carreras de caballos en Venezuela (La Rinconada y Valencia). \
Responde en español, breve y claro (unas 100 palabras salvo que pidan \
detalle).

REGLAS:
- Usa SOLO los datos del CONTEXTO que aparece al final. Si la respuesta no \
está ahí, dilo y sugiere qué sección de la app revisar.
- Las probabilidades son estimaciones del modelo, no garantías: nunca \
prometas ganadores ni des consejos de apuesta. Es uso informativo.
- Si preguntan por fechas u horses que el contexto no incluye, explica que \
el archivo histórico crece cada semana y que pueden cargar esa reunión.
- Puedes comparar probabilidades, cuotas y value bets con cuentas simples \
siempre basándote en el contexto.
"""


class ChatError(Exception):
    """Error entendible por el usuario final."""


class _ModeloNoDisponible(Exception):
    pass


def _env_o_secret(nombre: str) -> str | None:
    try:
        import streamlit as st

        valor = st.secrets.get(nombre)
    except Exception:  # noqa: BLE001  (fuera del runtime de Streamlit)
        valor = None
    return valor or os.environ.get(nombre) or None


def _cadena() -> list[dict]:
    """Proveedores utilizables en orden: los que tienen key + Pollinations."""
    cadena = []
    for p in PROVEEDORES:
        if p["env"] is None or _env_o_secret(p["env"]):
            cadena.append(p)
    return cadena


def proveedor() -> str | None:
    """Primer proveedor con API key configurada (``None`` = solo Pollinations)."""
    for p in PROVEEDORES:
        if p["env"] and _env_o_secret(p["env"]):
            return p["id"]
    return None


def disponible() -> bool:
    """Siempre hay al menos Pollinations; ``True`` si hay key configurada."""
    return proveedor() is not None


# ------------------------------------------------------------- OpenRouter

_modelos_or: list[str] | None = None


def _descubrir_modelos_free() -> list[str]:
    """IDs ``:free`` vigentes en OpenRouter (endpoint público, sin key)."""
    global _modelos_or
    if _modelos_or is not None:
        return _modelos_or
    ids: list[str] = []
    try:
        resp = requests.get(OR_MODELOS_URL, timeout=15)
        if resp.ok:
            ids = [
                m["id"] for m in resp.json().get("data", [])
                if m.get("id", "").endswith(":free")
            ]
    except requests.RequestException as exc:
        logger.info("No se pudo listar modelos de OpenRouter: %s", exc)
    _modelos_or = OR_MODELOS_FIJOS + ids[:4]
    return _modelos_or


def _modelos_de(p: dict) -> list[str]:
    preferido = os.environ.get(p["env_modelo"] or "")
    if p["id"] == "openrouter":
        base = _descubrir_modelos_free()
    else:
        base = list(p["modelos"])
    if preferido:
        return [preferido] + [m for m in base if m != preferido]
    return base


# ------------------------------------------------------------------- HTTP


def _extraer_texto(data: dict) -> str:
    """Texto de la respuesta; modelos de razonamiento pueden devolver
    ``content`` vacío si se acaban los tokens pensando -> probar otro."""
    try:
        mensaje = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise _ModeloNoDisponible("respuesta sin choices") from exc
    content = mensaje.get("content")
    if isinstance(content, list):  # partes multimodales
        content = "".join(
            parte.get("text", "") for parte in content if isinstance(parte, dict)
        )
    if not content or not str(content).strip():
        raise _ModeloNoDisponible("content vacío (posible razonamiento)")
    return str(content).strip()


def _post(p: dict, mensajes: list[dict], modelo: str, api_key: str | None) -> str:
    headers = dict(p["headers_extra"])
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.post(
        p["url"],
        headers=headers,
        json={
            "model": modelo,
            "messages": mensajes,
            "temperature": 0.4,
            "max_tokens": 1500,
        },
        timeout=TIMEOUT,
    )
    nombre = NOMBRES[p["id"]]
    if resp.status_code in {401, 403}:
        raise ChatError(f"La API key de {nombre} no es válida.")
    if resp.status_code == 402:
        raise ChatError(f"{nombre} pide créditos en la cuenta para este modelo.")
    if resp.status_code == 429:
        raise ChatError(f"{nombre} está limitando las peticiones (nivel gratuito).")
    if resp.status_code in {400, 404, 500, 502, 503, 504}:
        # Modelo retirado o servidor saturado: probar el siguiente modelo.
        raise _ModeloNoDisponible(str(resp.status_code))
    if resp.status_code >= 400:
        raise ChatError(f"{nombre} respondió {resp.status_code}: {resp.text[:200]}")
    return _extraer_texto(resp.json())


def _chatear_proveedor(p: dict, mensajes: list[dict]) -> str:
    """Prueba los modelos del proveedor en orden; se rinde al primer
    error que no sea de modelo (key mala, límite, red)."""
    api_key = _env_o_secret(p["env"]) if p["env"] else None
    nombre = NOMBRES[p["id"]]
    errores = []
    for modelo in _modelos_de(p):
        try:
            return _post(p, mensajes, modelo, api_key)
        except _ModeloNoDisponible as exc:
            logger.info("%s/%s no disponible (%s)", nombre, modelo, exc)
            errores.append(modelo)
        except requests.RequestException as exc:
            raise ChatError(f"No se pudo contactar con {nombre}: {exc}") from exc
    raise ChatError(f"Ningún modelo de {nombre} respondió bien.")


def chatear(
    pregunta: str,
    historial: list[dict],
    contexto: str,
) -> str:
    """Pregunta a la IA con contexto e historial, probando proveedores.

    ``historial`` es una lista de ``{"role": "user"|"assistant", "content": ...}``
    (ya sin la pregunta actual). Devuelve el texto de la respuesta o lanza
    ``ChatError`` si todos los proveedores fallan.
    """
    cadena = _cadena()
    if not cadena:
        raise ChatError("No hay ningún proveedor de IA disponible.")
    if not pregunta.strip():
        raise ChatError("Escribe una pregunta.")

    mensajes = [{"role": "system", "content": PROMPT_SISTEMA + "\n\nCONTEXTO:\n" + contexto}]
    mensajes += [{"role": m["role"], "content": m["content"]} for m in historial[-12:]]
    mensajes.append({"role": "user", "content": pregunta.strip()})

    fallos = []
    for p in cadena:
        try:
            return _chatear_proveedor(p, mensajes)
        except ChatError as exc:
            logger.info("Proveedor %s falló: %s", p["id"], exc)
            fallos.append(f"{NOMBRES[p['id']]}: {exc}")
    raise ChatError("Todos los proveedores de IA fallaron — " + " | ".join(fallos))
