# 03 → 04/05 · Herencia de la Biblioteca RAG

> Resumen ejecutivo de lo que las fases 04 (Expertos) y 05 (Redactor/Verificador)
> deben saber antes de empezar. Detalle completo en `03-REGISTRO-CONSIDERACIONES-BIBLIOTECA`.
> Estado de la fase 03: M0–M17 firmadas; falta D5 (muestreo) y M18 (cierre).

## 1 · Qué existe y cómo se usa

**Biblioteca operativa:** Chroma embebida en `data/chroma` · **1 959 chunks** de
**158 papers** · modelo `intfloat/multilingual-e5-large` con prefijos obligatorios
`query:` / `passage:`.

```python
from biblioteca.config import Settings
from biblioteca.store import ChunkStore

st = ChunkStore(Settings().chroma_dir)
st.retrieve(query, top_k=8, filter_paper_ids=[...], filter_sections=[...])  # -> list[ScoredChunk]
st.get_chunk(chunk_id)   # -> Chunk | None (lookup exacto, para el Verificador)
```

CLI: `python -m biblioteca query "..." --top-k 5` · `python -m biblioteca get CHUNK_ID`
· `python -m biblioteca stats`.

Archivos de respaldo: `data/tei/` (TEI de GROBID), `data/text/` (**el texto plano contra el
que los offsets de C2 significan algo** — decisión P8), `data/pdfs/` (originales).

## 2 · El corpus real: 158 papers, no 227

| | Papers | Chunks | Calidad del texto |
|---|---|---|---|
| Con PDF (GROBID) | 55 | ~1 830 | Buena; secciones reales |
| Solo abstract | 103 | 129 | **Degradada** (diacríticos rotos en origen) |
| Sin nada citable | 69 | 0 | No existen para la Biblioteca |

- Los **69 omitidos** tienen metadatos válidos pero ni PDF ni abstract: sirven como
  referencia bibliográfica y para snowballing, pero **no pueden sustentar ninguna afirmación**
  (D5 del contrato exige que toda cita apunte a un `chunk_id` real).
- **Fase 04 debe clusterizar sobre los 158 indexados**, no sobre la tabla `papers`.
- Los chunks del abstract llevan `from_abstract=True` en el payload de Chroma (decisión P6).
  Es texto tipográficamente degradado: "Bolvar Echeverra", "investigacion". El Verificador
  debe saberlo antes de juzgar un `not_entailed` que en realidad es ruido de transcripción.

## 3 · Tres límites medidos que condicionan el diseño de 04 y 05

### L1 · El score de retrieval NO mide confianza
Toda la banda útil vive entre **0.828 y 0.901**. El ruido evidente puntúa 0.835; el mejor
acierto, 0.901. Siete centésimas de separación.

**Implicación:** ni la `confidence` del `ExpertAnswer` (C5) ni los veredictos del
`VerificationReport` (C7) pueden derivarse de un umbral numérico. **Todo juicio sobre si un
pasaje sustenta una afirmación lo hace el LLM leyendo el texto.** Un umbral daría falsa
precisión.

### L2 · El retrieval empareja por TEMA, no por POSTURA
Preguntar "¿qué críticas se han hecho a X?" devuelve exposiciones de X. Comprobado: el texto
crítico existía en el corpus y no salió; salieron tres chunks del paper que expone la teoría.

**Implicación para C3:** el campo `stance: supports | contradicts | mentions` **no se puebla
buscando contradicciones**. La vía correcta es recuperar ampliamente por tema y que el LLM
clasifique la postura pasaje por pasaje.

### L3 · Las preguntas de síntesis no tienen un pasaje que las responda
Preguntas del tipo "¿cómo se complementan la dimensión A y la dimensión B?" no fallan por
mal retrieval: ningún chunk suelto las contiene. **Es exactamente el trabajo del Experto
(síntesis) y el Redactor (articulación).** No confundir esto con un fallo de la Biblioteca.

## 4 · Ruido conocido que el Verificador encontrará

- **Chunks-leyenda:** diagramas aplanados a prosa ("N = naturaleza M = medio natural K = materia").
- **Des-guionización imperfecta:** "Jakob-son", "presu-puesto", "finalmen- te".
- **Secciones genéricas:** cuando GROBID no halla subtítulo, la sección se llama `body-1` y
  puede abarcar 20+ chunks. Los distingue el `seq` del `chunk_id`.
- **Bibliografías filtradas** (stoplist P7): ya no llegan chunks de "Bibliografía",
  "Obras citadas", "Referencias", etc.
- **~4 % de chunks duplicados** por DOI-variantes heredados de fase 02 (C5 de aquel registro).
### Fidelidad de transcripción — MEDIDA, no supuesta (muestreo de 10 chunks)

| Veredicto | Tasa | Qué significa para el Verificador |
|---|---|---|
| Fiel | **70 %** | Sin problema |
| Ruido incrustado | **20 %** | Nota al pie completa o mobiliario de página ("d o s s i e r", nombres de autores, pie de revista) insertado a mitad de oración. **No se pierde texto**: el contenido sigue ahí y es citable |
| Roto | **10 %** | Texto perdido en el salto de página; la oración queda sin sujeto ni sentido |

**Todos los defectos ocurren en el salto de página** — GROBID reconstruye mal el orden de
lectura en maquetación latinoamericana (dos columnas + notas al pie + encabezados corridos).
No se repara: GROBID es determinista, reprocesar da el mismo error.

**Regla para el Verificador:** si un pasaje sale `not_entailed` y además **no tiene sentido
gramatical**, la causa probable es transcripción, no cita falsa del Redactor. Del `chunk_id`
se llega al PDF en un paso para comprobarlo. No castigar al Redactor por un chunk roto.

## 5 · Cobertura temática (evidencia de M17)

20 preguntas manuales, ~17–18 con el pasaje correcto en top-3. **Hallazgo que corrige una
expectativa pesimista de la fase 02:** aunque las obras primarias de Echeverría no están en el
corpus (sin PDF abierto), la literatura secundaria **glosa y cita el aparato conceptual con
detalle** — ethos (realista, romántico, barroco), blanquitud vs. blancura, modernidad vs.
modernidad capitalista, valor de uso, la lectura de *El capital*, la relación con Benjamin y
Jakobson, y la biografía intelectual. El corpus sostiene afirmaciones sobre el pensamiento de
Echeverría por vía indirecta y citable.
