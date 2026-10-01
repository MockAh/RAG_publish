# 04 · Registro de consideraciones — Expertos + Síntesis

> Compañero del plan de micro-tareas (`04-PLAN-MICROTAREAS-EXPERTOS.md`).
> Recoge hallazgos, deuda aceptada y herencias entre micro-tareas.
> Estado: **fase en curso** · N0–N6 firmadas.

---

## A · Hallazgos de datos reales

### A1 · Un paquete nuevo con prefijo de Settings propio rompe a los paquetes anteriores
**Descubierto en:** N1 (al añadir las claves `EXPERTOS_*` al `.env`).
**Qué:** `excavador/config.py` no llevaba `extra="ignore"` en su `SettingsConfigDict`.
Pydantic-settings lee el archivo entero, así que las claves de otro paquete se volvieron
campos prohibidos y `ValidationError` reventaba **cualquier** comando de la CLI del
Excavador. `biblioteca/` ya estaba inmunizado desde A11 de fase 03; `excavador/` no.
**Fix:** `extra="ignore"` en `excavador/config.py` (cambio justificado a módulo firmado,
precedente B2/B5 de fase 02) + `monkeypatch.chdir(tmp_path)` en los tres tests que
heredaban el `.env` real (regla F4 de fase 02).
**Regla general:** todo `.env` compartido por varios paquetes exige `extra="ignore"` en
todos ellos. Al crear un paquete nuevo con prefijo propio, verificar los anteriores.

### A2 · CRLF del `.env` viajando hasta la URL de la API
**Descubierto en:** N1.
**Qué:** el `.env` editado desde Windows dejó `\r` al final de cada valor.
`EXPERTOS_MODEL_LABEL` valía `'gemini-2.5-flash\r'` y ese retorno de carro llegó intacto
hasta la URL de la petición. Síntoma: **404 de modelo inexistente** — un error que invita
a culpar al modelo y a cambiarlo, en vez de mirar el valor.
**Fix:** `.gitattributes` con `* text=auto eol=lf` + validador `@field_validator(...,
mode="before")` que hace `.strip()` sobre `gemini_api_key`, `model_synthesis` y
`model_label`, con test de regresión que pasa un `.env` con CRLF.
**Familia:** es F5 de fase 02 (numpy hasta SQLite como BLOB) con otro disfraz: un valor
cruza una frontera sin que nadie lo inspeccione, y el fallo aparece lejos del origen.

### A3 · El entorno del shell pisa el `.env` y sobrevive a la edición del archivo
**Descubierto en:** N1.
**Qué:** un `set -a; source .env; set +a` ejecutado para un script de diagnóstico exportó
los valores de ese momento. Al corregir después el `.env`, las variables rancias seguían en
la sesión y pydantic-settings les da prioridad sobre el archivo. Resultado: test y script
leían `gemini-2.5-flash` mientras el `.env` ya decía `gemini-3.6-flash`, y la verificación
con `grep` sobre el archivo daba el visto bueno.
**Regla:** los scripts de diagnóstico construyen `Settings()` y no hacen `source .env`.
Si hiciera falta `source`, la terminal se cierra al terminar.
**Diagnóstico de un minuto:** `env | grep EXPERTOS_`.

### A4 · Los modelos Pro de Gemini son inaccesibles en el free tier
**Descubierto en:** N1 (sondeo de cuatro modelos con llamadas reales).
**Medido (2026-09-23):**

| Modelo | Resultado |
|---|---|
| `gemini-2.5-pro` | 404 — retirado para cuentas nuevas |
| `gemini-3.1-pro-preview` | 429 — cuota gratuita de Pro = 0 |
| `gemini-3.6-flash` | **OK** |
| `gemini-3.8-flash` | 503 — saturación transitoria, no rechazo |

