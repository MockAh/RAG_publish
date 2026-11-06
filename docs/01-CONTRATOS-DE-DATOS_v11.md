# 01 · Contratos de datos

> **El documento más importante del Proyecto.** Las conversaciones no se ven entre sí;
> estos esquemas son su única frontera común. Cualquier cambio aquí debe propagarse
> a todas las conversaciones activas.
> Estado: **v1.3** · esquemas en pseudocódigo Pydantic; la conversación de cada fase los
> refina SIN romper compatibilidad con los campos ya definidos.
> Cambios v1.1 (desde conversación 02, 2026-07-04): modelo de embeddings fijado;
> convención de prefijos e5; C1 gana `work_type`; formato de `paper_id` generalizado.
> Cambios v1.2 (cierre de fase 03, 2026-09-18; aplicados 2026-11-06): nota de payload en C2
> (`from_abstract`, `section`, offsets); API de la Biblioteca; parámetros de Chroma y chunk.
> Cambios v1.3 (cierre de fase 04, 2026-11-05; aplicados 2026-11-06): notas en C3 (`Claim`,
> `stance` por pares) y C5 (`gaps`, `confidence`); contenedor `SynthesisMap`; parámetros de
> clustering y retrieval. **Ningún esquema existente cambia** en v1.2 ni en v1.3.
> Nombre de archivo: sigue siendo `_v11.md` porque código y tests lo leen por ruta.

## C1 · PaperRecord — salida del Excavador, entrada del Procesador

```python
class PaperRecord(BaseModel):
    paper_id: str            # interno, estable: "doi:<doi normalizado>" preferente;
                             # fallback "<source_api>:<id nativo>" (ej. "openalex:W2741809807")
    doi: str | None
    title: str
    authors: list[str]
    year: int
    venue: str | None
    abstract: str
    source_api: Literal["arxiv", "openalex", "semanticscholar", "crossref", "pubmed"]
    work_type: Literal["article", "book", "book-chapter", "thesis", "other"]  # v1.1
    pdf_path: str | None     # ruta local; None si no se obtuvo PDF
    relevance_score: float   # 0–1, similitud abstract↔tema (asignado por el Filtro)
    references_ids: list[str]  # paper_ids citados, si la API los da (para snowballing)
    ingested_at: datetime
```

> **Nota v1.1 sobre `work_type`:** el corpus del primer tema (recepción de Bolívar
> Echeverría) incluye libros y capítulos, no solo artículos. El Procesador (fase 03)
> debe usar este campo para decidir el tratamiento en GROBID (un libro no se parsea
> igual que un paper).

## C2 · Chunk — salida del Indexador, unidad citable de la Biblioteca

```python
class Chunk(BaseModel):
    chunk_id: str            # f"{paper_id}#{section}#{seq}"
    paper_id: str
    section: str             # "abstract" | "introduction" | "methods" | "results" | ...
    text: str                # 200–500 tokens aprox., sin partir oraciones
    char_start: int          # offsets sobre el texto extraído del paper
    char_end: int
    embedding_model: str     # nombre+versión exactos del modelo usado
    # el vector vive en la base vectorial, indexado por chunk_id
```

**Regla de proveniencia (D5):** ninguna afirmación del sistema puede citar algo
que no sea un `chunk_id`. Se cita el pasaje, nunca "el paper".

