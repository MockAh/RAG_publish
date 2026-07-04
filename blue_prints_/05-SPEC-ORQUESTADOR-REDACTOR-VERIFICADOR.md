# 05 · Spec — Orquestador + Redactor + Verificador

> Conversación: "Fase Consulta". Leer antes `00` y `01` (contratos C4–C7).
> Estado: v1 · depende de Expertos funcionales (fase 04). Última fase.

## Objetivo

Implementar el flujo online completo: pregunta del usuario → texto académico con
citas verificadas contra la Biblioteca.

## Flujo (secuencia ①–⑥ de la Figura 1)

1. Usuario envía pregunta o encargo ("escribe la sección de estado del arte sobre X").
2. **Orquestador** lee el `SynthesisMap` completo, descompone el encargo en sub-preguntas
   y las asigna a Expertos (1–4 por encargo; puede consultar en paralelo).
3. Expertos devuelven `ExpertAnswer` (C5).
4. **Redactor** recibe pregunta + answers; produce `DraftSection` (C6):
   - Cada oración factual termina en `[n]`; el mapa n → chunk_ids va en `citations`.
   - Afirmación sin evidencia disponible → se marca ⟨sin fuente⟩, nunca se cita en falso.
5. **Verificador** — para cada par (oración, chunk):
   - `get_chunk(chunk_id)` → si no existe: `chunk_not_found`.
   - Juicio de entailment con LLM: ¿el pasaje sustenta la afirmación tal como está
     escrita? Atención explícita a *alcance* (población, condiciones, magnitudes):
     pasaje correcto pero afirmación sobregeneralizada → `scope_mismatch`.
   - Produce `VerificationReport` (C7).
6. Si `passed=False`: el reporte vuelve al Redactor (máx. 3 ciclos). Oraciones que
   sigan fallando → ⟨sin verificar⟩ visible en el texto final.
7. Salida al usuario: texto + bibliografía numerada (chunk_ids → paper: autores, año,
   título, DOI, sección citada).

## Reglas de los agentes

- **Orquestador:** nunca hace retrieval directo ni lee papers; solo mapa + expertos.
  Si el mapa no cubre la pregunta, lo dice y sugiere ampliar el corpus (nueva ingesta).
- **Redactor:** prohibido introducir hechos que no vengan en las `ExpertAnswer`.
  Estilo: registro académico, sin adjetivos promocionales.
- **Verificador:** no reescribe; solo juzga y reporta. Un LLM distinto prompt
  (idealmente distinta "personalidad") al del Redactor para evitar auto-complacencia.

## Criterios de aceptación

1. Extremo a extremo con corpus real: pregunta → texto con ≥ 90 % de oraciones
   factuales citadas y verificadas.
2. Cero citas a chunk_ids inexistentes en la salida final.
3. Prueba adversarial: inyectar al Redactor una afirmación falsa plausible;
   el Verificador debe atraparla (`not_entailed`).
4. Prueba de alcance: afirmación sobregeneralizada a partir de un pasaje acotado;
   el Verificador debe marcar `scope_mismatch` (esta es la falla residual conocida:
   medir su tasa, no asumir perfección).
5. Pregunta fuera del corpus → el sistema lo declara en vez de responder.

## Preguntas abiertas

- Formato final de bibliografía (¿APA? ¿BibTeX exportable?).
- ¿El usuario puede pedir "profundiza en [3]" y navegar al chunk? (muy deseable).
- Presupuesto de llamadas por consulta (coste): fijar tope y medirlo.
