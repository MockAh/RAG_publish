# 04 · Spec — Clustering + Expertos + Mapa de Síntesis

> Conversación: "Fase Expertos". Leer antes `00` y `01` (contratos C3, C4, C5).
> Estado: **v1.1 · FASE CERRADA (2026-11-05)**. Criterios de aceptación 1–5 cumplidos.
> Plan de tareas: `04-PLAN-MICROTAREAS-EXPERTOS.md` (N0–N14, todas firmadas).
> Lecciones y deuda: `04-REGISTRO-CONSIDERACIONES-EXPERTOS.md`.
> Herencia para la fase siguiente: `04-HERENCIA-PARA-FASE-05.md`.
> Cambios a los documentos maestros: `04-PROPAGACION-A-00-Y-01.md`.
> **Resultados finales:** **9 Expertos** (`C0`–`C8`, k-means k=9, seed 42, run
> `kmeans-k9-seed42-98b2c308`) sobre **154 papers** efectivos (158 indexados − 3 alias
> DOI − 1 excluido por datos cruzados) · **128 claims** en 9 Synthesis, 203/203 chunks
> verificados · `SynthesisMap` de ~1 453 tokens · modo consulta probado con 63 preguntas ·
> 431 tests en verde (+10 slow). Coste de una regeneración completa de síntesis: 0,26 USD.

> **Cambios v1.1 (cierre, N14):** el cuerpo de la v1 se conserva; se añaden notas de cierre
> («→ v1.1») donde la implementación concretó o se apartó de la letra, la sección
> *Resultados de los criterios* y la respuesta a las preguntas abiertas.

---

## Objetivo

Particionar el corpus en clústeres temáticos, instanciar un Experto por clúster, generar
las Synthesis (C3) y construir el SynthesisMap (C4). Además, definir el comportamiento
online del Experto: responder ExpertAnswer (C5) a consultas dirigidas.

## Alcance

### Clustering (código, no LLM)

- Embedding representativo por paper (abstract, o media de sus chunks).
  → v1.1: `passage: título. abstract` para todos (X1); media re-normalizada de chunks solo
  para los 3 indexados sin abstract (A5). Mezclar ambos tipos de vector habría separado por
  tipo de fuente, no por tema. 155 vectores (3 alias DOI colapsados, A6).
- HDBSCAN o k-means sobre esos vectores; objetivo: 5–15 clústeres para un corpus de
  100–500 papers. Papers "ruido" de HDBSCAN → clúster residual "misceláneo".
  → v1.1: k-means sobre vectores normalizados, barrido k = 5–12, HDBSCAN solo de contraste
  (X2). El silhouette es plano en todo el barrido (A7): k=9 se eligió por inspección humana
  (A8). Al no usarse HDBSCAN no hay clúster de ruido; el material marginal quedó en
  clústeres pequeños (C0, 6 papers; C8, 5).
- Etiquetado del clúster: un LLM nombra el tema a partir de 10 títulos + abstracts
  representativos (una llamada por clúster).
  → v1.1: hecho (N5). Etiquetas de producción con Gemini en `data/cluster_labels.json`;
  el campo `coherent` no es reproducible entre proveedores (A13).

### Experto (agente LLM) — dos modos

- **Modo síntesis (offline):** recibe su partición; produce Synthesis con key_claims, cada
  claim con supporting_chunks reales (obtenidos por retrieval sobre su partición, no de
  memoria). Prohibido afirmar sin chunk_id.
  → v1.1: el LLM genera 8–12 sub-consultas → `retrieve` sobre la partición → el LLM redacta
  claims → **el código** valida `supporting_chunks ⊆ recuperados` y descarta la claim
  inválida sin repararla (X3, `expertos/synthesis.py`). La prohibición la garantiza el
  código, no el prompt: cazó un `chunk_id` inventado en N9 (A21). `stance` por pares de
  tesis (A19); obras primarias marcadas (`PRIMARY_WORKS`, A17). Modelo `deepseek-v4-pro`
  (A20).
- **Modo consulta (online):** recibe una pregunta del Orquestador; hace retrieval con
  filter_paper_ids = su partición; responde ExpertAnswer. Si su corpus no cubre la
  pregunta: confidence="low" + campo gaps explicando el hueco.
  → v1.1: `expertos/consult.py` + CLI `ask`. Una llamada al LLM por pregunta; la pregunta
  tal cual es la única consulta, `top_k = 32` (A28), sin sub-consultas (se añaden solo si
  una medición muestra pasajes del corpus que no llegan). Sin evidencia válida, la prosa del
  LLM se tira y la respuesta es `low` por regla estructural (C9 del registro). `gaps` se
  refiere a los pasajes leídos, no a todo el corpus. Cada consulta queda auditada en disco
  (C10).

