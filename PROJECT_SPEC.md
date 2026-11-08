# PROJECT_SPEC.md — Sistema de Análisis Estadístico de Caballos

## 1. Rol y contexto

Eres un agente de ingeniería de software senior. Vas a construir un sistema completo en Python para analizar carreras de caballos a partir de una "gaveta" (programa de carrera) en formato PDF. El usuario gestiona el proyecto desde un teléfono móvil y revisará tu trabajo mediante Pull Requests en GitHub. Trabaja de forma autónoma, pero entrega incrementos pequeños y revisables.

## 2. Objetivo del sistema

Dado un PDF de gaveta de carreras, el sistema debe:
1. Extraer automáticamente los datos estructurados de cada caballo (nombre, jinete, entrenador, peso, cuota, número de programa, récord W-P-S, etc.).
2. Enriquecer esos datos con información externa gratuita (historial del caballo, jockey, trainer, últimas actuaciones).
3. Estimar la probabilidad de victoria de cada caballo mediante el modelo estadístico de Harville y detectar "value bets" comparando la probabilidad del modelo con la cuota implícita.
4. Presentar todo en un dashboard web local (Streamlit) donde el usuario puede subir el PDF y ver el análisis.

## 3. Restricciones obligatorias (NO NEGOCIABLES)

- **Presupuesto CERO**: solo librerías open-source, solo fuentes de datos gratuitas. Prohibido usar APIs de pago (Equibase API, DRF API, The Jockey Club API, RapidAPI premium, etc.).
- **Python 3.11+**. Gestión de dependencias con `requirements.txt` y `venv`.
- **Base de datos: SQLite** (incluida en la stdlib, sin servidores).
- **Frontend: Streamlit** (gratuito, local).
- **Todo el código, comentarios, docstrings y documentación en español.**
- **No hacer push directo a `main`**. Cada feature va en una rama `feature/<nombre>` y se entrega como Pull Request.
- **No descargar datasets gigantes (>200 MB)** ni commitear datos binarios pesados al repo. Usar `data/` con `.gitignore` para archivos generados.
- **Scraping respetuoso**: incluir `time.sleep()` entre peticiones, User-Agent identificable, y manejo de errores HTTP. Nunca más de 1 req/segundo al mismo dominio.
- **No inventar datos**. Si una fuente no está disponible, registrar un warning y continuar con valores `None`.

## 4. Estructura del repositorio

```

horse-analytics/
├── PROJECT_SPEC.md          # este archivo
├── README.md                # instrucciones de instalación y uso
├── requirements.txt
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── pdf_extractor.py     # Módulo 1: PDF → datos estructurados
│   ├── scraper.py           # Módulo 2: enriquecimiento web gratuito
│   ├── harville_model.py    # Módulo 3: probabilidades y value bets
│   ├── database.py          # Módulo 4: capa SQLite
│   └── app.py               # Módulo 5: dashboard Streamlit
├── tests/
│   ├── test_pdf_extractor.py
│   ├── test_scraper.py
│   ├── test_harville_model.py
│   └── test_database.py
├── data/
│   ├── samples/             # PDFs de ejemplo (uno público/generado)
│   └── .gitkeep
└── docs/
└── fuentes_datos.md     # documentación de fuentes gratuitas usadas

```

## 5. Especificación de cada módulo

### Módulo 1 — `src/pdf_extractor.py`

**Responsabilidad**: convertir un PDF de gaveta en una lista de diccionarios Python.

**Funciones públicas**:
- `extract_races(pdf_path: str) -> list[dict]`: devuelve una lista donde cada dict representa un caballo en una carrera, con las claves mínimas: `race_number`, `horse_name`, `jockey`, `trainer`, `weight`, `odds`, `post_position`, `record`, `morning_line_favorite` (bool), y cualquier otra columna detectada.
- `detect_columns(table: list[list[str]]) -> dict[str, int]`: heurística que mapea nombres de columna a índices, tolerando variaciones ("Jinete"/"Jockey"/"J.").
- `normalize_odds(raw: str) -> float | None`: convierte cuotas tipo "7-2", "5/1", "NADA", "3.5" a probabilidad implícita decimal. Devolver `None` si no es parseable.