**Qué significa:** `models.list()` devuelve el catálogo general, no lo que la key puede
invocar. **Listar no es poder llamar:** la única prueba válida es una llamada real.
**Decisión (X6″):** síntesis y etiquetado en `gemini-3.6-flash`. Su cuota de 1 500
peticiones diarias vuelve irrelevante el cálculo de RPD que se había hecho para Pro y
abarata Q1 (re-clusterizar y regenerar síntesis a voluntad).
**Escapes si N10 sale flojo:** activar los 10 USD mensuales de crédito de Cloud del plan
AI Pro (requiere proyecto GCP con facturación y alta en el Google Developer Program), o
reintentar `gemini-3.8-flash` cuando deje de dar 503.

### A5 · Tres papers sin abstract, resueltos por media de chunks re-normalizada
**Descubierto en:** N2 (construcción de `data/expert_vectors.npz`).
El corpus de N2 son los 158 papers indexados en Chroma, que tras colapsar los 3 alias de
DOI de A6 quedan en **155 papers únicos = 155 vectores**. De ellos, 152 usan
`título. abstract`; 3 (`doi:10.15174/rv.v17i33.756`,
`doi:10.22201/cisan.24487228e.2009.01.37`, `doi:10.22201/ffyl.29544270e.2024.46.2092`)
no tienen abstract en SQLite pese a estar indexados — se resuelven promediando los
embeddings de sus chunks (re-obtenidos vía `retrieve`, no leídos del store) y
renormalizando a norma 1, para no sesgar el clustering de N3 con vectores de menor
magnitud.

### A6 · Tres papers indexados dos veces por DOI-variante, colapsados en `vectors.py`
**Descubierto en:** N2 (revisión de las claves de `expert_vectors.npz`).
**Verificado (2026-09-23)** con `Storage.get_paper`: título, año y autores idénticos.

| Alias (descartado) | Canónico | Chunks alias / canónico |
|---|---|---|
| `doi:10.15332/25005375/5376` | `doi:10.15332/25005375.5376` | 1 / 26 |
| `doi:10.22201/ppla.24487988e.2016.6.58438` | `doi:10.22201/ppela.24487988e.2016.6.58438` | 1 / 1 (empate → alfabético) |
| `doi:10.37819/revhuman.v9i2.866` | `doi:10.37819/humanrev.v9i2.866` | 1 / 44 |

Son variantes de C5 (fase 02) que el dedup de esa fase no detectó, porque compara DOI
normalizado exacto, y llegaron indexadas dos veces a Chroma. La fase 04 las colapsa a
nivel de vector representativo (`DOI_ALIASES` + `canonicalize_paper_ids` en
`expertos/vectors.py`; canónico = más chunks en Chroma, empate → primero alfabético)
para no duplicar peso en el clustering.
**Deuda (E3):** la duplicación persiste en `excavador.db` y en Chroma; corregirla en
origen requiere reabrir fase 02/03 con causa documentada — no se hace en fase 04.
**Consecuencia pendiente para fase 05:** un mismo paper podría aparecer citado con dos
`chunk_id` de distinto `paper_id`; el Verificador o el Redactor deberían tratarlos como el
mismo paper (`DOI_ALIASES` es la fuente) si vuelve a aparecer.

### A7 · Silhouette plano en todo el barrido; la métrica solo sirve para descartar
**Descubierto en:** N3 (`data/cluster_sweep_report.md`, seed=42).
El silhouette (coseno) es plano (≤ 0.10) en todo el barrido k=5–12; HDBSCAN manda 80/155
a ruido. El corpus es monotemático y los subtemas se solapan de verdad, así que ninguna
métrica interna discrimina entre valores de k: las diferencias (0.096 en k=5 frente a
0.089 en k=9) están dentro del ruido. Es el mismo fenómeno de banda estrecha de A3
(fase 02) y A17 (fase 03), ahora en el espacio de papers.
**Consecuencia:** D1 se resuelve por inspección humana, como estaba previsto — la métrica
solo sirve para descartar. Descartados por la métrica: k ≥ 10 (aparecen clústeres de
1 paper) y HDBSCAN (>50 % del corpus a ruido, confirma X2). **Candidatos vivos para N4:
k=5, k=8, k=9.**

