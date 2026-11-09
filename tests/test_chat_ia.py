"""Tests del chat con IA multi-proveedor — sin red: se simula la API."""

import os

import pytest

from src import chat_ia


def _resp_json(texto="respuesta"):
    class R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": texto}}]}

    return R()


@pytest.fixture(autouse=True)
def _sin_keys(monkeypatch):
    for v in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
              "GITHUB_TOKEN", "NVIDIA_API_KEY", "OPENROUTER_MODEL", "GROQ_MODEL",
              "GEMINI_MODEL", "GITHUB_MODEL", "NVIDIA_MODEL", "POLLINATIONS_MODEL"):
        monkeypatch.delenv(v, raising=False)
    # Ignora secrets.toml real: los tests solo ven variables de entorno.
    monkeypatch.setattr(
        chat_ia, "_env_o_secret", lambda n: os.environ.get(n)
    )
    monkeypatch.setattr(chat_ia, "_modelos_or", ["openrouter/free", "x/y:free"])


def _post_ok(monkeypatch, registro=None):
    def fake_post(url, headers, json, timeout):
        if registro is not None:
            registro.append((url, json))
        return _resp_json("respuesta del modelo")

    monkeypatch.setattr(chat_ia.requests, "post", fake_post)


def test_sin_keys_usa_pollinations(monkeypatch):
    assert chat_ia.proveedor() is None
    urls = []
    _post_ok(monkeypatch, urls)
    assert chat_ia.chatear("hola", [], "ctx") == "respuesta del modelo"
    assert "pollinations" in urls[0][0]


def test_openrouter_ok(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    llamadas = []
    _post_ok(monkeypatch, llamadas)
    r = chat_ia.chatear("¿quién gana?", [{"role": "user", "content": "hola"}], "CTX")
    assert r == "respuesta del modelo"
    url, payload = llamadas[0]
    assert url == chat_ia.PROVEEDORES[3]["url"]
    assert payload["model"] == "openrouter/free"
    msgs = payload["messages"]
    assert msgs[0]["role"] == "system" and "CONTEXTO:\nCTX" in msgs[0]["content"]
    assert msgs[-1] == {"role": "user", "content": "¿quién gana?"}


def test_gemini_tiene_prioridad_sobre_openrouter(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    llamadas = []
    _post_ok(monkeypatch, llamadas)
    chat_ia.chatear("hola", [], "ctx")
    assert "generativelanguage" in llamadas[0][0]
    assert llamadas[0][1]["model"] == "gemini-3.8-flash"
    assert chat_ia.proveedor() == "gemini"


def test_rate_limit_salta_al_siguiente_proveedor(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    urls = []

    class R429:
        status_code = 429
        text = "rate limit"

    def fake_post(url, headers, json, timeout):
        urls.append(url)
        return R429() if "generativelanguage" in url else _resp_json()

    monkeypatch.setattr(chat_ia.requests, "post", fake_post)
    assert chat_ia.chatear("hola", [], "ctx") == "respuesta"
    assert "generativelanguage" in urls[0] and "openrouter" in urls[1]


def test_content_vacio_prueba_otro_modelo(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    intentos = []

    class RVacio:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": None}}]}

    def fake_post(url, headers, json, timeout):
        intentos.append(json["model"])
        return RVacio() if json["model"] == "openrouter/free" else _resp_json()

    monkeypatch.setattr(chat_ia.requests, "post", fake_post)
    assert chat_ia.chatear("hola", [], "ctx") == "respuesta"
    assert len(intentos) == 2


def test_todos_fallan_error_amable(monkeypatch):
    class R500:
        status_code = 500
        text = "boom"

    monkeypatch.setattr(chat_ia.requests, "post", lambda *a, **k: R500())
    with pytest.raises(chat_ia.ChatError, match="Todos los proveedores"):
        chat_ia.chatear("hola", [], "ctx")


def test_modelos_openrouter_descubiertos(monkeypatch):
    monkeypatch.setattr(chat_ia, "_modelos_or", None)

    class R:
        ok = True

        def json(self):
            return {"data": [{"id": "a/b:free"}, {"id": "c/d"}, {"id": "e/f:free"}]}

    monkeypatch.setattr(chat_ia.requests, "get", lambda *a, **k: R())
    modelos = chat_ia._descubrir_modelos_free()
    assert modelos[:1] == ["openrouter/free"]
    assert "a/b:free" in modelos and "e/f:free" in modelos
    assert "c/d" not in modelos  # sin :free no entra
