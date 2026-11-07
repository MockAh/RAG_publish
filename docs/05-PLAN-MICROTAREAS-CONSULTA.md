# 05 · Plan de micro-tareas — Orquestador + Redactor + Verificador

> Deriva de `05-SPEC-ORQUESTADOR-REDACTOR-VERIFICADOR.md`. Formato: sesiones de ~15 min/día,
> una micro-tarea por sesión.
> Estado: **v1 (2026-11-07)** · decisiones Y1–Y14 **cerradas en R0** con el usuario (sección A).
> Las micro-tareas de la sección B ya reflejan lo decidido.
> Herencia de fase 04: 9 Expertos sobre 154 papers · `answer_question` (C5) con `top_k=32` ·
> la prosa de `answer` no está verificada (A26) · `confidence` solo separa trampa de control ·
> E4–E7 · D10/D11 (cliente agnóstico, Verificador con otro proveedor) · D12 (el código
> garantiza las citas, no el prompt).

---

## A · Decisiones cerradas en R0 (2026-11-07)

| # | Propuesta | Por qué / qué la fuerza |
|---|---|---|
| Y1 ✅ | **Paquete `redaccion/`**, Settings con prefijo `REDACCION_` y `extra="ignore"`. Reutiliza `expertos.llm` (cliente agnóstico, `llm_calls`) y `expertos.consult.answer_question`, no los reimplementa. Produce **secciones verificadas** (prosa citada + bibliografía), no el artículo ensamblado. `interaccion/` queda reservado para una futura fase de discusión y análisis previo | Regla 3 del proyecto; X8/D10. `consulta/` se confundía con `expertos/consult.py`; `pregunta/` nombra la entrada, no el trabajo; `interaccion/` promete un diálogo que v1 no tiene. Cerrada 2026-11-07 |
| Y2 ✅ | **Verificador con Gemini; Redactor y Orquestador con DeepSeek (D11).** Modelo concreto de Gemini elegido en R2 con llamadas reales (candidatos: `gemini-3.6-flash`, ya probado en A4; `gemini-3.8-flash`). Free tier durante la construcción; si no alcanza para las mediciones de R11–R14, tier de pago cubierto por el crédito de Cloud (10 USD/mes) del plan Google AI Pro del usuario (confirmado 2026-11-07; A4 de fase 04), sin gasto extra. R2 compara 3.6-flash y 3.8-flash con los mismos casos. Claude descartado: su API se paga aparte de la suscripción Pro; queda para otra tarea del proyecto si hace falta | Decisión del usuario (2026-11-07): LLM de empresas distintas y complementarias, sin pagar extra. Precios de pago consultados el 2026-11-07 (AI Studio, por 1M tokens, razonamiento incluido en la salida): 3.6/3.8-flash 0,75 / 3,75 USD (**se duplican el 2027-01-01**); 3.1-pro-preview 2 / 12 (sin free tier). Cuota gratuita medida: 20 peticiones/día y 5 RPM por modelo (A10) |
| Y3 ✅ | **Tamaño de bandeja del Verificador como parámetro** (`1` = pieza por pieza; `N` = charola completa; intermedio = por párrafo). **Arranque: charola completa.** `get_chunk`/`chunk_not_found` por código, sin LLM. En los ciclos 2–3 solo se re-verifican las oraciones que cambiaron (Y6 lo hace posible). R11 y R12 corren los mismos casos con charola completa y con pieza por pieza; se elige con esos datos | Decisión del usuario (2026-11-07): construir para medir y decidir con datos. La falla residual de la spec (alcance) es la más sensible a la atención repartida en lote. Costo estimado por pedido con Flash: ~0,06 USD (charola) frente a ~0,25 USD (pieza por pieza); se mide en R10 |
| Y4 ✅ | **El Redactor redacta solo con material comprobable:** las claims de `evidence` + el texto completo de cada chunk citado (vía `get_chunk`, con la marca `from_abstract`) + `gaps` de cada Experto. La prosa de `answer` **no entra** al prompt del Redactor; se conserva en la auditoría. **Alternativa B** (añadir `answer` como orientación, «no como fuente») solo se prueba si R13 muestra secciones pobres o inconexas | Decisión del usuario (2026-11-07). A26: la prosa de `answer` no la valida nadie. Un dato del recado pegado a un lote parecido es el `not_entailed` sutil que más fácil se escapa al Verificador: se cierra la puerta por construcción, como X3 en fase 04. `gaps` permite declarar huecos y marcar ⟨sin fuente⟩ en vez de improvisar |
| Y5 ✅ | **El código valida que todo `chunk_id` de `citations` esté entre los `evidence` recibidos**; una cita ajena se retira y la oración pasa a ⟨sin fuente⟩ (no se repara). **Cada cita retirada queda registrada** (oración, `chunk_id`, causa) en la auditoría de la consulta, para medir cuántas veces se equivoca el Redactor | D12, regla de la spec «nunca se cita en falso». Mismo patrón que X3 de fase 04. Cubre el criterio 2 por construcción, antes de llegar al Verificador. Decisión del usuario (2026-11-07) |
| Y6 ✅ | **Segmentación de oraciones y emparejado (oración, `[n]` → chunks) por código**, no por LLM. Cada pieza lleva un índice estable. Tests con abreviaturas académicas («cf.», «p. 23», «et al.», «s. XX», comillas); la etiqueta `[n]` va siempre al final de la oración, antes del punto (el código lo valida y registra la excepción), así que las abreviaturas solo pesan en oraciones sin cita. Catálogo de abreviaturas en tres capas: (a) extraído del corpus (1 959 chunks, por frecuencia; contraste con Punkt), (b) normas de referencia (RAE, latinas académicas, inglesas de citación), (c) cortes erróneos hallados en R13 | C7 identifica la oración por su texto (`sentence: str`). Si el LLM segmenta, el reporte no se puede volver a cruzar con el borrador. Decisión del usuario (2026-11-07) |
| Y7 ✅ | **Registro interno por oración** (texto exacto de la pieza, `chunk_id`s, veredicto, motivo, ciclo), aparte de C7, con auditoría en disco por consulta. **El Verificador declara veredicto explícito para cada pieza, `ok` incluido**: una pieza sin veredicto es un error, no un acierto | C7 solo lista fallos. El criterio 1 (≥ 90 % de oraciones factuales verificadas) necesita también los aciertos. Mismo patrón que `ConsultRecord` (C10 de fase 04). C7 se mantiene literal. Tamaño estimado: ~1 KB por pieza, 15–60 KB por pedido (una consulta de Experto ya ocupa ~54 KB); coste extra ~5–10 tokens de salida por pieza, sin llamadas nuevas. Decisión del usuario (2026-11-07) |
| Y8 ✅ | **«Oración factual» por defecto: toda pieza.** Solo quedan exentas las que el Redactor marca como *transición* o *meta-texto* (dos tipos cerrados). La **síntesis entre fuentes es factual** y cita todos los chunks que une. Una pieza sin cita y sin marca de exenta → ⟨sin fuente⟩ y cuenta como fallo en el denominador. El registro (Y7) mide la proporción de exentas (alarma si > ~20 % en un pedido); en R13 el usuario revisa una muestra de exentas y se anota la tasa de clasificación errónea | El criterio 1 depende de esta definición: sin fijarla, el 90 % es incomparable entre corridas. Cierra la trampa del denominador (marcar como transición una pieza difícil para no citarla). Decisión del usuario (2026-11-07) |
| Y9 ✅ | **E6 · pares `supports`/`contradicts`: salida (a).** El Redactor separa en dos piezas: la atribución cita el chunk del miembro `supports` y la objeción cita el del `contradicts`. Regla general: un chunk `contradicts` solo sostiene una pieza que **reporta la objeción**, nunca la atribución. Si el `contradicts` llega sin su gemelo `supports`, la atribución va sin cita → ⟨sin fuente⟩. El registro (Y7) marca las piezas que vienen de un par y R13 cuenta sus `not_entailed` | Mantiene simple al Verificador: cada oración contra su chunk. Con (b) el Verificador tendría que conocer la estructura de pares de C3. **Medido el 2026-11-07:** de los 7 `contradicts` de las Synthesis, solo 2 tienen gemelo `supports` con el mismo texto (C6, C8); los otros 5 están solos (C0, C1, C2, C4 ×2). E6 suponía pares completos. Decisión del usuario (2026-11-07) |
| Y10 ✅ | **Fuera de corpus, dos niveles:** (1) el Orquestador no encuentra Experto en el mapa → lo declara y sugiere ingesta, sin llamar a ninguno; (2) todos los Expertos consultados responden `low` sin evidencia válida → el sistema lo declara, lista sus `gaps` y no llama al Redactor. **Caso intermedio:** si solo una parte de los Expertos aporta evidencia, se redacta con esa y los `gaps` de los demás se avisan en la salida. R14 mide en qué nivel se detecta cada pregunta y si alguna llega al Redactor | Criterio 5. El nivel 2 reutiliza C9 de fase 04, que ya es regla estructural (45/45 trampas en `low`, N13). Decisión del usuario (2026-11-07) |
| Y11 ✅ | **Presupuesto por consulta: tope por puesto.** Orquestador 1 · Expertos ≤ 4 (en paralelo) · Redactor ≤ 3. **Verificador contado en piezas, no en llamadas:** todas las piezas en el ciclo 1 y solo las corregidas en los ciclos 2–3, sea cual sea el tamaño de bandeja (Y3). Al superar un tope, el pedido se corta: lo verificado sale y el resto lleva ⟨sin verificar⟩, con el corte registrado. Cada llamada lleva `consultation_id` en el `context` de `llm_calls`; el coste real (tokens, segundos, USD) se mide en R10 (patrón A22) | Pregunta abierta 3. El tope de «11 llamadas» de la propuesta original solo valía con charola completa y chocaba con Y3 (pieza por pieza = una llamada por oración). Referencia medida el 2026-11-07: 147 consultas de Experto en fase 04, media ~7 400 tokens de entrada, ~1 700 de salida, ~20 s. Cuota gratuita de Gemini (20/día): ~6 pedidos/día con charola, ~1 con pieza por pieza → R11–R12 probablemente en tier de pago (Y2). Decisión del usuario (2026-11-07) |
| Y12 ✅ | **Bibliografía v1: numerada, «APA reducido» en texto plano** con los datos disponibles: autores, año, título, `venue`, DOI (o enlace OpenAlex) + **sección citada** + aviso explícito «faltan volumen, número y páginas». `html.unescape` en títulos (B2); autores según `authors` del paper (E5); el paper con DOI cruzado (E4) se bloquea por código. **Fuera de v1:** bibliografía lista para revista y exportación a gestor de referencias (el usuario aún no usa ninguno; formato a elegir cuando lo adopte: BibTeX, RIS o CSL-JSON) | Pregunta abierta 1. `papers` no guarda volumen, número, páginas, editores ni editorial: APA completo no es posible (medido el 2026-11-07 sobre `excavador.db`: `venue` 199/227, DOI 130/227). Lo que el sistema garantiza es que cada `[n]` apunte al lote correcto; la referencia definitiva la completa el usuario. Decisión del usuario (2026-11-07) |
| Y13 ✅ | **«Profundiza en [n]»: v1 solo muestra el chunk citado** (texto literal con marca `from_abstract` + paper + sección + veredicto del Verificador desde el registro de Y7), leído de la auditoría con `get_chunk`, sin LLM. **Opción: chunks vecinos** (`n−1`, `n+1` del mismo paper) para juzgar el alcance a mano. La navegación conversacional («explícame más sobre [n]» = nueva consulta) queda para `interaccion/` | Pregunta abierta 2. Coste cero y sirve también para la revisión manual de R12–R13 (el alcance es la falla residual, criterio 4). Nota para R9: el índice `n` del `chunk_id` parece correlativo por paper, no por sección (C8: `…#26`, `…#30` en una sección, `…#Conclusiones#43`), así que el vecino puede caer en otra sección; se localiza con `ChunkStore.all_metadata`, sin tocar `biblioteca/`. Verificar en R9. Decisión del usuario (2026-11-07) |
| Y14 ✅ | **E7 · `coherent` de C1/C8: no se añade al mapa en v1.** R4 mide el ruteo con preguntas reales, incluidas algunas dirigidas a C1, C7 y C8; si los errores se concentran ahí, hay causa documentada para añadir el aviso y se decide entonces cómo | C4 es contrato; añadir campos sin evidencia sería romperlo sin causa. La marca misma es poco fiable: `coherent` discrepa en 4/9 clústeres entre proveedores (A13). Red de seguridad: un mal ruteo lo atrapa el nivel 2 de Y10 (cuesta llamadas, no verdad). Decisión del usuario (2026-11-07) |

