# Proyecto: sistema multiagente de investigación con citas verificables

Sistema que responde preguntas de investigación con prosa académica citada y verificada
contra un corpus. Fases: Excavador (02) → Biblioteca RAG (03) → Expertos (04, EN CURSO) →
Orquestador/Redactor/Verificador (05).

**Leer antes de tocar nada:** `docs/00-VISION-Y-ARQUITECTURA.md`,
`docs/01-CONTRATOS-DE-DATOS_v11.md` (contratos C1–C7, no romper compatibilidad),
`docs/03-HERENCIA-PARA-FASES-04-Y-05.md`, `docs/04-PLAN-MICROTAREAS-EXPERTOS.md`,
`docs/04-REGISTRO-CONSIDERACIONES-EXPERTOS.md`.

## Estado actual

Fase 04, micro-tarea N8 firmada, N9 pendiente. N0–N8 firmadas. 155 papers únicos en
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
síntesis con `deepseek-v4-pro` (A20). Ninguna síntesis de producción escrita aún:
`data/synthesis/{expert_id}.json` lo llena N9. Las comparaciones de N8 están en
`data/synthesis_cmp/` (fuera de git), solo como material de consulta.
N9 (corrida completa de síntesis) no ha empezado — pedir el prompt antes de escribir código.
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

## Tarea en curso: N8 — Síntesis 2/2: claims validadas

Objetivo (fila N8 del plan; X3, X4, X7; A14–A17 del registro). Entrada: los
`data/synthesis/_retrieval/{expert_id}.json` de N7. N8 no llama al retrieval ni regenera
sub-consultas.

- `draft_claims(expert_id, label, candidates, llm_client)`: una llamada; el prompt lleva cada
  chunk con `chunk_id`, `paper_id`, autor, año y si es `from_abstract`. Devuelve `summary`
  (300–800 palabras) y `key_claims` (C3). Reglas del prompt: solo ids de la lista; atribución
  por autoría, no por tema (A17); `stance` leyendo cada pasaje (X4), sin `supports` por
  defecto; PDF antes que abstract (X7); pasajes sin sentido gramatical no se usan (E6 de 03).
- `PRIMARY_WORKS` (`expertos/assignments.py`, mismo patrón que la stoplist E4): 4 papers
  cuyo texto no es de quien dice `authors`. Su `real_author` sustituye a `authors` en el
  prompt, junto con su `attribution_note`.
- Validación en código: `supporting_chunks ⊆ recuperados`. Una claim con un id ajeno se
  descarta entera, no se repara (X3), y se cuentan las descartadas. Una claim que cita
  `PRIMARY_WORKS` no se descarta: se marca en el archivo de auditoría para N10.
- Persistencia con `save_synthesis` (N6). CLI: `python -m expertos synthesis draft [--expert-id Cn]`.

Hecho cuando: tests en verde (id ajeno descartado, vacío rechazado, los tres `stance`
persistidos, autor y año en el prompt, sustitución por `real_author`, round-trip), test `slow`
con un clúster, y **parar antes de los 9**: C8 con `deepseek-flash` y con `deepseek-v4-pro`,
claims de ambos al usuario. De esa comparación sale el modelo de N9.
