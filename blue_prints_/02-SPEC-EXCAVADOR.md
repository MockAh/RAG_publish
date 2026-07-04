# 02 · Spec — Excavador + Filtro/Dedup

> Conversación: "Fase Excavador". Leer antes `00` y `01` (contratos C1).
> Estado: v1 · lista para implementar.

## Objetivo

Dado un **tema de investigación** (texto libre del usuario), producir un corpus de
`PaperRecord` (contrato C1) relevante, deduplicado y con PDF descargado cuando sea posible.

## Alcance

- Traducir el tema a consultas para las APIs: arXiv, OpenAlex, Semantic Scholar, Crossref.
  (PubMed solo si el tema es biomédico.)
- Expansión por *snowballing*: 1 nivel de referencias de los k papers más relevantes.
- Descarga de PDF solo desde fuentes de acceso abierto (arXiv, campo `open_access` de
  OpenAlex/Unpaywall). Si no hay OA, se conserva el registro con `pdf_path = None`.
- Deduplicación: por DOI normalizado; sin DOI, por título normalizado + año.
- Puntuación de relevancia: similitud coseno entre embedding del abstract y embedding
  del tema. Umbral configurable (default 0.35, calibrar con corpus real).

## No-alcance (explícito)

- NO scraping de sitios de editoriales ni de Sci-Hub.
- NO parsing de PDF (eso es fase 03).
- NO agentes LLM en el flujo principal. Excepción opcional: un LLM puede reformular el
  tema en 3–5 consultas de búsqueda al inicio (una sola llamada, salida = lista de strings).

## Diseño propuesto

```
excavador/
  apis/            # un cliente por API, interfaz común: search(query) -> list[RawHit]
  normalize.py     # RawHit (por API) -> PaperRecord parcial
  dedup.py
  relevance.py     # embeddings + umbral
  snowball.py
  pipeline.py      # orquesta: buscar -> normalizar -> dedup -> puntuar -> snowball -> guardar
  storage.py       # SQLite: tabla papers (espejo de C1) + carpeta pdfs/
```

- Respetar rate limits de cada API (arXiv: 1 req/3s; Semantic Scholar: usar API key).
- Todo idempotente: re-ejecutar la pipeline no duplica registros (upsert por paper_id).
- CLI: `python -m excavador run --tema "..." --max-papers 300`

## Criterios de aceptación

1. Con un tema de prueba real, obtiene ≥ 100 PaperRecord válidos según C1.
2. Cero duplicados por DOI en la salida.
3. ≥ 60 % de los registros con PDF descargado (temas con buena cobertura OA).
4. Re-ejecución completa sin duplicar nada (idempotencia).
5. Los 20 papers con mayor relevance_score son, a ojo humano, claramente del tema.

## Preguntas abiertas (agenda de la conversación)

- ¿Qué APIs priorizar según el dominio del primer tema de prueba?
- ¿Cuántos papers semilla para el snowballing (k) y con qué corte de score?
- ¿Guardar también los papers descartados por el filtro (para auditoría)?
