# Fuentes de datos gratuitas

Todas las fuentes del sistema son gratuitas (presupuesto CERO). Este
documento lista cada fuente, cómo se usa y sus limitaciones.

## Fuente principal: gaceta semanal web (Desafío Hípico)

- Dominio: `www.desafiohipico.com` — publica gratis los datos oficiales
  del INH/HINAVA (La Rinconada y Hipódromo Nacional de Valencia).
- `robots.txt` (revisado el 09/11/2026) permite `/retrospectos` y
  `/revista/`; prohíbe `/api/`, `/admin/`, etc. El sistema **solo** usa
  las dos rutas permitidas.
- `/retrospectos`: lista de reuniones en el bloque JSON-LD
  (`SportsEvent` con `startDate` y URL). Cubre unos 2 meses recientes.
- `/revista/<id>`: página de la reunión; el JSON `initialData`
  incrustado (Next.js) trae carreras, inscritos, jinete, entrenador,
  kilos, puesto, retirados, estadística del año (`yearStats`), últimas
  actuaciones (`raceHistory`) y traqueos (`workouts`).
- **No publica cuotas**: el usuario las introduce a mano en el dashboard.
- Rate limiting: 1 petición/segundo vía `rate_limited_get`; cada reunión
  (~4 MB) se guarda en `data/cache/` para no repetir descargas.
- Si la estructura cambia, `GacetaWebError` muestra un error claro y la
  pestaña PDF sigue disponible.
- Implementación: `src/gaceta_web.py`.

### Videos y señal en vivo

- `videoUrl` (carrera y `raceHistory`) existe en el JSON pero llegaba
  vacío en todas las reuniones revisadas; si se llena, la app lo usa.
- La página `/en-vivo` de Desafío Hípico obtiene la señal del INH desde
  su `/api/` (prohibido por `robots.txt`), por lo que **no** se extrae:
  la app solo enlaza a la página.
- El usuario puede guardar enlaces (YouTube, MP4, Facebook...) o subir
  archivos; se reproducen desde su origen, sin retransmitir contenido.
- Enlaces oficiales verificados: `desafiohipico.com/en-vivo` y el canal
  de Telegram del INH (`t.me/s/INHOficial`).

Alternativas evaluadas (no usadas): `tricolorhipico.com` (bloquea
`/api/revista` en su `robots.txt`) y los PDFs de `pollamacaco.com`
(aptos para la pestaña PDF si se descargan a mano).

## Estrategia de enriquecimiento (orden)

`enrich_horse()` consulta en este orden y se detiene en el primer acierto:

1. **Caché SQLite** (`enrichment` en `data/hipico.db`) — instantáneo,
   sin red.
2. **CSVs locales** en `data/enrichment/*.csv` — descargas manuales.
3. **Scraping web** — solo si `offline=False` y hay credenciales
   configuradas.

Si ninguna fuente tiene datos, se registra un warning y se devuelve
`{"found": False, "source": None}`. **Nunca se inventan datos.**

## Fuentes documentadas

### 1. Kaggle (offline, manual)

Datasets públicos de carreras de caballos descargables con cuenta
gratuita de Kaggle:

- Buscar "horse racing" en https://www.kaggle.com/datasets — hay varios
  datasets de actuaciones históricas (HKJC, carreras UK/IRE).
- Descargar el CSV y colocarlo en `data/enrichment/`. El sistema busca
  una columna de nombre (`horse`, `horse_name`, `nombre`, `caballo`,
  `name`) y devuelve la fila completa como enriquecimiento.
- No se commitea ningún CSV al repositorio (ver `.gitignore`).

### 2. Brisnet Past Performances (gratis con registro)

- Requiere cuenta gratuita de Brisnet. Las credenciales se leen de las
  variables de entorno `BRISNET_USER` y `BRISNET_PASS`; **nunca
  hardcodeadas**.
- Dominio: `brisnet.com` — máximo 1 petición/segundo vía
  `rate_limited_get` (ver `src/scraper.py`).
- El punto de extensión de parseo vive en `scraper._scrape_fuente()`;
  si el sitio cambia o bloquea, devuelve `None` con warning sin romper
  el pipeline.

### 3. DRF Charts (últimos 7 días, gratis)

- Dominio: `drf.com` — resultados de los últimos 7 días accesibles sin
  suscripción.
- Misma política de rate limiting (1 req/s, User-Agent identificable,
  reintentos exponenciales).

### 4. Referencia: `rpscrape` (GitHub)

- Inspiración de estructura de scraping: https://github.com/ — buscar
  `rpscrape` (licencia abierta). No se usa su código, solo su patrón de
  caché + backoff.

## Política de scraping respetuoso

- `time.sleep(1)` entre peticiones (máx 1 req/segundo por dominio).
- User-Agent identificable: `SistemaHipico/<versión>`.
- Reintentos exponenciales: 1s, 2s, 4s (máx 3 intentos).
- Manejo de errores HTTP: fallos 5xx reintentan; otros códigos devuelven
  la respuesta para que el llamador decida.
- Degradación elegante: un sitio caído o cambiado nunca rompe el
  pipeline; se loguea el warning y se continúa con `None`.

## Prohibido

- APIs de pago (Equibase API, DRF API premium, The Jockey Club API,
  RapidAPI premium, etc.).
- Commitear PDFs reales con datos personales o copyright.
- Datasets >200 MB o binarios pesados en el repo.
