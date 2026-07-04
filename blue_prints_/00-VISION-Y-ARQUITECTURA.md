# 00 · Visión y arquitectura

> Documento maestro del proyecto. Todas las conversaciones deben leerlo primero.
> Estado: v1 · vivo. Si una decisión cambia, se actualiza AQUÍ y en el contrato afectado.

## 1. Qué construimos

Un sistema multiagente de **investigación y escritura de artículos científicos** con citas
verificables. El usuario hace una pregunta o encarga una sección; el sistema responde con
prosa académica donde cada afirmación factual está citada y cada cita fue cotejada contra
el corpus.

## 2. Arquitectura (resumen)

Dos fases desacopladas por una memoria compartida:

**Fase A — Ingesta (offline, periódica):**
Excavador → Filtro/Dedup → Procesador (GROBID) → Indexador → **Biblioteca RAG**
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

## 4. Stack por defecto (cámbialo si hay mejor razón, y documenta el cambio)

- **Lenguaje:** Python 3.12, `httpx` para APIs, `pydantic` para todos los esquemas.
- **Parsing de PDF:** GROBID vía Docker.
- **Base vectorial:** Qdrant (local vía Docker) o Chroma para el prototipo.
- **Metadatos relacionales:** SQLite (suficiente hasta ~10⁵ papers).
- **Embeddings:** un solo modelo para todo el proyecto; se fija en `01-CONTRATOS-DE-DATOS.md`.
- **Agentes LLM:** API de Anthropic; cada agente = un prompt de sistema + herramientas, no un proceso aparte.

## 5. Orden de implementación

1. Congelar contratos (`01`)
2. Excavador + Filtro (`02`)
3. Procesador + Indexador + Biblioteca (`03`)
4. Clustering + Expertos + Mapa de Síntesis (`04`)
5. Orquestador + Redactor + Verificador (`05`)

Cada fase tiene criterios de aceptación en su spec. No se avanza a la siguiente
sin cumplirlos.

## 6. Cómo trabajar en este Proyecto

- Una conversación por spec. Al abrirla: "Trabajamos la spec 0X. Lee 00 y 01 primero."
- Si una conversación toma una decisión que afecta un contrato compartido,
  el usuario actualiza `01-CONTRATOS-DE-DATOS.md` en el conocimiento del Proyecto
  antes de continuar en otras conversaciones.
- Las "Preguntas abiertas" al final de cada spec son la agenda de esa conversación.
