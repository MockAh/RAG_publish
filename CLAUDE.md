# Proyecto: sistema multiagente de investigación con citas verificables

Sistema que responde preguntas de investigación con prosa académica citada y verificada
contra un corpus. Fases: Excavador (02) → Biblioteca RAG (03) → Expertos (04, EN CURSO) →
Orquestador/Redactor/Verificador (05).

**Leer antes de tocar nada:** `docs/00-VISION-Y-ARQUITECTURA.md`,
`docs/01-CONTRATOS-DE-DATOS_v11.md` (contratos C1–C7, no romper compatibilidad),
`docs/03-HERENCIA-PARA-FASES-04-Y-05.md`, `docs/04-PLAN-MICROTAREAS-EXPERTOS.md`,
`docs/04-REGISTRO-CONSIDERACIONES-EXPERTOS.md`.

## Estado actual

Fase 04, micro-tarea N10 firmada, N11 pendiente. N0–N10 firmadas. 155 papers únicos en
data/expert_vectors.npz (3 DOI-variante colapsados, ver A5/A6/E3 del registro). k=9
elegido por inspección humana (A7/A8); asignación en la tabla `clusters` de
data/excavador.db, run_id `kmeans-k9-seed42-98b2c308` (sufijo = SHA-256[:8] de
expert_vectors.npz), expert_id `C0`–`C8`. Corpus efectivo 154 (stoplist E4 vía
`load_corpus_assignment`).
Etiquetas de producción en `data/cluster_labels.json` (Gemini, C0–C8; A13).
`data/cluster_labels_slowtest.json` (DeepSeek) es solo material de comparación: no
sustituye a las de producción ni se regenera.
Modelos C3/C4/C5 en `expertos/models.py`, persistencia atómica en `expertos/persistence.py`
(`data/synthesis_map.json` aún no existe: lo llena N9/N11).
Sub-consultas y retrieval por partición en `expertos/synthesis.py` (N7, C5–C8 del registro);
material intermedio en `data/synthesis/_retrieval/{expert_id}.json`, generado para C0–C8
(A14: hay evidencia válida bajo 0.83; A15: 35 de los 38 papers no cubiertos son de solo
abstract).
A17: `doi:10.29166/economia.v70i111.1393` (C1) es *El capital* de Marx traducido por
Echeverría — obra primaria, no estudio; no excluir, pero atribuir a Marx (E5).
Modelo de síntesis aparte: `EXPERTOS_DEEPSEEK_MODEL_SYNTHESIS` (defecto `deepseek-flash`).
Claims validadas en `expertos/synthesis.py` (N8): `draft_claims` + CLI `synthesis draft`;
`PRIMARY_WORKS` en `expertos/assignments.py` (A17); stance por pares de tesis (A19);
síntesis con `deepseek-v4-pro` (A20). Las comparaciones de N8 están en
`data/synthesis_cmp/` (fuera de git), solo como material de consulta.
N9: síntesis de producción en `data/synthesis/{expert_id}.json` para C0–C8 (fuera de git;
auditoría en `_draft/`), 128 claims, criterio 2 ✓ (203/203 `get_chunk`). CLI reanudable
(`pending_drafts`, `--force`). A21: X3 cazó un `chunk_id` inventado en C3. A22: regeneración
completa = 0,26 USD, 908 s, máx. salida 61 % del tope (cierra D2). Stance todo `supports` en
C3, C5, C7 y 0 `mentions` en total: candidatos de N10.
N10: muestra estratificada (A23) en `data/synthesis/_review/N10-muestra.md`, 10/10 `ok`,
criterio 3 ✓ (100 % ponderada) y acierto de stance 100 %. A24: el cero en `mentions` es
estructural, porque el retrieval trae pasajes sustantivos. E6 (→05): el miembro `contradicts`
de un par A19 no sustenta en su chunk la atribución de la tesis.
N11 (`SynthesisMap`) no ha empezado — pedir el prompt antes de escribir código.
Repo: `~/WandaVision/RAG_publish`, rama `main` (ver plan para N0–N14).

