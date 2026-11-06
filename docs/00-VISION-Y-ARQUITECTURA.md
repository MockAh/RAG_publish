# 00 · Visión y arquitectura

> Documento maestro del proyecto. Todas las conversaciones deben leerlo primero.
> Estado: v1.2 · vivo (v1.1: cierre de fase 03; v1.2: cierre de fase 04; aplicados 2026-11-06). Si una decisión cambia, se actualiza AQUÍ y en el contrato afectado.

## 1. Qué construimos

Un sistema multiagente de **investigación y escritura de artículos científicos** con citas
verificables. El usuario hace una pregunta o encarga una sección; el sistema responde con
prosa académica donde cada afirmación factual está citada y cada cita fue cotejada contra
el corpus.

## 2. Arquitectura (resumen)

Dos fases desacopladas por una memoria compartida:

**Fase A — Ingesta (offline, periódica):**
Excavador → Filtro/Dedup → Procesador (GROBID) → Indexador → **Biblioteca RAG**
*Papers sin PDF entran por una ruta alterna: título + abstract como chunk único marcado
`from_abstract=True`.*
Después: clustering temático → Expertos generan síntesis → **Mapa de Síntesis**

**Fase B — Consulta (online):**
Usuario → Orquestador (lee el Mapa, rutea) → Expertos (retrieval sobre sus particiones)
→ Redactor (prosa con citas [n]) → Verificador (entailment cita↔pasaje) → Usuario

**Memoria compartida:**
- *Biblioteca RAG*: base vectorial + metadatos. Fuente de verdad citable.
- *Mapa de Síntesis*: índice compacto (tema → resumen → expertos → papers).

## 3. Decisiones ya tomadas (no reabrir sin causa)

| # | Decisión | Razón |
|---|----------|-------|
| D1 | Excavador usa APIs académicas (arXiv, OpenAlex, Semantic Scholar, Crossref), NO scraping libre | Robustez, legalidad, metadatos limpios |
| D2 | Expertos por clúster temático, NO por autor | Escala con temas, no con bibliografía |
| D3 | El Orquestador es un agente separado del RAG | El RAG es memoria; el Orquestador la consulta |
| D4 | Redactor y Verificador son obligatorios en Fase B | Sin ellos no hay escritura ni control de citas alucinadas |
| D5 | Proveniencia total: cada chunk lleva DOI + sección + offsets | Requisito para citas verificables |
| D6 | Filtro, Procesador e Indexador son código convencional (no agentes LLM) | Usan modelos (embeddings, GROBID) pero sin razonamiento agéntico |
| D7 | Base vectorial: **Chroma embebida**, no Qdrant | Un contenedor menos; el corpus (≈2 000 chunks) cabe holgado. Migrable |
| D8 | **El corpus citable no es el corpus recuperado** | 158 de 227 papers tienen texto indexable; los 69 restantes sirven como referencia bibliográfica, no como sustento de afirmaciones |
| D9 | **Ningún juicio del sistema se deriva de umbrales de similitud** | Medido en fase 03: la banda útil es 0.83–0.90 y el ruido vive dentro. Confianza y entailment son juicios del LLM sobre el texto, no comparaciones numéricas |
| D10 | Los agentes LLM se acceden vía una interfaz agnóstica de proveedor (`LLMClient.complete_json(system, user, schema)`) | Cambiar de proveedor es una línea de configuración; hace posible D11. La fase 04 pasó de Gemini a DeepSeek (X6‴) sin tocar código de agentes |
| D11 | El Verificador (fase 05) usa un proveedor LLM distinto al del Redactor | Decisión de arquitectura, no solo de la fase 05 (tomada en N0 de fase 04). Ya es posible sin tocar código de agentes gracias a D10 |
| D12 | Las restricciones de cita las garantiza el código, no el prompt | En fase 04 la validación `supporting_chunks ⊆ recuperados` cazó un `chunk_id` inventado con apariencia realista (A21) |

## 4. Stack por defecto (cámbialo si hay mejor razón, y documenta el cambio)

- **Lenguaje:** Python 3.12, `httpx` para APIs, `pydantic` para todos los esquemas.
- **Parsing de PDF:** GROBID vía Docker.
- **Base vectorial:** Chroma embebida en `data/chroma` (D7); Qdrant si el corpus crece.
- **Metadatos relacionales:** SQLite (suficiente hasta ~10⁵ papers).
- **Embeddings:** un solo modelo para todo el proyecto; se fija en `01-CONTRATOS-DE-DATOS.md`.
- **Agentes LLM:** proveedor configurable tras una interfaz común (D10); cada agente = un
  prompt de sistema + herramientas, no un proceso aparte. Fase 04: DeepSeek
  (`deepseek-flash` para etiquetado, `deepseek-v4-pro` para síntesis y consulta);
  Gemini (`gemini-3.6-flash`) reservado como segundo proveedor para D11. Elegidos por
  disponibilidad, no por calidad de juicio medida. Toda llamada queda en la tabla
  SQLite `llm_calls`.

## 5. Orden de implementación

1. ✅ Congelar contratos (`01`) — v1.3
2. ✅ Excavador + Filtro (`02`) — CERRADA 2026-07-06 · 227 papers
3. ✅ Procesador + Indexador + Biblioteca (`03`) — CERRADA 2026-09-18 · 1 959 chunks de 158 papers
4. ✅ Clustering + Expertos + Mapa de Síntesis (`04`) — CERRADA 2026-11-05 · 9 Expertos sobre 154 papers
5. ⬜ Orquestador + Redactor + Verificador (`05`)

Cada fase tiene criterios de aceptación en su spec. No se avanza a la siguiente
sin cumplirlos.

## 6. Cómo trabajar en este Proyecto

- Una conversación por spec. Al abrirla: "Trabajamos la spec 0X. Lee 00 y 01 primero."
- Si una conversación toma una decisión que afecta un contrato compartido,
  el usuario actualiza `01-CONTRATOS-DE-DATOS.md` en el conocimiento del Proyecto
  antes de continuar en otras conversaciones.
- Las "Preguntas abiertas" al final de cada spec son la agenda de esa conversación.
