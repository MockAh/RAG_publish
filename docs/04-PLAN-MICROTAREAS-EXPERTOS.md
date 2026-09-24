# 04 · Plan de micro-tareas — Clustering + Expertos + Mapa de Síntesis

> Deriva de `04-SPEC-EXPERTOS-Y-SINTESIS.md`. Formato: sesiones de ~15 min/día.
> Regla de trabajo: cada día se ejecuta UNA micro-tarea. En la conversación se pide
> «dame el prompt de N_n» y se recibe el prompt para Copilot de esa tarea, nada más.
> Herencia de fase 03: 158 papers indexables · 1 959 chunks · el score NO mide confianza (L1) ·
> el retrieval empareja por tema, no por postura (L2) · ~10 % de chunks de cuerpo rotos (E6).

---

## A · Decisiones cerradas en N0 (2026-09-19)

| # | Decisión | Detalle |
|---|---|---|
| Q1 | **Re-clusterizar desde cero** en cada ingesta, con semilla fija | Solo se regeneran las síntesis de clústeres cuya composición cambió (Jaccard < 0.8). Clusterizar 158 puntos tarda segundos; lo caro son las llamadas LLM |
| Q2 | **Sin síntesis jerárquicas en v1** | Gatillo para reabrir: un clúster con > 40 papers o > 600 chunks |
| Q3 | **Cada prompt de agente tiene su micro-tarea**, con tests trampa | Método heredado de fase 03 |
| X1 | Vector representativo = `passage: título. abstract` (de SQLite) para todos | Mezclar vectores de abstract con medias de ~33 chunks haría que el clustering separe por tipo de fuente, no por tema. Media de chunks solo para indexados sin abstract |
| X2 | **k-means sobre vectores normalizados, barrido k = 5–12**, HDBSCAN como contraste | Con 158 puntos en 1024 dims y banda estrecha, HDBSCAN manda demasiado a ruido. Se conserva el clúster «misceláneo» para el front-matter (D1 de fase 02) |
| X3 | **Síntesis sin alucinación por construcción:** el LLM genera 8–12 sub-consultas → `retrieve` sobre la partición → el LLM redacta claims → el código valida `supporting_chunks ⊆ recuperados`. Claim inválido se descarta, no se repara | «Prohibido afirmar sin chunk_id» lo garantiza el código, no el prompt |
| X4 | **`stance` se clasifica por pasaje** sobre material recuperado por tema | L2: buscar «críticas a X» devuelve exposiciones de X |
| X5 | Paquete `expertos/`. Tabla SQLite `clusters(paper_id, expert_id, run_id)`; `data/synthesis/{expert_id}.json` (C3); `data/synthesis_map.json` (C4) | Persistencia auditable, patrón de P4/P8 |
| X6″ | **Síntesis y etiquetado en `gemini-3.6-flash`** | Los Pro son inaccesibles en el free tier: 2.5 retirado, 3.1 con cuota cero (ver A4 del registro). Escapes si N10 sale flojo: activar los créditos de Cloud, o `gemini-3.8-flash` |
| X7 | Los chunks `from_abstract` son citables, pero el prompt prefiere un chunk de PDF cuando ambos sustentan la claim | E1 de fase 03: texto degradado |
| X8 | **Cliente LLM agnóstico de proveedor:** `LLMClient.complete_json(system, user, schema) -> BaseModel` | Cambiar de proveedor es una línea de config. Habilita D11 |

**A propagar a `00`:**
- **D10:** los agentes LLM se acceden vía interfaz agnóstica de proveedor (X8). El stack por defecto de §4 deja de decir «API de Anthropic» y pasa a «proveedor configurable; fase 04 usa Gemini API».
- **D11:** el Verificador (fase 05) usa un proveedor distinto al del Redactor. Es decisión de arquitectura, no solo de la fase 05.

**Ajuste al criterio de aceptación 3 de la spec:** al muestrear claims, clasificar cada fallo
como *claim infiel* o *chunk roto* (E6 de fase 03). Solo el primero cuenta contra el Experto.

---

## B · Micro-tareas

Convenciones: mismo repo, paquete `expertos/`. Python 3.12, pydantic v2, tests por tarea,
un commit por tarea firmada (F2). `.venv` siempre (F1). Prueba manual desde la raíz del
repo antes de firmar cualquier módulo con CLI o con entrada de entorno (A11 de fase 03).

| # | Tarea (~15 min) | Hecho cuando |
|---|---|---|
| N0 | Confirmar Q1–Q3 y X1–X8; anotar en la spec 04 | Decisiones cerradas por escrito |
| N1 | Bootstrap `expertos/`: Settings, `LLMClient`/`GeminiClient`, tabla `llm_calls` | `Ping(ok=True)` real desde la raíz del repo + fila en `llm_calls` |
| N2 | Vectores representativos de los 158 papers → `.npy` | Test de prefijos; conteo = 158 |
| N3 | Barrido de clustering (k = 5–12) + HDBSCAN de contraste; informe de silhouette y tamaños | Informe generado |
| N4 | Inspección humana de 3 clústeres; elegir k | Criterio 1 cumplido |
| N5 | Etiquetado LLM: una llamada por clúster (10 títulos + abstracts) | Etiquetas persistidas |
| N6 | Modelos C3/C4/C5 + persistencia en `data/synthesis/` | Round-trip JSON en verde |
| N7 | Modo síntesis 1/2: sub-consultas y `retrieve` sobre la partición | Test con store dummy |
| N8 | Modo síntesis 2/2: claims, `stance` y validación `⊆ recuperados` | Test: un chunk_id ajeno se descarta |
| N9 | **Corrida completa de síntesis** (desatendida) | Criterio 2: 100 % de los `get_chunk` existen |
| N10 | Muestreo manual de 10 claims, con clasificación del tipo de fallo | Criterio 3 medido |
| N11 | `SynthesisMap` (C4) con conteo de tokens | Criterio 5: ≤ 4 000 tokens |
| N12 | Modo consulta: `ExpertAnswer` (C5), `confidence` juzgada por el LLM | Test con store dummy |
| N13 | 5 preguntas trampa fuera del tema de cada Experto | Criterio 4 medido |
| N14 | Cierre de fase: checklist, registro, propagación a 00/01 | Spec 04 marcada CERRADA |

## C · Dependencias

```
N1 ─► N2 ─► N3 ─► N4 ─► N5 ─► N6 ─► N7 ─► N8 ─► N9 ─► N10 ─► N14
                                      N11 ◄─────────┘
                                      N12 ─► N13 ─────────────┘
```

N9 es corrida desatendida: se lanza al final de la sesión y se revisa al día siguiente.

## D · Riesgos conocidos al entrar

- **Corpus monotemático:** todo trata de Echeverría; los clústeres serán subtemas con
  separación débil. El silhouette será bajo por naturaleza, no por fallo (se decide con
  inspección humana, no con la métrica).
- **~10 % de chunks de cuerpo rotos** (E6 de fase 03): aprieta el criterio 3. Por eso N10
  clasifica el tipo de fallo en vez de contar aciertos a secas.
- **105 de los 158 papers aportan un solo chunk de abstract** degradado: el peso real del
  corpus verificable está en los 55 con PDF (E3 de fase 03).
- **Cuota del free tier de Gemini:** el modelo elegido tiene 1 500 peticiones diarias, pero
  la disponibilidad puede cambiar sin aviso (ver A4 del registro).
