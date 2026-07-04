# 02 · Plan de implementación — Excavador + Filtro/Dedup

> Deriva de `02-SPEC-EXCAVADOR.md`. Preguntas abiertas resueltas el 2026-07-04.
> Tema de prueba: **recepción crítica de Bolívar Echeverría** (todas sus obras,
> con énfasis en *La definición de la cultura*).

---

## A · Decisiones tomadas (cierre de preguntas abiertas)

| # | Decisión | Detalle |
|---|----------|---------|
| A1 | Prioridad de APIs | OpenAlex (columna vertebral) > Crossref > Semantic Scholar. arXiv y PubMed quedan como stubs con interfaz común, sin implementar. |
| A2 | OpenAlex como normalizador canónico | Todo RawHit, venga de donde venga, se intenta enriquecer vía OpenAlex (DOI, referencias, flag OA, URL de PDF). |
| A3 | Búsqueda dual | (a) semántica por embedding del tema y (b) exacta por frase «Bolívar Echeverría» en título/abstract. Un tema-autor exige ambas. |
| A4 | Snowballing | k=15 semillas por relevance_score, **bidireccional**: referencias (hacia atrás) + cited_by de OpenAlex (hacia adelante). 1 nivel. |
| A5 | Descartados a auditoría | Tabla `papers_discarded`: espejo de C1 + `discard_reason` + `relevance_score`. |
| A6 | Embeddings | `intfloat/multilingual-e5-large`, 1024 dims. Prefijos obligatorios: `"query: "` para consultas, `"passage: "` para documentos. Congelar en `01`. |
| A7 | C1 gana campo | `work_type: Literal["article", "book", "book-chapter", "thesis", "other"]`. Aditivo, propagar a `01`. |
| A8 | Criterio de aceptación 3 recalibrado | ≥ 40 % de registros con PDF para este dominio (el 60 % original aplica a STEM). |
| A9 | Umbral de relevancia | Default 0.35 pero **se calibra** con la tabla de descartados; en tema-autor probablemente suba. Configurable por CLI. |

## B · Estructura de carpetas (final)

```
excavador/
  __init__.py
  __main__.py          # CLI (typer): python -m excavador run --tema "..." --max-papers 300
  config.py            # Settings (pydantic-settings): rutas, umbral, k, API keys, mailto
  models.py            # C1 PaperRecord + RawHit + DiscardedRecord
  apis/
    __init__.py
    base.py            # ApiClient abstracto: search(query) -> list[RawHit]; rate limit + retry
    openalex.py        # search, search_exact_phrase, enrich(doi), get_references, get_citing
    crossref.py
    semanticscholar.py
    arxiv.py           # stub: NotImplementedError con mensaje claro
    pubmed.py          # stub
  normalize.py         # RawHit -> PaperRecord parcial; enriquecimiento canónico vía OpenAlex
  dedup.py             # DOI normalizado; fallback título normalizado + año
  relevance.py         # e5 multilingüe + coseno + umbral
  snowball.py          # bidireccional sobre k semillas
  download.py          # PDFs solo OA (URL de OpenAlex/Unpaywall)
  storage.py           # SQLite: papers, papers_discarded; carpeta pdfs/
  pipeline.py          # buscar -> normalizar -> dedup -> puntuar -> snowball -> descargar -> guardar
tests/
  conftest.py          # fixtures: RawHits de ejemplo, DB temporal
  test_models.py … test_pipeline.py (uno por módulo)
```

## C · Orden de implementación y dependencias

```
T0 setup ──► T1 models ──► T2 storage ──► T3 apis/base ──► T4 openalex
                 │                                            │
                 └──► T5 normalize ◄──────────────────────────┘
                          │
              T6 dedup ◄──┴──► T7 relevance
                          │
        T8 crossref+s2 ──►│◄── T9 snowball (necesita T4, T7)
                          │
                 T10 download ──► T11 pipeline ──► T12 CLI ──► T13 corrida real
```

Regla: no empezar una tarea si su dependencia no cumple su criterio de "hecho".

---

## D · Tareas (prompts para Copilot)

Convenciones para todas las tareas:
- Python 3.12, `httpx` (async no necesario en v1: cliente síncrono), `pydantic` v2.
- Type hints completos; docstrings breves en español.
- Cada tarea incluye sus tests; "hecho" siempre implica `pytest` en verde.

---

### T0 · Bootstrap del proyecto

**Prompt para Copilot:**

