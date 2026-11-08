"""Pruebas de la capa SQLite (src/database.py)."""

import sqlite3

import pytest

from src import database


@pytest.fixture
def db_path(tmp_path):
    """Base de datos temporal e inicializada para cada prueba."""
    path = str(tmp_path / "sub" / "test.db")
    database.init_db(path)
    return path


RACE = {
    "date": "2026-11-08",
    "track": "La Rinconada",
    "race_number": 3,
    "distance": "1200m",
    "surface": "arena",
}


def test_init_db_crea_tablas_y_carpeta(db_path):
    with sqlite3.connect(db_path) as conn:
        tablas = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"horses", "races", "entries", "enrichment"} <= tablas


def test_init_db_es_idempotente(db_path):
    database.init_db(db_path)
    database.init_db(db_path)
    assert database.get_horse("Nadie", db_path) is None


def test_init_db_usa_variable_de_entorno(tmp_path, monkeypatch):
    path = str(tmp_path / "env.db")
    monkeypatch.setattr(database, "DEFAULT_DB_PATH", path)
    assert database.init_db() == path
    assert (tmp_path / "env.db").exists()


def test_upsert_horse_inserta_y_devuelve_id(db_path):
    horse_id = database.upsert_horse("Relámpago", birth_year=2021, sex="M", db_path=db_path)
    horse = database.get_horse("Relámpago", db_path)
    assert horse["id"] == horse_id
    assert horse["birth_year"] == 2021
    assert horse["sex"] == "M"
    assert horse["last_updated"]


def test_upsert_horse_no_duplica_y_no_borra_datos(db_path):
    first = database.upsert_horse("Relámpago", sire="Padre", db_path=db_path)
    second = database.upsert_horse("  relámpago ", dam="Madre", db_path=db_path)
    assert first == second
    horse = database.get_horse("Relámpago", db_path)
    assert horse["sire"] == "Padre"
    assert horse["dam"] == "Madre"


def test_upsert_horse_rechaza_nombre_vacio(db_path):
    with pytest.raises(ValueError):
        database.upsert_horse("   ", db_path=db_path)


def test_upsert_race_reutiliza_carrera_existente(db_path):
    first = database.upsert_race(RACE, db_path)
    second = database.upsert_race({**RACE, "distance": None}, db_path)
    assert first == second
    history_race = database.upsert_race({**RACE, "race_number": 4}, db_path)
    assert history_race != first


def test_save_entries_guarda_carrera_caballos_e_inscripciones(db_path):
    entries = [
        {"horse_name": "Relámpago", "jockey": "J. Pérez", "odds": 3.5, "post_position": 1},
        {"horse_name": "Tormenta", "jockey": "L. Gómez", "weight": 54.0, "post_position": 2},
    ]
    assert database.save_entries(RACE, entries, db_path) == 2

    history = database.get_horse_history("Tormenta", db_path)
    assert history["horse"]["name"] == "Tormenta"
    assert len(history["entries"]) == 1
    entry = history["entries"][0]
    assert entry["track"] == "La Rinconada"
    assert entry["race_number"] == 3
    assert entry["jockey"] == "L. Gómez"
    assert entry["weight"] == 54.0
    assert entry["odds"] is None


def test_save_entries_actualiza_sin_duplicar(db_path):
    database.save_entries(RACE, [{"horse_name": "Relámpago", "odds": 3.5}], db_path)
    database.save_entries(
        RACE, [{"horse_name": "Relámpago", "result_position": 1}], db_path
    )
    entries = database.get_horse_history("Relámpago", db_path)["entries"]
    assert len(entries) == 1
    assert entries[0]["odds"] == 3.5
    assert entries[0]["result_position"] == 1


def test_save_entries_omite_entradas_sin_nombre(db_path, caplog):
    entries = [{"horse_name": ""}, {"jockey": "Sin caballo"}, {"horse_name": "Brisa"}]
    with caplog.at_level("WARNING"):
        assert database.save_entries(RACE, entries, db_path) == 1
    assert "omitida" in caplog.text


