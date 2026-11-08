"""Pruebas del enriquecimiento (sin red real: HTTP simulado con ``responses``)."""

import pytest
import requests
import responses

from src import database, scraper

URL = "https://datos.ejemplo.test/caballos"


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    """Evita esperas reales y registra cuánto se habría dormido."""
    esperas = []
    monkeypatch.setattr(scraper.time, "sleep", esperas.append)
    monkeypatch.setattr(scraper, "_last_request_at", {})
    monkeypatch.delenv("HORSE_DATA_URL", raising=False)
    monkeypatch.delenv("HORSE_CSV_PATH", raising=False)
    return esperas


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    database.init_db(path)
    return path


@pytest.fixture
def csv_historial(tmp_path):
    path = tmp_path / "historial.csv"
    path.write_text(
        "Caballo;Año nacimiento;Sexo;Padre;Madre;starts;wins;earnings\n"
        "Relámpago Azul;2020;M;Trueno Real;Brisa Fina;12;4;15000.5\n"
        "Niña Bonita;2021;H;N/A;;5;1;NA\n"
        ";2019;M;X;Y;1;0;0\n",
        encoding="utf-8-sig",
    )
    return path


# ------------------------------------------------------------------ rate_limited_get


@responses.activate
def test_rate_limited_get_envia_user_agent():
    responses.get(URL, json={"ok": True})
    respuesta = scraper.rate_limited_get(URL)
    assert respuesta.json() == {"ok": True}
    assert responses.calls[0].request.headers["User-Agent"] == scraper.USER_AGENT


@responses.activate
def test_rate_limited_get_espera_entre_peticiones_al_mismo_dominio(sin_esperas):
    responses.get(URL, json={})
    responses.get("https://otro.test/x", json={})
    scraper.rate_limited_get(URL)
    scraper.rate_limited_get("https://otro.test/x")
    assert sin_esperas == []  # dominios distintos no esperan
    scraper.rate_limited_get(URL)
    assert len(sin_esperas) == 1
    assert 0 < sin_esperas[0] <= scraper.MIN_INTERVAL_SECONDS


@responses.activate
def test_rate_limited_get_reintenta_con_backoff_exponencial(sin_esperas):
    responses.get(URL, status=503)
    responses.get(URL, status=429)
    responses.get(URL, json={"ok": True})
    respuesta = scraper.rate_limited_get(URL, min_interval=0)
    assert respuesta.status_code == 200
    assert len(responses.calls) == 3
    assert sin_esperas == [1.0, 2.0]


@responses.activate
def test_rate_limited_get_maximo_3_reintentos(sin_esperas):
    responses.get(URL, status=500)
    with pytest.raises(requests.HTTPError):
        scraper.rate_limited_get(URL, min_interval=0)
    assert len(responses.calls) == 1 + scraper.MAX_RETRIES
    assert sin_esperas == [1.0, 2.0, 4.0]


@responses.activate
def test_rate_limited_get_reintenta_errores_de_conexion():
    responses.get(URL, body=requests.ConnectionError("sin red"))
    responses.get(URL, json={"ok": True})
    assert scraper.rate_limited_get(URL, min_interval=0).json() == {"ok": True}


@responses.activate
def test_rate_limited_get_no_reintenta_404():
    responses.get(URL, status=404)
    with pytest.raises(requests.HTTPError):
        scraper.rate_limited_get(URL)
    assert len(responses.calls) == 1


# ------------------------------------------------------------------ CSV y cache_to_db


def test_load_csv_normaliza_columnas_y_valores(csv_historial):
    registros = scraper.load_csv(csv_historial)
    assert len(registros) == 2  # la fila sin nombre se omite
    rel = registros[0]
    assert rel["name"] == "Relámpago Azul"
    assert rel["birth_year"] == 2020
    assert rel["sire"] == "Trueno Real"
    assert rel["wins"] == 4
    assert rel["earnings"] == 15000.5
    nina = registros[1]
    assert nina["sire"] is None and nina["dam"] is None and nina["earnings"] is None