> Crea un proyecto Python 3.12 llamado `excavador` con `pyproject.toml` (build backend hatchling). Dependencias: `httpx`, `pydantic>=2`, `pydantic-settings`, `tenacity`, `typer`, `sentence-transformers`. Dev: `pytest`, `pytest-httpx`. Crea la estructura de carpetas: paquete `excavador/` con submódulo `apis/`, y carpeta `tests/` con `conftest.py` vacío. Añade `excavador/config.py` con una clase `Settings(BaseSettings)` que lea de entorno con prefijo `EXCAVADOR_`: `db_path: Path = "data/excavador.db"`, `pdf_dir: Path = "data/pdfs"`, `relevance_threshold: float = 0.35`, `snowball_k: int = 15`, `openalex_mailto: str`, `semanticscholar_api_key: str | None = None`, `embedding_model: str = "intfloat/multilingual-e5-large"`. Añade un test que instancia Settings con variables de entorno simuladas.

**Hecho cuando:** `pip install -e .` funciona; `pytest` pasa; `Settings()` lee de entorno.

---

### T1 · Modelos (contrato C1 + internos)

**Prompt para Copilot:**

> En `excavador/models.py` define con pydantic v2:
> 1. `PaperRecord` exactamente con estos campos: `paper_id: str` (formato `"doi:<doi>"` o `"openalex:<id>"`), `doi: str | None`, `title: str`, `authors: list[str]`, `year: int`, `venue: str | None`, `abstract: str`, `source_api: Literal["arxiv","openalex","semanticscholar","crossref","pubmed"]`, `work_type: Literal["article","book","book-chapter","thesis","other"]`, `pdf_path: str | None`, `relevance_score: float` (0–1), `references_ids: list[str]`, `ingested_at: datetime`. Este esquema es un contrato compartido: NO añadas ni renombres campos.
> 2. `RawHit`: resultado crudo de cualquier API antes de normalizar. Campos: `source_api` (mismo Literal), `raw: dict` (payload original), `doi: str | None`, `title: str | None`, `external_id: str` (id nativo de la API).
> 3. `DiscardedRecord`: hereda de `PaperRecord` y añade `discard_reason: Literal["low_relevance","duplicate","invalid_record"]`.
> Añade tests: serialización round-trip JSON de los tres modelos; `PaperRecord` rechaza `relevance_score` fuera de [0,1] (usa `Field(ge=0, le=1)`).

**Hecho cuando:** tests en verde; los campos de `PaperRecord` coinciden 1:1 con C1 de `01-CONTRATOS-DE-DATOS.md` + `work_type`.

---

### T2 · Storage (SQLite idempotente)

**Prompt para Copilot:**

> Crea `excavador/storage.py` con clase `Storage(db_path: Path)` usando `sqlite3` de la stdlib. Tablas: `papers` (columnas espejo de `PaperRecord`; `paper_id` PRIMARY KEY; `authors` y `references_ids` como JSON text) y `papers_discarded` (espejo de `DiscardedRecord`). Métodos: `upsert_paper(p: PaperRecord)` — INSERT OR REPLACE por `paper_id`; `upsert_discarded(d: DiscardedRecord)`; `get_paper(paper_id) -> PaperRecord | None`; `all_papers() -> list[PaperRecord]`; `known_dois() -> set[str]`; `count()`. El constructor crea las tablas si no existen y crea el directorio de PDFs de Settings. Tests con DB en tmp_path: upsert dos veces el mismo paper_id no duplica (count sigue en 1); round-trip completo de un PaperRecord con acentos y ñ en título/autores (el tema del corpus es en español).

**Hecho cuando:** tests en verde; upsert repetido es idempotente; UTF-8 intacto.

---

### T3 · Cliente base de APIs

**Prompt para Copilot:**

> Crea `excavador/apis/base.py` con clase abstracta `ApiClient`: atributos de clase `source_api: str`, `min_interval_s: float` (segundos mínimos entre requests); método abstracto `search(self, query: str, max_results: int = 50) -> list[RawHit]`; método protegido `_get(self, url: str, params: dict) -> dict` que usa un `httpx.Client` compartido, aplica el rate limit (sleep si la última llamada fue hace menos de `min_interval_s`) y reintenta con `tenacity` (3 intentos, backoff exponencial, solo en 429/5xx/timeouts; en 4xx distintos de 429 levanta inmediatamente). Crea también `excavador/apis/arxiv.py` y `pubmed.py` como stubs: subclases cuyo `search` levanta `NotImplementedError("No implementado en v1: dominio humanidades")`. Tests con `pytest-httpx`: el rate limit espacia dos llamadas consecutivas; un 429 seguido de 200 termina en éxito; un 404 no se reintenta.