---

## B · Micro-tareas

Convenciones: mismo repo, paquete `redaccion/` (Y1). Python 3.12, pydantic v2, tests
`tests/redaccion/test_redaccion_*.py` (B1 de fase 04), un commit por tarea firmada. `.venv`
siempre. Prueba manual desde la raíz del repo antes de firmar cualquier módulo con CLI o con
entrada de `.env`.

| # | Tarea (~15 min) | Hecho cuando |
|---|---|---|
| R0 | Cerrar Y1–Y14; anotar en la spec 05 | Decisiones cerradas por escrito |
| R1 | Bootstrap `redaccion/`: Settings, modelos C6/C7 literales + registro por oración (Y7), persistencia atómica | Test: campos 1:1 con `01` (patrón de N6) + round-trip JSON |
| R2 | **Sondeo del proveedor del Verificador** (Y2): llamadas reales desde la raíz, cuota efectiva | Llamada real OK con proveedor ≠ Redactor + fila en `llm_calls`; cuota anotada |
| R3 | Orquestador 1/2: lee `map_text`, descompone y asigna 1–4 Expertos; nivel 1 de Y10 | Test con LLM dummy: pregunta fuera del mapa → declaración, cero Expertos llamados |
| R4 | Orquestador 2/2: consulta a los Expertos (paralelo) vía `answer_question`; nivel 2 y caso intermedio de Y10; prueba de ruteo real (Y14), con preguntas dirigidas a C1, C7 y C8 | Test con store dummy + preguntas reales ruteadas a mano; aciertos de ruteo anotados por Experto |
| R5 | Redactor: `DraftSection` desde las claims + texto de chunks + `gaps` (Y4), validación de citas con registro de retiradas (Y5), ⟨sin fuente⟩, marcas de exenta (Y8), pares E6 y `contradicts` sin gemelo (Y9) | Test: un `chunk_id` ajeno se retira, la oración queda ⟨sin fuente⟩ y la retirada queda registrada; una pieza sin cita ni marca cuenta como fallo |
| R6 | Segmentación y emparejado (oración, chunks) por código (Y6); catálogo de abreviaturas capas a + b; probar con llamadas reales cualquier segmentador externo (pySBD, Punkt) antes de depender de él | Tests con marcadores `[n]`, `[n, m]`, oraciones sin cita, `[n]` a media frase y banco fijo de abreviaturas anotado a mano |
| R7 | Verificador: `chunk_not_found` por código; entailment con tamaño de bandeja parametrizable (Y3); `from_abstract` visible al juez (herencia de fase 03) | Test con LLM dummy: los tres `reason` de C7 se producen con bandeja 1 y con bandeja N |
| R8 | Bucle Redactor↔Verificador ≤ 3 ciclos, re-verificando solo piezas cambiadas; topes por puesto y corte con ⟨sin verificar⟩ (Y11) | Test: un fallo persistente sale marcado al tercer ciclo; superar un tope corta el pedido y lo registra |
| R9 | Salida: texto + bibliografía «APA reducido» (Y12) + «profundiza en [n]» con vecinos opcionales (Y13) | Test: bibliografía con HTML escapado, obra primaria (E5), aviso de datos faltantes y bloqueo del DOI cruzado (E4); numeración de vecinos verificada contra Chroma |
| R10 | CLI de extremo a extremo + auditoría por consulta + coste medido con `consultation_id` (Y11) | Prueba manual desde la raíz; coste por pedido (tokens, s, USD) leído de `llm_calls` |
| R11 | Prueba adversarial: afirmación falsa plausible inyectada al Redactor, con bandeja completa y con bandeja 1 (Y3) | Criterio 3 medido en ambos modos |
| R12 | Prueba de alcance: afirmaciones sobregeneralizadas, con bandeja completa y con bandeja 1 (Y3) | Criterio 4: tasa de `scope_mismatch` medida en ambos modos; tamaño de bandeja decidido |
| R13 | Corrida extremo a extremo con corpus real, oraciones factuales revisadas por el usuario (Y8); cortes erróneos de segmentación contados y añadidos al catálogo (Y6, capa c) | Criterios 1 y 2 medidos; tasa de cortes erróneos anotada |
| R14 | Preguntas fuera de corpus (ambos niveles de Y10) | Criterio 5 medido; nivel de detección anotado por pregunta |
| R15 | Cierre de fase: checklist, registro, propagación a 00/01 | Spec 05 marcada CERRADA |