def test_cache_to_db_guarda_caballo_y_enriquecimiento(db, csv_historial):
    registros = scraper.load_csv(csv_historial) + [{"name": "  "}, {"wins": 3}]
    assert scraper.cache_to_db(registros, db) == 2
    historial = database.get_horse_history("RELÁMPAGO AZUL", db)
    assert historial["horse"]["birth_year"] == 2020
    assert historial["horse"]["sire"] == "Trueno Real"
    assert historial["enrichment"][0]["source"] == "csv"
    assert historial["enrichment"][0]["data"]["wins"] == 4


# ------------------------------------------------------------------ enrich_horse


def test_enrich_horse_no_encontrado_offline(db):
    assert scraper.enrich_horse("Fantasma", db, offline=True) == {"found": False, "source": None}


def test_enrich_horse_nombre_vacio(db):
    assert scraper.enrich_horse("  ", db) == {"found": False, "source": None}


def test_enrich_horse_desde_csv_y_luego_desde_cache(db, csv_historial):
    primero = scraper.enrich_horse("relámpago azul", db, offline=True, csv_path=csv_historial)
    assert primero["found"] is True
    assert primero["source"] == "csv"
    assert primero["cached"] is False
    assert primero["data"]["wins"] == 4

    segundo = scraper.enrich_horse("Relámpago Azul", db, offline=True)
    assert segundo["found"] is True and segundo["cached"] is True
    assert segundo["horse"]["name"] == "Relámpago Azul"


def test_enrich_horse_csv_por_variable_de_entorno(db, csv_historial, monkeypatch):
    monkeypatch.setenv("HORSE_CSV_PATH", str(csv_historial))
    assert scraper.enrich_horse("Niña Bonita", db, offline=True)["found"] is True


def test_enrich_horse_csv_inexistente_no_rompe(db, tmp_path):
    resultado = scraper.enrich_horse("X", db, offline=True, csv_path=tmp_path / "no.csv")
    assert resultado == {"found": False, "source": None}


@responses.activate
def test_enrich_horse_offline_no_hace_peticiones(db, monkeypatch):
    monkeypatch.setenv("HORSE_DATA_URL", URL + "?nombre={name}")
    assert scraper.enrich_horse("Caribeño", db, offline=True)["found"] is False
    assert len(responses.calls) == 0


@responses.activate
def test_enrich_horse_desde_http_y_cachea(db, monkeypatch):
    monkeypatch.setenv("HORSE_DATA_URL", URL + "?nombre={name}")
    responses.get(URL, json=[{"birth_year": 2019, "wins": 7, "starts": 20}])
    resultado = scraper.enrich_horse("Caribeño", db)
    assert resultado["found"] is True
    assert resultado["source"] == "datos.ejemplo.test"
    assert resultado["horse"]["birth_year"] == 2019
    assert "nombre=Caribe%C3%B1o" in responses.calls[0].request.url
    # La segunda vez sale de SQLite, sin red.
    assert scraper.enrich_horse("Caribeño", db)["cached"] is True
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize(
    "respuesta",
    [
        {"status": 404},
        {"status": 500},
        {"json": []},
        {"body": "<html>sitio cambiado</html>"},
        {"body": requests.ConnectionError("bloqueado")},
    ],
)
def test_enrich_horse_degrada_si_la_fuente_falla(db, respuesta):
    responses.get(URL, **respuesta)
    fetcher = scraper.http_json_fetcher(URL + "?nombre={name}")
    resultado = scraper.enrich_horse("Caribeño", db, fetchers=[fetcher])
    assert resultado == {"found": False, "source": None}


def test_enrich_horse_prueba_la_siguiente_fuente(db):
    def caida(nombre):
        raise RuntimeError("caída")

    def buena(nombre):
        return {"wins": 2}

    resultado = scraper.enrich_horse("Brisa del Ávila", db, fetchers=[caida, buena])
    assert resultado["found"] is True
    assert resultado["source"] == "buena"
    assert resultado["data"] == {"name": "Brisa del Ávila", "wins": 2}


def test_enrich_horse_sin_fuentes_configuradas(db):
    assert scraper.default_fetchers() == []
    assert scraper.enrich_horse("Tormenta Criolla", db)["found"] is False


def test_enrich_horse_db_inaccesible_no_rompe(tmp_path):
    carpeta = tmp_path / "es_un_directorio"
    carpeta.mkdir()
    assert scraper.enrich_horse("X", str(carpeta), offline=True)["found"] is False