### A8 · k=9 elegido por inspección, no por métrica
**Decidido en:** N4 (resuelve D1). Asignación persistida en `clusters`,
`run_id = kmeans-k9-seed42-98b2c308` (X5; el sufijo son los 8 primeros caracteres del
SHA-256 de `data/expert_vectors.npz`, que ata la partición a los vectores de entrada).
El silhouette no discrimina (A7); la decisión se tomó leyendo los 10 papers más cercanos
al centroide de cada clúster en k=5, 8 y 9 (`data/cluster_inspect_k{5,8,9}.md`).
**Razón decisiva:** k=5 fusiona en un clúster de 46 papers (un tercio del corpus) dos
líneas de recepción que k=9 separa legiblemente — la lectura marxista (C2: teoría
crítica, Lukács, *El capital*) y la filosofía de la cultura (C4: modernidad barroca). Un
Experto sobre 46 papers no podría escribir una síntesis con la que el Orquestador rutee.
k=8 y k=9 son casi idénticos; k=9 gana por mejor reparto (mayor clúster de 35 frente a
40) y ausencia de clústeres unitarios. Cinco clústeres son inequívocamente nombrables
(C6 valor de uso, C3 ethos barroco, C2 teoría crítica/marxismo, C4 modernidad barroca,
C5 Marx/Braudel); C1 (23) es heterogéneo y su etiqueta debe reflejarlo; C0 (6) es el
misceláneo previsto por X2.

### A9 · C7 (12 papers) es un volumen, no un tema
**Descubierto en:** N4.
Agrupa las 12 secciones de *Crítica e interpretación. Homenaje a Bolívar Echeverría*
(2011). El clustering aisló el material estructural tal como D1 de fase 02 confiaba.
**Consecuencia para N9:** su síntesis será delgada y su Experto debería declarar
`confidence="low"` con frecuencia. No es fallo.

### A10 · Cuota real del free tier: 5 RPM y 20 peticiones/día por modelo
**Descubierto en:** N5 (primera corrida real del etiquetado, 2026-09-26).
Los 429 de `gemini-3.6-flash` traen la cuota en el cuerpo del error:
`GenerateRequestsPerMinutePerProjectPerModel-FreeTier` = **5** y
`GenerateRequestsPerDayPerProjectPerModel-FreeTier` = **20**. `.env` tenía
`EXPERTOS_LLM_RPM_LABEL=10` y `EXPERTOS_LLM_RPM_SYNTHESIS=10`, así que el rate limiter
propio dejaba pasar el doble de lo permitido (tenacity absorbió los 429, pero cada uno
es un intento perdido). Los 503 «high demand» del modelo también se reintentan: ese día
hubo 35 intentos registrados en `llm_calls` para 14 éxitos, y la cuota diaria se agotó.
**Corregido:** `EXPERTOS_LLM_RPM_LABEL=5` y `EXPERTOS_LLM_RPM_SYNTHESIS=5` en `.env`.
**Consecuencia para N9:** síntesis y etiquetado usan el mismo modelo, así que comparten
las **20 peticiones diarias**. La síntesis de X3 (8–12 sub-consultas + redacción de
claims, por clúster) no cabe en 20 llamadas/día para 8–9 Expertos, ni siquiera
repartida entre varios días sin reintentos. Antes de N9 hay que decidir el escape de
X6″ (créditos de Cloud) y medir D2 con esa decisión tomada. Hasta entonces, cada
llamada real se presupuesta: el test slow de N5 cuesta 9.
**Actualización (2026-09-27): los 503 cuentan contra la cuota diaria.** Reconstruido
desde `llm_calls` (26/09): el primer 429 con `limit: 20` es el id 26, precedido de solo
13 éxitos — si contaran únicamente los éxitos, ese 429 no se explica; contando éxitos y
503 juntos, el id 26 es la petición 22. Los 429 con `limit: 5` son del límite por
minuto, no del diario. El contador de Google es aproximado (el id 27 pasó después del
primer 429 diario), así que no conviene apurar el margen.
**Rendimiento medido:** el 27/09 se gastaron 7 peticiones (ids 38–44) para 3 etiquetas,
2 de ellas conservadas (C1 y C8; la de C0 fusionado se descartó, A11); C8 necesitó 4
intentos por saturación. Con 503 frecuentes, las 20 diarias rinden en la práctica 6–8
llamadas útiles, no 20.
**Consecuencia para N9, revisada:** el diseño de X3 (8–12 sub-consultas por clúster × 9
clústeres) es inviable incluso holgadamente en el free tier — no es cuestión de repartir
la corrida en varios días. La decisión de X6″ (créditos de Cloud, o rediseñar N7/N8
para gastar una sola llamada por clúster) hay que tomarla **antes de N7, no antes de
N9**.

