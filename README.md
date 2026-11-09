# Sistema Hípico — Análisis Estadístico de Caballos

Sistema en Python que descarga la gaceta hípica semanal de la web (La
Rinconada y Valencia) o lee un PDF de gaveta, extrae los datos de cada
caballo (inscritos, historial, traqueos), estima la probabilidad de
victoria por forma con el modelo estadístico de Harville y detecta
"value bets" cuando introduces las cuotas. Todo se presenta en un
dashboard web local (Streamlit).

**Presupuesto CERO**: solo librerías open-source y fuentes de datos
gratuitas. Sin APIs de pago.

## Requisitos

- Python 3.11+ (probado en 3.12)
- Git

## Instalación (<10 minutos)

```bash
git clone <url-del-repo>
cd Sistema-Hipico-main

# Crear y activar el entorno virtual
py -3.12 -m venv .venv          # Windows
# python3 -m venv .venv         # Linux/macOS

.venv\Scripts\activate          # Windows (cmd)
# .venv\Scripts\Activate.ps1    # Windows (PowerShell)
# source .venv/bin/activate     # Linux/macOS

pip install -r requirements.txt
```

## Uso

```bash
# (Opcional) generar una gaveta y un historial sintéticos de ejemplo
python scripts/generar_muestras.py
#  -> data/samples/gaveta_ejemplo.pdf
#  -> data/enrichment/historial_ejemplo.csv

streamlit run src/app.py
```

## Versión web (para el celular)

La app se publica gratis en **Streamlit Community Cloud** con un enlace
fijo (`https://<nombre>.streamlit.app`) que funciona desde cualquier
lugar, aunque tu PC esté apagada.

### 1. Subir el proyecto a GitHub (una sola vez, desde tu PC)

```bash
git config --global user.name "Tu Nombre"
git config --global user.email "tu-correo@ejemplo.com"
git commit -m "Sistema Hípico: gaceta web, modelo entrenado y laboratorio"
```

En github.com crea un repositorio nuevo **vacío** (puede ser privado),
por ejemplo `sistema-hipico`, y luego:

```bash
git remote add origin https://github.com/<tu-usuario>/sistema-hipico.git
git push -u origin feature/setup
```

En GitHub abre el Pull Request de `feature/setup` y mézclalo en `main`
(o, si el repositorio está vacío, elige `feature/setup` como base y
renómbrala a `main` en *Settings → Branches*).

### 2. Publicar la app

1. Entra en https://share.streamlit.io con tu cuenta de GitHub.
2. **Create app → Deploy a public app from GitHub**.
3. Repositorio: `sistema-hipico` · Rama: `main` · Archivo principal:
   `src/app.py`.
4. En **Advanced settings** elige Python **3.12**.
5. Pulsa **Deploy**. En unos minutos tendrás el enlace.

En el celular abre el enlace y usa **"Añadir a pantalla de inicio"**
para tenerla como una app. Si nadie la abre en varios días, la primera
carga tarda un poco (la nube la "despierta").

### Vista móvil

La app detecta sola si la abres desde un teléfono (por el User-Agent
del navegador) y cambia a una vista hecha para el celular: sin barra
lateral ni pestañas, con barra superior (Semana · PDF · Ajustes) y una
navegación fija abajo (**Resumen · Domingo · Carrera · En vivo · Lab ·
Chat**). Las
tarjetas van a pantalla completa y las cuotas se escriben en campos
apilados en vez de la tabla ancha del PC. Las tabletas y los PCs
reciben la vista de escritorio.

Para forzar una vista concreta añade `?vista=movil` o `?vista=pc` al
enlace (por ejemplo para probarla en el PC).

### Chat con IA (gratis, multi-proveedor)

La pestaña **Chat IA** (y la sección **Chat** en la vista móvil) permite
preguntar en lenguaje natural sobre la reunión cargada, los pronósticos,
los value bets y los resultados del laboratorio. El chat recibe un
resumen de todo el sistema como contexto.

Encadena varios proveedores gratuitos compatibles con OpenAI y **salta
solo al siguiente si uno llega a su límite o falla**:

| Proveedor | Variable | Cuota gratis aprox. |
|---|---|---|
| Google Gemini | `GEMINI_API_KEY` | ~1.500 preguntas/día (el más generoso) |
| GitHub Models | `GITHUB_TOKEN` | según el PAT de GitHub |
| NVIDIA NIM | `NVIDIA_API_KEY` | ~40 req/min |
| OpenRouter | `OPENROUTER_API_KEY` | ~50 preguntas/día (modelos `:free`) |
| Groq | `GROQ_API_KEY` | ~1.000 preguntas/día |
| Pollinations | — (sin key) | último recurso, puede ser lento |

Para conseguir una key: `aistudio.google.com` (Gemini), `github.com`
→ Settings → Tokens (GitHub Models), `build.nvidia.com`,
`openrouter.ai/keys` o `console.groq.com`.

**En local:** añade las keys en `.streamlit/secrets.toml` (ya está en
`.gitignore`) o como variables de entorno. Ejemplo:

```toml
GEMINI_API_KEY = "tu-key"
OPENROUTER_API_KEY = "sk-or-tu-key"
```

**En la nube:** en *share.streamlit.io → Manage app → Secrets* añade las
mismas variables. Sin ninguna key el chat funciona igual con
Pollinations, solo que más lento.

### Avisos por Telegram (gratis)

Desde la pestaña **Domingo** puedes enviar el pronóstico completo a tu
Telegram con un botón. Para configurarlo (una sola vez, ~5 minutos):

1. En Telegram habla con **@BotFather** → `/newbot` → elige nombre →
   copia el **token** que te da.
2. Escríbele a tu bot cualquier mensaje (así "te conoce").
3. Abre `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` y copia tu
   **chat_id** (el número dentro de `"chat":{"id": ...}`).
4. Guarda ambos en `.streamlit/secrets.toml` (local) o en *Secrets* de
   Streamlit Cloud:

```toml
TELEGRAM_BOT_TOKEN = "123456:ABC..."
TELEGRAM_CHAT_ID = "123456789"
```

El envío solo ocurre cuando pulsas el botón; la app nunca manda mensajes
sola.

### 3. Actualización automática cada semana

La tarea `.github/workflows/archivar.yml` corre sola el sábado y el
domingo por la noche (hora de Venezuela): guarda las reuniones nuevas en
`data/archivo/`, reentrena el modelo y actualiza el laboratorio. Para
ejecutarla a mano: GitHub → **Actions → Archivar reuniones y reentrenar
→ Run workflow**. Si GitHub no la deja subir cambios, activa
*Settings → Actions → General → Workflow permissions → Read and write*.

En la nube, los videos que guardes desde la app y la señal en vivo se
borran cuando la app se reinicia (el disco de Streamlit Cloud no es
permanente). El archivo histórico y el modelo **sí** se conservan porque
viven en GitHub.

### Elegir la gaceta

- **Semana**: elige en el calendario cualquier día de la semana (lunes a
  domingo). Si la semana no tiene reuniones publicadas, un botón te
  lleva a la última disponible.
- **Reunión**: Valencia (sábado) o La Rinconada (domingo). Se carga
  sola al elegirla: inscritos, jinetes, kilos, récord del año, últimas
  actuaciones y traqueos.
- **Subir PDF**: botón de respaldo para analizar una gaveta en PDF.

### Pestaña "Domingo" (modo pronóstico)

La pantalla lista para el día de carreras:

- Por cada carrera pendiente: **top 3 del modelo** con su probabilidad,
  probabilidad de quedar entre los 3 primeros, nivel de **confianza**
  (Alta/Media/Baja según el favorito y su margen), la **combinación
  sugerida para el 5y6** (el menor grupo de caballos que cubre ganador +
  segundo en cualquier orden, con su cobertura estimada) y la exacta más
  probable.
- **Actualizar retirados**: vuelve a descargar la reunión para reflejar
  los caballos retirados de última hora antes de que corra.
- **Compartir por WhatsApp**: abre WhatsApp con el pronóstico completo
  en texto, listo para enviar.
- **Enviar por Telegram**: manda el mismo texto a tu Telegram (requiere
  configurar el bot, ver abajo).

### Pestaña "Reunión"

Cabecera con hipódromo y fecha, indicadores (inscritos, retirados,
value bets y **efectividad del modelo**: cuántas veces su 1er pick ganó
en las carreras ya corridas) y una tarjeta por carrera con el podio del
modelo y el ganador real.