**Hecho cuando:** tests en verde; comportamiento de retry y rate limit verificado.

---

### T4 · Cliente OpenAlex (el crítico)

**Prompt para Copilot:**

> Crea `excavador/apis/openalex.py`, subclase de `ApiClient` (`source_api="openalex"`, `min_interval_s=0.15`). Base URL `https://api.openalex.org`. Incluye siempre el parámetro `mailto` desde Settings (polite pool). Métodos:
> 1. `search(query, max_results=50)` — endpoint `/works?search=...`, pagina con `cursor=*` hasta max_results, devuelve `list[RawHit]` con `external_id` = id de OpenAlex (ej. `W2741809807`), `doi` extraído y limpiado del prefijo `https://doi.org/`.
> 2. `search_exact_phrase(phrase, max_results=200)` — igual pero con `filter=title_and_abstract.search:"<phrase>"` para coincidencia de frase.
> 3. `enrich(doi) -> RawHit | None` — `/works/doi:<doi>`; None si 404.
> 4. `get_references(openalex_id) -> list[str]` — campo `referenced_works` del work.
> 5. `get_citing(openalex_id, max_results=100) -> list[RawHit]` — `/works?filter=cites:<id>`, paginado.
> Importante: pide siempre `select=id,doi,title,display_name,authorships,publication_year,primary_location,abstract_inverted_index,type,referenced_works,open_access,best_oa_location` para respuestas ligeras. Incluye función `invert_abstract(inverted_index: dict) -> str` que reconstruye el abstract desde el índice invertido de OpenAlex (posición → palabra). Tests con `pytest-httpx` usando payloads reales recortados de OpenAlex como fixtures (inclúyelos en `tests/fixtures/openalex_*.json`): reconstrucción correcta del abstract invertido, paginación por cursor de 2 páginas, extracción de DOI limpio.

**Hecho cuando:** tests en verde; una llamada manual real (`python -c ...`) a `search_exact_phrase("Bolívar Echeverría", 10)` devuelve ≥ 5 hits plausibles.

---

### T5 · Normalización + enriquecimiento canónico

**Prompt para Copilot:**

> Crea `excavador/normalize.py` con:
> 1. `normalize_openalex(hit: RawHit) -> PaperRecord | None`, `normalize_crossref(...)`, `normalize_semanticscholar(...)` — mapean cada payload a `PaperRecord` con `relevance_score=0.0` provisional y `ingested_at=now(UTC)`. Mapeo de `work_type`: OpenAlex `type` ∈ {article→article, book→book, book-chapter→book-chapter, dissertation→thesis, resto→other}; análogos para Crossref (`type`) y S2 (`publicationTypes`). Devuelven None si falta título o año (registro inválido: el llamador lo manda a descartados con `invalid_record`).
> 2. `canonical_enrich(record: PaperRecord, openalex: OpenAlexClient) -> PaperRecord` — si el record no vino de OpenAlex y tiene DOI, llama `enrich(doi)` y completa campos vacíos (abstract, venue, references_ids, work_type) sin sobrescribir los ya presentes. `paper_id`: `f"doi:{doi_normalizado}"` si hay DOI; si no, `f"{source_api}:{external_id}"`.
> Tests: fixture de cada API → PaperRecord correcto; hit sin año → None; enriquecimiento no pisa campos existentes.

**Hecho cuando:** tests en verde con fixtures de las tres APIs.

---

### T6 · Deduplicación

**Prompt para Copilot:**

> Crea `excavador/dedup.py`:
> 1. `normalize_doi(doi: str) -> str` — minúsculas, sin prefijos `https://doi.org/` ni `doi:`, sin espacios.
> 2. `normalize_title(title: str) -> str` — minúsculas, sin acentos (unicodedata NFD), solo [a-z0-9 ], espacios colapsados. Debe tratar «La definición de la cultura» y «La Definición de la Cultura» como iguales.
> 3. `dedup(records: list[PaperRecord]) -> tuple[list[PaperRecord], list[PaperRecord]]` — devuelve (únicos, duplicados). Clave primaria: DOI normalizado; sin DOI: `(título normalizado, year)`. Al chocar, conserva el registro más completo (más campos no-None; en empate, prefiere source_api openalex) y fusiona `references_ids` (unión).
> Tests: mismo DOI con mayúsculas distintas → 1 único; mismo título con/sin acentos y mismo año → 1 único; títulos iguales pero años distintos → 2 únicos; el ganador conserva la unión de references_ids.

**Hecho cuando:** tests en verde, incluidos los casos con acentos.

