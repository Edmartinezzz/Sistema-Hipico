"""Tests del módulo de Telegram (API simulada, sin red)."""

import pytest

from src import telegram


def _patch_secret(monkeypatch, token="tok", chat="123"):
    monkeypatch.setattr(telegram, "_env_o_secret", lambda n: {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat}.get(n))


def test_no_configurado(monkeypatch):
    monkeypatch.setattr(telegram, "_env_o_secret", lambda n: None)
    assert not telegram.configurado()
    with pytest.raises(RuntimeError, match="configuración"):
        telegram.enviar("hola")


def test_enviar_ok(monkeypatch):
    _patch_secret(monkeypatch)

    class Resp:
        ok = True
        status_code = 200
        text = '{"ok": true}'

    llamadas = []

    def fake_post(url, json=None, timeout=None):
        llamadas.append((url, json))
        return Resp()

    monkeypatch.setattr(telegram.requests, "post", fake_post)
    telegram.enviar("pronóstico")
    assert llamadas[0][0].startswith("https://api.telegram.org/bot")
    assert llamadas[0][1]["chat_id"] == "123"
    assert "pronóstico" in llamadas[0][1]["text"]


def test_enviar_error(monkeypatch):
    _patch_secret(monkeypatch)

    class Resp:
        ok = False
        status_code = 400
        text = "bad request"

    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: Resp())
    with pytest.raises(RuntimeError, match="400"):
        telegram.enviar("x")