Un Experto NO es un proceso persistente: es un prompt de sistema parametrizado por
expert_id + la restricción de retrieval a su partición.
→ v1.1: así quedó. La partición se lee de la tabla `clusters` con la stoplist aplicada
(`load_corpus_assignment`, E4).

### Mapa de Síntesis

Se regenera tras cada ingesta. Tamaño total objetivo: que el mapa completo quepa holgado en
el contexto del Orquestador (≤ ~4 000 tokens).
→ v1.1: `expertos/synthesis_map.py` + CLI `map build`, sin LLM, en `data/synthesis_map.json`.
La regeneración tras ingesta es una secuencia manual de CLI (`vectors` → `cluster` →
`synthesis retrieve` → `synthesis draft` → `map build`); la regeneración selectiva por
Jaccard (Q1) no está implementada (B3 del registro).

## No-alcance

- NO ruteo de preguntas (Orquestador, fase 05).
- NO redacción de artículos.

## Criterios de aceptación

1. Los clústeres son temáticamente coherentes a revisión humana (inspeccionar 3 al azar).
2. Toda Synthesis cumple C3 y el 100 % de sus supporting_chunks existen (validar con
   get_chunk).
3. Muestreo manual: 10 claims al azar; ≥ 9 realmente sustentadas por su pasaje.
4. En modo consulta, ante una pregunta fuera de su tema, el Experto responde
   confidence="low" y NO inventa (probar con 5 preguntas trampa).
5. El SynthesisMap completo ≤ 4 000 tokens.

### Resultados de los criterios (v1.1)

| # | Resultado | Tarea | Evidencia | Matiz |
|---|---|---|---|---|
| 1 | ✓ k=9 elegido por inspección humana | N4 | A8, `data/cluster_sweep_report.md` | El etiquetado marcó `coherent=false` en C1 y C8 (A13); C7 es un volumen de homenaje, no un tema (A9). C4 no expone esa marca al Orquestador (E7) |
| 2 | ✓ 9/9 Synthesis válidas contra C3; 203/203 `get_chunk` existen | N9 | A21–A22 | 1 claim de 129 descartada por `chunk_id` inventado |
| 3 | ✓ 10/10 sustentadas (100 % ponderada y cruda) | N10 | A23, `data/synthesis/_review/N10-muestra.md` | Muestra estratificada a propósito, no al azar simple (A23). Fallos se habrían clasificado en *claim infiel* / *chunk roto*. E6: el miembro `contradicts` de un par no sustenta la atribución en su propio chunk |
| 4 | ✓ trampas 45/45 en `low`, ninguna atribuye tesis a un autor ausente; controles 18/18 responden | N13 | A27–A28, `data/consult_traps/` | 5 trampas por Experto (2 fáciles + 3 difíciles) + 2 controles. Juicio del usuario. Fidelidad de la prosa de los controles y cita textual sin medir (A26 → 05) |
| 5 | ✓ ~1 453 tokens de 4 000 | N11 | A25 | Medido con el tokenizador de DeepSeek; el conteo offline es pesimista a propósito |

## Preguntas abiertas → respuestas (v1.1)

- **¿Re-clusterizar desde cero en cada ingesta o asignar incrementalmente?** → Desde cero,
  con semilla fija; solo se regeneran las síntesis de clústeres cuya composición cambie
  (Jaccard < 0.8) (Q1). Decidido, **no implementado**: con 0,26 USD por regeneración completa
  (A22), regenerar todo es aceptable hasta que el corpus crezca (B3).
- **¿Síntesis jerárquicas si un clúster supera N papers?** → No en v1 (Q2). Gatillo para
  reabrir: un clúster con > 40 papers o > 600 chunks. El mayor es C2 con 35 papers.
- **Prompt exacto del Experto en cada modo.** → Redactado y probado en el código, con tests
  trampa por micro-tarea (Q3): sub-consultas en `build_subqueries_prompt` y claims en
  `build_draft_prompt` (`expertos/synthesis.py`, N7–N8); consulta en `build_answer_prompt`
  (`expertos/consult.py`, N12–N13). El código es la fuente de verdad, no esta spec.
