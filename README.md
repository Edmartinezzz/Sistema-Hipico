# horse-analytics

Sistema de análisis estadístico de carreras de caballos: extrae los datos de una
gaveta (programa de carrera) en PDF, los enriquece con fuentes gratuitas, estima
probabilidades con el modelo de Harville y muestra los resultados en un dashboard
de Streamlit. La especificación completa está en [`PROJECT_SPEC.md`](PROJECT_SPEC.md).

> Estado: en desarrollo (Sprint 1 — estructura y base de datos).

## Requisitos

- Python 3.11 o superior
- Git

## Instalación

```bash
git clone https://github.com/Edmartinezzz/horse-analytics.git
cd horse-analytics
python -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecutar las pruebas

```bash
pytest
python -m compileall src/
```

## Base de datos

La capa SQLite está en `src/database.py`. Por defecto el archivo se crea en
`data/horse_analytics.db` (ignorado por git). Se puede cambiar con la variable de
entorno `HORSE_DB_PATH`.

```python
from src import database

database.init_db()
database.save_entries(
    {"date": "2026-11-08", "track": "La Rinconada", "race_number": 1},
    [{"horse_name": "Relámpago", "jockey": "J. Pérez", "odds": 3.5, "post_position": 1}],
)
print(database.get_horse_history("Relámpago"))
```

## Estructura

```
src/        código fuente (database, pdf_extractor, scraper, harville_model, app)
tests/      pruebas con pytest
data/       archivos generados localmente (no se suben al repo)
docs/       documentación adicional
```
