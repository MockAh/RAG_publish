# 03 · Cambios a propagar a `00` y `01` (cierre de fase, 2026-09-18)

> Aplicar estos cambios a mano en los documentos maestros. Son pocos y aditivos:
> **ningún contrato existente se rompe**.
> **✅ Aplicado el 2026-11-06** (junto con la propagación de fase 04): `01` v1.3, `00` v1.2.

---

## A · `01-CONTRATOS-DE-DATOS.md` → v1.2

### A1 · C2 · Chunk — añadir nota sobre el payload (el esquema NO cambia)

Debajo del bloque de código de C2, añadir:

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

### A2 · Nuevo bloque tras C2 · API de la Biblioteca

> ## Biblioteca — API de consulta (fase 03, estable)
>
> ```python
> from biblioteca.config import Settings
> from biblioteca.store import ChunkStore
>
> st = ChunkStore(Settings().chroma_dir)
> st.retrieve(query, top_k=8, filter_paper_ids=None, filter_sections=None)  # -> list[ScoredChunk]
> st.get_chunk(chunk_id)   # -> Chunk | None — lookup exacto, requisito del Verificador
> st.has_paper(paper_id) ; st.delete_paper(paper_id) ; st.count()
> ```
>
> `ScoredChunk`: `chunk: Chunk`, `score: float` (coseno en [0,1] = `1 − distancia`),
> `from_abstract: bool`.
>
> **Advertencia medida (fase 03):** el `score` **no es una medida de confianza utilizable**.
> Toda la banda útil de este corpus cae entre 0.83 y 0.90, y el ruido evidente puntúa dentro
> de ella. Ni la `confidence` de C5 ni los veredictos de C7 pueden derivarse de umbrales
> numéricos: el juicio lo hace el LLM leyendo el pasaje.

### A3 · Tabla de parámetros globales — añadir filas

| Parámetro | Valor v1.2 |
|---|---|
| Base vectorial | **Chroma embebida** en `data/chroma` (decisión P1, fase 03). Migrable a Qdrant si el corpus crece |
| Tamaño real de chunk | banda medida **200–280 tokens** (`min_tokens` gobierna el cierre; `max_tokens=500` queda prácticamente inerte). Sin overlap, decidido con evidencia en M17 |
| Texto de referencia de los offsets | `data/text/<paper_id saneado>.txt` (P8) |

---

## B · `00-VISION-Y-ARQUITECTURA.md`

### B1 · Sección 5 · Orden de implementación

Marcar el estado de las fases:

> 1. ✅ Congelar contratos (`01`) — v1.2
> 2. ✅ Excavador + Filtro (`02`) — CERRADA 2026-07-06 · 227 papers
> 3. ✅ Procesador + Indexador + Biblioteca (`03`) — CERRADA 2026-09-18 · 1 959 chunks de 158 papers
> 4. ⬜ Clustering + Expertos + Mapa de Síntesis (`04`)
> 5. ⬜ Orquestador + Redactor + Verificador (`05`)

### B2 · Sección 3 · Decisiones ya tomadas — añadir filas

| # | Decisión | Razón |
|---|---|---|
| D7 | Base vectorial: **Chroma embebida**, no Qdrant | Un contenedor menos; el corpus (≈2 000 chunks) cabe holgado. Migrable |
| D8 | **El corpus citable no es el corpus recuperado** | 158 de 227 papers tienen texto indexable; los 69 restantes sirven como referencia bibliográfica, no como sustento de afirmaciones |
| D9 | **Ningún juicio del sistema se deriva de umbrales de similitud** | Medido en fase 03: la banda útil es 0.83–0.90 y el ruido vive dentro. Confianza y entailment son juicios del LLM sobre el texto, no comparaciones numéricas |

### B3 · Sección 2 · Arquitectura — precisar la Fase A

> **Fase A — Ingesta (offline, periódica):**
> Excavador → Filtro/Dedup → Procesador (GROBID) → Indexador → **Biblioteca RAG**
> *Papers sin PDF entran por una ruta alterna: título + abstract como chunk único marcado
> `from_abstract=True`.*
