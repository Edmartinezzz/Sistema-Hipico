"""Envío de mensajes por Telegram (gratis) para el pronóstico del domingo.

Configuración: ``TELEGRAM_BOT_TOKEN`` y ``TELEGRAM_CHAT_ID`` en secrets de
Streamlit o variables de entorno. El bot se crea gratis con @BotFather en
Telegram y el chat_id se obtiene escribiendo al bot y consultando
``getUpdates``.
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT = 20


def _env_o_secret(nombre: str) -> str | None:
    try:
        import streamlit as st

        valor = st.secrets.get(nombre)
    except Exception:  # noqa: BLE001
        valor = None
    return valor or os.environ.get(nombre) or None


def configurado() -> bool:
    return bool(_env_o_secret("TELEGRAM_BOT_TOKEN") and _env_o_secret("TELEGRAM_CHAT_ID"))


def enviar(texto: str) -> None:
    """Envía ``texto`` al chat configurado. Lanza ``RuntimeError`` si falta
    configuración o Telegram rechaza el mensaje."""
    token = _env_o_secret("TELEGRAM_BOT_TOKEN")
    chat_id = _env_o_secret("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        raise RuntimeError(
            "Falta configuración: define TELEGRAM_BOT_TOKEN y "
            "TELEGRAM_CHAT_ID en secrets o variables de entorno."
        )
    resp = requests.post(
        f"{API}/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": texto[:4000],  # límite de Telegram por mensaje
            "disable_web_page_preview": True,
        },
        timeout=TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(f"Telegram respondió {resp.status_code}: {resp.text[:200]}")
    logger.info("Mensaje de Telegram enviado")


def url_configuracion() -> str:
    return (
        "1. En Telegram habla con @BotFather → /newbot → copia el token.\n"
        "2. Escríbele a tu bot cualquier mensaje.\n"
        "3. Abre https://api.telegram.org/bot<TU_TOKEN>/getUpdates y copia "
        "el número de \"chat\":{...} (tu chat_id).\n"
        "4. Guarda ambos en secrets como TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID."
    )
