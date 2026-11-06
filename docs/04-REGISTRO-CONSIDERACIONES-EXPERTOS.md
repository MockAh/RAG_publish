# 04 · Registro de consideraciones — Expertos + Síntesis

> Compañero del plan de micro-tareas (`04-PLAN-MICROTAREAS-EXPERTOS.md`).
> Recoge hallazgos, deuda aceptada y herencias entre micro-tareas.
> Estado: **FASE 04 CERRADA (2026-11-05)** · N0–N14 firmadas. Este registro pasa a ser referencia
> histórica y herencia para la fase 05 (resumen en `04-HERENCIA-PARA-FASE-05.md`).
> Resultado final: 9 Expertos sobre 154 papers, 128 claims, mapa de ~1 453 tokens, 431 tests.

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

### A14 · L1 confirmado por el otro lado: hay evidencia válida por debajo de 0.83

**Descubierto en:** N7 (corrida real de los 9 clústeres, 2026-10-03). **Evidencia propia de
fase 04, no heredada.** L1 (fase 03) mostró que el ruido puntúa *dentro* de la banda
0.83–0.90. N7 muestra lo simétrico: material bueno puntúa *por debajo*. En C3 los
candidatos van de 0.805 a 0.888, y **17 de 46 quedan bajo 0.83**. Leídos uno a uno, los 17
son pertinentes. Entre ellos está el texto más valioso del clúster para N8: la crítica
explícita de Carlos Espinosa (*Íconos* 43, 2012, `doi:10.17141/iconos.43.2012.349`) a la
tesis del barroco como predominio de la «forma natural» («subsisten tres problemas de
fondo…», 0.813–0.829), recuperada por tema y no por postura (confirma L2 también).
Los dos de 0.805 (la conclusión de Espinosa y el mestizo colonial en
`doi:10.15332/25005375.5376`) también son pertinentes.
El fenómeno no es exclusivo de C3. Candidatos bajo 0.83 por clúster: C0 7/29, C1 2/62,
C2 8/63, C3 17/46, C4 5/63, C5 6/30, C6 3/76, C7 2/11, C8 10/20 (mínimo global 0.765, C8).
Solo se leyeron los de C3.
**Consecuencia:** un umbral en 0.83 habría descartado evidencia válida, incluida la
única crítica sustantiva del clúster. Ningún filtro por score en N7 ni en N8 (C6).

### A15 · Los papers que el retrieval no alcanza son casi todos de solo abstract

**Descubierto en:** N7 (mismo día). Con 8–12 sub-consultas × `top_k=8`, el retrieval cubre
**116 de 154 papers**. De los **38 no cubiertos, 35 solo tienen un chunk `from_abstract`**
(sin PDF indexado). Verificado contra los metadatos de Chroma.

| Clúster | Papers cubiertos | No cubiertos | De ellos, solo abstract |
|---|---|---|---|
| C0 | 6/6 | 0 | — |
| C1 | 16/23 | 7 | 6 |
| C2 | 22/35 | 13 | 13 |
| C3 | 10/12 | 2 | 2 |
| C4 | 21/32 | 11 | 10 |
| C5 | 11/12 | 1 | 1 |
| C6 | 15/18 | 3 | 2 |
| C7 | 11/12 | 1 | 1 |
| C8 | 4/4 | 0 | — |

Las 3 excepciones tienen PDF y aun así no salieron:
`doi:10.29166/economia.v70i111.1393` (C1, 130 chunks),
`doi:10.22201/ffyl.29544270e.2024.46.2092` (C4, 10) y `doi:10.32719/13900102.2024.56.9`
(C6, 45). La cobertura no excluye por sistema el material de abstract: 64 de los 116
cubiertos también son de solo abstract, y C7 —un volumen sin PDFs, A9— sale entero de
abstracts. El mecanismo plausible es la competencia por los 8 puestos de cada consulta: un paper
con un único chunk tiene un solo boleto, y uno con PDF tiene decenas.
**Verificado para las 3 excepciones con PDF (2026-10-03, sin LLM): es competencia, no
exclusión.** Su `paper_id` en `clusters` coincide byte a byte con el de Chroma (sin
variantes de mayúsculas, prefijo ni espacios), está en la lista de `filter_paper_ids` y
`has_paper` es `True`. Relanzando las sub-consultas guardadas de cada clúster con
`top_k=50`, los tres aparecen, aunque en pocas consultas y lejos del corte del puesto 8:

| Paper | Clúster | Consultas que lo traen en top 50 | Mejor puesto | Score / corte #8 |
|---|---|---|---|---|
| `doi:10.29166/economia.v70i111.1393` (*El capital. Crítica de la economía política*, 2018) | C1 | 2/11 | 33 | 0.827 / 0.843 |
| `doi:10.22201/ffyl.29544270e.2024.46.2092` (reseña de *Modernidad barroca y capitalismo*) | C4 | 3/12 | 23 | 0.835 / 0.842 |
| `doi:10.32719/13900102.2024.56.9` (Echeverría y Benjamin sobre arte) | C6 | 4/12 | 20 | 0.824 / 0.846 |

