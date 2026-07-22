# 03 · Plan de micro-tareas — Procesador + Indexador + Biblioteca RAG

> Deriva de `03-SPEC-BIBLIOTECA-RAG.md`. Formato: sesiones de ~15 min/día.
> Regla de trabajo: cada día se ejecuta UNA micro-tarea. En la conversación se pide
> «dame el prompt de M_n» y se recibe el prompt para Copilot de esa tarea, nada más.
> Herencia de fase 02: 227 papers · 55 con PDF · e5 multilingüe con prefijos
> `query:`/`passage:` · abstracts con diacríticos degradados (A1) · ~4 % chunks
> duplicados tolerables (C5).

---

## A · Decisiones propuestas (confirmar en M0, propagar a 01 si aplica)

| # | Decisión propuesta | Razón |
|---|---|---|
| P1 | Base vectorial: **Chroma embebida** (no Qdrant) | Cero Docker extra; 227 papers ≈ 2–5 k chunks, sobra; migrable después. Filtro por `year`: pre-consulta a SQLite → `filter_paper_ids` (C2 no lleva year). |
| P2 | Tablas y fórmulas de GROBID: **ignorar en v1** | Corpus de humanidades, casi no hay (E1 del registro 02). |
| P3 | Chunks **sin overlap** en v1 | Se mide en M17 con las 10 preguntas; overlap solo si falla top-3. |
| P4 | **Guardar TEI XML** completo en `data/tei/` | Reproceso barato; recomendado ya en la spec. |
| P5 | Libros (`work_type=book/book-chapter`): intentar GROBID igual; si el TEI no trae secciones útiles → **fallback: segmentación plana por párrafos con `section="body"`** | GROBID está afinado para papers; se verifica con datos en M15. |

## B · Micro-tareas

Convenciones: mismo repo, nuevo paquete `biblioteca/`. Python 3.12, pydantic v2,
tests por tarea, un commit por tarea firmada (F2). `.venv` siempre (F1).

| # | Tarea (~15 min) | Hecho cuando |
|---|---|---|
| M0 | Confirmar/vetar P1–P5; anotar en spec 03 | Decisiones cerradas por escrito |
| M1 | Bootstrap: paquete `biblioteca/`, deps (`chromadb`, `lxml`), Settings extendida (`grobid_url`, `tei_dir`, `chroma_dir`) | `pytest` verde; Settings lee entorno |
| M2 | Levantar GROBID en Docker + smoke test con 1 PDF real vía `curl` (sin código) | Un `.tei.xml` legible en disco |
| M3 | `models.py`: `Chunk` (C2 exacto) + `SectionText` interno | Round-trip JSON en verde; campos 1:1 con C2 |
| M4 | Cliente GROBID: `process_fulltext(pdf_path) -> str` (TEI), guarda en `tei_dir`, no reprocesa si ya existe | Test con fixture; idempotente |
| M5 | Parser TEI 1/2: abstract + secciones del body (título + párrafos) con lxml | Test con TEI fixture real recortado |
| M6 | Parser TEI 2/2: texto plano por sección con `char_start`/`char_end` | Test: offsets reconstruyen el texto exacto |
| M7 | Sentence splitter + chunker 200–500 tokens, corte por oración, sin cruzar secciones | Tests: ninguna oración partida, ningún chunk cruza sección |
| M8 | Embedder compartido: extraer wrapper e5 (prefijo `passage:`) reutilizable desde `relevance.py` | Test de prefijos; excavador sigue en verde |
| M9 | Store Chroma: colección, `upsert_chunks`, `get_chunk(chunk_id)` | Tests con embeddings dummy; upsert idempotente |
| M10 | `retrieve(query, top_k, filter_paper_ids, filter_sections)` con prefijo `query:` | Test: filtros respetados, orden por score |
| M11 | Ruta sin PDF: chunk único `section="abstract"` | Test con PaperRecord `pdf_path=None` |
| M12 | Pipeline de indexación: itera SQLite, salta papers ya indexados, `IndexStats` | Test: segunda corrida no re-procesa nada |
| M13 | CLI: `python -m biblioteca index` y `python -m biblioteca query "..."` | Corre extremo a extremo con 2–3 papers |
| M14 | **Corrida real GROBID** sobre los 55 PDFs (lanzar y dejar; revisar log al día siguiente) | Log de éxitos/fallos; medir criterio 1 (≥ 95 %) |
| M15 | Inspección de TEI de 1–2 libros; activar fallback P5 si hace falta | Decisión documentada con evidencia |
| M16 | **Indexación completa** (227 papers) + verificación `get_chunk` exacto | Criterio 4 ✓; conteo de chunks anotado |
| M17 | Escribir 10 preguntas de prueba a mano; medir top-3 | Criterio 3 medido (10/10 o diagnóstico); decidir overlap (P3) con datos |
| M18 | Cierre de fase: checklist de criterios, registro de consideraciones diferidas, propagar cambios a 00/01 | Spec 03 marcada CERRADA |

## C · Dependencias

```
M0 ─► M1 ─► M3 ─► M4* ─► M5 ─► M6 ─► M7 ─► M9 ─► M10 ─► M12 ─► M13 ─► M14 ─► M16 ─► M17 ─► M18
      M2 ──────────┘        M8 ────────┘    M11 ──┘              M15 ──┘
```
\* M4 necesita M2 (GROBID vivo). M8 puede hacerse cualquier día tras M1.
M14 y M16 son corridas desatendidas: se lanzan al final de la sesión y se revisan al día siguiente.

## D · Riesgos conocidos al entrar

- Papers sin PDF (172/227) → texto citable de baja calidad tipográfica (A1 de fase 02).
- Libros mal parseados por GROBID → P5.
- Frontera numpy→persistencia: convertir a tipos nativos SIEMPRE (F5 de fase 02).