### A11 · La fusión C8→C0 se probó y se revirtió, con evidencia
**Decidido en:** N5 (2026-09-27).
Ante `coherent=False` en C8 (5 papers), se generó una partición derivada C0+C8
(`kmeans-k9-seed42-98b2c308+merge-C8-C0`) y se etiquetó para comparar. Resultado: la
etiqueta fusionada («Crítica de la modernidad y lecturas desde América Latina») es más
paraguas que la de C0 solo, y su `note` pierde el hilo propio de C0 (razón burguesa,
eurocentrismo, límites de la secularización), sustituido por el núcleo Quijano que
aportaba C8. La fusión no gana nitidez: transfiere dispersión. Además la etiqueta
resultante se solapa con C1, C2 y C4, lo que la vuelve inútil para rutear.
**Decisión:** 9 clústeres, partición `kmeans-k9-seed42-98b2c308`. La corrida derivada se
borró de `clusters` y sus etiquetas de `data/cluster_labels.json`. C8 queda como
clúster pequeño y heterogéneo con etiqueta honesta: **4 papers efectivos** tras la
stoplist de E4 (5 en la partición), re-etiquetado sin el paper excluido como «Lecturas
comparadas sobre modernidad latinoamericana y existencialismo» (`coherent=False`). Su
Experto declarará `confidence="low"` a menudo, como C7 (A9). El código
`merge_clusters` y su CLI se conservan para ingestas futuras: se descarta esta fusión
concreta, no la herramienta.
**Método:** la alternativa se decidió comparando dos etiquetas reales, no razonando
sobre la partición. Costó 2 peticiones (1 etiqueta + 1 reintento por 503) y evitó una
decisión estructural tomada a ojo.

### A12 · El test slow de N5 no era reanudable y `llm_calls` no decía qué clúster falló
**Descubierto en:** N5 (primera corrida del test slow, 2026-09-30).
`pytest -m slow -k test_real_labeling_of_9_clusters` gastó 9 peticiones (ids 45–53,
08:24–08:26 UTC): 2 éxitos y 7 × 503, y falló con `ServerError 503` en el tercer
clúster tras agotar los reintentos. Dos pérdidas: (1) el test no pasaba `labels_path`,
así que las 2 etiquetas obtenidas se perdieron con la excepción, y relanzar habría
costado otra vez las 9; (2) `llm_calls` no registraba para qué era cada llamada, así
que no se podía saber qué clústeres habían fallado.
**Corregido:**
- `llm_calls` gana la columna `context` (JSON, genérica: N7–N9 la necesitarán para
  sub-consultas y claims). `GeminiClient.complete_json(..., context=...)` la escribe en
  cada intento. Las tablas existentes se migran con `ALTER TABLE` al crear el cliente;
  las filas anteriores quedan en `NULL`. **Toca `expertos/llm.py`, firmado en N1:** el
  cambio es aditivo (parámetro opcional, columna nueva) y los tests de N1 siguen verdes
  sin tocarlos.
- `label_cluster` envía `{"task": "label", "run_id", "expert_id"}`.
- `label_all_clusters(..., skip_existing=True)` (exige `labels_path`) omite los
  clústeres ya guardados para ese `run_id`.