Paquetes previos, YA FIRMADOS, no modificar sin causa documentada (precedente en el
registro de fase 02, sección B): `excavador/`, `biblioteca/`.

## Reglas de trabajo (method, no negociables)

1. **Una micro-tarea por sesión.** No adelantar N3 mientras N2 no esté "hecho cuando..."
   según su definición en `04-PLAN-MICROTAREAS-EXPERTOS.md`.
2. **`.venv` siempre.** Verificar el intérprete antes de correr nada.
3. **Todo `.env` compartido exige `extra="ignore"`** en cada `Settings` (pydantic-settings
   lee el archivo entero; un paquete nuevo con prefijo propio revienta a los demás — A1
   de fase 04, A11 de fase 03).
4. **Nunca hacer `source .env` en una sesión que sigue viva.** El entorno pisa el archivo
   y sobrevive a su edición (A3 de fase 04). Diagnóstico: construir `Settings()` y
   `print(repr(...))` del valor, nunca asumir.
5. **Frontera modelo→persistencia: convertir siempre a tipos nativos de Python**
   (numpy, SecretStr, etc. nunca cruzan crudos a SQLite/JSON — F5 de fase 02).
6. **Modelo de embeddings congelado:** `intfloat/multilingual-e5-large`. Prefijo
   `"query: "` para consultas, `"passage: "` para documentos/chunks/vectores
   representativos. Obligatorio en TODA la fase 04. Reutilizar `biblioteca/embedder.py`
   (wrapper ya unificado, decisión B2 de fase 03) — no reimplementar.
7. **El score de retrieval NO mide confianza** (L1, banda útil 0.83–0.90, el ruido vive
   dentro). Ningún umbral numérico decide `confidence` (C5) ni `stance` (C3): son
   juicios del LLM leyendo el pasaje.
8. **El retrieval empareja por tema, no por postura** (L2). `stance` se clasifica
   recuperando ampliamente por tema y dejando que el LLM juzgue pasaje por pasaje —
   nunca buscando "críticas a X" directamente.
9. **Corpus citable real: 158 papers indexados, no los 227 de `excavador.db`**
   (E3 de fase 03). Todo lo que toque el corpus de la fase 04 parte de los indexados
   en Chroma, verificado con `ChunkStore.has_paper`, nunca de la tabla `papers` completa.
10. **Prueba manual desde la raíz del repo, fuera de pytest,** antes de firmar cualquier
    módulo con CLI o con entrada de `.env` (A11 de fase 03). El aislamiento de los tests
    (`monkeypatch.chdir`) puede ocultar bugs que solo aparecen en el entorno real.
11. **Ninguna conclusión causal de un asistente de código se acepta sin verificarla a
    mano** (F4 de fase 04). Un 404/429/500 se diagnostica imprimiendo el valor efectivo
    antes de cambiar de modelo o de código.
12. **Un commit por tarea firmada**, mensaje `N_n: descripción`. Push tras confirmar
    que `git status --short` no incluye `.env` ni archivos de memoria/caché del asistente.

## Proveedor LLM de esta fase

**Síntesis y etiquetado: DeepSeek** (X6‴, A12–A13 del registro), vía `expertos/llm.py`.
`make_client(task, settings)` devuelve el cliente de `EXPERTOS_LLM_PROVIDER`
(`deepseek` | `gemini`); ambos implementan `LLMClient.complete_json` sobre la base común
`_LoggedLLMClient` (cliente agnóstico — X8).

