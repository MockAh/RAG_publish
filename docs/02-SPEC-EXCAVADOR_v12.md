# 02 · Spec — Excavador + Filtro/Dedup

> Conversación: "Fase Excavador". Leer antes `00` y `01` (contratos C1).
> Estado: **v1.2 · FASE CERRADA (2026-07-06)**. Criterios de aceptación cumplidos.
> Plan de tareas: `02-PLAN-IMPLEMENTACION-EXCAVADOR.md` (T0–T13, todos firmados).
> Lecciones y deuda: `02-REGISTRO-CONSIDERACIONES-DIFERIDAS.md`.
> **Resultados finales:** corpus de 227 papers · umbral de relevancia **0.78** (calibrado
> con evidencia; default en config) · 24.2 % con PDF (techo del dominio, ver criterio 3) ·
> 57.3 % con DOI · cero duplicados por DOI · tabla de descartados poblada (28 dup /
> 3 inválidos / 12 baja relevancia).

## Objetivo

Dado un **tema de investigación** (texto libre del usuario), producir un corpus de
`PaperRecord` (contrato C1) relevante, deduplicado y con PDF descargado cuando sea posible.

**Primer tema de prueba:** recepción crítica de la obra de Bolívar Echeverría
(énfasis en *La definición de la cultura*; corpus mayormente en español).

## Alcance

- Traducir el tema a consultas para las APIs. Prioridad para este dominio (humanidades
  en español): **OpenAlex** (columna vertebral; indexa SciELO, Redalyc, repositorios
  institucionales) > **Crossref** > **Semantic Scholar**. arXiv y PubMed quedan como
  stubs con interfaz común, sin implementar en v1.
- **Búsqueda dual** (tema-autor): semántica por embedding + exacta por frase
  («Bolívar Echeverría») vía filtro `title_and_abstract.search` de OpenAlex.
- **OpenAlex como normalizador canónico:** todo hit, venga de donde venga, se intenta
  enriquecer vía OpenAlex (DOI, referencias, flag OA, URL de PDF).
- Expansión por *snowballing* **bidireccional**, 1 nivel, k=15 semillas por score:
  referencias (hacia atrás) + `cited_by` de OpenAlex (hacia adelante).
- Descarga de PDF solo desde fuentes de acceso abierto (`best_oa_location` /
  `open_access` de OpenAlex/Unpaywall; `openAccessPdf` de S2). Si no hay OA, se
  conserva el registro con `pdf_path = None`.
- Deduplicación: por DOI normalizado; sin DOI, por título normalizado (sin acentos)
  + año.
- Puntuación de relevancia: similitud coseno entre embedding del abstract y embedding
  del tema, con `intfloat/multilingual-e5-large` y prefijos obligatorios
  `query:`/`passage:` (ver parámetros globales en `01`). Umbral default 0.35,
  **a calibrar en T13** con la tabla de descartados (en tema-autor probablemente suba).
- **Auditoría de descartes:** tabla `papers_discarded` (espejo de C1 +
  `discard_reason: low_relevance | duplicate | invalid_record` + score obtenido).

## No-alcance (explícito)

- NO scraping de sitios de editoriales ni de Sci-Hub.
- NO parsing de PDF (eso es fase 03).
- NO agentes LLM en el flujo principal. Excepción opcional: un LLM puede reformular el
  tema en 3–5 consultas de búsqueda al inicio (una sola llamada, salida = lista de strings).

## Diseño

```
excavador/
  __main__.py      # CLI (typer)
  config.py        # Settings (pydantic-settings)
  models.py        # C1 PaperRecord + RawHit + DiscardedRecord
  apis/            # base.py (rate limit + retry) + un cliente por API
  normalize.py     # RawHit -> PaperRecord parcial + enriquecimiento canónico
  dedup.py
  relevance.py     # e5 multilingüe + umbral
  snowball.py      # bidireccional
  download.py      # PDFs solo OA
  storage.py       # SQLite: papers + papers_discarded; carpeta pdfs/
  pipeline.py      # buscar -> normalizar -> dedup -> puntuar -> snowball -> descargar -> guardar
```

- Respetar rate limits de cada API (OpenAlex: polite pool con `mailto`;
  Crossref: 1 req/s; Semantic Scholar: API key si disponible).
- Todo idempotente: re-ejecutar la pipeline no duplica registros (upsert por paper_id).
- CLI: `python -m excavador run --tema "..." --max-papers 300`

## Criterios de aceptación — RESULTADOS (v1.2, cierre)

1. ✅ 227 PaperRecord válidos según C1 (≥ 100).
2. ✅ Cero duplicados por DOI (query de verificación vacía).
3. ⚠️→✅ **24.2 % con PDF.** Recalibrado dos veces con evidencia: el 60 % original era para
   STEM; el 40 % intermedio tampoco refleja este dominio. Diagnóstico del log de descargas:
   403 de servidores que bloquean clientes sin User-Agent (corregido: UA identificado con
   mailto instalado para corridas futuras) y `oa_url` de OpenAlex apuntando a landing pages
   HTML (rechazadas por el guardián `%PDF-`). **~25 % es el techo medido del dominio con
   OA declarado y sin re-resolución.** Mejora futura si duele: persistir URL de PDF
   candidata en tabla auxiliar local (sin tocar C1).
4. ✅ Re-ejecución sin duplicar nada. Nota: +1 paper legítimo (hit nuevo devuelto por
   OpenAlex entre corridas); el sistema lo incorporó una sola vez. Re-corrida: 47 s vs 491 s.
5. ✅ Top-20 por score validado a ojo humano: inequívocamente sobre Echeverría.
6. ✅ Umbral calibrado: **0.78**, con evidencia en `papers_discarded` (la zona de frontera
   0.77–0.82 mostró relevante y ruido entrelazados; se priorizó no perder relevantes — el
   ruido residual lo aísla el clustering de fase 04). Default actualizado en config.

## Limitaciones conocidas (medidas, aceptadas — detalle en el REGISTRO)

- ~4 % de duplicados DOI-variante (mismo título/año, DOIs distintos) y pares año-divergente:
  la clave de dedup no los cruza, deliberadamente (fusionar por título es peligroso).
- Abstracts de OpenAlex con diacríticos degradados en origen (inocuo para e5 y dedup).
- Solo ~55 papers con PDF para GROBID (fase 03); el resto se indexa por abstract.

## Preguntas abiertas — RESUELTAS (2026-07-04)

1. ~~¿Qué APIs priorizar?~~ → OpenAlex > Crossref > Semantic Scholar (ver Alcance).
2. ~~¿Cuántos papers semilla para el snowballing?~~ → k=15, bidireccional, 1 nivel.
3. ~~¿Guardar los papers descartados?~~ → Sí, tabla `papers_discarded` con motivo y score.

Decisiones propagadas a `01-CONTRATOS-DE-DATOS.md` (v1.1): modelo de embeddings +
convención de prefijos e5; campo `work_type` en C1; formato de `paper_id` generalizado.