- El test slow guarda en `data/cluster_labels_slowtest.json` (fuera de git, como todo
  `data/`) con `skip_existing=True` y verifica las 9 etiquetas leyendo el archivo, así
  que valen las de corridas anteriores. Relanzar cuesta solo los clústeres que faltan.
  Para empezar de cero, borrar ese archivo.
**Diagnóstico tras un fallo:** `SELECT id, ok, json_extract(context, '$.expert_id'),
substr(error, 1, 60) FROM llm_calls WHERE ts > '<fecha>' ORDER BY id;`
**Segundo intento (2026-09-30), y salida:** ya reanudable, el test volvió a caer por 503.
Entre los dos intentos del día, 17 peticiones a Gemini (ids 45–61) para 3 etiquetas
útiles. Con esa tasa, ni el test slow de N5 cabe con holgura en la cuota diaria, y X3
(N7–N9) queda descartado en Gemini free tier (A10). → **Decisión X6‴.**

**Decisión X6‴ (2026-09-30): síntesis y etiquetado pasan a DeepSeek.** Sustituye a X6″
para esas dos tareas. Gemini no se retira: queda como proveedor alternativo para D11
(Verificador de fase 05 con proveedor distinto al del Redactor).
- **Código:** `DeepSeekClient` en `expertos/llm.py` (API compatible con OpenAI, `httpx`
  directo, sin el SDK `openai`, cuyos reintentos propios se sumarían a los de tenacity
  sin quedar en `llm_calls`). DeepSeek solo ofrece `response_format=json_object`, sin
  schema nativo: el JSON Schema viaja en el prompt de sistema y la validación sigue
  siendo `model_validate_json`. Base común `_LoggedLLMClient` con `GeminiClient`
  (rate limit, reintentos ante 429/5xx/timeout, fila en `llm_calls` por intento).
  `make_client(task, settings)` elige proveedor según `EXPERTOS_LLM_PROVIDER`.
- **Settings:** `EXPERTOS_LLM_PROVIDER=deepseek`, `EXPERTOS_DEEPSEEK_API_KEY`,
  `EXPERTOS_DEEPSEEK_MODEL=deepseek-flash`. Con `deepseek`, faltar clave o modelo es
  error de arranque, no un 401 a mitad de corrida.
- **Sondeo (2026-10-01), desde la raíz del repo:** `GET /models` → `deepseek-flash`
  (DeepSeek-V4.1-Flash, contexto 1 048 576) y `deepseek-v4-pro`. Llamada de humo real con
  schema trivial → OK en 1,2 s (`llm_calls` id 62). Límites: las docs no declaran RPM ni
  cuota diaria, solo concurrencia; prepago, **402 = sin saldo**. `GET /user/balance` no
  trae cabeceras de rate limit: no verificado bajo carga.
- **Tests:** `tests/expertos/test_expertos_llm_deepseek.py` (28, `pytest-httpx`): JSON
  válido, inválido y vacío → `LLMOutputError` sin reintento; 429/5xx/timeout
  reintentados; 400/401/402/422 sin reintento y con el cuerpo en `llm_calls.error`;
  rate limit; `provider`/`context` en cada fila; `make_client` y validación de Settings.
- **Coste medido:** ver A13.

### A13 · El campo `coherent` no es reproducible entre proveedores
**Descubierto en:** N5 (test slow con DeepSeek, 2026-10-01, `llm_calls` ids 63–71).
Con el mismo prompt y los mismos papers, Gemini (`data/cluster_labels.json`) y DeepSeek
(`data/cluster_labels_slowtest.json`) discrepan en `coherent` en **4 de 9 clústeres**, en
ambas direcciones:

| Clúster | Gemini | DeepSeek |
|---|---|---|
| C0 | True | False |
| C1 | False | **True** |
| C5 | True | False |
| C7 | True | False |

