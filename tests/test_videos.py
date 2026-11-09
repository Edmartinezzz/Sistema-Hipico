"""Tests del Módulo 8 — videos de carreras."""

import pytest

from src.database import (
    delete_race_video,
    get_race_video,
    get_setting,
    init_db,
    save_race_video,
    set_setting,
)
from src.videos import busqueda_youtube, es_url, ruta_video_subido, tipo_video, youtube_id


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=30",
        "https://www.youtube.com/live/dQw4w9WgXcQ",
        "https://m.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
    ],
)
def test_youtube_id(url):
    assert youtube_id(url) == "dQw4w9WgXcQ"


def test_youtube_id_invalido():
    assert youtube_id("https://www.youtube.com/results?search_query=x") is None
    assert youtube_id("no es url") is None


def test_tipo_video(tmp_path):
    assert tipo_video("https://youtu.be/dQw4w9WgXcQ") == "youtube"
    assert tipo_video("https://cdn.ejemplo.test/carrera.mp4") == "archivo"
    assert tipo_video("https://www.facebook.com/inh/videos/123") == "enlace"
    local = tmp_path / "c1.mp4"
    local.write_bytes(b"x")
    assert tipo_video(str(local)) == "archivo"
    assert tipo_video(str(tmp_path / "no_existe.mp4")) is None
    assert tipo_video("") is None
    assert tipo_video("ftp://x.test/a.mp4") is None


def test_es_url():
    assert es_url("https://x.test")
    assert not es_url("javascript:alert(1)")
    assert not es_url(None)


def test_busqueda_youtube():
    url = busqueda_youtube("LA RINCONADA", "08/11/2026", 3, 44)
    assert url.startswith("https://www.youtube.com/results?search_query=")
    assert "La+Rinconada+reuni%C3%B3n+44+carrera+3+08%2F11%2F2026" in url


def test_ruta_video_subido():
    ruta = ruta_video_subido("LA RINCONADA", "2026-11-08", 3, "mi video.MP4")
    assert ruta.name == "LA_RINCONADA_2026_11_08_c3.mp4"
    with pytest.raises(ValueError):
        ruta_video_subido("X", "2026-11-08", 1, "virus.exe")


def test_videos_en_db(db_path):
    init_db(db_path)
    assert get_race_video(db_path, "LA RINCONADA", "2026-11-08", 3) is None
    save_race_video(db_path, "LA RINCONADA", "2026-11-08", 3, "https://youtu.be/a")
    save_race_video(db_path, "LA RINCONADA", "2026-11-08", 3, "https://youtu.be/b")
    assert get_race_video(db_path, "LA RINCONADA", "2026-11-08", 3) == "https://youtu.be/b"
    delete_race_video(db_path, "LA RINCONADA", "2026-11-08", 3)
    assert get_race_video(db_path, "LA RINCONADA", "2026-11-08", 3) is None


def test_settings(db_path):
    init_db(db_path)
    assert get_setting(db_path, "url_en_vivo", "def") == "def"
    set_setting(db_path, "url_en_vivo", "https://youtu.be/x")
    assert get_setting(db_path, "url_en_vivo") == "https://youtu.be/x"
    set_setting(db_path, "url_en_vivo", None)
    assert get_setting(db_path, "url_en_vivo") is None