**Librerías permitidas**: `pdfplumber` (principal), `camelot-py` (opcional como fallback), `pytesseract` + `pdf2image` (solo si el PDF es imagen; documentar la dependencia de Tesseract del sistema).

**Requisitos**:
- Manejar tablas que se rompen en varias páginas.
- Devolver `[]` con warning si el PDF no contiene tablas.
- Tests con al menos un PDF de muestra generado programáticamente (usar `reportlab` para crear un PDF sintético de prueba, así no dependemos de archivos externos).

### Módulo 2 — `src/scraper.py`

**Responsabilidad**: enriquecer datos de caballos con información histórica gratuita.

**Fuentes permitidas (documentar en `docs/fuentes_datos.md`)**:
- Inspirarse en `rpscrape` (GitHub, licencia abierta) para estructura de scraping.
- Brisnet Past Performances gratuitas (registro gratuito; el usuario provee credenciales por variable de entorno).
- DRF Charts (últimos 7 días, gratis).
- Kaggle como fuente offline: documentar qué dataset se puede descargar manualmente y cargar por CSV.

**Funciones públicas**:
- `enrich_horse(horse_name: str, db_path: str) -> dict`: busca en SQLite; si no está, intenta scraper; si falla, devuelve `{"found": False, "source": None}`.
- `cache_to_db(records: list[dict], db_path: str) -> int`: upsert en SQLite.
- `rate_limited_get(url: str, **kwargs) -> requests.Response`: wrapper con `time.sleep(1)`, User-Agent, y reintentos exponenciales (máx 3).

**Requisitos**:
- Si el scraper falla (sitio cambió, bloqueo), debe degradar elegantemente y NO romper el pipeline.
- Modo `offline=True` que solo usa SQLite y CSV locales (útil para tests).
- Tests con `responses` o `pytest-httpx` para simular respuestas sin red real.

### Módulo 3 — `src/harville_model.py`

**Responsabilidad**: convertir cuotas en probabilidades y detectar value bets.

**Funciones públicas**:
- `implied_probability(odds_decimal: float) -> float`: `1 / odds_decimal` (sin margen de casa).
- `normalize_probabilities(probs: list[float]) -> list[float]`: reescala para que sumen 1.0 (elimina el "overround" de la casa).
- `harville_win_probabilities(strengths: list[float]) -> list[float]`: implementa el modelo de Harville. Dado un vector de "fuerzas" (por ejemplo, derivadas de las cuotas), devuelve la probabilidad de victoria de cada caballo. La fórmula de Harville asume tiempos exponenciales: P(i gana) = strength_i / sum(strengths).
- `detect_value_bets(model_probs: list[float], market_probs: list[float], threshold: float = 0.05) -> list[dict]`: devuelve caballos donde `model_prob - market_prob > threshold`, con el edge calculado.
- `kelly_fraction(prob: float, odds_decimal: float) -> float`: fracción de Kelly para sizing (informativo, no apostar real).

**Requisitos**:
- Docstrings con la fórmula matemática en LaTeX o texto claro.
- Tests con casos conocidos (verificar que probabilidades suman 1, que un caballo con cuota 2.0 tiene prob ≈ 0.5 antes de normalizar, etc.).
- Incluir función auxiliar para convertir cuotas fraccionarias UK ("7-2") a decimal.

### Módulo 4 — `src/database.py`

**Responsabilidad**: capa de acceso a SQLite.

**Tablas mínimas**:
- `horses(id, name, birth_year, sex, sire, dam, last_updated)`
- `races(id, date, track, distance, surface, race_number)`
- `entries(id, race_id, horse_id, jockey, trainer, weight, odds, post_position, result_position)`
- `enrichment(id, horse_id, source, data_json, fetched_at)`