En C1, DeepSeek marca `coherent=True` mientras su propia `note` enumera las piezas que
no encajan (dos notas informativas y un estudio bibliométrico): **inconsistencia
interna, no criterio distinto.**
**Consecuencia para N12 y fase 05:** la `confidence` de C5 y el `stance` de C3 son
juicios del mismo tipo, así que hay que asumir la misma inestabilidad. No tratarlos
como veredictos firmes. N13 (preguntas trampa) debe medir si el proveedor elegido
reconoce que no sabe. Refuerza L1 (herencia de fase 03) y E4 de fase 03 con evidencia
propia: ni el score ni un único juicio del LLM son medida estable de confianza.
**Etiquetas de producción: las de Gemini** (`data/cluster_labels.json`, sin regenerar).
Ninguna de las 9 contiene «Echeverría» (cuatro de DeepSeek sí: C2, C5, C7, C8; el
apellido no discrimina porque lo comparte todo el corpus) y su `coherent` concuerda con
sus `note`. El JSON del test slow se conserva como material de comparación (fuera de
git, como todo `data/`). **DeepSeek queda como proveedor de síntesis por
disponibilidad, no por calidad de juicio medida.**
**Coste medido:** 9 etiquetas = **22 805 tokens** (15 296 de entrada + 7 509 de
salida), 103 s, cero reintentos. Frente a Gemini: 17 peticiones para 3 etiquetas
útiles el 30/09 (A12). El saldo prepago no varió de forma visible (4,33 USD antes y
después).

---

## B · Deuda técnica aceptada

### B1 · `tests/expertos/` sin `__init__.py` obliga a nombres de test únicos
**Origen:** N1. Con `tests/test_config.py` ya existente, un `tests/expertos/test_config.py`
colisiona en la importación. Se resolvió renombrando a `test_expertos_config.py` y
`test_expertos_llm.py`.
**Por qué se acepta:** añadir `__init__.py` cambiaría la disposición de toda la suite.
**Convención de la fase:** todo test de `expertos/` se llama `test_expertos_*.py`.

### B2 · Títulos con HTML escapado
**Origen:** N4. Algunos títulos llegan con entidades HTML (`&lt;i&gt;`, prefijo
`doi:10.15381/`).
**Por qué se acepta:** es deuda menor de datos de origen; no se toca la base.
**Cómo se maneja:** aplicar `html.unescape` al mostrar títulos en el etiquetado (N5) y en
la bibliografía (fase 05).

## C · Comportamientos deliberados que parecen bugs

- **C1 · `ExpertAnswer.gaps` es obligatorio aunque admita `None`** (N6). El contrato C5
  escribe `gaps: str | None` sin default; se transcribe literal. Omitir el campo es error
  de validación: el Experto tiene que pronunciarse sobre lo que su corpus no cubre (N13).
- **C2 · Un `Claim` con `supporting_chunks=[]` se rechaza** (N6), también dentro de
  `ExpertAnswer.evidence`. C3 no autoriza la lista vacía y D5 prohíbe afirmar sin
  `chunk_id`; X3: la claim inválida se descarta, no se repara.
- **C3 · `SynthesisMap` no está en el contrato** (N6). C4 define solo la entrada; el
  contenedor (`run_id`, `updated_at`, `entries`) es decisión de fase 04 y rechaza
  `expert_id` repetidos. Las entradas son C4 literal. A propagar a `01` en N14.
- **C4 · Las funciones de persistencia reciben la ruta como argumento keyword**
  (`synthesis_dir=`, `path=`), no leen `Settings` por dentro: mismo patrón que
  `save_labels` / `db_path`, y los tests no dependen del `.env`.

## D · Verificaciones pospuestas

- **D1 (→N4) ✅ resuelta en N4 (A8: k=9).** Elección de k. El silhouette será bajo por el carácter monotemático del
  corpus; manda la inspección humana de 3 clústeres, no la métrica.
- **D2 (→N9):** coste real de una regeneración completa. Se lee de `llm_calls`, no se estima.
- **D3 (→N10):** tasa de claims realmente sustentadas, con los fallos clasificados en
  *claim infiel* frente a *chunk roto* (E6 de fase 03).