---

### T7 · Relevancia (embeddings e5)

**Prompt para Copilot:**

> Crea `excavador/relevance.py` con clase `RelevanceScorer(model_name: str)` (default desde Settings) usando `sentence-transformers`.
> REGLA CRÍTICA del modelo e5: toda consulta se embebe con prefijo `"query: "` y todo documento con prefijo `"passage: "`. Sin estos prefijos los vectores no son comparables. Deja esto en un comentario destacado.
> Métodos: `score(topic: str, records: list[PaperRecord]) -> list[PaperRecord]` — embebe el tema una vez como query, embebe `f"{title}. {abstract}"` de cada record como passage (batch), asigna similitud coseno (normalizada a [0,1] con `(cos+1)/2`... NO: e5 devuelve ya vectores normalizados y el coseno queda en ~[0.6,1]; usa el coseno crudo y documenta que el rango útil es estrecho) a `relevance_score`. `split_by_threshold(records, threshold) -> tuple[keep, discard]`.
> El modelo se carga lazy (primera llamada) para que importar el módulo sea barato. Tests: con un modelo dummy inyectable (fixture que parchea el encoder con vectores fijos) verifica prefijos aplicados, orden por score y corte por umbral. Marca un test `@pytest.mark.slow` que usa el modelo real: "cultura y capitalismo en América Latina" debe puntuar más alto para un abstract sobre Echeverría que para uno sobre química orgánica.

**Hecho cuando:** tests rápidos en verde; el test slow pasa en local.

---

### T8 · Clientes Crossref y Semantic Scholar

**Prompt para Copilot:**

> Crea `excavador/apis/crossref.py` (`min_interval_s=1.0`, base `https://api.crossref.org`, incluye `mailto` en User-Agent) con `search(query, max_results)` sobre `/works?query=...` y `enrich(doi)`. Crea `excavador/apis/semanticscholar.py` (`min_interval_s=1.1`, header `x-api-key` si Settings la tiene) con `search` sobre `/graph/v1/paper/search` pidiendo `fields=externalIds,title,abstract,year,venue,authors,references.paperId,openAccessPdf,publicationTypes` y `get_references(paper_id)`. Ambos devuelven `RawHit`. Tests con fixtures de payloads reales recortados, análogos a los de T4.

**Hecho cuando:** tests en verde; `normalize.py` (T5) acepta sus RawHits sin cambios.

---

### T9 · Snowballing bidireccional

**Prompt para Copilot:**

> Crea `excavador/snowball.py` con `snowball(seeds: list[PaperRecord], openalex: OpenAlexClient, k: int) -> list[RawHit]`:
> 1. Toma los k seeds con mayor `relevance_score` que tengan id de OpenAlex o DOI resoluble.
> 2. Hacia atrás: `get_references` de cada seed → ids de OpenAlex → `enrich` en lote (endpoint `/works?filter=openalex_id:W1|W2|...`, hasta 50 por request; añade este método al cliente si no existe).
> 3. Hacia adelante: `get_citing` de cada seed (máx. 100 por seed).
> 4. Devuelve RawHits sin filtrar ni deduplicar (eso lo hace la pipeline), pero sí deduplicados entre sí por external_id para no enriquecer dos veces.
> Registra con `logging` cuántos hits aporta cada dirección. Tests con httpx mock: 2 seeds → verifica que se piden referencias y citantes de ambos y que el batch de enriquecimiento agrupa ids.

**Hecho cuando:** tests en verde; logging muestra conteos por dirección.

---

### T10 · Descarga de PDFs (solo OA)

**Prompt para Copilot:**

> Crea `excavador/download.py` con `download_pdf(record: PaperRecord, raw: dict | None, pdf_dir: Path, client: httpx.Client) -> str | None`:
> 1. Obtiene URL candidata SOLO de fuentes OA: `best_oa_location.pdf_url` u `open_access.oa_url` del payload de OpenAlex, u `openAccessPdf.url` de S2. Si no hay, devuelve None. PROHIBIDO construir URLs de editoriales o resolver DOIs a ciegas.
> 2. Descarga con timeout 30 s, verifica que los primeros bytes sean `%PDF`, guarda como `{paper_id con ':' y '/' reemplazados por '_'}.pdf` en pdf_dir.
> 3. Si el archivo ya existe, no re-descarga (idempotencia). Errores de red o contenido no-PDF → None + log warning, nunca excepción.
> Tests: mock de descarga válida, contenido HTML (no PDF) → None, archivo preexistente no dispara request.

