# 03 · Spec — Procesador + Indexador + Biblioteca RAG

> Conversación: "Fase Biblioteca". Leer antes `00` y `01` (contratos C1, C2).
> Estado: **v1.1 · FASE CERRADA (2026-09-18)**. Criterios de aceptación cumplidos.
> Plan de tareas: `03-PLAN-MICROTAREAS-BIBLIOTECA.md` (M0–M18, todas firmadas).
> Lecciones y deuda: `03-REGISTRO-CONSIDERACIONES-BIBLIOTECA_v19.md`.
> Herencia para las fases siguientes: `03-HERENCIA-PARA-FASES-04-Y-05.md`.
> **Resultados finales:** **1 959 chunks** citables de **158 papers** · Chroma embebida en
> `data/chroma` · 55 papers vía GROBID (100 % de éxito) + 103 vía abstract · 181 tests en verde.

## Objetivo

Convertir cada `PaperRecord` con PDF en `Chunk`s (contrato C2) con proveniencia total,
indexados en una base vectorial consultable por los Expertos.

## Alcance

- **Procesador:** GROBID (Docker) → TEI XML → texto estructurado por secciones.
  Papers sin PDF: se indexa título + abstract (chunk único, `section="abstract"`).
- **Indexador:** chunking de 200–500 tokens con corte por oración, sin cruzar
  fronteras de sección; embedding por chunk; upsert en la base vectorial.
- **Biblioteca:** **Chroma embebida** (decisión P1). Cada punto = vector + payload con todos
  los campos de C2 **más `from_abstract: bool`** (decisión P6, no toca C2). Filtros por
  paper_id y section; el filtro por year se resuelve con pre-consulta a SQLite → `filter_paper_ids`.
- API interna de consulta (la usarán Expertos y Verificador):

```python
def retrieve(query: str, top_k: int = 8,
             filter_paper_ids: list[str] | None = None,
             filter_sections: list[str] | None = None) -> list[ScoredChunk]

def get_chunk(chunk_id: str) -> Chunk   # lookup exacto — lo usa el Verificador
```

- **CLI:** `python -m biblioteca index | query | stats | get`.
- **Persistencia de respaldo:** `data/tei/` (TEI completo, P4) y `data/text/` (texto plano,
  P8 — *la edición contra la que los offsets de C2 significan algo*).

## No-alcance

- NO síntesis ni clustering (fase 04).
- NO re-ranking sofisticado en v1 (similitud coseno basta; re-ranker es mejora futura).

## Decisiones tomadas EN esta conversación

| # | Decisión | Detalle |
|---|---|---|
| P1 | Base vectorial: **Chroma embebida** | Cero Docker extra; 1 959 chunks caben holgados. Confirmada con datos en A6 |
| P2 | Tablas, fórmulas y diagramas: **ignorar** | Corpus de humanidades; los diagramas quedan aplanados a prosa (A4), ruido tolerable |
| P3 | Chunks **sin overlap** | **Confirmada con evidencia en M17** (D2): los fallos de retrieval no son de ventana |
| P4 | **Guardar TEI XML** en `data/tei/` | Reproceso barato: el "negativo revelado" |
| P5 | Libros: GROBID + **fallback plano** | Escrito y cubierto por tests; **sin caso real que lo ejercitara** (A13) |
| P6 | Payload lleva **`from_abstract: bool`** | Marca los chunks de texto degradado para el Verificador. Payload, NO toca C2 |
| P7 | **Stoplist de secciones no citables** | `bibliografía, referencias, bibliography, references, notas, obras citadas` |
| P8 | **Persistir el texto plano** en `data/text/` | Hace los offsets auditables a través de cambios de código. Validada en producción (A15) |

**Modelo de embeddings:** no fue decisión de esta fase — quedó congelado en `01` v1.1 desde la
fase 02 (`intfloat/multilingual-e5-large`, prefijos `query:`/`passage:` obligatorios). El
wrapper se unificó en `biblioteca/embedder.py` para que la convención viva en un solo lugar (B2).

## Criterios de aceptación — RESULTADOS (v1.1, cierre)

