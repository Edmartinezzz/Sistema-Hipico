"""Tests del Módulo 6 — gaceta desde la web, con HTML sintético (sin red)."""

import json
from datetime import date

import pytest
import responses

from src.gaceta_web import (
    BASE_URL,
    GacetaWebError,
    fetch_meeting,
    list_meetings,
    meeting_to_records,
    meetings_for_week,
    parse_meeting_html,
    parse_meetings,
    week_range,
)

LISTA_HTML = """<html><head>
<script type="application/ld+json">{"@type":"WebSite","name":"x"}</script>
<script type="application/ld+json">{"@type":"CollectionPage","hasPart":[
 {"@type":"SportsEvent","name":"Reunión Hípica 44 · LA RINCONADA",
  "startDate":"2026-11-08T12:00:00.000Z","url":"https://www.desafiohipico.com/revista/aa11"},
 {"@type":"SportsEvent","name":"Reunión Hípica 28 · NACIONAL DE VALENCIA",
  "startDate":"2026-11-07T12:00:00.000Z","url":"https://www.desafiohipico.com/revista/bb22"},
 {"@type":"SportsEvent","name":"Reunión Hípica 43 · LA RINCONADA",
  "startDate":"2026-11-01T12:00:00.000Z","url":"https://www.desafiohipico.com/revista/cc33"}
]}</script></head><body></body></html>"""

REUNION = {
    "meeting": {"id": "aa11", "meetingNumber": 44, "trackName": "LA RINCONADA"},
    "races": [
        {
            "raceNumber": 1,
            "distance": 1200,
            "status": "scheduled",
            "entries": [
                {
                    "dorsalNumber": 1, "postPosition": 3, "horseName": "QUEEN VISION",
                    "jockeyName": "FUNEZ JR LUIS AL.", "trainerName": "BALZAN G JOSE L",
                    "studName": "", "weightDeclared": "57-2", "isScratched": False,
                    "finishPosition": None,
                    "yearStats": {"starts": 7, "wins": 0},
                    "raceHistory": [
                        {"date": "2026-04-26T12:00:00.000Z", "trackName": "LA RINCONADA",
                         "distance": 1300, "finishPosition": 4, "diffVsFirst": "5 c",
                         "jockeyName": "YANEZ SAMUEL", "weight": "57-4",
                         "officialTime": "81.1", "winnerName": "FANTASTIC SHOT"},
                        {"date": "2026-05-17T12:00:00.000Z", "trackName": "LA RINCONADA",
                         "distance": 1100, "finishPosition": 1, "diffVsFirst": "—"},
                    ],
                    "workouts": [{"workoutDate": "2026-11-05T12:00:00.000Z",
                                  "workoutType": "EP", "splits": "", "comment": "GALOPO",
                                  "jockeyName": "R.ARRAGA"}],
                },
                {
                    "dorsalNumber": 2, "postPosition": 1, "horseName": "RETIRADA",
                    "isScratched": True,
                },
                {
                    "dorsalNumber": 3, "postPosition": 2, "horseName": "SALOME",
                    "jockeyName": "MEDINA", "trainerName": "SANCHEZ",
                    "weightDeclared": "53", "isScratched": False,
                    "yearStats": {"starts": 10, "wins": 2}, "raceHistory": [],
                },
            ],
        }
    ],
}


def _html_reunion(datos: dict) -> str:
    """Simula el payload Next.js partido en varios trozos."""
    texto = 'f:["$","$L17",null,{"meetingId":"aa11","initialData":' + json.dumps(
        datos, ensure_ascii=False
    ) + "}]"
    mitad = len(texto) // 2
    trozos = [texto[:mitad], texto[mitad:]]
    return "".join(
        f'<script>self.__next_f.push([1,{json.dumps(t, ensure_ascii=False)}])</script>'
        for t in trozos
    )


def test_parse_meetings():
    reuniones = parse_meetings(LISTA_HTML)
    assert [r["id"] for r in reuniones] == ["aa11", "bb22", "cc33"]
    assert reuniones[0]["number"] == 44
    assert reuniones[0]["track"] == "LA RINCONADA"
    assert reuniones[1]["track"] == "NACIONAL DE VALENCIA"
    assert reuniones[0]["date"] == date(2026, 11, 8)


def test_week_range_y_filtro():
    assert week_range(date(2026, 11, 4)) == (date(2026, 11, 2), date(2026, 11, 8))
    reuniones = parse_meetings(LISTA_HTML)
    semana = meetings_for_week(date(2026, 11, 4), reuniones)
    # Sábado Valencia primero, domingo La Rinconada después.
    assert [r["id"] for r in semana] == ["bb22", "aa11"]
    assert meetings_for_week(date(2026, 12, 1), reuniones) == []


def test_parse_meeting_html():
    datos = parse_meeting_html(_html_reunion(REUNION))
    assert datos["meeting"]["meetingNumber"] == 44
    assert datos["races"][0]["entries"][0]["horseName"] == "QUEEN VISION"


def test_parse_meeting_html_estructura_cambiada():
    with pytest.raises(GacetaWebError):
        parse_meeting_html("<html>sin datos</html>")


def test_meeting_to_records():
    registros = meeting_to_records(REUNION)
    # El retirado se excluye.
    assert [r["horse_name"] for r in registros] == ["QUEEN VISION", "SALOME"]
    queen = registros[0]
    assert queen["race_number"] == 1
    assert queen["jockey"] == "FUNEZ JR LUIS AL."
    assert queen["weight"] == 57.0
    assert queen["post_position"] == 3
    assert queen["odds"] is None
    assert queen["record"] == "7-0"
    assert queen["lengths_behind"] == [5.0, 0.0]
    assert queen["history"][0]["Ganador"] == "FANTASTIC SHOT"
    assert queen["workouts"][0]["Comentario"] == "GALOPO"
    assert registros[1]["lengths_behind"] == []


@responses.activate
def test_list_meetings_red_simulada():
    responses.get(f"{BASE_URL}/retrospectos", body=LISTA_HTML, status=200)
    assert len(list_meetings()) == 3


@responses.activate
def test_list_meetings_sin_reuniones():
    responses.get(f"{BASE_URL}/retrospectos", body="<html></html>", status=200)
    with pytest.raises(GacetaWebError):
        list_meetings()


@responses.activate
def test_fetch_meeting_usa_cache(tmp_path):
    terminada = json.loads(json.dumps(REUNION))
    terminada["races"][0]["status"] = "finished"
    responses.get(f"{BASE_URL}/revista/aa11", body=_html_reunion(terminada), status=200)
    primera = fetch_meeting("aa11", cache_dir=tmp_path)
    segunda = fetch_meeting("aa11", cache_dir=tmp_path)
    assert primera == segunda
    # La segunda lectura sale de la caché: solo una petición HTTP.
    assert len(responses.calls) == 1


@responses.activate
def test_fetch_meeting_http_error(tmp_path):
    responses.get(f"{BASE_URL}/revista/zz99", status=404)
    with pytest.raises(GacetaWebError):
        fetch_meeting("zz99", cache_dir=tmp_path)