**Hecho cuando:** tests en verde; corrida real descarga ≥ 1 PDF de SciELO/Redalyc vía URL OA.

---

### T11 · Pipeline

**Prompt para Copilot:**

> Crea `excavador/pipeline.py` con `run(tema: str, max_papers: int, settings: Settings) -> PipelineStats`. Secuencia:
> 1. Búsqueda: OpenAlex `search(tema)` + OpenAlex `search_exact_phrase` con cada frase entrecomillada que aparezca en el tema (si no hay comillas, usa el tema entero como frase) + Crossref + Semantic Scholar.
> 2. Normalizar todos los RawHits (T5); inválidos → descartados `invalid_record`.
> 3. Dedup (T6) contra sí mismos Y contra `storage.known_dois()`; duplicados → descartados `duplicate` (solo los nuevos; los ya en DB simplemente se saltan).
> 4. Scoring (T7); bajo umbral → descartados `low_relevance` CON su score.
> 5. Snowball (T9) sobre los aceptados; los hits nuevos repiten pasos 2–4.
> 6. Enriquecimiento canónico (T5) de los aceptados sin abstract o sin references.
> 7. Descarga de PDFs (T10) de los aceptados.
> 8. Upsert de todo en storage. Corta en max_papers aceptados (por score descendente).
> Devuelve `PipelineStats` (pydantic): conteos por etapa, % con PDF, % con DOI, duración. Todo el flujo debe ser re-ejecutable sin duplicar (los upserts lo garantizan). Tests: pipeline completa con las 3 APIs mockeadas y 20 hits sintéticos que cubren los tres motivos de descarte; segunda ejecución no cambia `storage.count()`.

**Hecho cuando:** test de pipeline en verde; segunda corrida idéntica no altera la DB.

---

### T12 · CLI

**Prompt para Copilot:**

> Crea `excavador/__main__.py` con `typer`: comando `run --tema TEXT --max-papers 300 --threshold FLOAT (opcional, pisa Settings)`. Imprime PipelineStats como tabla legible al final. Añade comando `stats` que lee la DB y muestra: total papers, % con PDF, % con DOI, top-20 por relevance_score (título, año, score), y conteo de descartados por motivo. Test: invocar `run` con pipeline mockeada vía `typer.testing.CliRunner`.

**Hecho cuando:** `python -m excavador run --tema "..." --max-papers 10` corre extremo a extremo con red real.

---

### T13 · Corrida real + calibración (manual, sin Copilot)

Ejecutar:

```
python -m excavador run \
  --tema 'recepción crítica de la obra de "Bolívar Echeverría", filosofía de la cultura, modernidad barroca, valor de uso' \
  --max-papers 300
```

Checklist contra criterios de aceptación (recalibrados):

- [ ] ≥ 100 PaperRecord válidos según C1.
- [ ] Cero duplicados por DOI (`SELECT doi, COUNT(*) FROM papers WHERE doi IS NOT NULL GROUP BY doi HAVING COUNT(*)>1` vacío).
- [ ] ≥ 40 % con PDF descargado (criterio recalibrado para humanidades, A8).
- [ ] Re-ejecución completa: `count()` idéntico antes y después.
- [ ] Top-20 por score: revisión humana — claramente sobre Echeverría.
- [ ] Calibración del umbral: revisar `papers_discarded` con score en [0.25, umbral]; si hay falsos descartes relevantes, bajar umbral; si en aceptados hay ruido (papers que solo citan a Echeverría de pasada), subirlo. Documentar el valor final.

---

## E · Decisiones a propagar a `01-CONTRATOS-DE-DATOS.md`

1. **Tabla de parámetros globales — Modelo de embeddings:** `intfloat/multilingual-e5-large` (1024 dims). **Convención obligatoria de prefijos:** `"query: "` para consultas, `"passage: "` para documentos/chunks. Aplica a TODAS las fases (02: relevancia; 03: indexación y retrieve; 04: clustering).
2. **C1 · PaperRecord:** nuevo campo `work_type: Literal["article","book","book-chapter","thesis","other"]` (aditivo). El Procesador (03) lo usará para decidir tratamiento en GROBID.
3. **C1 · paper_id:** precisar formato: `"doi:<doi normalizado>"` preferente; fallback `"<source_api>:<id nativo>"` (el ejemplo original decía `arxiv:<id>`; generalizar).
4. **Nota al pie en 02 (no en 01):** criterio de aceptación 3 recalibrado a ≥ 40 % con PDF para dominios de humanidades en español; tabla `papers_discarded` añadida al diseño; snowballing definido como bidireccional con k=15.
