"""Tests del Módulo 2 — enriquecimiento con mocks (sin red real)."""

import responses

from src.database import init_db, save_enrichment, upsert_horse
from src.scraper import cache_to_db, enrich_horse, rate_limited_get

URL = "https://ejemplo.test/datos"


@responses.activate
def test_rate_limited_get_ok():
    responses.get(URL, json={"ok": True}, status=200)
    respuesta = rate_limited_get(URL)
    assert respuesta.status_code == 200
    assert respuesta.json() == {"ok": True}
    assert "SistemaHipico" in responses.calls[0].request.headers["User-Agent"]


@responses.activate
def test_rate_limited_get_reintenta_5xx():
    responses.get(URL, status=500)
    responses.get(URL, json={"ok": True}, status=200)
    respuesta = rate_limited_get(URL)
    assert respuesta.status_code == 200
    assert len(responses.calls) == 2


@responses.activate
def test_rate_limited_get_falla_tras_3():
    for _ in range(3):
        responses.get(URL, status=503)
    try:
        rate_limited_get(URL)
    except Exception as exc:
        assert "503" in str(exc)
    else:
        raise AssertionError("Debió lanzar excepción tras 3 intentos")
    assert len(responses.calls) == 3


def test_enrich_horse_desde_cache(db_path):
    init_db(db_path)
    hid = upsert_horse(db_path, "Relampago")
    save_enrichment(db_path, hid, "kaggle", {"rating": 85})
    resultado = enrich_horse("Relampago", str(db_path), offline=True)
    assert resultado["found"] is True
    assert resultado["source"] == "kaggle"
    assert resultado["data"] == {"rating": 85}


def test_enrich_horse_offline_no_encontrado(db_path):
    init_db(db_path)
    resultado = enrich_horse("Inexistente", str(db_path), offline=True)
    assert resultado == {"found": False, "source": None}


def test_enrich_horse_desde_csv(db_path, tmp_path):
    init_db(db_path)
    csv_dir = tmp_path / "enrichment"
    csv_dir.mkdir()
    (csv_dir / "historial.csv").write_text(
        "horse,rating,starts\nRelampago,90,12\nTrueno,77,8\n",
        encoding="utf-8",
    )
    resultado = enrich_horse(
        "Relampago", str(db_path), offline=True, csv_dir=csv_dir
    )
    assert resultado["found"] is True
    assert resultado["source"] == "csv:historial.csv"
    assert resultado["data"]["rating"] == "90"


def test_cache_to_db(db_path):
    init_db(db_path)
    guardados = cache_to_db(
        [
            {"horse_name": "Relampago", "source": "kaggle", "rating": 85},
            {"horse_name": "Trueno", "source": "kaggle", "rating": 77},
            {"source": "kaggle"},  # sin horse_name -> ignorado
        ],
        str(db_path),
    )
    assert guardados == 2
    assert enrich_horse("Trueno", str(db_path), offline=True)["found"] is True
