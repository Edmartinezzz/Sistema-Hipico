"""Tests del Módulo 4 — capa SQLite."""

from src.database import (
    get_connection,
    get_horse_history,
    init_db,
    save_enrichment,
    save_entries,
    save_race,
    upsert_horse,
)


def test_init_db_crea_tablas(db_path):
    init_db(db_path)
    with get_connection(db_path) as conn:
        tablas = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {"horses", "races", "entries", "enrichment"} <= tablas


def test_upsert_horse_idempotente(db_path):
    init_db(db_path)
    hid1 = upsert_horse(db_path, "Relampago", birth_year=2020, sex="M")
    hid2 = upsert_horse(db_path, "Relampago", sire="Galileo")
    assert hid1 == hid2
    with get_connection(db_path) as conn:
        fila = conn.execute(
            "SELECT * FROM horses WHERE id = ?", (hid1,)
        ).fetchone()
    assert fila["birth_year"] == 2020
    assert fila["sire"] == "Galileo"


def test_save_entries_y_historial(db_path):
    init_db(db_path)
    race_id = save_race(db_path, 1, date="2026-11-09", track="La Zarzuela")
    guardadas = save_entries(
        db_path,
        race_id,
        [
            {
                "horse_name": "Relampago",
                "jockey": "J. Perez",
                "trainer": "M. Lopez",
                "weight": 55.0,
                "odds": 4.5,
                "post_position": 1,
                "result_position": 2,
            },
            {"horse_name": "Trueno", "jockey": "A. Diaz", "odds": 6.0},
        ],
    )
    assert guardadas == 2

    historial = get_horse_history(db_path, "Relampago")
    assert historial["horse"]["name"] == "Relampago"
    assert len(historial["entries"]) == 1
    assert historial["entries"][0]["result_position"] == 2
    assert historial["entries"][0]["track"] == "La Zarzuela"


def test_get_horse_history_desconocido(db_path):
    init_db(db_path)
    assert get_horse_history(db_path, "Inexistente") is None


def test_save_enrichment(db_path):
    init_db(db_path)
    hid = upsert_horse(db_path, "Relampago")
    save_enrichment(db_path, hid, "kaggle", {"rating": 85})
    historial = get_horse_history(db_path, "Relampago")
    assert historial["enrichment"][0]["source"] == "kaggle"
    assert historial["enrichment"][0]["data_json"] == {"rating": 85}