El de C1 resultó ser obra primaria de Marx, no un estudio sobre Echeverría (A17), lo que
explica que casi ningún chunk puntúe con sub-consultas sobre Echeverría.
**Consecuencia para fase 05:** la síntesis de un Experto no habla por toda su partición.
Un paper de solo abstract es invisible para la síntesis salvo que una sub-consulta caiga
justo sobre su tema, así que el Redactor no puede asumir que «el Experto no lo menciona»
equivale a «el corpus no lo dice». Las palancas posibles (subir `top_k`, una consulta por
paper no cubierto) quedan para decidir en N8/N9. No se aplicó ninguna.

### A16 · El LLM devolvió 13 sub-consultas pidiéndole 8–12; el schema lo rechazó

**Descubierto en:** N7 (C2, `llm_calls` id 76). DeepSeek ignoró el máximo del prompt. El
validador de `SubQueries` lo rechazó (`LLMOutputError`, sin reintento automático), la CLI
siguió con los demás clústeres y señaló C2. Un reintento manual con `--expert-id C2`
(id 82) devolvió 12. Es el diseño de X3 funcionando: no se trunca ni se repara.
**Coste total de N7** (`context.task = "synthesis.subqueries"`, ids 72–82): 11 llamadas
(9 válidas de producción, 1 del test slow, 1 rechazada) = **27 567 tokens** (11 052 de
entrada + 16 515 de salida), 89 s. La salida varía mucho para listas de tamaño parecido,
de 711 (C1) a 3 459 tokens (C8). La causa no se ha verificado. Dato para D2.

### A17 · Obra primaria infiltrada: *El capital* de Marx, traducido por Echeverría

**Descubierto en:** N7 (verificación de A15, 2026-10-03, sin LLM: `papers` + `get_chunk`).
`doi:10.29166/economia.v70i111.1393` (C1, 130 chunks de PDF) **no es un estudio sobre
Echeverría: es el texto de Marx.** Es el capítulo I («La mercancía») del Libro I de *El
capital*. El chunk `#body-1#0` abre con «CAPÍTULO PRIMERO 1. LOS DOS FACTORES DE LA
MERCANCÍA…», y las secciones indexadas son las de ese capítulo («La forma del valor o el
valor de cambio», «El carácter fetiche que tiene la mercancía, y su secreto»…). El vínculo
con el corpus está solo en el abstract, que es una nota del editor: la *Revista Economía*
(2018, número de aniversario de Marx) republica la **traducción de Echeverría**, publicada
antes en *Anales* n.º 354 (1976) de la Universidad Central del Ecuador. Ninguno de los 130
chunks menciona a Echeverría.
**No lo podía detectar el Excavador:** los metadatos son legítimos y coherentes. El DOI
resuelve a esa pieza, `authors = ["Karl Marx"]` es correcto, `work_type = "article"`
describe bien la republicación en revista, y el abstract habla de Echeverría, así que el
filtro de relevancia acertó al admitirlo.
**No es candidato a exclusión automática** (a diferencia de E4, que tiene datos
corruptos): citarlo puede ser correcto, por ejemplo para la traducción de Echeverría o
para su lectura del valor de uso. Tampoco se excluye por score (L1, A14).
**Consecuencia para fase 05 (→E5):** el Redactor y el Verificador deben saber que un chunk
de este paper es **palabra de Marx, no de Echeverría ni de un comentarista**. La pieza dice
`work_type = "article"`, pero es un capítulo de un libro de otro autor; el traductor no
figura en `authors`. Atribuirle a Echeverría una tesis sacada de estos chunks sería una
cita infiel con un `chunk_id` válido, que la validación `supporting_chunks ⊆ recuperados`
de X3 no detecta. Revisar si hay más obra primaria (traducciones y ediciones de textos
de Echeverría o de otros) con un censo de `authors` que no contengan a ningún
comentarista. No se ha hecho.
**Dato de autoría (N8, censo previo, 2026-10-03, sin LLM):** de los 154 papers del corpus
efectivo, **solo 3 tienen «Echeverría» en `authors`, y uno es Julio Echeverría, no
Bolívar** (`openalex:W2485338004`, mesa del homenaje de 2011). Los otros dos son
`doi:10.2307/jj.39017669.8` (*La religión de los modernos*, con un solo chunk de abstract)
y `openalex:W1675963835` (una nota de prensa sobre un premio). Ninguno aporta texto de
PDF escrito por Echeverría. **Confirma E3 de fase 02 desde dentro: el corpus verificable
es recepción, no obra primaria.** Por eso la regla de atribución no puede apoyarse en la
autoría del sujeto. «Autor distinto de Echeverría» describe a 151 de 154 papers, y marcar
por ese criterio no distinguiría nada. La auditoría de N8 usa una lista explícita de obra
primaria conocida (`PRIMARY_WORKS`).
**Censo de obra primaria (N8, sin LLM).** Se revisaron los 154 papers con tres señales:
autor canónico (Marx, Benjamin, el propio Echeverría…), patrones en el título
(traducción, entrevista, edición, *El capital*…) y patrones en el abstract
(republicación, traducción, entrevista). Se leyeron los chunks de cada candidato fuerte.
Entran en `PRIMARY_WORKS` (`expertos/assignments.py`) cuatro papers cuyo texto indexado no
es de quien figura en `authors`:

| paper_id | Clúster | Qué es | Autor real del texto |
|---|---|---|---|
| `doi:10.29166/economia.v70i111.1393` | C1 | *El capital*, cap. I | Karl Marx (traducción de Echeverría) |
| `doi:10.22201/cisan.24487228e.2009.01.37` | C0 | Entrevista a Echeverría (2009); `authors` = los entrevistadores | Bolívar Echeverría (respuestas) |
| `doi:10.17141/iconos.17.2003.502` | C4 | Diálogo con Echeverría (2003); `authors` = los entrevistadores | Bolívar Echeverría (respuestas) |
| `openalex:W1675963835` | C1 | Nota de prensa sobre el premio por *Vuelta de siglo*; `authors` incluye a Echeverría y a un gobierno | Laura Romero (periodista) |

Las dos entrevistas son las **únicas piezas con palabras de Echeverría en PDF**. Por
`authors`, se le atribuirían a los entrevistadores y la regla de atribución las
descartaría como sustento de lo que piensa Echeverría. Por eso el `real_author` sustituye
a `authors` en el prompt de N8, y no solo marca el claim.
**Caso descartado que enseña algo: `doi:10.15517/revfil.2025.2132`** (Sigüenza, 2025). El
abstract anuncia que la pieza reproduce el discurso de Echeverría como profesor emérito
(2009). Pero los 29 chunks indexados son solo la conferencia de Sigüenza y la nota del
director: el discurso no llegó al índice. **El abstract describe el artículo publicado, no
lo que GROBID extrajo.** Una decisión sobre qué texto contiene un paper se toma leyendo
sus chunks, nunca el abstract.
**Límite del censo:** es heurístico. Una obra primaria sin marcas en el título, el
abstract ni `authors` se escaparía. La búsqueda de «traducción de Bolívar Echeverría» en
el texto de todos los chunks dio cero resultados, pero no es exhaustiva. Si N10 encuentra
otra, se añade a `PRIMARY_WORKS`.

### A18 · El razonamiento cuenta como salida: 8 192 tokens no bastan para un borrador

**Descubierto en:** N8 (primer borrador real, C8, `llm_calls` id 83). Con
`max_tokens=8192`, DeepSeek cortó la respuesta (`finish_reason=length`) a los 33 s. Con
32 768, el mismo borrador gastó **10 274 tokens de salida** (id 84) para unas ~1 500
palabras de JSON. El razonamiento (`reasoning_content`) cuenta dentro de `max_tokens`, igual
que en las sub-consultas de N7 (C8: 3 459 tokens para 12 frases).
**Cambios:** `deepseek_max_tokens_synthesis = 32768` (etiquetado sigue en 4 096). Un
`finish_reason=length` levanta ahora `LLMOutputError` con el desglose (`prompt_tokens`,
`completion_tokens`, `reasoning_tokens`, longitudes del contenido y del razonamiento), y ese
mensaje queda en `llm_calls.error`. Antes habría sido un «JSON inválido» sin causa visible.
El límite de 384K de salida de la serie V4 viene de fuentes de terceros, no de la
documentación oficial; no se ha probado por encima de 32 768.

### A19 · `stance` no se poblaba porque el prompt lo impedía, no porque el modelo no viera la crítica

