# Proyecto: sistema multiagente de investigación con citas verificables

Sistema que responde preguntas de investigación con prosa académica citada y verificada
contra un corpus. Fases: Excavador (02) → Biblioteca RAG (03) → Expertos (04, EN CURSO) →
Orquestador/Redactor/Verificador (05).

**Leer antes de tocar nada:** `docs/00-VISION-Y-ARQUITECTURA.md`,
`docs/01-CONTRATOS-DE-DATOS_v11.md` (contratos C1–C7, no romper compatibilidad),
`docs/03-HERENCIA-PARA-FASES-04-Y-05.md`, `docs/04-PLAN-MICROTAREAS-EXPERTOS.md`,
`docs/04-REGISTRO-CONSIDERACIONES-EXPERTOS.md`.

## Estado actual

Fase 04, micro-tarea N6 firmada, N7 pendiente. N0–N6 firmadas. 155 papers únicos en
data/expert_vectors.npz (3 DOI-variante colapsados, ver A5/A6/E3 del registro). k=9
elegido por inspección humana (A7/A8); asignación en la tabla `clusters` de
data/excavador.db, run_id `kmeans-k9-seed42-98b2c308` (sufijo = SHA-256[:8] de
expert_vectors.npz), expert_id `C0`–`C8`. Corpus efectivo 154 (stoplist E4 vía
`load_corpus_assignment`).
Etiquetas de producción en `data/cluster_labels.json` (Gemini, C0–C8; A13).
`data/cluster_labels_slowtest.json` (DeepSeek) es solo material de comparación: no
sustituye a las de producción ni se regenera.
Modelos C3/C4/C5 en `expertos/models.py`, persistencia atómica en `expertos/persistence.py`
(`data/synthesis/` y `data/synthesis_map.json` aún no existen: los llena N9).
N7 (síntesis 1/2: sub-consultas) no ha empezado — pedir el prompt antes de escribir código.
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
  `EXPERTOS_DEEPSEEK_API_KEY`, `EXPERTOS_DEEPSEEK_MODEL=deepseek-flash` (el mismo para
  ambas tareas). Solo `response_format=json_object`: el schema viaja en el prompt de
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

## Tarea en curso: N6 — Modelos C3/C4/C5 y persistencia

Objetivo (fila N6 de `04-PLAN-MICROTAREAS-EXPERTOS.md`, X5): `expertos/models.py` con
`Claim`, `Synthesis` (C3), `SynthesisMapEntry` (C4) y `ExpertAnswer` (C5) transcritos
**exactamente** de `docs/01-CONTRATOS-DE-DATOS_v11.md` — sin añadir ni renombrar campos
(contrato compartido con fase 05).

- Restricciones en comentario del contrato → validadores que rechazan: `summary` 300–800
  palabras, `one_liner` ≤ 40 palabras (misma lógica que N5, sin duplicarla).
- `Claim.supporting_chunks` vacío se rechaza (D5: prohibido afirmar sin `chunk_id`; C3 no
  autoriza la lista vacía). `stance` y `confidence`: solo los literales del contrato; son
  juicios del LLM (L1, L2, A13), ningún validador ni default los deriva de un score.
- `SynthesisMap`: contenedor (decisión de fase 04, no está en el contrato) con `run_id`,
  `updated_at` y entradas C4 literales.
- Persistencia: `save_synthesis` / `load_synthesis` (inexistente → `None`) /
  `load_all_syntheses` en `data/synthesis/{expert_id}.json`; `save_synthesis_map` /
  `load_synthesis_map` en `data/synthesis_map.json` (`Settings.synthesis_map_path`, nuevo).
  Escritura atómica (temporal + rename): una corrida de N9 interrumpida no deja JSON a medias.
- Frontera modelo→persistencia: tipos nativos de Python (regla 5).
- N6 no hace llamadas LLM ni consume cuota.

Hecho cuando: tests en verde (round-trip con acentos y ñ, validadores, stance, `None` en
inexistente, escritura atómica con fallo simulado, nombres de campo 1:1 con el contrato),
round-trip verificado, commit `N6: modelos C3/C4/C5 y persistencia` + push.

Al terminar N6: actualizar la tabla de estado en `04-REGISTRO-CONSIDERACIONES-EXPERTOS.md`;
N7 empieza con DeepSeek (X6‴), y su diseño (X3) debe presupuestar llamadas con
`llm_calls` (D2).
