# Fuentes de datos

Todas las fuentes son gratuitas. El sistema funciona **sin internet** (modo offline,
activado por defecto) usando solo la gaveta en PDF, la caché SQLite y un CSV local.

## 1. Gaveta en PDF (obligatoria)

El programa de carreras que sube el usuario. `src/pdf_extractor.py` lee las tablas con
texto (no escaneadas) y reconoce columnas como «Caballo», «Jinete/Jockey», «Entrenador»,
«Peso», «Cuota/ML», «Récord» y «#». Si una columna no está, el campo queda en `None`.

- No se suben PDFs reales al repositorio. El de `data/samples/gaveta_ejemplo.pdf` es
  **sintético**: lo genera `python -m src.sample_data` con caballos inventados.
- El récord se interpreta como `carreras-1.º-2.º-3.º` (por ejemplo `12-4-3-2`).

## 1b. Gaceta en internet (botón «Buscar gaceta de hoy»)

`src/gaceta_online.py` busca la reunión sin que subas nada:

1. **Desafío Hípico** (<https://www.desafiohipico.com/retrospectos>): lista de reuniones
   de La Rinconada y Valencia; se elige la de hoy o la próxima (o la más reciente si no
   hay ninguna futura). De `/revista/<id>` se leen inscritos, jinete, entrenador, peso,
   retirados y carreras/victorias del año. Su `robots.txt` permite `/retrospectos` y
   `/revista/`; no se usa `/api/`.
2. **Respaldo: pollamacaco.com** (`/Revistas/LaRinconada.pdf`): revista en PDF de Movil
   Hipismo, leída por `pdf_extractor` (récord `Act: (carreras-1.º-2.º-3.º)`). Solo La
   Rinconada; la app avisa si el PDF no es del día.

Ninguna de las dos publica cuotas. Las peticiones usan `rate_limited_get` (User-Agent
propio, 1 petición/s por dominio, reintentos). Los tests usan HTML y PDF sintéticos.

## 2. Caché SQLite (automática)

`data/horse_analytics.db` (cambiable con `HORSE_DB_PATH`). Guarda cada carrera analizada y
todo lo que se encuentre en el CSV o en internet, así no se repiten consultas.

## 3. CSV local de historial (recomendada)

Se carga desde la barra lateral de la app o con la variable `HORSE_CSV_PATH`.
`scraper.load_csv` acepta separador `,` o `;`, UTF-8 con o sin BOM, y estos nombres de
columna (sin importar mayúsculas ni acentos):

| Campo | Alias aceptados |
| --- | --- |
| `name` (obligatorio) | `horse`, `horse_name`, `caballo`, `ejemplar`, `nombre` |
| `birth_year` | `year_of_birth`, `foaled`, `año nacimiento`, `nacimiento` |
| `sex` | `sexo`, `gender` |
| `sire` / `dam` | `padre` / `madre` |
| `starts` (carreras) | `runs`, `races`, `carreras`, `salidas`, `corridas` |
| `wins` (victorias) | `victorias`, `ganadas`, `primeros` |

El resto de columnas se guarda tal cual y se muestra en el «Detalle por caballo».
`starts` y `wins` son las que usa el modelo.

**Ejemplo incluido:** `data/samples/historial_ejemplo.csv` contiene datos **ficticios**
de los caballos de la gaveta de ejemplo. No representa caballos reales.

### Kaggle (descarga manual)

Kaggle ofrece datasets gratuitos de carreras (requiere una cuenta gratuita). Por ejemplo,
buscar «horse racing» en <https://www.kaggle.com/datasets> devuelve conjuntos con resultados
por caballo (Hong Kong, Reino Unido, EE. UU.). Pasos:

1. Descargar el CSV desde la web de Kaggle (no se automatiza para no guardar credenciales).
2. Renombrar o agregar las columnas `name`, `starts` y `wins` si el dataset tiene un
   resultado por fila (hay que agregar por caballo: contar carreras y victorias).
3. Cargarlo en la barra lateral o con `HORSE_CSV_PATH=/ruta/al/archivo.csv`.

Revisar la licencia de cada dataset en su página antes de usarlo.

## 4. Fuente HTTP propia (opcional)

Con el modo offline desactivado y la variable `HORSE_DATA_URL` definida, el scraper pide
`HORSE_DATA_URL` reemplazando `{name}` por el nombre del caballo y espera JSON (un objeto o
una lista de objetos con los mismos campos que el CSV):

```bash
HORSE_DATA_URL="https://mi-servidor.example/caballos?nombre={name}"
```

Reglas que aplica `rate_limited_get`:

- User-Agent propio: `horse-analytics/0.1 (proyecto educativo; +https://github.com/Edmartinezzz/Sistema-Hipico)`.
- Máximo **1 petición por segundo por dominio**.
- Hasta 3 reintentos con espera exponencial (1, 2 y 4 s) ante errores de red, 429 o 5xx.
- Si la fuente falla o devuelve algo inesperado, el caballo queda como «sin datos» y el
  análisis continúa.

## 5. Fuentes evaluadas y no automatizadas

| Fuente | Estado | Motivo |
| --- | --- | --- |
| [rpscrape](https://github.com/joenano/rpscrape) | Referencia | Sirve de inspiración para la estructura del scraping (Racing Post, Reino Unido). Puede usarse por separado para generar un CSV e importarlo como en la sección 3. |
| Brisnet Past Performances gratuitas | No implementado | Requiere iniciar sesión. Si se agrega, las credenciales deben ir en variables de entorno (`BRISNET_USER`, `BRISNET_PASSWORD`), nunca en el código. |
| DRF Charts (últimos 7 días) | No implementado | Se publican como PDF y su formato no pudo verificarse; no se escribió un parser sin probarlo con documentos reales. |

Antes de automatizar cualquiera de ellas hay que revisar sus términos de uso y
`robots.txt`, y documentar aquí el dominio.