- **DeepSeek** (`DeepSeekClient`, httpx directo): `.env` con `EXPERTOS_LLM_PROVIDER=deepseek`,
  `EXPERTOS_DEEPSEEK_API_KEY`, `EXPERTOS_DEEPSEEK_MODEL=deepseek-flash` (etiquetado).
  **Síntesis: `deepseek-v4-pro`** (`EXPERTOS_DEEPSEEK_MODEL_SYNTHESIS`, por defecto en
  `Settings`; A20), con `max_tokens=32768` porque el razonamiento cuenta como salida (A18).
  Solo `response_format=json_object`: el schema viaja en el prompt de
  sistema. Prepago: **402 = sin saldo**, no se reintenta. Las docs no declaran RPM ni cuota
  diaria (no verificado bajo carga); el rate limiter propio sigue en `llm_rpm_<task>`.
  Coste medido: etiquetar los 9 clústeres = 22 805 tokens, 103 s, cero reintentos.
- **Gemini** (`GeminiClient`, `gemini-3.6-flash`) se conserva para D11: el Verificador
  de fase 05 usará un proveedor distinto al del Redactor. Free tier: 5 RPM / 20
  peticiones/día y 503 frecuentes (A10) — no apto para síntesis.
- Elegido **por disponibilidad, no por calidad de juicio medida** (A13): `coherent` no es
  reproducible entre proveedores (4/9 discrepan). `confidence` (C5) y `stance` (C3) son
  juicios del mismo tipo — no tratarlos como veredictos firmes.

No cambiar de proveedor ni de modelo sin sondeo con llamadas reales desde la raíz del
repo (`GET /models` / `models.list()` no basta: "listar no es poder llamar").

Toda llamada, éxito o fallo, se registra en la tabla SQLite `llm_calls`
(`data/excavador.db`), con `provider` y `context` (JSON: para qué era la llamada).
Diagnóstico tras un fallo: leer `llm_calls.error`, nunca relanzar (F5).

## Tarea en curso: N10 — Muestreo manual de 10 claims

Objetivo (fila N10 del plan; criterio de aceptación 3 de la spec 04: «10 claims al azar;
≥ 9 realmente sustentadas por su pasaje», con el ajuste del plan: cada fallo se clasifica,
E6 de fase 03). Sin LLM: se leen los 9 `data/synthesis/{expert_id}.json` de N9 (128 claims)
y el texto de los chunks de `data/synthesis/_retrieval/` (el mismo que leyó el modelo).

- `expertos/sampling.py`: `sample_claims(n=10, seed=42)` reproducible y **estratificado** en
  tres estratos (A23): 3 `contradicts` al azar, 3 `mencion` (candidatas fuertes a `mentions`
  elegidas a mano: C2#11, C5#11, C6#11) y 4 `corriente` al azar. `dump_for_review` → `.md` con
  claim, stance, estrato, chunks completos (autor, año, `from_abstract`, `PRIMARY_WORKS`) y un
  bloque vacío de veredicto por claim. `load_verdicts` + resumen.
- Veredictos: `ok` · `claim_infiel` (cuenta contra el Experto) · `chunk_roto` (E6, sale del
  denominador) · `stance_erroneo` (el pasaje sustenta el texto pero la postura está mal; **no**
  cuenta como sustentada).
- Dos tasas: criterio 3 = `ok` / juzgables y acierto de stance = `ok` / (`ok` + `stance_erroneo`),
  ambas ponderadas por la población de cada estrato. **El criterio 3 se juzga por la ponderada**
  (A23).
- CLI: `python -m expertos sample --n 10` y `python -m expertos sample --report`. No pisar un
  `.md` con veredictos ya anotados.
- Añadidos sin LLM: candidatos a `mentions` clasificados como `supports`, y concentración de
  fuentes por clúster (C8 85 %, C2 67 %, C0 57 %; C7 son 11 registros de un mismo homenaje).

Hecho cuando: el `.md` de revisión está generado y el usuario tiene el material para leerlo.
Los veredictos los pone el usuario a mano; el resumen se corre después. **No firmar hasta
que el usuario lo vea.**