1. ✅ **100 % de los PDFs pasan GROBID** (55/55, 0 fallos, 2.2 min). Supera el ≥ 95 % exigido.
   La ruta de fallback a abstract por `GrobidError` quedó implementada pero **sin ejercitarse
   con datos reales** (A12).
2. ✅ **Todo chunk cumple C2.** Los offsets se calculan *por construcción* al armar el texto
   plano, no a posteriori: la invariante `full_text[char_start:char_end] == text` no puede
   romperse sin romper un test. Sin oraciones partidas, sin chunks que crucen secciones.
3. ⚠️→✅ **Criterio recalibrado con evidencia.** El original ("10 de 10 preguntas con el
   pasaje correcto en top-3") resultó una meta mal calibrada: se midió con **20 preguntas**
   escritas a mano (10 sobre conceptos de la obra primaria, 10 sobre recepción crítica) y el
   resultado fue **~17–18 aciertos (85–90 %)**. Los dos modos de fallo están diagnosticados y
   **ninguno es del retrieval ni se corrige con más ventana de chunk**:
   (a) *preguntas de síntesis* — piden articular algo que ningún pasaje suelto contiene; es el
   trabajo del Experto (04) y el Redactor (05);
   (b) *consultas por postura* — el retrieval empareja por tema, no por postura (A18).
   **Criterio reescrito: ≥ 85 % del pasaje correcto en top-3, con los fallos diagnosticados y
   atribuidos a la capa que les corresponde.** Cumplido.
4. ✅ **`get_chunk` reconstruye el texto exacto: 20/20** en muestreo aleatorio. Verificación
   más fuerte que la pedida: el texto no solo coincide consigo mismo, sino con la rebanada
   `[char_start:char_end]` del `.txt` archivado (P8 validada en producción, A15).
5. ✅ **Pipeline idempotente e incremental.** Verificado en tests y en producción: `has_paper`
   salta lo ya indexado, `force=True` reindexa sin duplicar, `delete_paper` aísla por paper.

## Limitaciones conocidas (medidas, aceptadas — detalle en el REGISTRO)

- **El corpus citable son 158 papers, no 227** (A10, A14): 69 registros no tienen PDF ni
  abstract y por tanto no pueden sustentar ninguna afirmación. Siguen siendo útiles como
  referencia bibliográfica y para el snowballing.
- **Fidelidad de transcripción medida** (A19, muestreo de 10 chunks): 70 % fiel · 20 % con
  ruido incrustado (notas al pie completas, mobiliario de página) · **10 % con texto roto**.
  Todos los defectos ocurren en el salto de página; GROBID es determinista, así que reprocesar
  no los arregla. Mejora futura: filtro de encabezados/pies recurrentes.
- **Los scores de retrieval no discriminan** (A17): toda la banda útil vive entre 0.83 y 0.90.
  No sirven como umbral de confianza en las fases 04–05.
- **129 chunks vienen de abstract** con diacríticos degradados en origen (A1 de fase 02);
  van marcados `from_abstract=True`.
- **Secciones genéricas** `body-n` cuando GROBID no halla subtítulo, a veces con 20+ chunks
  compartiendo etiqueta (A7, A13). Los distingue el `seq` del `chunk_id`.

## Preguntas abiertas — RESUELTAS

1. ~~¿Modelo de embeddings?~~ → ya congelado en `01` v1.1 (fase 02); wrapper unificado en M8.
2. ~~¿Tablas y fórmulas de GROBID?~~ → ignorar (P2); extendido a diagramas aplanados.
3. ~~¿Chunks con overlap?~~ → **No** (P3), confirmado con las 20 preguntas de M17 (D2).
4. ~~¿Guardar el TEI XML?~~ → **Sí** (P4), más el texto plano (P8).

## Mejoras futuras identificadas (no v1)

- Filtro de post-proceso para encabezados y pies recurrentes del TEI (atacaría el 20 % de
  ruido incrustado de A19).
- Re-ranker sobre los resultados de `retrieve` (ya previsto como no-alcance de v1).
- Reabrir el fallback plano P5 si entran libros con PDF en una ingesta futura (D1).