## E · Cuestiones que tocan otras fases

- **E1 (→05):** D11 — el Verificador usa un proveedor distinto al del Redactor. El cliente
  agnóstico de N1 (X8) ya lo hace posible sin tocar código de agentes.
- **E2 (→05):** la tabla `llm_calls` es la base para responder la pregunta abierta de la
  spec 05 sobre presupuesto de llamadas por consulta.
- **E3 (→02/03, deuda no urgente):** 3 papers indexados por duplicado (DOI-variante no
  capturada por el dedup de fase 02). Colapsados en fase 04 a nivel de vector (A6);
  persisten como registros duplicados en `excavador.db` y `data/chroma`. Corregir si el
  volumen crece en una ingesta futura, o si aparecen más casos.
  **Ampliación (N4):** la inspección detectó cuatro grupos adicionales sospechosos que
  `DOI_ALIASES` no cubre: tres registros de *Modelos elementales…* (dos reseñas de 2013 y
  un tercero, `doi:10.26620/uniminuto.polisemia.9.15.2013.84-87`, 2015, también en
  C5), *Jornadas Braudelianas* (1994/2018), *Mestizaje cultural y ethos barroco* (2000/2001) y el par
  Quijano/Echeverría en castellano y catalán. No se verificaron ni se colapsaron, por tres
  razones: los pares año-divergente son la limitación ya documentada en C1/C2 de fase 02;
  las versiones idiomáticas son publicaciones distintas y legítimas; y fusionar por título
  es peligroso (el registro de fase 02 documenta dos reseñas distintas del mismo libro que
  deben seguir separadas). Además, cada grupo cae dentro de un mismo clúster, así que no
  distorsiona la partición — solo aporta algo de peso extra. Revisar solo si la tasa
  crece en una ingesta futura.
  Comprobado en `clusters` (`run_id = kmeans-k9-seed42-98b2c308`):

  | Grupo | IDs | Clúster |
  |---|---|---|
  | *Modelos elementales…* | `doi:10.18504/rl0203-005-2013`, `openalex:W2284838268`, `doi:10.26620/uniminuto.polisemia.9.15.2013.84-87` | C5 |
  | *Jornadas Braudelianas* | `openalex:W3110251602` (1994), `openalex:W2903663981` (2018) | C5 |
  | *Mestizaje cultural y ethos barroco* | `openalex:W2140093523` (2000), `openalex:W2516540948` (2001) | C3 |
  | Quijano/Echeverría ES/CA | `doi:10.1344/oxi.2013.i2.6382`, `openalex:W1524321516` | C8 |
- **E4 (→02/05, deuda con gatillo):** DOI cruzado en origen. `doi:10.1002/ajpa.22921`
  corresponde a *American Journal of Physical Anthropology* pero titula «Modos y usos del
  pensamiento de Bolívar Echeverría». En fase 05 la bibliografía imprimiría un DOI que
  resuelve a otro artículo — cita falsa por datos sucios, no por el Redactor.
  **Gatillo:** corregir esa fila a mano si el paper aparece en las síntesis. Revisar si
  hay más casos con un censo de DOI-prefijo frente a venue.
  **Actualización (N5):** el daño no se limita al DOI. El abstract almacenado también es
  del otro artículo (metilación de ADN en dientes), así que el vector representativo de
  N2 se construyó con un texto ajeno y **no representa nada real**; el paper cayó en C8.
  Lo detectó el propio LLM de etiquetado en la `note` de C8. **Resolución en fase 04:**
  excluido por stoplist (`EXCLUDED_PAPER_IDS` en `expertos/assignments.py`), aplicada al
  leer la partición (`load_corpus_assignment`), no al construir vectores: excluirlo en
  `vectors.py` cambiaría el hash de `expert_vectors.npz`, obligaría a re-clusterizar e
  invalidaría la inspección de N4 (A8). Su vector sigue entre los 155 que vio k-means
  (un punto de 155; efecto despreciable y confinado a C8). Corpus efectivo de fase 04:
  **154 papers**. La fila de `excavador.db` sigue sin tocar (fase 02 firmada).