**Descubierto en:** N8 (comparación de modelos en C8 y C3, 2026-10-03, `llm_calls` ids 85–88).
**Medido: 0 `contradicts` y 0 `mentions` en 56 claims**, con los dos modelos (C8: 14 de flash
y 13 de v4-pro; C3: 15 y 14). El material crítico se había recuperado bien por tema: 15
pasajes de Espinosa (*Íconos* 43, 2012) entre los candidatos de C3, incluida su crítica a la
tesis de la «forma natural» (A14). Es decir, **L2/X4 funcionaba**. Los modelos sí leían la
crítica: v4-pro la recogió en tres claims (#27, #29, #38) y flash en uno (#27). Pero la
regla de atribución de A17 («nombra a quién atribuyes cada tesis») la convertía en «Espinosa
critica la tesis de Echeverría…» con `supports`. Eso es correcto, porque el pasaje sí
respalda que Espinosa critica, pero hace `contradicts` **inalcanzable por construcción**: un
pasaje de X siempre respalda «X dice Y». El prompt solo *permitía* la vía alternativa, y
ningún modelo la tomó.
**Corrección:** la regla «Tesis discutidas» es ahora obligatoria. Cuando un pasaje discute
una tesis, el borrador emite **dos claims con el mismo texto de tesis**: uno cita los pasajes
que la exponen (`supports`) y el otro los que la discuten (`contradicts`). Ambos atribuyen la
tesis a quien la sostiene y nombran entre paréntesis a los autores de los pasajes citados.
El disenso va en `stance`, no en la frase; «X critica Y» con `supports` queda prohibido.
**Validado** (C3, v4-pro, id 89): #27 y #29 salen como `contradicts` frente a «Echeverría
sostiene que el barroco privilegió la "forma natural" de la vida…» (supports: #3, #5, #15),
y #38 como `contradicts` frente a la tesis del mestizaje intrínseco al barroco (supports:
#37 y Artunduaga #11). Resultado: 12 claims, 10 `supports` y 2 `contradicts`.
**Fuga residual:** el claim 12 (Carrión, «dimensiones que no habrían sido suficientemente
consideradas por Echeverría») sigue llevando el disenso en la frase, con `supports`.
`mentions` sigue en 0. Se revisará en N10.
**Coste de la corrección:** 20 972 tokens de salida y 191 s, frente a 14 820 y 131 s con el
prompt anterior. Cabe en `max_tokens=32768` (A18), pero el margen se ha reducido.
**Matiz (N10, A24):** la corrección explica el cero en `contradicts`, pero no el cero en
`mentions`. Las tres candidatas más fuertes a `mentions` resultaron `supports` correctos
según la lectura humana. Así que lo más probable es que ese cero no venga del prompt, sino de
la fuente: el retrieval apenas trae menciones de pasada. Ver A24.

### A20 · Comparación de modelos para síntesis: `deepseek-v4-pro`

**Descubierto en:** N8 (C8 y C3, una llamada por modelo y clúster, ids 85–88, prompt anterior
a A19). Tres medidas:

| Medida | deepseek-flash | deepseek-v4-pro |
|---|---|---|
| Atribución: claims que nombran al autor del pasaje citado (C8 / C3) | 6/14 / 15/15 | 13/13 / 14/14 |
| Detección de crítica: pasajes críticos de Espinosa recogidos en algún claim (C3) | 1 (#27) | 3 (#27, #29, #38) |
| Transcripción: mediana de 5-gramas del claim que aparecen tal cual en su pasaje (C3) | 33 % (12/15 claims ≥ 30 %; peor 66 %) | 4,5 % (0/14 ≥ 30 %) |
| Coste C8: tokens de entrada / salida, tiempo | 7 232 / 9 205, 35 s | 7 283 / 10 009, 89 s |
| Coste C3: tokens de entrada / salida, tiempo | 14 711 / 9 397, 36 s | 14 762 / 14 820, 131 s |

La atribución de flash no es estable entre clústeres (6/14 en C8 y 15/15 en C3); la de
v4-pro sí. v4-pro sintetiza combinando fuentes, mientras flash tiende a transcribir el
pasaje. Su baja copia literal se comprobó a mano en los claims 7 y 8 (contra #29 y #38):
son fieles.
**Decisión:** `deepseek-v4-pro` para síntesis (`deepseek_model_synthesis`, por defecto en
`Settings`). **`deepseek-flash` se queda para etiquetado** (`deepseek_model`).
**Límite de la medida:** una sola muestra por modelo y clúster. Como `coherent` en A13,
estos juicios pueden variar entre corridas. La decisión se apoya en que las tres medidas
apuntan en la misma dirección, no en ninguna cifra aislada. No se compararon precios por
token.

### A21 · La validación ⊆ recuperados interceptó una alucinación realista

**Descubierto en:** N9 (C3, `llm_calls` id 94). Un claim citó
`doi:10.17141/iconos.43.2012.349#¿Retorno al barroco?#38`: paper real de la partición, seq
real, nombre de sección inventado (los candidatos de ese paper son, p. ej.,
`…#Barroco y Mestizaje#38`). El chunk no existe (`get_chunk` → `None`). Ningún prompt lo
habría evitado y ninguna revisión por similitud lo habría detectado: el id es plausible. Lo
cazó la comprobación en código de X3, que descartó el claim entero sin repararlo.
**Consecuencia:** confirma el diseño de X3: la garantía de «prohibido afirmar sin `chunk_id`»
la da el código, no el prompt. Tasa medida: 1 de 129 claims generados (0,8 %).

### A22 · Coste real de una regeneración completa (cierra D2)

**Descubierto en:** N9 (`llm_calls` ids 90–98, `deepseek-v4-pro`, `max_tokens=32768`).
9 llamadas, 141 939 tokens de entrada y 127 016 de salida, 908 s de latencia sumada,
0,26 USD (saldo 4,13 → 3,90 USD por los 8 clústeres de la corrida; C6, lanzado antes,
estimado en ~0,03 USD por proporción de tokens). Sin reintentos. Margen de salida: el máximo
fue C4 con 19 945 tokens, el 61 % del tope de 32 768. La salida no escala con el número de
candidatos (C6, 76 candidatos: 10 899; C3, 46: 17 363).
**Consecuencia:** para la spec 05, el presupuesto por consulta se calcula sobre estos números.

### A23 · El criterio 3 se juzga por la tasa ponderada: la muestra está inclinada a propósito

**Descubierto en:** N10 (diseño de la muestra, 2026-10-11). La spec pide «10 claims al azar;
≥ 9 sustentadas». Un azar uniforme sobre las 128 claims de N9 deja fuera los 7 `contradicts`
con probabilidad ≈ 57 % ((121/128)^10), y no garantiza ver ninguna de las candidatas a
`mentions` mal clasificadas (N9: 0 `mentions` en 128, poco verosímil). Son justo los dos casos
frágiles de A19. Por eso la muestra (`expertos/sampling.py`) es **estratificada**, con tres
estratos disjuntos:

| estrato | población | en la muestra | cómo entra |
|---|---|---|---|
| `contradicts` | 7 | 3 | al azar (semilla 42) |
| `mencion`: `supports` con marcador léxico fuerte de mención («reseña», «cita a», «autores como»…) | 5 | 3 | elegidas a mano leyendo las candidatas: C2#11, C5#11, C6#11 |
| `corriente`: el resto | 116 | 4 | al azar |

La heurística léxica no mira el paréntesis final de autores: «(pasaje de X, que cita a
Echeverría)» describe el pasaje, no la claim (era el falso positivo de C4#4).
**Consecuencia:** la tasa cruda de la muestra está sesgada hacia los estratos raros: 6 de 10
claims salen de 12 de 128. Juzgar el criterio por ella penalizaría el corpus por haber mirado
adrede donde más falla. **El criterio 3 se juzga por la tasa ponderada**: la tasa de cada
estrato, pesada por su población (116/5/7 sobre 128). La cruda se informa al lado.
Con 3–4 claims por estrato, cada tasa por estrato es gruesa; la ponderada está dominada por las
4 de `corriente`. Es una estimación de muestra pequeña, como pide la spec, no una medida fina.
**Dos tasas, no una.** `stance_erroneo` (el pasaje sustenta el texto pero la postura está mal)
**no cuenta como sustentada**: la claim C3 es texto + postura, y el Redactor leerá la postura.
Se informa aparte el acierto de stance = `ok` / (`ok` + `stance_erroneo`), también ponderado.
`chunk_roto` (E6) sale de ambos denominadores: no cuenta contra el Experto.

### A24 · El cero en `mentions` es estructural: el retrieval devuelve pasajes sustantivos

**Descubierto en:** N10 (lectura humana de la muestra, 2026-10-17). En el estrato `mencion`
se eligieron las tres candidatas más claras a `mentions` mal clasificadas, según el marcador
léxico: C2#11 («autores como»), C5#11 («reseña») y C6#11 («cita a»). **Las tres son `supports`
correctos.** En cada una, el pasaje expone la tesis por extenso y no la nombra de pasada:
- Piñeiro Aguiar y Breilh desarrollan la relación entre Echeverría y el Buen Vivir.
- Ortega Esquivel describe la edición de Itaca.
- Torres Gaxiola cita a Echeverría para apoyar su propio argumento.

El marcador léxico venía de la regla de atribución de A17, no de una mención real.
**Lectura:** el cero en `mentions` (N9: 0 de 128) no parece un defecto del juicio de stance,
sino de dónde sale el material. El Experto solo ve los pasajes que recuperan las sub-consultas
temáticas de N7. Esas sub-consultas premian el pasaje denso sobre el tema, y una mención de
pasada (una línea que nombra la tesis y sigue con otra cosa) rara vez queda entre los
candidatos. No se puede clasificar como `mentions` lo que nunca llega al modelo.
**Alcance:** es una muestra de 3, elegida a mano, y no prueba que no existan menciones mal
clasificadas entre las 116 `corriente`. Tampoco se ha medido cuántas menciones de pasada hay en
el corpus fuera de lo recuperado. Para fase 05: no esperar `mentions` de los Expertos. Si el
Redactor necesita distinguir «trata» de «nombra», tendrá que salir de otra vía de
recuperación, no de reajustar el prompt.

---

### A25 · El mapa cumple el criterio 5 con margen; el conteo offline es pesimista a propósito

`data/synthesis_map.json` (N11): 9 entradas, 154 papers, 5 515 bytes. Estimación offline
(`bytes / 2.5`): 2 206 tokens. Contraste real con `deepseek-flash` (`llm_calls` 99 y 100): 1 569
tokens de entrada con el mapa menos 116 de la llamada base con un `ok` por mensaje ≈ 1 453 tokens,
36 % del tope de 4 000, unos 3,8 bytes por token. Solo se midió con DeepSeek: el proveedor del
Orquestador no está decidido, por eso el código usa una estimación con holgura y no un tokenizador
concreto. Se cuenta el archivo tal como se guarda (`indent=2`).

---

### A26 · Primera prueba real del modo consulta: reconoce lo que no sabe, pero la prosa no está verificada

**Descubierto en:** N12, con 2 preguntas a C6 en `deepseek-v4-pro` (`llm_calls` 101 y 102). No es
una medición: eso es N13.
Fuera de tema (pan de muerto): `evidence` vacía, `low`, `gaps` explícito; 6 s y 257 tokens de salida.
Dentro de tema (valor de uso y forma natural): 7 claims, `high`, `gaps` nulo; 93 s y 7 577 tokens de
salida. Leídos a mano los 7 pasajes: 6 sustentan su claim y 1 se estira. La de Peralta García atribuye
«para Echeverría» una aclaración entre paréntesis del propio Peralta, cuyo pasaje solo dice «podemos
sospechar que esto lo sabía Echeverría», y mezcla las «propiedades» de la maquinaria con la definición.
**La prosa añade:** `answer` dice «configuración cualitativa», y «cualitativa» no está en ninguna claim
ni en los pasajes leídos. El código valida los `chunk_id` de `evidence`, no el texto de `answer` ni la
fidelidad de cada claim.
**Consecuencia para 05:** el Verificador debe juzgar la prosa contra los pasajes. `answer` no es
evidencia: el Redactor debería construir desde `evidence`.

---

### A27 · Primera corrida de N13: las trampas no cuelan, pero la búsqueda deja pasajes fuera

**Descubierto en:** N13, 2026-11-04, `top_k=16`, `deepseek-v4-pro`: 64 llamadas de `consult.answer`
(63 de N13 y 1 prueba de N12), 393 534 tokens de entrada, 107 121 de salida, media 23 s, máximo 114 s.
**Trampas (45):** todas `low`. Fáciles 18/18 sin evidencia. Difíciles 24/27 sin evidencia y 3 con
evidencia, leídas a mano: las tres declaran que el corpus no lo cubre. Fallo menor: los `gaps` de
C5-dificil2 traen «teatralidad» y «estetización», ajenas a lo citado. Los `gaps` de las otras 42 no se
leyeron.
**Controles (18):** ninguno se niega, 17 `high` y 1 `medium`. Recuperan 41/58 chunks de referencia.
Sondeo solo de recuperación (18 llamadas, `N13.subquery-probe`; guion fuera de git en
`data/synthesis/_review/N13-sondeo-recuperacion.py`):

| Búsqueda | Referencia | Pasajes (media) | Papers (media) |
|---|---|---|---|
| pregunta, `top_k=16` | 41/58 | 15,6 | 5,8 |
| pregunta, `top_k=32` | 47/58 | 29,8 | 8,4 |
| pregunta + 4–6 sub-consultas, 8 c/u | 42/58 | 22,1 | 8,6 |
| pregunta + 4–6 sub-consultas, 16 c/u | 49/58 | 36,3 | 11,3 |

Muestra pequeña, y la referencia son los chunks citados en N9, no un conjunto ideal.
**Problemas:** (1) `gaps` confunde «no lo leí» con «el corpus no lo cubre» (C4-control2: dice que se
limita a ciertas críticas sin haber recuperado a Parra Ayala ni a Sabugal). (2) `confidence` casi no
discrimina: `low` en trampas, `high` en controles, también con `gaps` declarados. (3) C1-control2 perdió
3 claims con ids a los que parece faltarles la sección (X3 actuó y se rehízo la prosa).
**Recomendación pendiente de decisión del usuario:** `top_k=32` sin sub-consultas, `gaps` referido a los
pasajes leídos, repetir las 63 preguntas. La fidelidad de las respuestas de control no está medida.

### A28 · Segunda corrida de N13: `top_k=32` y `gaps` referido a los pasajes leídos

**Descubierto en:** N13, 2026-11-05. Decisión del usuario sobre A27: `DEFAULT_TOP_K = 32`, sin
sub-consultas; el prompt pide que `gaps` hable de los pasajes leídos y no de todo el corpus (también
`NO_EVIDENCE_GAPS`). Primera corrida conservada en `data/consult_traps_k16/` y
`data/synthesis/_review/N13-trampas-k16.md` (fuera de git).
**Coste:** 63 llamadas, 0 fallos, 680 063 tokens de entrada (1,7× la primera corrida), 125 014 de
salida, media 18 s, máximo 71 s, 23 min en total.

| | `top_k=16` | `top_k=32` |
|---|---|---|
| Fáciles sin evidencia | 18/18 | 18/18 |
| Difíciles sin evidencia / con evidencia | 24 / 3 | 22 / 5 |
| Controles que responden (`high`/`medium`) | 18 (17/1) | 18 (17/1) |
| Chunks de referencia recuperados | 41/58 | 47/58 |
| Claims descartadas por X3 | 3 (C1-control2) | 0 |
| `gaps` que hablan de «corpus» | 40/63 | 0/63 |

Las 5 difíciles con evidencia (C1-dificil3, C2-dificil3, C3-dificil2, C6-dificil2, C8-dificil2) se leyeron a
mano: todas dicen que los pasajes no responden a la pregunta. Las claims citan solo lo
tangencial que sí está, y el término trampa aparece únicamente negado («no menciona a Adorno»). Ninguna
atribuye una tesis al autor ausente. C5-dificil2 pasó a cero evidencia. Los `gaps` de los 7 controles
que los declaran se refieren a lo que no precisan los pasajes. `confidence` sigue sin
discriminar más allá de trampa/control (problema 2 de A27, sin cambios).
**Sin medir:** fidelidad de las respuestas de control (→ Verificador, 05) y cita textual.

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

### B3 · Regeneración selectiva tras ingesta (Q1) decidida, no implementada
**Origen:** N14 (revisión de cierre). Q1 fija re-clusterizar desde cero y regenerar solo las
síntesis de clústeres con Jaccard < 0.8. Ninguna micro-tarea lo implementó porque en la fase no
hubo ingesta nueva: no existe el cálculo de Jaccard ni la correspondencia entre `expert_id` de
dos runs.
**Por qué se acepta:** una regeneración completa cuesta 0,26 USD y 908 s (A22); la optimización
no compensa hoy.
**Cómo se maneja:** tras una ingesta, secuencia manual `vectors` → `cluster` → `synthesis retrieve`
→ `synthesis draft` → `map build`, con inspección humana del nuevo k (A8). El `run_id` cambia, así
que los `expert_id` no son estables entre runs.
**Gatillo:** el coste de regenerar se vuelve relevante, o la fase 05 necesita `expert_id` estables.

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
- **C5 · Partición vacía = error, no «sin filtro»** (N7). `ChunkStore.retrieve` traduce
  `filter_paper_ids=[]` a ningún `where`, es decir, a todo el corpus. `retrieve_for_expert`
  levanta `ValueError` antes de llamar al store, y además rechaza cualquier chunk devuelto
  fuera de la partición.
- **C6 · `CandidateChunk` extiende `ScoredChunk` con `queries`; `RetrievalRecord` guarda el
  texto de cada chunk** (N7). Modelos internos de fase 04, no contrato. N8 redacta desde
  `data/synthesis/_retrieval/{expert_id}.json` sin volver al LLM ni a Chroma. Ningún
  candidato se descarta por score (L1); los `from_abstract` se conservan y la preferencia
  por PDF (X7) es tarea del prompt de N8.
- **C7 · `synthesis retrieve` sin `--expert-id` omite los clústeres con archivo ya escrito;
  con `--expert-id` regenera siempre** (N7). Mismo criterio que `skip_existing` de N5: una
  corrida cortada se reanuda gastando solo las llamadas que faltan.
- **C8 · Sub-consultas que derivan a un subtema marginal no se filtran** (N7). En C3 una
  derivó a «ethos corporativo»: N8 decidirá leyendo si aporta. Hallazgos de la corrida
  real en A14–A16.
- **C9 · Sin evidencia válida se tira la prosa del LLM** (N12). `answer_question` devuelve una
  respuesta fija con `confidence="low"` aunque el LLM dijera `high`, y si se descarta una claim rehace
  `answer` con las supervivientes (D5, X3). Es una regla estructural, no un umbral numérico (regla 7).
  `gaps` en blanco pasa a `None`; sin evidencia, `gaps` siempre tiene contenido.
- **C10 · Cada consulta se guarda en un archivo propio que nunca se pisa** (N12), en `data/consult/`.
  `llm_calls` no conserva la respuesta ni los pasajes, y repetir la pregunta no garantiza la misma
  salida. `draft` conserva la prosa cruda aunque C9 la haya sustituido.

## D · Verificaciones pospuestas

- **D1 (→N4) ✅ resuelta en N4 (A8: k=9).** Elección de k. El silhouette será bajo por el carácter monotemático del
  corpus; manda la inspección humana de 3 clústeres, no la métrica.
- **D2 (→N9) ✅ resuelta en N9 (A22: 0,26 USD, 268 955 tokens, 908 s).** Coste real de una regeneración completa. Se lee de `llm_calls`, no se estima.
- **D3 (→N10) ✅ resuelta en N10 (A23: 10/10 `ok`, 100 % ponderada, ningún fallo que clasificar).** Tasa de claims realmente sustentadas, con los fallos clasificados en
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
- **E5 (→05):** obra primaria en el corpus (A17). Un chunk puede ser texto del autor
  estudiado o de quien él traduce, no de un comentarista. La atribución en la prosa debe
  seguir `authors` del paper, no el tema del corpus.
- **E6 (→05):** el miembro `contradicts` de un par A19 lleva una atribución que su propio
  chunk no sustenta. Las dos claims del par comparten el texto de la tesis, atribuida a quien
  la sostiene, pero el miembro `contradicts` cita el pasaje que la *discute*, no el que la
  atribuye. Caso: C6#13, «Guillén sostiene, citado por Campos Madrigal, que…». La atribución a
  Guillén está en `doi:10.46652/rgn.v6i29.837#Introducción#2`, que es el chunk de la gemela
  C6#12 (`supports`). C6#13 cita `#…valor de uso#17`, donde Guillén no aparece y que matiza la
  tesis. En N10 se juzgó `ok`, porque es lo que pide A19. Pero un Verificador de fase 05 que
  compruebe frase contra chunk lo marcaría `not_entailed` **por diseño, no por cita falsa**.
  Afecta a los 7 `contradicts` de N9. Hay dos salidas, a decidir en fase 05:
  (a) el Redactor no arrastra la atribución cuando cita el miembro `contradicts`: escribe
  «Y matiza la tesis de que…» y cita la atribución con el chunk del miembro `supports`;
  (b) el Verificador trata el par como unidad: la atribución se comprueba contra los chunks de
  ambos miembros, y la discusión, solo contra los del `contradicts`.
  Detectado en el muestreo de N10.
- **E7 (→05):** C4 no lleva `coherent`, así que el Orquestador no ve que C1 y C8 se etiquetaron
  `coherent=false` (A13) y puede rutear a ellos como a cualquier otro. El `one_liner` de C1 tampoco
  distingue su parte teórica de sus notas institucionales. No se añade el campo (C4 es contrato);
  decidir en fase 05 si hace falta, con preguntas de ruteo reales.

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
| N7 | Síntesis 1/2: sub-consultas | ✅ 2026-10-03 · `expertos/synthesis.py` (sub-consultas → retrieval por partición → candidatos) + CLI `synthesis retrieve` · `EXPERTOS_DEEPSEEK_MODEL_SYNTHESIS` · 9/9 clústeres en `data/synthesis/_retrieval/` (27 567 tokens) · 343 tests (+9 slow) · test slow OK · comportamientos C5–C8, hallazgos A14–A17 |
| N8 | Síntesis 2/2: claims validadas | ✅ 2026-10-03 · `draft_claims` + CLI `synthesis draft` · `PRIMARY_WORKS` (4 papers) · stance por pares de tesis, validado en C3 (#27, #29, #38 → contradicts) · síntesis con `deepseek-v4-pro`, `max_tokens=32768` · 359 tests (+10 slow) · test slow OK · hallazgos A17 (censo), A18–A20 |
| N9 | Corrida completa de síntesis | ✅ 2026-10-07 · 9/9 síntesis en `data/synthesis/` (128 claims: 121 supports, 7 contradicts, 0 mentions; 1 descartada; 12 marcas de `PRIMARY_WORKS`) · criterio 2: 203/203 `get_chunk` ✓ · CLI reanudable con `--force` (`pending_drafts`) · 362 tests (+10 slow) · stance todo `supports` en C3, C5, C7 (→N10) · hallazgos A21–A22, cierra D2 |
| N10 | Muestreo de 10 claims | ✅ 2026-10-17 · `expertos/sampling.py` + CLI `sample` · muestra estratificada (3 `contradicts`, 3 `mencion`, 4 `corriente`; A23) en `data/synthesis/_review/N10-muestra.md` · 10/10 `ok`: criterio 3 = 100 % ponderada (cruda 100 %) ✓, acierto de stance 100 % · 378 tests (+10 slow) · hallazgos A23–A24 (matiza A19), E6 |
| N11 | SynthesisMap | ✅ 2026-11-04 · `expertos/synthesis_map.py` + CLI `map build` · `data/synthesis_map.json` (9 entradas, 154 papers) · criterio 5: ~1 453 tokens reales de 4 000 ✓ (A25) · 391 tests (+10 slow, no corridos) · E7 |
| N12 | Modo consulta | ✅ 2026-11-04 · `expertos/consult.py` + CLI `ask` · auditoría en `data/consult/` (C10) · sin sub-consultas hasta medir en N13 · 418 tests (+10 slow, no corridos) · A26, C9 |
| N13 | Preguntas trampa | ✅ 2026-11-05 · `expertos/traps.py` + CLI `traps run\|report` · 63 preguntas · criterio 4 ✓ (juicio del usuario) · `DEFAULT_TOP_K = 32` · `gaps` sobre pasajes leídos · 431 tests (+10 slow, no corridos) · A27, A28 |
| N14 | Cierre de fase | ✅ 2026-11-05 · spec `04-SPEC-EXPERTOS-Y-SINTESIS_v11.md` CERRADA (criterios 1–5 ✓) · `04-PROPAGACION-A-00-Y-01.md` (D10–D12, contenedor `SynthesisMap`, parámetros) · `04-HERENCIA-PARA-FASE-05.md` · 431 tests en verde; slow: 5 sin LLM en verde (vectores, clustering, chunker, embedder, relevancia), GROBID omitido (servicio apagado), 4 con LLM real no corridos (gastan saldo; el de etiquetado reescribe `cluster_labels_slowtest.json`) · D3 cerrada, B3 |
