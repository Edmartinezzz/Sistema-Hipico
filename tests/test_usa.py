"""Tests del módulo de hipódromos de EE.UU. (Equibase).

Los fixtures son HTML sintético con la estructura real de
``tvg.equibase.com`` (índice ``#tracks``, ``RaceCardIndex`` con
``#entryRaces`` y la tabla de inscritos por carrera) y de
``mobile.equibase.com`` (respaldo), para no depender de la red.
"""

from datetime import date
from pathlib import Path

import pytest

from src import hipodromos_usa as usa

INDEX_HTML = """
<table id="tracks">
  <thead><tr><th>Featured Tracks</th><th>Today</th><th>Tomorrow</th>
  <th>Future</th><th>Past</th></tr></thead>
  <tbody>
    <tr>
      <td><a href="/static/entry/PRX-calendar.html">Parx Racing</a></td>
      <td><a class="entryLink" href="/static/entry/RaceCardIndexPRX111026USA-EQB.html">10</a></td>
      <td><a class="entryLink" href="/static/entry/RaceCardIndexPRX111126USA-EQB.html">11</a></td>
      <td><a class="entryLink" href="/static/entry/RaceCardIndexPRX111226USA-EQB.html">12</a></td>
      <td><a class="entryLink" href="/static/entry/RaceCardIndexPRX110926USA-EQB.html">09</a></td>
    </tr>
    <tr>
      <td><a href="/static/entry/GP-calendar.html">Gulfstream Park</a></td>
      <td></td>
      <td></td>
      <td><a class="entryLink" href="/static/entry/RaceCardIndexGP111326USA-EQB.html">13</a></td>
      <td><a class="entryLink" href="/static/entry/RaceCardIndexGP110826USA-EQB.html">08</a></td>
    </tr>
  </tbody>
</table>
<table id="tracks">
  <tbody>
    <tr>
      <td><a href="/static/entry/PRX-calendar.html">Parx Racing</a></td>
      <td><a class="entryLink" href="/static/entry/RaceCardIndexPRX111026USA-EQB.html">10</a></td>
      <td></td><td></td>
      <td><a class="entryLink" href="/static/entry/RaceCardIndexPRX110926USA-EQB.html">09</a></td>
    </tr>
  </tbody>
</table>
"""

CARD_HTML = """
<table id="entryRaces">
  <thead><tr><th>Race</th><th>Purse</th><th>Race Type</th><th>Distance</th>
  <th>Surface</th><th>Starters</th><th>Est. Post</th></tr></thead>
  <tbody>
    <tr>
      <td class="text-center"><a href="/static/entry\\PRX111026USA1-EQB.html">1</a></td>
      <td>$21,000</td><td>Claiming</td><td>5 1/2 F</td><td>Dirt</td>
      <td>7</td><td>12:05 PM ET</td><td></td>
    </tr>
    <tr>
      <td class="text-center"><a href="/static/entry\\PRX111026USA2-EQB.html">2</a></td>
      <td>$30,000</td><td>Maiden Special Weight</td><td>1 M</td><td>Turf</td>
      <td>9</td><td>12:32 PM ET</td><td></td>
    </tr>
  </tbody>
</table>
"""