### Pestaña "Carrera"

- Botones 1 · 2 · 3 … para cambiar de carrera.
- Tarjeta por caballo con el color de su mantilla, barra de probabilidad
  y etiquetas (value bet, llegada). Botón **Ficha** abre una ventana con
  forma reciente (gráfico), últimas actuaciones, traqueos y el video de
  cualquier actuación anterior.
- Gráfico de probabilidad; si escribes las cuotas de **todos** los
  caballos ("Escribir cuotas…"), compara modelo vs. mercado y marca los
  value bets en dorado.
- **Video de la carrera**: se muestra si la web lo publica o si guardaste
  uno (enlace de YouTube/MP4/Facebook o archivo subido). Botón para
  buscar la carrera en YouTube. Puedes empezar la reproducción en un
  segundo concreto para analizar una parte.

### Pestaña "En vivo"

Próxima carrera de la reunión cargada con los picks del modelo, el
reproductor de la señal en vivo (pega el enlace de la transmisión una
vez y queda guardado) y accesos a las señales oficiales del INH.

### Pestaña "Laboratorio"

Mide al modelo con **validación cronológica**: para cada reunión se
entrena solo con las anteriores, como si fuera ese domingo. Muestra el %
de veces que el 1er pick ganó (y el ganador quedó en el top 3) para el
modelo entrenado, el modelo de forma original y el azar; la calibración
(si dice 30%, ¿gana ~30%?), el peso de cada factor y los resultados por
reunión.

### Cómo calcula el modelo

**Modelo entrenado** (`src/modelo.py`, se usa si existe
`data/modelo.json`): logit condicional, la generalización de Harville.
Cada caballo tiene una fuerza `exp(w · x)` con 10 factores estandarizados
dentro de su carrera: forma del año, segundos perdidos frente al ganador
(tiempos en quintos), llegadas recientes, efectividad de jinete y de
entrenador (solo con fechas previas), distancia conocida, días de
descanso, debutante, cambio de kilos y puesto de salida. Los pesos `w`
se aprenden con los ganadores reales del archivo. La ficha de cada
caballo explica qué factores lo favorecen o perjudican.

**Modelo de forma** (respaldo, y para PDFs): fuerza =
`(victorias_año + 1) / (carreras_año + 2)` ×
`exp(−0.1 × cuerpos_perdidos_promedio)`.

**Resultados honestos (sep–nov 2026, 86 carreras evaluadas):** el 1er
pick ganó 31% con el modelo entrenado, 28% con el de forma y 13% al
azar; el ganador quedó entre los 3 primeros picks ~62% de las veces. Con
tan pocas carreras la diferencia entre ambos modelos es pequeña y puede
ser casualidad: se irá aclarando a medida que el archivo crezca.

## Estructura

```
src/
  pdf_extractor.py   # Módulo 1: PDF -> datos estructurados
  scraper.py         # Módulo 2: enriquecimiento web gratuito + caché
  harville_model.py  # Módulo 3: probabilidades Harville + value bets
  database.py        # Módulo 4: capa SQLite (stdlib)
  app.py             # Módulo 5: dashboard Streamlit
  gaceta_web.py      # Módulo 6: gaceta semanal desde la web (sin PDF)
  analisis.py        # Módulo 7: análisis por carrera (forma + cuotas)
  videos.py          # Módulo 8: videos de carreras y señal en vivo
  ui.py              # componentes visuales (tarjetas, mantillas, gráficos)
  archivo.py         # Módulo 9: archivo histórico propio (data/archivo)
  modelo.py          # Módulo 10: modelo entrenado (logit condicional)
  laboratorio.py     # Módulo 11: evaluación cronológica del modelo
  ocr_gaceta.py      # Módulo 12: cuotas ML desde gacetas escaneadas (OCR)
scripts/archivar.py  # archiva reuniones nuevas y reentrena (--entrenar)
.github/workflows/   # tarea semanal de archivo + tests en cada PR
.streamlit/config.toml  # tema visual (oscuro verde y dorado)
tests/               # suite pytest (PDFs sintéticos con reportlab)
data/                # datos locales; archivo/, modelo.json y laboratorio.json sí van a git
docs/fuentes_datos.md  # documentación de fuentes gratuitas
```

## Tests

```bash
pytest
```

