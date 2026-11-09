"""Tests del Módulo 12 — cuotas ML desde gacetas escaneadas (sin OCR real)."""

from datetime import date

import pytest

from src.ocr_gaceta import (
    asignar_cuotas,
    clave_nombre,
    compacto,
    cuota_decimal,
    fecha_pagina,
    numero_carrera,
)


def test_compacto_y_clave_nombre():
    assert compacto("The King Zeus") == "THEKINGZEUS"
    assert compacto("Niño del Cielo") == "NINODELCIELO"
    assert clave_nombre("FATIMA BLUSH (USA)") == "FATIMABLUSH"


@pytest.mark.parametrize(
    "textos, esperado",
    [
        (["Premiacion:27.040", "Segunda Carrera"], 2),
        (["Decimatercera Carrera"], 13),
        (["Undecima Carrera"], 11),
        (["Duodecima Carrera"], 12),
        (["Décima Carrera"], 10),
        (["3a Carrera"], 3),
        (["ENTRENADORES LIDERES"], None),
    ],
)
def test_numero_carrera(textos, esperado):
    assert numero_carrera(textos) == esperado


def test_fecha_pagina():
    assert fecha_pagina(["La Rinconada", "08/11/26"]) == date(2026, 11, 8)
    assert fecha_pagina(["sin fecha"]) is None


def test_cuota_decimal():
    assert cuota_decimal(3, 2) == 2.5
    assert cuota_decimal(30, 1) == 31.0
    assert cuota_decimal(9, 5) == 2.8
    assert cuota_decimal(0, 1) is None


def test_asignar_cuotas_franja_real():
    """Líneas tal como las devuelve el OCR en la gaceta del 08/11/26 (2ª carrera)."""
    lineas = [
        (10, "Segunda Carrera"), (20, "13/04/18"),
        (30, "PAPASUU"), (40, "MLC.C.8a Champlain-Blue Secret"), (50, "30/1 p.Water Poet"),
        (60, "THEKINGZEUS"), (70, "ML"), (75, "08/02/18"), (80, "30/1"),
        (90, "BASEARMADOR"), (100, "ML"), (110, "3/2"),
        (120, "JETFUEL(USA)"), (130, "271"),  # cuota mal leída -> sin cuota
        (140, "FATIMA BLUSH"), (150, "9/5 p.Tapit"),
    ]
    nombres = ["PAPA SUU", "THE KING ZEUS", "BASE ARMADOR", "JET FUEL (USA)",
               "FATIMA BLUSH (USA)", "NO ESTA"]
    cuotas = asignar_cuotas(lineas, nombres)
    assert cuotas == {
        "PAPA SUU": 31.0,
        "THE KING ZEUS": 31.0,
        "BASE ARMADOR": 2.5,
        "FATIMA BLUSH (USA)": 2.8,
    }


def test_asignar_cuotas_tolera_errores_de_ocr():
    # "EL TRUEN0" (cero en vez de O) ~ "EL TRUENO".
    assert asignar_cuotas([(1, "ELTRUEN0"), (2, "5/1")], ["EL TRUENO"]) == {"EL TRUENO": 6.0}
    # Las fechas dd/mm/aa no se confunden con cuotas.
    assert asignar_cuotas([(1, "ADEMAN"), (2, "11/03/18")], ["ADEMAN"]) == {}


def test_cache_ocr(tmp_path, monkeypatch):
    from src import ocr_gaceta

    monkeypatch.setattr(ocr_gaceta, "CACHE_DIR", tmp_path)
    pdf = b"%PDF-falso"
    assert ocr_gaceta.leer_cache(pdf) is None
    resultado = {
        "fecha": date(2026, 11, 8),
        "cuotas": {(3, "FUEGO"): 2.5, (3, "REY"): 8.0},
        "paginas": 2,
        "carreras": [3],
    }
    ocr_gaceta.guardar_cache(pdf, resultado)
    leido = ocr_gaceta.leer_cache(pdf)
    assert leido["fecha"] == date(2026, 11, 8)
    assert leido["cuotas"] == {(3, "FUEGO"): 2.5, (3, "REY"): 8.0}
    assert leido["carreras"] == [3]
    # Otro PDF no tiene caché.
    assert ocr_gaceta.leer_cache(b"otro") is None
