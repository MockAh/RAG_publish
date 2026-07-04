# 01 · Contratos de datos

> **El documento más importante del Proyecto.** Las conversaciones no se ven entre sí;
> estos esquemas son su única frontera común. Cualquier cambio aquí debe propagarse
> a todas las conversaciones activas.
> Estado: **v1.1** · esquemas en pseudocódigo Pydantic; la conversación de cada fase los
> refina SIN romper compatibilidad con los campos ya definidos.
> Cambios v1.1 (desde conversación 02, 2026-07-04): modelo de embeddings fijado;
> convención de prefijos e5; C1 gana `work_type`; formato de `paper_id` generalizado.

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

## C4 · SynthesisMap — lo único que lee el Orquestador para rutear

```python
class SynthesisMapEntry(BaseModel):
    expert_id: str
    topic_label: str
    one_liner: str           # ≤ 40 palabras; el mapa completo debe caber en un contexto
    n_papers: int
    keywords: list[str]
```

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

| Parámetro | Valor v1.1 |
|---|---|
| Modelo de embeddings | `intfloat/multilingual-e5-large` (1024 dims, multilingüe — el corpus mezcla es/en/pt/de). **Decidido en conversación 02.** |
| **Convención de prefijos e5 (OBLIGATORIA)** | Toda consulta se embebe con prefijo `"query: "`; todo documento/chunk con prefijo `"passage: "`. Sin esto los espacios vectoriales no son comparables. Aplica a TODAS las fases: 02 (relevancia), 03 (indexación y `retrieve`), 04 (clustering). |
| Tamaño de chunk | 200–500 tokens, corte por oración |
| Formato de cita en prosa | numérico `[n]`, mapeado a chunk_ids en C6 |
