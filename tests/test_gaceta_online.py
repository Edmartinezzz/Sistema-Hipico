"""Pruebas de la búsqueda automática de la gaceta (HTTP simulado, sin red real)."""

import json
from datetime import date

import pytest
import responses

from src import gaceta_online, pipeline, scraper
from src.sample_data import create_sample_movil

HOY = date(2026, 11, 8)
REVISTA_URL = f"{gaceta_online.DESAFIO_BASE}/revista/abc123"
PDF_URL = gaceta_online.POLLAMACACO_URLS["LA RINCONADA"]


def next_html(payload: str) -> str:
    """Imita cómo Next.js incrusta los datos: fragmentos ``self.__next_f.push``."""
    trozos = [payload[i:i + 300] for i in range(0, len(payload), 300)]
    scripts = "".join(
        f"<script>self.__next_f.push([1,{json.dumps(t)}])</script>" for t in trozos
    )
    return f"<html><body>{scripts}</body></html>"


def lista_html(reuniones) -> str:
    partes = [
        {"@type": "SportsEvent", "name": f"Reunión Hípica {n} · {pista}", "startDate": dia,
         "url": url}
        for n, pista, dia, url in reuniones
    ]
    datos = {"@context": "https://schema.org", "@type": "CollectionPage", "hasPart": partes}
    return next_html("17:T1," + json.dumps(datos, ensure_ascii=False))


def revista_html() -> str:
    def entrada(dorsal, nombre, inicios, victorias, retirado=False):
        return {
            "dorsalNumber": dorsal, "postPosition": dorsal, "horseName": nombre,
            "jockeyName": "JINETE PRUEBA", "trainerName": "ENTRENADOR PRUEBA",
            "weightDeclared": "54-2", "isScratched": retirado,
            "yearStats": {"starts": inicios, "wins": victorias}, "raceHistory": [],
        }

    datos = {
        "meetingId": "abc123",
        "initialData": {
            "meeting": {"id": "abc123", "meetingNumber": 44, "date": "2026-11-08T12:00:00.000Z",
                        "trackName": "LA RINCONADA"},
            "races": [
                {"raceNumber": 1, "distance": 1200, "entries": [
                    entrada(1, "CABALLO UNO", 10, 4),
                    entrada(2, "CABALLO DOS", 8, 0),
                    entrada(3, "RETIRADO TRES", 5, 1, retirado=True),
                ]},
                {"raceNumber": 2, "distance": 1600, "entries": [
                    entrada(1, "ÑANDÚ FICTICIO", 0, 0),
                    entrada(2, "OTRO FICTICIO", 3, 1),
                ]},
            ],
            "hasWorkouts": True,
        },
    }
    return next_html('5:["$","$L17",null,' + json.dumps(datos, ensure_ascii=False) + "]")


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    monkeypatch.setattr(scraper, "_last_request_at", {})


@pytest.fixture
def pdf_movil(tmp_path):
    return create_sample_movil(tmp_path / "movil.pdf").read_bytes()


def test_parse_meeting_list_y_pick_meeting():
    html = lista_html([
        (45, "LA RINCONADA", "2026-11-15T12:00:00.000Z", "https://x/revista/c"),
        (44, "LA RINCONADA", "2026-11-08T12:00:00.000Z", "https://x/revista/b"),
        (28, "NACIONAL DE VALENCIA", "2026-11-07T12:00:00.000Z", "https://x/revista/v"),
    ])
    reuniones = gaceta_online.parse_meeting_list(html)
    assert [r["track"] for r in reuniones] == ["LA RINCONADA", "LA RINCONADA", "VALENCIA"]
    assert gaceta_online.pick_meeting(reuniones, "LA RINCONADA", HOY)["url"].endswith("/b")
    manana = date(2026, 11, 9)
    assert gaceta_online.pick_meeting(reuniones, "LA RINCONADA", manana)["url"].endswith("/c")
    # Sin reuniones futuras se usa la más reciente.
    assert gaceta_online.pick_meeting(reuniones, "VALENCIA", HOY)["url"].endswith("/v")
    assert gaceta_online.pick_meeting([], "VALENCIA", HOY) is None


def test_parse_meeting_list_sin_datos():
    assert gaceta_online.parse_meeting_list("<html>nada</html>") == []