def test_save_entries_es_atomico(db_path):
    entries = [{"horse_name": "Válido"}, {"horse_name": "Malo", "weight": object()}]
    with pytest.raises(sqlite3.Error):
        database.save_entries(RACE, entries, db_path)
    assert database.get_horse("Válido", db_path) is None


def test_get_horse_history_ordena_de_mas_reciente_a_mas_antigua(db_path):
    database.save_entries({**RACE, "date": "2026-01-01"}, [{"horse_name": "Brisa"}], db_path)
    database.save_entries({**RACE, "date": "2026-06-01"}, [{"horse_name": "Brisa"}], db_path)
    fechas = [e["date"] for e in database.get_horse_history("Brisa", db_path)["entries"]]
    assert fechas == ["2026-06-01", "2026-01-01"]


def test_get_horse_history_caballo_inexistente(db_path):
    assert database.get_horse_history("Fantasma", db_path) == {
        "horse": None,
        "entries": [],
        "enrichment": [],
    }


def test_save_enrichment_y_lectura_json(db_path):
    horse_id = database.upsert_horse("Brisa", db_path=db_path)
    database.save_enrichment(horse_id, "csv_local", {"victorias": 3, "nota": "ñandú"}, db_path)
    enrichment = database.get_horse_history("Brisa", db_path)["enrichment"]
    assert enrichment[0]["source"] == "csv_local"
    assert enrichment[0]["data"] == {"victorias": 3, "nota": "ñandú"}


def test_enrichment_requiere_caballo_existente(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        database.save_enrichment(9999, "csv_local", {}, db_path)


def test_upsert_horse_unifica_mayusculas_acentuadas(db_path):
    database.save_entries(RACE, [{"horse_name": "Relámpago"}], db_path)
    database.save_entries({**RACE, "race_number": 4}, [{"horse_name": "RELÁMPAGO"}], db_path)
    database.save_entries({**RACE, "race_number": 5}, [{"horse_name": " relámpago  "}], db_path)
    for nombre in ("Relámpago", "RELÁMPAGO", "relÁmpago"):
        history = database.get_horse_history(nombre, db_path)
        assert history["horse"]["name"] == "Relámpago"
        assert len(history["entries"]) == 3


def test_name_key_normaliza_unicode_y_espacios():
    compuesto = "Pin\u0303a  Bonita"  # «ñ» como n + tilde combinada
    assert database.name_key(compuesto) == database.name_key("PIÑA BONITA")


@pytest.mark.parametrize("campo", ["date", "track", "race_number"])
@pytest.mark.parametrize("valor", [None, "", "   "])
def test_save_entries_rechaza_carrera_sin_clave_completa(db_path, campo, valor):
    with pytest.raises(ValueError):
        database.save_entries({**RACE, campo: valor}, [{"horse_name": "Brisa"}], db_path)
    assert database.get_horse("Brisa", db_path) is None


@pytest.mark.parametrize("numero", ["tercera", "3.7", 3.7, True, False, [3]])
def test_upsert_race_rechaza_numero_no_entero(db_path, numero):
    with pytest.raises(ValueError):
        database.upsert_race({**RACE, "race_number": numero}, db_path)


@pytest.mark.parametrize("numero", [3, 3.0, "3", " 3 "])
def test_upsert_race_acepta_numero_entero_en_varios_formatos(db_path, numero):
    first = database.upsert_race(RACE, db_path)
    assert database.upsert_race({**RACE, "race_number": numero}, db_path) == first


def test_upsert_race_conserva_distancia_y_acepta_numero_como_texto(db_path):
    first = database.upsert_race(RACE, db_path)
    second = database.upsert_race({**RACE, "race_number": "3", "surface": "grama"}, db_path)
    assert first == second
    with database.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM races WHERE id = ?", (first,)).fetchone()
    assert row["distance"] == "1200m"
    assert row["surface"] == "grama"