RACE_HTML = """
<div class="race-info">
  <p>Daily Double / Pick 3 (Races 1-2-3) Exacta</p>
  <p><strong>Parx Racing</strong> CLAIMING $7,500</p>
  <div class="entries-race-conditions">
    <div class="conditions-text"><p>Purse $21,000. Five And One Half Furlongs.</p></div>
  </div>
  <table class="fullwidth">
    <thead><tr><th>P#</th><th>PP</th><th>Horse</th><th>VS</th><th>A/S</th>
    <th>Med</th><th>Claim $</th><th>Jockey</th><th>Wgt</th><th>Trainer</th>
    <th>M/L</th></tr></thead>
    <tbody>
      <tr>
        <td><div class="paddingSaddleCloths saddlecloth-1">1</div></td>
        <td><div class="stubborn-cell"><b>1</b></div></td>
        <td><b><a href="/profiles/Results.cfm?type=Horse&refno=1"
              title=" (Sire - Dam, by Damsire)">Crimson Red (KY)</a></b></td>
        <td></td>
        <td><div class="bigger-stubborn-cell">3/F</div></td>
        <td>L</td><td>$7,500</td>
        <td><a href="/profiles/Results.cfm?type=People">E   Ruiz</a></td>
        <td><div class="bigger-stubborn-cell">119<sup></sup></div></td>
        <td><a href="/profiles/Results.cfm?type=People">W   Potts</a></td>
        <td>3/1</td>
      </tr>
      <tr>
        <td><div class="paddingSaddleCloths saddlecloth-2">2</div></td>
        <td><div class="stubborn-cell"><b>2</b></div></td>
        <td><b><a href="/profiles/Results.cfm?type=Horse&refno=2"
              title=" (S - D, by DS)">Disco Hopp (PA)</a></b></td>
        <td></td>
        <td><div class="bigger-stubborn-cell">4/F</div></td>
        <td></td><td></td>
        <td><a href="/profiles/Results.cfm?type=People">N   Herman</a></td>
        <td><div class="bigger-stubborn-cell">122<sup></sup></div></td>
        <td><a href="/profiles/Results.cfm?type=People">H   Padilla</a></td>
        <td>7/2</td>
      </tr>
      <tr>
        <td><div class="paddingSaddleCloths saddlecloth-3">3</div></td>
        <td><div class="stubborn-cell"><b>3</b></div></td>
        <td><b><a href="/profiles/Results.cfm?type=Horse&refno=3"
              title=" (S - D, by DS)">Old Paint</a></b></td>
        <td></td>
        <td><div class="bigger-stubborn-cell">5/G</div></td>
        <td></td><td></td>
        <td>Scratched</td>
        <td><div class="bigger-stubborn-cell">120<sup></sup></div></td>
        <td><a href="/profiles/Results.cfm?type=People">T   McFly</a></td>
        <td>SCR</td>
      </tr>
    </tbody>
  </table>
</div>
"""

MOBILE_DAY_HTML = """
<a href="/html/entriesPRX2026111001.html">Race 1 12:05</a><br>
<a href="/html/entriesPRX2026111002.html">Race 2 12:32</a><br>
"""

MOBILE_RACE_HTML = """
<b>Post Time: 12:05</b><br>
<br>Claiming<br>
Program: 1 Post: 1 Odds: 3/1 <br>
<b>Crimson Red</b><br>Jockey: Eliseo   Ruiz<br>Trainer: Wayne   Potts<br>
Program: 2 Post: 2 Odds: 7/2 <br>
<b>Disco Hopp</b><br>Jockey: Noel   Herman<br>Trainer: Hugo O. Padilla<br>
"""


def test_parse_meetings_slots_y_dedup():
    reuniones = usa.parse_meetings(INDEX_HTML)
    # La segunda tabla repite PRX hoy: se deduplica por (pista, fecha).
    assert len(reuniones) == 6
    hoy = usa.meetings_for_day(reuniones, "today")
    assert len(hoy) == 1
    assert hoy[0]["track_code"] == "PRX"
    assert hoy[0]["track_name"] == "Parx Racing"
    assert hoy[0]["date"] == date(2026, 11, 10)
    assert hoy[0]["url"].endswith(
        "RaceCardIndexPRX111026USA-EQB.html"
    )
    manana = usa.meetings_for_day(reuniones, "tomorrow")
    assert manana[0]["date"] == date(2026, 11, 11)
    futuro = {r["track_code"] for r in usa.meetings_for_day(reuniones, "future")}
    assert futuro == {"PRX", "GP"}


def test_parse_card_index():
    carreras = usa.parse_card_index(CARD_HTML)
    assert len(carreras) == 2
    assert carreras[0]["race_number"] == 1
    assert carreras[0]["purse"] == "$21,000"
    assert carreras[0]["distance"] == "5 1/2 F"
    assert carreras[0]["surface"] == "Dirt"
    assert carreras[0]["post_time"] == "12:05 PM ET"
    # El enlace con backslash queda normalizado y lleva el n° de carrera.
    assert carreras[0]["url"].endswith("PRX111026USA1-EQB.html")
    assert carreras[1]["race_type"] == "Maiden Special Weight"


