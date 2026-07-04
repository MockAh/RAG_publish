# 03 · Spec — Procesador + Indexador + Biblioteca RAG

> Conversación: "Fase Biblioteca". Leer antes `00` y `01` (contratos C1, C2).
> Estado: v1 · depende de que exista corpus de la fase 02.

## Objetivo

Convertir cada `PaperRecord` con PDF en `Chunk`s (contrato C2) con proveniencia total,
indexados en una base vectorial consultable por los Expertos.

## Alcance

- **Procesador:** GROBID (Docker) → TEI XML → texto estructurado por secciones.
  Papers sin PDF: se indexa solo el abstract (chunk único, section="abstract").
- **Indexador:** chunking de 200–500 tokens con corte por oración, sin cruzar
  fronteras de sección; embedding por chunk; upsert en la base vectorial.
- **Biblioteca:** Qdrant o Chroma. Cada punto = vector + payload con todos los
  campos de C2. Filtros por paper_id, section, year (join con SQLite de fase 02).
- API interna de consulta (la usarán Expertos y Verificador):

```python
def retrieve(query: str, top_k: int = 8,
             filter_paper_ids: list[str] | None = None,
             filter_sections: list[str] | None = None) -> list[ScoredChunk]

def get_chunk(chunk_id: str) -> Chunk   # lookup exacto — lo usa el Verificador
```

## No-alcance

- NO síntesis ni clustering (fase 04).
- NO re-ranking sofisticado en v1 (similitud coseno basta; re-ranker es mejora futura).

## Decisiones a tomar EN ESTA conversación (y propagar a 01)

- **Modelo de embeddings** (único para todo el proyecto). Candidatos: uno multilingüe
  si el corpus mezcla idiomas; uno especializado en texto científico si es todo inglés.
  Al decidir: actualizar tabla de parámetros globales en `01-CONTRATOS-DE-DATOS.md`.
- Estrategia para tablas y fórmulas extraídas por GROBID (¿indexar, ignorar, aparte?).

## Criterios de aceptación

1. ≥ 95 % de los PDFs procesables pasan GROBID sin error fatal (los que fallen,
   se registran y se indexan por abstract).
2. Todo chunk cumple C2: offsets válidos, sección correcta, sin oraciones partidas.
3. `retrieve("<pregunta obvia del corpus>")` devuelve el pasaje correcto en top-3,
   en 10 de 10 preguntas de prueba escritas a mano.
4. `get_chunk(chunk_id)` reconstruye exactamente el texto citado (requisito del Verificador).
5. Pipeline idempotente e incremental: indexar papers nuevos no reprocesa los viejos.

## Preguntas abiertas

- ¿Chunks con solapamiento (overlap) o sin él? Medir con las 10 preguntas de prueba.
- ¿Guardar el TEI XML completo para reprocesos futuros? (recomendado: sí)