## C · Dependencias

```
R0 ─► R1 ─► R2 ─► R3 ─► R4 ─► R5 ─► R6 ─► R7 ─► R8 ─► R9 ─► R10 ─► R13 ─► R15
                                                     R10 ─► R11, R12, R14 ──┘
```

## D · Riesgos conocidos al entrar

- **Cuota del Verificador (Y2/Y3/Y11).** Con 20 peticiones/día gratuitas: ~6 pedidos/día con
  charola completa, ~1 con pieza por pieza. R11–R12 probablemente en tier de pago, cubierto por el
  crédito de Google AI Pro (Y2). Sondeo real en R2 antes de depender de él.
- **El alcance es la falla residual conocida** (criterio 4). El corpus es de humanidades: los
  «alcances» rara vez son poblaciones o magnitudes. Son atribuciones (quién sostiene qué) y
  matices de tesis. Las pruebas de R12 deben construirse con ese tipo de sobregeneralización.
- **Chunks degradados:** 105 de 158 papers solo aportan el abstract, con diacríticos rotos
  (E1 de fase 03); ~10 % de chunks de cuerpo rotos (E6 de fase 03). El Verificador puede marcar
  `not_entailed` por texto ilegible, no por cita falsa.
- **Pares `contradicts` (E6 de fase 04):** 7 casos en las síntesis. Y9 los resuelve en el
  Redactor; si falla, el Verificador los marcaría por diseño.