## F · Higiene de proceso

- **F1 · Imprimir el valor efectivo antes de formular la hipótesis.** En N1, el síntoma
  «la API rechaza mi modelo» tuvo tres causas distintas en un día —un `\r`, un modelo
  retirado y una variable de entorno rancia— y ninguna estaba en la API. `repr()` del
  valor que el programa usa de verdad cuesta un segundo y las descarta todas.
- **F2 · `grep -c` devuelve 0 cuando no hay coincidencias**, así que encadenar con `&&`
  corta el comando siguiente en silencio. No encadenar verificaciones con `&&`.
- **F3 · Heredadas y vigentes:** `.venv` siempre; un commit y push por tarea firmada;
  frontera modelo→persistencia convierte a tipos nativos (F5 de fase 02); prueba manual
  desde la raíz del repo antes de firmar (A11 de fase 03).
- **F4 · Una conclusión de Copilot no es evidencia.** En N1 declaró «config issue, not a
  code bug» sobre el 404 y siguió adelante; la causa real era otra. Las afirmaciones
  causales se verifican a mano antes de aceptarlas.
- **F5 · Leer la salida antes de relanzar un comando que gasta cuota.** En N5 el test slow
  falló y se relanzó solo para ver el error, que ya estaba en la salida anterior; la
  segunda corrida quemó ~6 intentos más y agotó la cuota diaria (A10). Con llamadas
  LLM reales: redirigir la salida a un archivo y leerlo, o leer `llm_calls.error`, que ya
  guarda el mensaje completo — nunca repetir la llamada para diagnosticar.

---

## Estado de micro-tareas

| # | Tarea | Estado |
|---|---|---|
| N0 | Decisiones Q1–Q3, X1–X8 | ✅ 2026-09-19 |
| N1 | Bootstrap `expertos/` + cliente LLM | ✅ 2026-09-23 · commit a4564b0 · 194 tests · hallazgos A1–A4 |
| N2 | Vectores representativos | ✅ 2026-09-23 · `data/expert_vectors.npz` = 155 vectores (1024-d, norma 1; 158 indexados − 3 alias) · test slow OK · hallazgos A5–A6 |
| N3 | Barrido de clustering | ✅ 2026-09-26 · `data/cluster_sweep_report.md` (k-means k=5–12 + HDBSCAN, seed=42) · 206 tests (+7 slow) · test slow OK · hallazgo A7 |
| N4 | Inspección humana; elegir k | ✅ 2026-09-26 · k=9, seed=42, por inspección (A8) · `clusters` run_id `kmeans-k9-seed42-98b2c308` (155 filas) · 212 tests (+7 slow) · hallazgos A8–A9, B2, E4 |
| N5 | Etiquetado LLM | ✅ 2026-10-01 · `data/cluster_labels.json` (C0–C8, Gemini) · test slow OK con DeepSeek (9/9, 22 805 tokens) · 264 tests (+8 slow) · hallazgos A10–A13, decisión X6‴ |
| N6 | Modelos C3/C4/C5 | ✅ 2026-10-01 · `expertos/models.py` (campos 1:1 con C3/C4/C5, verificados también contra el documento de contratos) + `expertos/persistence.py` (escritura atómica) · 323 tests (+8 slow) · comportamientos deliberados C1–C4 (sección C) |
| N7 | Síntesis 1/2: sub-consultas | ⬜ |
| N8 | Síntesis 2/2: claims validadas | ⬜ |
| N9 | Corrida completa de síntesis | ⬜ |
| N10 | Muestreo de 10 claims | ⬜ |
| N11 | SynthesisMap | ⬜ |
| N12 | Modo consulta | ⬜ |
| N13 | Preguntas trampa | ⬜ |
| N14 | Cierre de fase | ⬜ |
