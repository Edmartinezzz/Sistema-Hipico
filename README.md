# horse-analytics

Sistema de análisis estadístico de carreras de caballos: extrae los datos de una
gaveta (programa de carrera) en PDF, los enriquece con fuentes gratuitas, estima
probabilidades con el modelo de Harville y muestra los resultados en un dashboard
de Streamlit. La especificación completa está en [`PROJECT_SPEC.md`](PROJECT_SPEC.md).

> Estado: en desarrollo (Sprint 5 — dashboard Streamlit).

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

## Abrir el dashboard

```bash
streamlit run src/app.py
```

Se abre en el navegador (http://localhost:8501). Sube una gaveta en PDF y pulsa **Analizar**,
o usa **Usar gaveta de ejemplo**. Verás una tabla por carrera con Caballo, Jinete, Cuota,
Prob. modelo, Prob. mercado y Edge; las filas con value bet salen en verde. Abajo está el
detalle por caballo.

## Extraer una gaveta en PDF

```bash
python -m src.sample_data data/samples/gaveta_ejemplo.pdf   # crea una gaveta sintética
python -c "from src.pdf_extractor import extract_races; import pprint; pprint.pprint(extract_races('data/samples/gaveta_ejemplo.pdf')[:2])"
```

`extract_races()` reconoce encabezados como «Caballo/Ejemplar», «Jinete/Jockey/J.»,
«Entrenador/E.», «Peso», «Cuota/ML», «Récord» y «#/Nº». Lee «Hipódromo:», «Fecha:» y los
títulos «Carrera N» del texto, y une las tablas partidas entre páginas. Las cuotas se
convierten a decimal («7-2» → 4.5) y a probabilidad implícita (1 / 4.5).

## Estructura

```
src/        código fuente (database, pdf_extractor, scraper, harville_model, app)
tests/      pruebas con pytest
data/       archivos generados localmente (no se suben al repo)
docs/       documentación adicional
```