- **Corpus monotemático:** varios Expertos responden lo mismo. El Orquestador puede llamar a 4
  cuando bastaba 1, y eso gasta presupuesto (Y11).

## E · Glosario de la panadería (usado en R0 con el usuario)

| Sistema | Panadería |
|---|---|
| Artículo para revista arbitrada | pan-bizcocho en venta; v1 hornea una capa (sección) por encargo |
| Paper | lote |
| Sección del paper | estante |
| Chunk | costal; su texto literal es la harina |
| `chunk_id` | etiqueta del costal (lote + estante + n.º) |
| Expertos | maestros de estación |
| SynthesisMap | pizarrón de la cocina |
| Orquestador | jefe de turno |
| Redactor | panadero; su prompt es el horno |
| Verificador | inspector de otra empresa |
| `answer` / `evidence` / `gaps` | recado / afirmaciones con etiquetas de costal / huecos declarados |
| Oración | pieza; el borrador entero es la charola |
| Tamaño de bandeja (Y3) | inspeccionar pieza por pieza o la charola completa |
| Registro por pieza (Y7) | libro de inspección |
| Transición / meta-texto (Y8) | caja y moño |
| `not_entailed` / `scope_mismatch` | etiqueta que miente / etiqueta que exagera |
| ⟨sin fuente⟩ / ⟨sin verificar⟩ | avisos honestos en la pieza |