def test_parse_desafio_revista():
    caballos = gaceta_online.parse_desafio_revista(revista_html())
    assert len(caballos) == 5
    uno = caballos[0]
    assert uno["horse_name"] == "CABALLO UNO"
    assert (uno["race_number"], uno["distance"], uno["track"], uno["date"]) == (
        1, "1200 m", "La Rinconada", "2026-11-08"
    )
    assert (uno["starts"], uno["wins"], uno["weight"], uno["odds"]) == (10, 4, 54.0, None)
    assert uno["odds_published"] is False
    retirado = caballos[2]
    assert retirado["scratched"] and retirado["odds_raw"] == "RET"
    assert caballos[3]["horse_name"] == "ÑANDÚ FICTICIO"


def test_parse_desafio_revista_sin_datos():
    assert gaceta_online.parse_desafio_revista("<html></html>") == []


@responses.activate
def test_fetch_gaceta_usa_desafio_hipico():
    responses.get(gaceta_online.DESAFIO_LIST_URL, body=lista_html(
        [(44, "LA RINCONADA", "2026-11-08T12:00:00.000Z", REVISTA_URL)]
    ))
    responses.get(REVISTA_URL, body=revista_html())
    caballos, fuente = gaceta_online.fetch_gaceta("LA RINCONADA", HOY)
    assert len(caballos) == 5
    assert fuente.startswith("Desafío Hípico")
    assert all(c.request.headers["User-Agent"] == scraper.USER_AGENT for c in responses.calls)


@responses.activate
def test_fetch_gaceta_respaldo_pollamacaco(pdf_movil):
    responses.get(gaceta_online.DESAFIO_LIST_URL, status=404)
    responses.get(PDF_URL, body=pdf_movil, content_type="application/pdf")
    caballos, fuente = gaceta_online.fetch_gaceta("LA RINCONADA", HOY)
    assert fuente.startswith("pollamacaco.com")
    assert [c["horse_name"] for c in caballos][:2] == ["QUEEN DEMO", "ESTRELLA FICTICIA"]
    assert caballos[0]["record"] == "20-5-3-2"


@responses.activate
def test_fetch_gaceta_respaldo_si_no_hay_reunion_del_hipodromo(pdf_movil):
    responses.get(gaceta_online.DESAFIO_LIST_URL, body=lista_html(
        [(28, "NACIONAL DE VALENCIA", "2026-11-07T12:00:00.000Z", REVISTA_URL)]
    ))
    responses.get(PDF_URL, body=pdf_movil)
    _, fuente = gaceta_online.fetch_gaceta("LA RINCONADA", HOY)
    assert fuente.startswith("pollamacaco.com")


@responses.activate
def test_fetch_gaceta_rechaza_respuesta_que_no_es_pdf():
    responses.get(gaceta_online.DESAFIO_LIST_URL, status=404)
    responses.get(PDF_URL, body="<html>403</html>")
    with pytest.raises(gaceta_online.GacetaNoEncontrada, match="PDF válido"):
        gaceta_online.fetch_gaceta("LA RINCONADA", HOY)


@responses.activate
def test_fetch_gaceta_valencia_sin_respaldo():
    responses.get(gaceta_online.DESAFIO_LIST_URL, status=404)
    with pytest.raises(gaceta_online.GacetaNoEncontrada, match="Valencia"):
        gaceta_online.fetch_gaceta("VALENCIA", HOY)
    assert len(responses.calls) == 1


def test_fetch_gaceta_hipodromo_desconocido():
    with pytest.raises(ValueError):
        gaceta_online.fetch_gaceta("PALERMO", HOY)


@responses.activate
def test_analyze_online_sin_cuotas_usa_mercado_uniforme(tmp_path):
    responses.get(gaceta_online.DESAFIO_LIST_URL, body=lista_html(
        [(44, "LA RINCONADA", "2026-11-08T12:00:00.000Z", REVISTA_URL)]
    ))
    responses.get(REVISTA_URL, body=revista_html())
    resultado = pipeline.analyze_online("LA RINCONADA", db_path=str(tmp_path / "x.db"), today=HOY)
    assert resultado["source"].startswith("Desafío Hípico")
    filas = resultado["races"][0]["rows"]
    assert sum(f["model_prob"] for f in filas if f["model_prob"]) == pytest.approx(1.0)
    assert filas[0]["model_prob"] > filas[1]["model_prob"]
    assert filas[2]["model_prob"] is None
    assert all(f["market_prob"] is None and not f["value_bet"] for f in filas)
    assert filas[0]["form_source"] == "gaveta"