**Funciones**: `init_db()`, `upsert_horse()`, `get_horse_history()`, `save_entries()`.

**Requisitos**: usar `sqlite3` de la stdlib. Sin ORM pesado (evitar SQLAlchemy a menos que sea estrictamente necesario).

### Módulo 5 — `src/app.py` (Streamlit)

**Responsabilidad**: dashboard para el usuario final.

**Requisitos**:
- `st.file_uploader` para subir la gaveta PDF.
- Botón "Analizar" que ejecuta: extractor → enriquecimiento → modelo → tabla de resultados.
- Tabla con columnas: Caballo, Jinete, Cuota, Prob. modelo, Prob. mercado, Edge (value bet).
- Resaltar en verde las filas con value bet positivo.
- Sección de "detalle por caballo" con historial enriquecido.
- Manejo de errores visible (st.error), nunca dejar la app en blanco.
- Ejecutar con `streamlit run src/app.py`.

## 6. Workflow de entrega (obligatorio)

Para cada módulo:
1. Crear rama `feature/<modulo>` desde `main`.
2. Implementar código + tests + docstrings.
3. Ejecutar `pytest` localmente en la sesión de Devin y asegurar que pasa.
4. Actualizar `README.md` con instrucciones nuevas si aplica.
5. Abrir Pull Request con título `feat: <módulo>` y descripción que incluya:
   - Qué hace.
   - Cómo probarlo.
   - Limitaciones conocidas.
6. **NO mergear**. El usuario lo revisará y aprobará.

## 7. Orden de ejecución (sprints)

Ejecuta en este orden, un PR por sprint:

- **Sprint 1**: estructura del repo, `requirements.txt`, `.gitignore`, `database.py` + tests.
- **Sprint 2**: `pdf_extractor.py` + PDF sintético de prueba generado con `reportlab` + tests.
- **Sprint 3**: `harville_model.py` + tests (independiente del scraper, se puede hacer en paralelo al Sprint 2).
- **Sprint 4**: `scraper.py` con modo `offline=True` funcional + tests con mocks.
- **Sprint 5**: `app.py` (Streamlit) integrando los módulos anteriores.
- **Sprint 6**: `README.md` completo con capturas (o texto descriptivo), `docs/fuentes_datos.md`, y un dataset de ejemplo sintético.

## 8. Criterios de aceptación globales

- `pytest` pasa al 100% en cada PR.
- `python -m compileall src/` sin errores.
- La app Streamlit arranca sin excepciones con un PDF de muestra.
- El README permite a un usuario nuevo clonar, instalar y ejecutar en <10 minutos.
- Ninguna dependencia de pago en `requirements.txt`.
- Cero secretos hardcodeados (usar `os.getenv`).

## 9. Qué NO hacer

- No usar APIs de pago ni servicios con tarjeta de crédito.
- No scrapear sitios sin documentar el dominio y sin rate limiting.
- No commitear PDFs reales con datos personales o de derechos de autor; usar solo PDFs sintéticos generados por `reportlab` o de dominio público.
- No inventar campos que no estén en la gaveta: si no se detecta una columna, marcarla como `None`.
- No crear dependencias circulares entre módulos (el modelo no importa al scraper; el extractor no importa a Streamlit).
- No usar `print()` para logging; usar el módulo `logging`.

## 10. Entregable final esperado

Al terminar los 6 sprints, el usuario podrá:
1. Clonar el repo en su PC.
2. `pip install -r requirements.txt`.
3. `streamlit run src/app.py`.
4. Subir un PDF de gaveta y ver el análisis con probabilidades y value bets.

---

**Instrucción inicial para Devin**: Lee este archivo completo, confirma en un comentario qué sprints vas a ejecutar y en qué orden, y comienza por el **Sprint 1** en una rama `feature/setup`. Abre el PR y espera revisión antes de continuar al Sprint 2.
