# 04 · Spec — Clustering + Expertos + Mapa de Síntesis

> Conversación: "Fase Expertos". Leer antes `00` y `01` (contratos C3, C4, C5).
> Estado: v1 · depende de Biblioteca funcional (fase 03).
> Aquí empiezan los agentes LLM.

## Objetivo

Particionar el corpus en clústeres temáticos, instanciar un Experto por clúster,
generar las `Synthesis` (C3) y construir el `SynthesisMap` (C4). Además, definir el
comportamiento online del Experto: responder `ExpertAnswer` (C5) a consultas dirigidas.

## Alcance

### Clustering (código, no LLM)
- Embedding representativo por paper (abstract, o media de sus chunks).
- HDBSCAN o k-means sobre esos vectores; objetivo: 5–15 clústeres para un corpus
  de 100–500 papers. Papers "ruido" de HDBSCAN → clúster residual "misceláneo".
- Etiquetado del clúster: un LLM nombra el tema a partir de 10 títulos + abstracts
  representativos (una llamada por clúster).

### Experto (agente LLM) — dos modos
- **Modo síntesis (offline):** recibe su partición; produce `Synthesis` con
  `key_claims`, cada claim con `supporting_chunks` reales (obtenidos por retrieval
  sobre su partición, no de memoria). Prohibido afirmar sin chunk_id.
- **Modo consulta (online):** recibe una pregunta del Orquestador; hace retrieval
  con `filter_paper_ids = su partición`; responde `ExpertAnswer`. Si su corpus no
  cubre la pregunta: `confidence="low"` + campo `gaps` explicando el hueco.

Un Experto NO es un proceso persistente: es un prompt de sistema parametrizado por
`expert_id` + la restricción de retrieval a su partición.

### Mapa de Síntesis
- Se regenera tras cada ingesta. Tamaño total objetivo: que el mapa completo quepa
  holgado en el contexto del Orquestador (≤ ~4 000 tokens).

## No-alcance

- NO ruteo de preguntas (Orquestador, fase 05).
- NO redacción de artículos.

## Criterios de aceptación

1. Los clústeres son temáticamente coherentes a revisión humana (inspeccionar 3 al azar).
2. Toda Synthesis cumple C3 y el 100 % de sus supporting_chunks existen
   (validar con `get_chunk`).
3. Muestreo manual: 10 claims al azar; ≥ 9 realmente sustentadas por su pasaje.
4. En modo consulta, ante una pregunta fuera de su tema, el Experto responde
   `confidence="low"` y NO inventa (probar con 5 preguntas trampa).
5. El SynthesisMap completo ≤ 4 000 tokens.

## Preguntas abiertas

- ¿Re-clusterizar desde cero en cada ingesta o asignar papers nuevos al clúster
  más cercano (incremental)?
- ¿Síntesis jerárquicas (sub-temas) si un clúster supera N papers?
- Prompt exacto del Experto en cada modo: redactarlo y probarlo en esta conversación.