def test_parse_race_page():
    datos = usa.parse_race_page(RACE_HTML, 1)
    assert datos["race_number"] == 1
    assert "CLAIMING" in datos["race_name"]
    assert "Purse $21,000" in datos["conditions"]
    e1, e2, e3 = datos["entries"]
    assert e1["program"] == 1 and e1["post_position"] == 1
    assert e1["horse_name"] == "Crimson Red (KY)"
    assert e1["bred"] == "KY"
    assert e1["pedigree"] == "Sire - Dam, by Damsire"
    assert e1["age"] == 3 and e1["sex"] == "F"
    assert e1["medication"] == "L"
    assert e1["claiming_price"] == 7500.0
    assert e1["jockey"] == "E Ruiz"
    assert e1["weight"] == 119.0
    assert e1["trainer"] == "W Potts"
    assert e1["morning_line"] == "3/1"
    assert not e1["scratched"]
    assert e3["scratched"]  # "Scratched" en la fila marca al retirado


def test_meeting_to_records_odds_y_favorito():
    carrera = usa.parse_race_page(RACE_HTML, 1)
    datos = {
        "meeting": {
            "track_code": "PRX", "trackName": "Parx Racing",
            "country": "USA", "date": "2026-11-10",
        },
        "slot": "today",
        "races": [carrera],
    }
    registros = usa.meeting_to_records(datos)
    # El retirado queda fuera.
    assert len(registros) == 2
    assert usa.scratched(datos) == [
        {"race_number": 1, "horse_name": "Old Paint"}
    ]
    r1, r2 = registros
    assert r1["odds"] == 4.0  # 3/1 + 1
    assert r2["odds"] == 4.5  # 7/2 + 1
    assert r1["morning_line_favorite"] and not r2["morning_line_favorite"]
    assert r1["track"] == "Parx Racing"
    assert r1["track_code"] == "PRX"
    assert r1["date"] == "2026-11-10"
    assert r1["source"] == "equibase"
    assert r1["weight_lbs"] is True


def test_fetch_meeting_respaldo_movil(tmp_path, monkeypatch):
    """Si la fuente principal falla, se usa el sitio móvil."""
    llamadas = []

    def falso_get(url: str) -> str:
        llamadas.append(url)
        if "RaceCardIndex" in url or "tvg.equibase" in url:
            raise usa.HipodromosUsaError("caído")
        if url.endswith("entriesPRX20261110.html"):
            return MOBILE_DAY_HTML
        return MOBILE_RACE_HTML

    monkeypatch.setattr(usa, "_get_html", falso_get)
    reunion = {
        "track_code": "PRX", "track_name": "Parx Racing", "country": "USA",
        "date": "2026-11-10", "slot": "today",
        "url": "https://tvg.equibase.com/static/entry/RaceCardIndexPRX.html",
    }
    datos = usa.fetch_meeting(reunion, cache_dir=tmp_path)
    assert datos["source"] == "equibase_mobile"
    assert len(datos["races"]) == 2
    registros = usa.meeting_to_records(datos)
    assert registros[0]["horse_name"] == "Crimson Red"
    assert registros[0]["jockey"] == "Eliseo Ruiz"
    assert registros[0]["odds"] == 4.0


def test_fetch_meeting_cache(tmp_path, monkeypatch):
    """La segunda lectura de la misma tarjeta usa el archivo cacheado."""
    escrito = {
        "meeting": {"track_code": "PRX", "trackName": "Parx Racing",
                    "country": "USA", "date": "2026-11-10"},
        "slot": "past",
        "races": [],
    }
    ruta = tmp_path / "usa_PRX_USA_20261110.json"
    ruta.write_text(__import__("json").dumps(escrito), encoding="utf-8")

    def fallar(url: str) -> str:
        raise AssertionError("no debería pedir la red con la caché válida")

    monkeypatch.setattr(usa, "_get_html", fallar)
    reunion = {
        "track_code": "PRX", "track_name": "Parx Racing", "country": "USA",
        "date": "2026-11-10", "slot": "past", "url": "http://x",
    }
    datos = usa.fetch_meeting(reunion, cache_dir=tmp_path)
    assert datos["meeting"]["track_code"] == "PRX"


def test_parse_meetings_vacio():
    assert usa.parse_meetings("<table id='tracks'></table>") == []


def test_parse_card_index_sin_tabla():
    with pytest.raises(usa.HipodromosUsaError):
        usa.parse_card_index("<div>sin tabla</div>")
