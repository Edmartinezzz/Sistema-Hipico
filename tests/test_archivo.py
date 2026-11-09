"""Tests del Módulo 9 — archivo histórico."""

import json
from datetime import date

import responses

from src import archivo
from src.gaceta_web import BASE_URL
from tests.test_gaceta_web import LISTA_HTML, REUNION, _html_reunion


def _reunion(meeting_id: str, fecha: str, estado: str = "finished") -> dict:
    datos = json.loads(json.dumps(REUNION))
    datos["meeting"].update({"id": meeting_id, "date": f"{fecha}T12:00:00.000Z",
                             "extraPesado": "x" * 100})
    for c in datos["races"]:
        c["status"] = estado
    return datos


def test_recortar_quita_campos_extra():
    recortada = archivo.recortar(_reunion("aa11", "2026-11-08"))
    assert "extraPesado" not in recortada["meeting"]
    inscrito = recortada["races"][0]["entries"][0]
    assert inscrito["horseName"] == "QUEEN VISION"
    assert inscrito["raceHistory"][0]["winnerName"] == "FANTASTIC SHOT"


def test_terminada():
    assert archivo.terminada(_reunion("a", "2026-11-08"))
    pendiente = _reunion("a", "2026-11-08", "scheduled")
    assert not archivo.terminada(pendiente, hoy=date(2026, 11, 8))
    # Fecha pasada: no va a cambiar aunque tenga carreras sin terminar.
    assert archivo.terminada(pendiente, hoy=date(2026, 11, 9))


def test_guardar_listar_buscar(tmp_path):
    ruta = archivo.guardar_reunion(_reunion("aa11", "2026-11-08"), tmp_path)
    assert ruta.name == "2026-11-08_LA_RINCONADA_aa11.json.gz"
    # Mismo contenido -> archivo idéntico (sin commits vacíos en git).
    antes = ruta.read_bytes()
    archivo.guardar_reunion(_reunion("aa11", "2026-11-08"), tmp_path)
    assert ruta.read_bytes() == antes

    archivo.guardar_reunion(_reunion("bb22", "2026-11-01"), tmp_path)
    listadas = archivo.listar(tmp_path)
    assert [r["id"] for r in listadas] == ["aa11", "bb22"]
    assert listadas[0]["date"] == date(2026, 11, 8)
    assert archivo.buscar("bb22", tmp_path)["meeting"]["id"] == "bb22"
    assert archivo.buscar("zz", tmp_path) is None
    assert [d["meeting"]["id"] for d in archivo.cargar_todas(tmp_path)] == ["bb22", "aa11"]


def test_unir_con_web():
    web = [{"id": "aa11", "date": date(2026, 11, 8)}]
    archivadas = [{"id": "aa11", "date": date(2026, 11, 8), "ruta": "x"},
                  {"id": "old", "date": date(2026, 8, 2), "ruta": "y"}]
    unidas = archivo.unir_con_web(web, archivadas)
    assert [r["id"] for r in unidas] == ["aa11", "old"]
    assert "ruta" not in unidas[1]


@responses.activate
def test_sincronizar(tmp_path, monkeypatch):
    monkeypatch.setattr("src.gaceta_web.CACHE_DIR", tmp_path / "cache")
    responses.get(f"{BASE_URL}/retrospectos", body=LISTA_HTML)
    responses.get(f"{BASE_URL}/revista/aa11", body=_html_reunion(_reunion("aa11", "2026-11-08")))
    responses.get(f"{BASE_URL}/revista/bb22", body=_html_reunion(_reunion("bb22", "2026-11-07")))
    responses.get(f"{BASE_URL}/revista/cc33", status=500)
    destino = tmp_path / "archivo"
    resumen = archivo.sincronizar(destino)
    assert resumen["nuevas"] == 2
    assert resumen["errores"] == 1
    assert len(archivo.listar(destino)) == 2