Los tests generan un PDF de gaveta sintético con `reportlab` y simulan
respuestas HTTP con `responses`; no necesitan archivos externos ni red.

## Gacetas escaneadas (CamScanner / WhatsApp): cuotas ML automáticas

Las gacetas que circulan como fotos no tienen texto. Al subirlas en
**Subir PDF**, el sistema usa OCR (`rapidocr_onnxruntime`, se instala con
`requirements.txt`, sin Tesseract) para leer solo lo que la web no
publica: **la cuota de la línea de la mañana (ML)** de cada caballo.

1. Detecta en cada página el número de carrera y la fecha
   (salta portada, estadísticas y traqueos).
2. Carga la reunión de esa fecha desde la web o el archivo.
3. Reconoce los nombres de los ejemplares y pone su cuota ML
   (`3/2` → 2.50) en cada carrera. Con todas las cuotas de una carrera
   aparecen la probabilidad de mercado y los **value bets**.

Prueba real (Gaceta Hípica, La Rinconada 08/11/2026, 17 páginas): 127
de 129 cuotas leídas; tarda **unos 7 minutos** en un PC normal (~20 s
por página de carrera). Las que no se lean se indican para escribirlas a
mano. Si el PDF no trae alguna carrera, esa queda sin cuotas.

El resultado del OCR se guarda en `data/ocr_cache/` (por huella del
archivo): si vuelves a subir **el mismo PDF** las cuotas aparecen al
instante, sin repetir los ~7 minutos de lectura.

En Streamlit Cloud `packages.txt` instala las librerías del sistema que
necesita el OCR (`libgl1`, `libglib2.0-0`).

## Credenciales opcionales

Ninguna credencial se hardcodea. Si tienes cuenta gratuita de Brisnet
Past Performances, exporta las variables:

```bash
# Windows (cmd)
set BRISNET_USER=tu_usuario
set BRISNET_PASS=tu_password

# Linux/macOS
export BRISNET_USER=tu_usuario
export BRISNET_PASS=tu_password
```

Sin credenciales, el sistema opera en modo offline (SQLite + CSVs).

## Datos locales

- `data/hipico.db` — base SQLite que se crea al ejecutar la app.
- `data/enrichment/*.csv` — CSVs de enriquecimiento manual (ver
  `docs/fuentes_datos.md` para datasets de Kaggle descargables).
- `data/samples/` — PDFs de muestra generados.
- `data/cache/` — reuniones descargadas de la web (cada una pesa varios
  MB; las terminadas no se vuelven a descargar, las pendientes se
  refrescan cada hora). Puedes borrar esta carpeta sin problema.
- `data/videos/` — videos que subas desde la app (no se suben a git).
- `data/ocr_cache/` — cuotas OCR ya leídas por PDF (no se suben a git).
- `data/archivo/*.json.gz` — archivo histórico propio (~20 KB por
  reunión; **sí** se sube a git). Crece cada semana.
- `data/modelo.json` y `data/laboratorio.json` — pesos del modelo y
  última evaluación. Regenerar a mano con
  `python scripts/archivar.py --entrenar`.

## Limitaciones conocidas

- La gaceta web depende de Desafío Hípico: solo publica unos 2 meses de
  reuniones hacia atrás, y si cambian su página el sistema mostrará un
  error claro (usa la pestaña PDF como respaldo).
- La web no publica cuotas (en Venezuela salen de la taquilla el día de
  la carrera): hay que escribirlas a mano para obtener value bets.
- Videos: la web trae el campo `videoUrl` pero hoy llega vacío, y el
  canal de YouTube del INH desapareció en abril de 2026. Por eso los
  videos y la señal en vivo se añaden con un enlace o archivo propio.
- El modelo aún no usa los traqueos (parciales de los ejercicios) ni la
  categoría de la carrera; y con solo ~2 meses de datos su ventaja sobre
  el modelo de forma no está demostrada todavía.
- Ningún modelo garantiza ganadores: en el mejor caso acertará el
  ganador una de cada tres carreras.
- La extracción de PDF depende del formato de la gaveta: columnas no
  reconocidas se guardan como `extra_<idx>`.
- Uso informativo: no constituye recomendación de apuesta.
- El scraping real está diseñado para degradar elegantemente; sin
  credenciales opera solo con datos locales.
