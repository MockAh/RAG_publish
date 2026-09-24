# 04 · Registro de consideraciones — Expertos + Síntesis

> Compañero del plan de micro-tareas (`04-PLAN-MICROTAREAS-EXPERTOS.md`).
> Recoge hallazgos, deuda aceptada y herencias entre micro-tareas.
> Estado: **fase en curso** · N0–N1 firmadas.

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
**Deuda (E7):** la duplicación persiste en `excavador.db` y en Chroma; corregirla en
origen requiere reabrir fase 02/03 con causa documentada — no se hace en fase 04.
**Consecuencia pendiente para fase 05:** un mismo paper podría aparecer citado con dos
`chunk_id` de distinto `paper_id`; el Verificador o el Redactor deberían tratarlos como el
mismo paper (`DOI_ALIASES` es la fuente) si vuelve a aparecer.

---

## B · Deuda técnica aceptada

### B1 · `tests/expertos/` sin `__init__.py` obliga a nombres de test únicos
**Origen:** N1. Con `tests/test_config.py` ya existente, un `tests/expertos/test_config.py`
colisiona en la importación. Se resolvió renombrando a `test_expertos_config.py` y
`test_expertos_llm.py`.
**Por qué se acepta:** añadir `__init__.py` cambiaría la disposición de toda la suite.
**Convención de la fase:** todo test de `expertos/` se llama `test_expertos_*.py`.

## C · Comportamientos deliberados que parecen bugs

*(vacío aún)*

## D · Verificaciones pospuestas

- **D1 (→N4):** elección de k. El silhouette será bajo por el carácter monotemático del
  corpus; manda la inspección humana de 3 clústeres, no la métrica.
- **D2 (→N9):** coste real de una regeneración completa. Se lee de `llm_calls`, no se estima.
- **D3 (→N10):** tasa de claims realmente sustentadas, con los fallos clasificados en
  *claim infiel* frente a *chunk roto* (E6 de fase 03).

## E · Cuestiones que tocan otras fases

- **E1 (→05):** D11 — el Verificador usa un proveedor distinto al del Redactor. El cliente
  agnóstico de N1 (X8) ya lo hace posible sin tocar código de agentes.
- **E2 (→05):** la tabla `llm_calls` es la base para responder la pregunta abierta de la
  spec 05 sobre presupuesto de llamadas por consulta.
- **E7 (→02/03, deuda no urgente):** 3 papers indexados por duplicado (DOI-variante no
  capturada por el dedup de fase 02). Colapsados en fase 04 a nivel de vector (A6);
  persisten como registros duplicados en `excavador.db` y `data/chroma`. Corregir si el
  volumen crece en una ingesta futura, o si aparecen más casos.

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

---

## Estado de micro-tareas

| # | Tarea | Estado |
|---|---|---|
| N0 | Decisiones Q1–Q3, X1–X8 | ✅ 2026-09-19 |
| N1 | Bootstrap `expertos/` + cliente LLM | ✅ 2026-09-23 · commit a4564b0 · 194 tests · hallazgos A1–A4 |
| N2 | Vectores representativos | ✅ 2026-09-23 · `data/expert_vectors.npz` = 155 vectores (1024-d, norma 1; 158 indexados − 3 alias) · test slow OK · hallazgos A5–A6 |
| N3 | Barrido de clustering | ⬜ |
| N4 | Inspección humana; elegir k | ⬜ |
| N5 | Etiquetado LLM | ⬜ |
| N6 | Modelos C3/C4/C5 | ⬜ |
| N7 | Síntesis 1/2: sub-consultas | ⬜ |
| N8 | Síntesis 2/2: claims validadas | ⬜ |
| N9 | Corrida completa de síntesis | ⬜ |
| N10 | Muestreo de 10 claims | ⬜ |
| N11 | SynthesisMap | ⬜ |
| N12 | Modo consulta | ⬜ |
| N13 | Preguntas trampa | ⬜ |
| N14 | Cierre de fase | ⬜ |