> **Nota v1.2 (fase 03):** los chunks viven en **Chroma embebida** (`data/chroma`), un punto
> por `chunk_id`. El `text` es el documento de Chroma; el resto de campos de C2 va en el
> metadata, **más un campo de payload que no forma parte del contrato**:
>
> - `from_abstract: bool` — `True` cuando el chunk proviene del abstract de SQLite en vez del
>   PDF. Ese texto es tipográficamente degradado en origen (diacríticos rotos de OpenAlex).
>   El Verificador (fase 05) debe conocerlo antes de juzgar un `not_entailed`.
>
> Se mantiene fuera de C2 deliberadamente: es información sobre la *procedencia del texto*,
> no sobre el chunk como unidad citable.
>
> **Sobre `section`:** en humanidades el valor es el `<head>` textual del TEI (a veces un
> numeral romano, a veces un título temático) o el fallback `body-{n}` cuando GROBID no halla
> subtítulo. El vocabulario STEM de los ejemplos ("methods", "results") es ilustrativo, no
> normativo.
>
> **Sobre los offsets:** `char_start`/`char_end` indexan el texto plano archivado en
> `data/text/<paper_id saneado>.txt` (decisión P8 de fase 03), no una cadena reconstruida al
> vuelo. Reprocesar el TEI con otras reglas de parseo produciría otra cadena y los offsets
> guardados apuntarían a otro pasaje, en silencio.

## Biblioteca — API de consulta (fase 03, estable; v1.2)

```python
from biblioteca.config import Settings
from biblioteca.store import ChunkStore

st = ChunkStore(Settings().chroma_dir)
st.retrieve(query, top_k=8, filter_paper_ids=None, filter_sections=None)  # -> list[ScoredChunk]
st.get_chunk(chunk_id)   # -> Chunk | None — lookup exacto, requisito del Verificador
st.has_paper(paper_id) ; st.delete_paper(paper_id) ; st.count()
```

`ScoredChunk`: `chunk: Chunk`, `score: float` (coseno en [0,1] = `1 − distancia`),
`from_abstract: bool`.

**Advertencia medida (fase 03):** el `score` **no es una medida de confianza utilizable**.
Toda la banda útil de este corpus cae entre 0.83 y 0.90, y el ruido evidente puntúa dentro
de ella. Ni la `confidence` de C5 ni los veredictos de C7 pueden derivarse de umbrales
numéricos: el juicio lo hace el LLM leyendo el pasaje.

## C3 · Synthesis — salida de un Experto (offline), entrada del Mapa

```python
class Synthesis(BaseModel):
    synthesis_id: str
    expert_id: str           # = cluster_id
    topic_label: str         # etiqueta humana del clúster
    summary: str             # 300–800 palabras
    key_claims: list[Claim]
    paper_ids: list[str]     # corpus que cubre
    updated_at: datetime

class Claim(BaseModel):
    text: str                # afirmación atómica
    supporting_chunks: list[str]  # chunk_ids que la sustentan
    stance: Literal["supports", "contradicts", "mentions"]
```

> **Nota v1.3 (fase 04):** una `Claim` con `supporting_chunks=[]` es inválida (lo exige D5:
> nada se afirma sin `chunk_id`). La implementación lo valida con `min_length=1`, también
> dentro de `ExpertAnswer.evidence` (C5). Además, todo `chunk_id` debe estar entre los
> pasajes que el Experto recuperó: la claim que cite otro se **descarta, no se repara**
> (X3 de fase 04).
>
> **Semántica de `stance` (fase 04, A19):** cuando una tesis tiene defensores y críticos en
> el corpus, el Experto emite un **par** de claims con el mismo texto de la tesis: una
> `supports` (cita el pasaje que la atribuye) y otra `contradicts` (cita el pasaje que la
> discute). El chunk del miembro `contradicts` no sustenta la atribución por sí solo
> (E6 → fase 05).

## C4 · SynthesisMap — lo único que lee el Orquestador para rutear

```python
class SynthesisMapEntry(BaseModel):
    expert_id: str
    topic_label: str
    one_liner: str           # ≤ 40 palabras; el mapa completo debe caber en un contexto
    n_papers: int
    keywords: list[str]
```

**Contenedor `SynthesisMap` (v1.3, decisión de fase 04).** C4 define solo la entrada; el
archivo `data/synthesis_map.json` es este contenedor:

```python
class SynthesisMap(BaseModel):
    run_id: str              # run de clustering del que sale la partición
    updated_at: datetime
    entries: list[SynthesisMapEntry]   # C4 literal; expert_id único
```

Tamaño medido: ~1 453 tokens para 9 entradas (criterio ≤ 4 000).

## C5 · ExpertAnswer — respuesta de un Experto al Orquestador (online)

```python
class ExpertAnswer(BaseModel):
    expert_id: str
    question: str
    answer: str              # prosa breve
    evidence: list[Claim]    # cada afirmación con sus chunk_ids
    confidence: Literal["high", "medium", "low"]
    gaps: str | None         # "mi corpus no cubre X"
```

> **Nota v1.3 (fase 04):** `gaps` no tiene default: el Experto siempre se pronuncia, y
> `None` significa «los pasajes leídos cubren la pregunta». `gaps` se refiere a los
> pasajes recuperados, no a todo el corpus del Experto. Sin ninguna claim válida, la
> respuesta es `confidence="low"` con prosa fija, sea cual sea el juicio del LLM.
> `confidence` es juicio del LLM, no umbral numérico (L1), y solo se ha medido que separa
> preguntas trampa de controles (N13).

## C6 · DraftSection — salida del Redactor, entrada del Verificador

```python
class DraftSection(BaseModel):
    text: str                # prosa con marcadores [1], [2], ...
    citations: dict[int, list[str]]   # nº de cita → chunk_ids
    unsupported_marked: bool # las afirmaciones sin cita van marcadas ⟨sin fuente⟩
```

## C7 · VerificationReport — salida del Verificador

```python
class VerificationReport(BaseModel):
    passed: bool
    failures: list[CitationFailure]

class CitationFailure(BaseModel):
    sentence: str
    chunk_id: str
    reason: Literal["not_entailed", "scope_mismatch", "chunk_not_found"]
```

Si `passed == False`, el Orquestador devuelve `failures` al Redactor (máx. 3 ciclos;
después, las oraciones fallidas se marcan ⟨sin verificar⟩ y se reporta al usuario).

## Parámetros globales congelados

| Parámetro | Valor (v1.3; la versión de origen de cada fila nueva va entre paréntesis) |
|---|---|
| Modelo de embeddings | `intfloat/multilingual-e5-large` (1024 dims, multilingüe — el corpus mezcla es/en/pt/de). **Decidido en conversación 02.** |
| **Convención de prefijos e5 (OBLIGATORIA)** | Toda consulta se embebe con prefijo `"query: "`; todo documento/chunk con prefijo `"passage: "`. Sin esto los espacios vectoriales no son comparables. Aplica a TODAS las fases: 02 (relevancia), 03 (indexación y `retrieve`), 04 (clustering). |
| Tamaño de chunk | 200–500 tokens, corte por oración |
| Formato de cita en prosa | numérico `[n]`, mapeado a chunk_ids en C6 |
| Base vectorial (v1.2) | **Chroma embebida** en `data/chroma` (decisión P1, fase 03). Migrable a Qdrant si el corpus crece |
| Tamaño real de chunk (v1.2) | banda medida **200–280 tokens** (`min_tokens` gobierna el cierre; `max_tokens=500` queda prácticamente inerte). Sin overlap, decidido con evidencia en M17 |
| Texto de referencia de los offsets (v1.2) | `data/text/<paper_id saneado>.txt` (P8) |
| Clustering de Expertos (v1.3) | k-means sobre vectores `passage: título. abstract` normalizados, **k = 9**, seed 42 (k elegido por inspección humana, no por silhouette). Re-clusterizar desde cero en cada ingesta. |
| Retrieval del modo consulta (v1.3) | Pregunta tal cual como única consulta, `top_k = 32`, filtrada a la partición del Experto |
| Retrieval del modo síntesis (v1.3) | 8–12 sub-consultas generadas por el LLM; 6–15 claims por Synthesis |
