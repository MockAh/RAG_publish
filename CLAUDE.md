# Proyecto: sistema multiagente de investigación con citas verificables

Sistema que responde preguntas de investigación con prosa académica citada y verificada
contra un corpus. Fases: Excavador (02) → Biblioteca RAG (03) → Expertos (04, CERRADA 2026-11-05) →
Orquestador/Redactor/Verificador (05, EN CURSO).

**Leer antes de tocar nada:** `docs/00-VISION-Y-ARQUITECTURA.md`,
`docs/01-CONTRATOS-DE-DATOS_v11.md` (contratos C1–C7, no romper compatibilidad),
`docs/03-HERENCIA-PARA-FASES-04-Y-05.md`, `docs/04-PLAN-MICROTAREAS-EXPERTOS.md`,
`docs/04-REGISTRO-CONSIDERACIONES-EXPERTOS.md`, `docs/04-SPEC-EXPERTOS-Y-SINTESIS_v11.md`,
`docs/04-HERENCIA-PARA-FASE-05.md`, `docs/04-PROPAGACION-A-00-Y-01.md`.
Fase 05: `docs/05-SPEC-ORQUESTADOR-REDACTOR-VERIFICADOR.md`, `docs/05-PLAN-MICROTAREAS-CONSULTA.md`, `docs/05-REGISTRO-CONSIDERACIONES-CONSULTA.md`.

## Estado actual

**Fase 04 CERRADA (N14, 2026-11-05).** N0–N14 firmadas; spec v1.1 CERRADA, criterios 1–5 ✓.
Propagaciones de fases 03 y 04 aplicadas (2026-11-06): `01` v1.3 (archivo sigue `_v11.md`), `00` v1.2.
**Fase 05 en curso:** spec v1 en el repo (2026-11-06); **R0 firmada (2026-11-07)**: decisiones Y1–Y14
cerradas (plan v1, sección A; resumen al final de la spec 05). **R1 firmada (2026-11-15):** `redaccion/`
con Settings, C6/C7 literales, registro por pieza Y7 y persistencia atómica (notas C1–C3 del registro 05;
diagrama en `docs/05-flujo-redaccion-y-evidence.html`). Siguiente: R2 (sondeo del proveedor del Verificador).
Lo que sigue de esta sección es el estado final de la fase 04. 155 papers únicos en
data/expert_vectors.npz (3 DOI-variante colapsados, ver A5/A6/E3 del registro). k=9
elegido por inspección humana (A7/A8); asignación en la tabla `clusters` de
data/excavador.db, run_id `kmeans-k9-seed42-98b2c308` (sufijo = SHA-256[:8] de
expert_vectors.npz), expert_id `C0`–`C8`. Corpus efectivo 154 (stoplist E4 vía
`load_corpus_assignment`).
Etiquetas de producción en `data/cluster_labels.json` (Gemini, C0–C8; A13).
`data/cluster_labels_slowtest.json` (DeepSeek) es solo material de comparación: no
sustituye a las de producción ni se regenera.
Modelos C3/C4/C5 en `expertos/models.py`, persistencia atómica en `expertos/persistence.py`
(`data/synthesis_map.json`: lo genera N11).
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
N11: `data/synthesis_map.json` (fuera de git) con 9 entradas y 154 papers, generado por
`expertos/synthesis_map.py` y `python -m expertos map build`, sin LLM. Criterio 5 ✓: ~1 453 tokens
reales de 4 000 (A25, medido solo con DeepSeek). E7 (→05): C4 no expone `coherent=false` de C1 y C8.
N12: `expertos/consult.py` + CLI `ask`; una llamada por pregunta, pregunta tal cual como única
consulta (`top_k=16`), sin sub-consultas por decisión del usuario: se agregan solo si N13 muestra que
faltan pasajes que sí están en el corpus. Auditoría en `data/consult/`. A26: la prosa de `answer` y la
fidelidad de cada claim no las valida el código (→05). Cita textual por verificar con código: se decide
con los resultados de N13.
N13: `expertos/traps.py` + CLI `traps run|report`; 63 preguntas (7 por Experto: 2 fáciles, 3 difíciles,
2 control). Criterio 4 ✓ (juicio del usuario sobre A28): trampas 45/45 en `low`, ninguna atribuye tesis
a un autor ausente; controles 18/18 responden. `DEFAULT_TOP_K = 32` (47/58 chunks de referencia frente a
41/58), sin sub-consultas; `gaps` se refiere a los pasajes leídos (A27, A28). Corrida vigente en
`data/consult_traps/`, la de `top_k=16` en `data/consult_traps_k16/` (fuera de git). `confidence` solo
separa trampa de control; fidelidad de controles y cita textual sin medir (→05).
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

## Tarea en curso: R2 — sondeo del proveedor del Verificador (sin empezar)

Fila de `05-PLAN-MICROTAREAS-CONSULTA.md`: llamadas reales desde la raíz, cuota efectiva (Y2: comparar
`gemini-3.6-flash` y `gemini-3.8-flash` con los mismos casos). **Hecho cuando:** llamada real OK con
proveedor ≠ Redactor + fila en `llm_calls`; cuota anotada. Al empezar R2, reescribir esta sección con
el detalle (va en el commit de R2).
