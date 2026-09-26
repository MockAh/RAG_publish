# Proyecto: sistema multiagente de investigación con citas verificables

Sistema que responde preguntas de investigación con prosa académica citada y verificada
contra un corpus. Fases: Excavador (02) → Biblioteca RAG (03) → Expertos (04, EN CURSO) →
Orquestador/Redactor/Verificador (05).

**Leer antes de tocar nada:** `docs/00-VISION-Y-ARQUITECTURA.md`,
`docs/01-CONTRATOS-DE-DATOS_v11.md` (contratos C1–C7, no romper compatibilidad),
`docs/03-HERENCIA-PARA-FASES-04-Y-05.md`, `docs/04-PLAN-MICROTAREAS-EXPERTOS.md`,
`docs/04-REGISTRO-CONSIDERACIONES-EXPERTOS.md`.

## Estado actual

Fase 04, micro-tarea N4 firmada, N5 pendiente. N0–N4 firmadas. 155 papers únicos en
data/expert_vectors.npz (3 DOI-variante colapsados, ver A5/A6/E3 del registro). k=9
elegido por inspección humana (A7/A8); asignación en la tabla `clusters` de
data/excavador.db, run_id `kmeans-k9-seed42`, expert_id `C0`–`C8`.
N5 (etiquetado LLM) no ha empezado — pedir el prompt antes de escribir código.
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

Gemini API vía `expertos/llm.py` (`GeminiClient`, implementa `LLMClient.complete_json`,
cliente agnóstico de proveedor — X8, habilita D11: el Verificador de fase 05 usará un
proveedor distinto al del Redactor).

Modelos en `.env` (`EXPERTOS_MODEL_SYNTHESIS`, `EXPERTOS_MODEL_LABEL`): **ambos
`gemini-3.6-flash`**. Los Pro son inaccesibles en el free tier (2.5 retirado, 3.1 con
cuota cero — A4 de fase 04). No cambiar sin repetir el sondeo de N1 con llamadas reales
(`models.list()` no basta: "listar no es poder llamar").

Toda llamada, éxito o fallo, se registra en la tabla SQLite `llm_calls`
(`data/excavador.db`).

## Tarea en curso: N3 — Barrido de clustering

Objetivo: `expertos/clustering.py` que, sobre los 155 vectores de
`data/expert_vectors.npz` (`load_vectors`), corra k-means con k = 5–12 y HDBSCAN como
contraste (decisión X2), y escriba un informe legible en `data/cluster_sweep_report.md`
(`Settings.cluster_report_path`). CLI: `python -m expertos cluster sweep`.

- Matriz en orden determinista (por `paper_id`); vectores ya en norma 1, no reescalar.
- `sweep_kmeans`: `KMeans(random_state=seed, n_init="auto")`, silhouette con métrica
  coseno, tamaños por clúster. Semilla fija `seed=42` por defecto (Q1), parametrizable.
- `run_hdbscan`: `sklearn.cluster.HDBSCAN(metric="cosine")` (aceptado directamente,
  sin matriz precomputada); reporta `n_clusters` y `n_noise` (label -1).
- El informe **no recomienda un k**: eso lo decide N4 con inspección humana.

Hecho cuando: informe generado (fila N3 de `04-PLAN-MICROTAREAS-EXPERTOS.md`), tests
verdes y test `@pytest.mark.slow` sobre los 155 vectores reales pasando.

Al terminar N3: actualizar la tabla de estado en `04-REGISTRO-CONSIDERACIONES-EXPERTOS.md`
y avanzar a N4 (inspección humana de 3 clústeres, elegir k) solo tras revisar el informe.
