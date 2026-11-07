# 05 · Spec — Orquestador + Redactor + Verificador

> Conversación: "Fase Consulta". Leer antes `00` y `01` (contratos C4–C7).
> Estado: **v1 + decisiones de R0 (2026-11-07)** · depende de Expertos funcionales (fase 04,
> CERRADA 2026-11-05). Última fase. El cuerpo de la v1 se conserva literal; lo decidido en R0
> va en la sección final y, en detalle, en la sección A del plan (Y1–Y14).
> Plan de tareas: `05-PLAN-MICROTAREAS-CONSULTA.md`. Lecciones y deuda:
> `05-REGISTRO-CONSIDERACIONES-CONSULTA.md`. Herencia: `04-HERENCIA-PARA-FASE-05.md` y
> `03-HERENCIA-PARA-FASES-04-Y-05.md`.

## Objetivo

Implementar el flujo online completo: pregunta del usuario → texto académico con citas
verificadas contra la Biblioteca.

## Flujo (secuencia ①–⑥ de la Figura 1)

1. Usuario envía pregunta o encargo ("escribe la sección de estado del arte sobre X").
2. **Orquestador** lee el SynthesisMap completo, descompone el encargo en sub-preguntas y
   las asigna a Expertos (1–4 por encargo; puede consultar en paralelo).
3. **Expertos** devuelven ExpertAnswer (C5).
4. **Redactor** recibe pregunta + answers; produce DraftSection (C6):
   - Cada oración factual termina en `[n]`; el mapa n → chunk_ids va en `citations`.
   - Afirmación sin evidencia disponible → se marca ⟨sin fuente⟩, nunca se cita en falso.
5. **Verificador** — para cada par (oración, chunk):
   - `get_chunk(chunk_id)` → si no existe: `chunk_not_found`.
   - Juicio de entailment con LLM: ¿el pasaje sustenta la afirmación tal como está escrita?
     Atención explícita a alcance (población, condiciones, magnitudes): pasaje correcto
     pero afirmación sobregeneralizada → `scope_mismatch`.
   - Produce VerificationReport (C7).
   - Si `passed=False`: el reporte vuelve al Redactor (máx. 3 ciclos). Oraciones que sigan
     fallando → ⟨sin verificar⟩ visible en el texto final.
6. **Salida al usuario:** texto + bibliografía numerada (chunk_ids → paper: autores, año,
   título, DOI, sección citada).

## Reglas de los agentes

- **Orquestador:** nunca hace retrieval directo ni lee papers; solo mapa + expertos. Si el
  mapa no cubre la pregunta, lo dice y sugiere ampliar el corpus (nueva ingesta).
- **Redactor:** prohibido introducir hechos que no vengan en las ExpertAnswer. Estilo:
  registro académico, sin adjetivos promocionales.
- **Verificador:** no reescribe; solo juzga y reporta. Un LLM distinto prompt (idealmente
  distinta "personalidad") al del Redactor para evitar auto-complacencia.

## Criterios de aceptación

1. Extremo a extremo con corpus real: pregunta → texto con ≥ 90 % de oraciones factuales
   citadas y verificadas.
2. Cero citas a chunk_ids inexistentes en la salida final.
3. Prueba adversarial: inyectar al Redactor una afirmación falsa plausible; el Verificador
   debe atraparla (`not_entailed`).
4. Prueba de alcance: afirmación sobregeneralizada a partir de un pasaje acotado; el
   Verificador debe marcar `scope_mismatch` (esta es la falla residual conocida: medir su
   tasa, no asumir perfección).
5. Pregunta fuera del corpus → el sistema lo declara en vez de responder.

## Preguntas abiertas

- Formato final de bibliografía (¿APA? ¿BibTeX exportable?).
- ¿El usuario puede pedir "profundiza en [3]" y navegar al chunk? (muy deseable).
- Presupuesto de llamadas por consulta (coste): fijar tope y medirlo.

→ R0: bibliografía = Y12; «profundiza en [3]» = Y13; presupuesto = Y11.

## Decisiones de R0 (2026-11-07)

Resumen; el detalle y las razones están en `05-PLAN-MICROTAREAS-CONSULTA.md`, sección A.

| # | Decisión |
|---|---|
| Y1 | Paquete `redaccion/` (prefijo `REDACCION_`, `extra="ignore"`); reutiliza `expertos.llm` y `answer_question`. Produce **secciones verificadas**, no el artículo ensamblado. `interaccion/` reservado para una fase futura de discusión previa |
| Y2 | Verificador con **Gemini**; Orquestador y Redactor con **DeepSeek** (D11). Modelo de Gemini (3.6-flash frente a 3.8-flash) elegido en R2 con llamadas reales. Tier de pago, si hace falta, con el crédito de Google AI Pro |
| Y3 | Tamaño de bandeja del Verificador parametrizable (1 = pieza por pieza, N = charola). Arranque con charola; R11–R12 comparan ambos. `chunk_not_found` por código. En ciclos 2–3 solo se re-verifica lo que cambió |
| Y4 | El Redactor recibe solo claims de `evidence` + texto completo de cada chunk (`from_abstract` visible) + `gaps`. La prosa de `answer` no entra (A26); alternativa B solo si R13 muestra secciones pobres |
| Y5 | El código retira toda cita a un `chunk_id` fuera de `evidence` → ⟨sin fuente⟩, y registra cada retirada |
| Y6 | Segmentación y emparejado por código, con índice estable. `[n]` siempre al final de la oración. Catálogo de abreviaturas: corpus + normas de referencia + errores hallados en R13 |
| Y7 | Registro por pieza (aparte de C7, que no cambia), con veredicto explícito para todas, `ok` incluido |
| Y8 | Toda pieza es factual salvo *transición* o *meta-texto* marcados; la síntesis entre fuentes es factual. Pieza sin cita ni marca = fallo. Se mide la proporción de exentas |
| Y9 | Pares E6: atribución y objeción en piezas separadas, cada una con su chunk. Un chunk `contradicts` solo sostiene la objeción. Solo 2 de 7 `contradicts` tienen gemelo `supports` |
| Y10 | Fuera de corpus en dos niveles (mapa sin Experto; Expertos `low` sin evidencia) + caso intermedio (se redacta con los que aportan y se avisan los `gaps` del resto) |
| Y11 | Tope por puesto: Orquestador 1, Expertos ≤ 4, Redactor ≤ 3; Verificador contado en piezas. Corte con ⟨sin verificar⟩ registrado. `consultation_id` en `llm_calls` |
| Y12 | Bibliografía numerada «APA reducido» con aviso de datos faltantes (no hay volumen, número ni páginas en `papers`); sin exportación en v1 |
| Y13 | «Profundiza en [n]» muestra el chunk (texto, paper, sección, veredicto), con vecinos opcionales; sin LLM |
| Y14 | `coherent` no entra a C4 en v1; R4 mide el ruteo hacia C1, C7 y C8 |

Contratos: **ninguno cambia** en R0. C6 y C7 se transcriben literales en R1; el registro por
pieza (Y7) es un modelo interno, como `ConsultRecord` en fase 04.
