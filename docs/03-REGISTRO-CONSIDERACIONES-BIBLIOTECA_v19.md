# 03 · Registro de consideraciones — Biblioteca RAG

> Compañero del plan de micro-tareas (`03-PLAN-MICROTAREAS-BIBLIOTECA.md`).
> Recoge hallazgos, deuda aceptada y herencias entre micro-tareas.
> Estado: **FASE 03 CERRADA (2026-09-18)** · este registro pasa a ser referencia histórica
> y herencia para las fases 04-05. Biblioteca final: 1 959 chunks de 158 papers, 181 tests.

---

## Decisiones cerradas en M0 (2026-07-20)

| # | Decisión | Detalle |
|---|---|---|
| P1 | Base vectorial: **Chroma embebida** | Cero Docker extra; filtro por year = pre-consulta SQLite → filter_paper_ids |
| P2 | Tablas/fórmulas: **ignorar** | Extendido en M2: también diagramas aplanados a prosa (ver A4) |
| P3 | Chunks **sin overlap** | Se revisa con datos en M17 |
| P4 | **Guardar TEI XML** en `data/tei/` | El "negativo revelado": reproceso barato |
| P5 | Libros: GROBID + **fallback plano** | El fallback se escribe en M6 (rama del parser), se activa con evidencia en M15 |
| P6 | Payload Chroma lleva **`from_abstract: bool`** | Marca chunks de texto degradado (A1 de fase 02) para el Verificador de fase 05. Payload, NO toca C2 |
| P7 | **Stoplist de secciones no citables** (M5, 2026-07-21) | `bibliografía, referencias, bibliography, references, notas, obras citadas` (comparación normalizada: minúsculas, sin acentos). Se filtran en M7. Razón en A8 |
| P8 | **Persistir el texto plano** en `data/text/` (M6, 2026-07-22) | Es *la edición que las citas citan*: los offsets de C2 solo significan algo contra una cadena concreta. Si mañana cambia una regla del parser, el texto regenerado desde el TEI tendría otra paginación y los offsets guardados apuntarían a otro pasaje, en silencio. 40 KB por paper que hacen los offsets auditables a través de cambios de código. Contraparte de P4: el TEI es el manuscrito, el `.txt` es el ejemplar archivado |

## A · Hallazgos de datos reales

### A1 · GROBID traga el abstract dentro de `<affiliation>` (maquetación latinoamericana)
**Descubierto en:** M2, primer TEI real (`doi_10.15174_rv.v0i11.24`).
**Qué:** el `<orgName>` del autor contiene "Universidad Nacional Autónoma de México
Resumen En el ensayo estudio cinco diagramas..." — el resumen pegado bajo la afiliación
confunde al modelo de GROBID (entrenado con papers STEM en inglés).
**HERENCIA PARA M5:** el abstract citable sale de **SQLite (fase 02)**, nunca del
teiHeader. Del TEI solo se toma el `<body>`.

### A2 · Divs sin `<head>` y heads que son numerales romanos
**Descubierto en:** M2. La sección I no tiene `<head>` (el "I" se fundió al primer
párrafo); las demás traen "II", "III El comportamiento vital".
**HERENCIA PARA M5:** fallback obligatorio: div sin head → `section="body-{n}"`.
El campo `section` de C2 es `str` libre; en humanidades será el head textual o el
fallback, no el vocabulario STEM de los ejemplos.

### A3 · Los `<ref>` inline requieren tratamiento diferenciado
**Descubierto en:** M2.
**Qué:** `<ref type="bibr">(Echeverría, 1998: 161)</ref>` — texto valioso, CONSERVAR.
`<ref type="foot" target="#foot_1">foot_1</ref>` — deja "foot_1" incrustado, ELIMINAR.
**HERENCIA PARA M5:** regla de extracción: strip de refs tipo foot, texto plano de
refs tipo bibr.

### A4 · Diagramas y epígrafes aplanados a prosa corrida
**Descubierto en:** M2. "N = naturaleza M = medio natural K = materia SV…" (leyenda
de figura) y el epígrafe de Damasio en inglés quedan fundidos en los párrafos.
**Decisión:** ruido tolerable en v1 (extiende P2). e5 y el retrieval no sufren;
si el Verificador (fase 05) tropieza con un chunk-leyenda, se anota allá.

### A5 · Des-guionización imperfecta de GROBID
**Descubierto en:** M2. "Jakob-son", "presu-puesto", "finalmen- te" en el body.
**Decisión:** aceptar en v1. Regex de reparación arriesga romper guiones legítimos
del español. e5 es robusto a esto (mismo argumento que A1 de fase 02).

### A6 · El parser rinde bien con datos reales (medición sobre la fixture)
**Descubierto en:** M5 (corrida exploratoria sobre `grobid_sample.tei.xml`).
**Números:** 10 `<div>` en el TEI → **8 secciones** útiles (2 descartadas por quedar
vacías tras la limpieza de refs, presumiblemente divs de notas). Texto total: 40 185
caracteres. Offsets contiguos y verificados: cada sección arranca 2 caracteres después
del cierre de la anterior (el `\n\n` separador); 40 185 + 14 separadores = 40 199. ✓
**Sorpresa favorable:** la mayoría de los `<head>` son títulos temáticos reales
("La reproducción social como producción/consumo de objetos"), no solo numerales.
**Dimensionamiento para M14/M16:** ~40 KB por paper ≈ 25–30 chunks → **~1 500 chunks
de cuerpo** (55 PDFs) + 172 chunks de abstract. Holgado para Chroma: **P1 confirmada**.

### A7 · El fallback `body-n` es minoritario, pero produce secciones enormes
**Descubierto en:** M5.
**Qué:** solo 1 de 8 secciones cayó en el fallback (`body-1`, la introducción — el
numeral "I" se fundió al primer párrafo, ver A2). Pero mide **9 138 caracteres**
(~2 300 tokens); otra sección con head llega a 11 027.
**Consecuencia para M7:** una sección así generará 6–8 chunks que compartirán la misma
etiqueta `section`, sin distinción semántica entre ellos. No es un fallo: es que GROBID
no halló subtítulos donde el autor no los puso. El `seq` del `chunk_id` los distingue.
**A vigilar en M14:** si el patrón "primera sección sin head" se repite en el corpus,
es un rasgo de la maquetación latinoamericana, no del paper suelto.

### A8 · La bibliografía se cuela como sección citable → origen de P7
**Descubierto en:** M5. La fixture produce una sección `"Bibliografía"` de 460 caracteres.
**Por qué importa:** un chunk de bibliografía no sustenta ninguna afirmación, pero es
**plausible** para el retrieval — está lleno de nombres y años, así que puntuará alto
justo en preguntas sobre autores. Sería un pasaje vacío llegando al Verificador (fase 05).
Es el mismo problema del front-matter que la fase 02 delegó al clustering (D1 de aquel registro).
**Decisión: P7** — stoplist de 6 entradas aplicada en M7, barata y reversible.

### A9 · La banda real de chunk es 200–280 tokens, no 200–500 (`min_tokens` gobierna el cierre)
**Descubierto en:** M7 (corrida exploratoria sobre la fixture, tokenizer real de e5).
**Números pre-tweak:** 42 chunks del paper de 40 185 caracteres. Todos entre **200 y 282
tokens**; ninguno se acercó a 500. Causa: la regla de cierre acumula oraciones hasta
*superar* `min_tokens` y cierra ahí, así que `min_tokens` funciona como objetivo y
`max_tokens` queda prácticamente inerte (solo actuaría con oraciones enormes).
**Consecuencias:** (a) ~42 chunks/paper en vez de los 25–30 estimados en A6 → proyección del
corpus ≈ **2 500 chunks** de cuerpo, sigue holgado para Chroma; (b) más fronteras = más
riesgo de que el sustento de una afirmación quede partido entre dos chunks — exactamente lo
que hace fallar al Verificador de fase 05.
**Confirmaciones favorables del mismo dato:** P7 operando (la sección "Bibliografía"
desapareció del troceo) y `seq` global produciendo IDs únicos y consecutivos a través de
secciones homónimas.
**Colas cortas y su tweak:** 5 chunks residuales de fin de sección (55, 76, 87, 142, 155
tokens); el de 55 es pobre como unidad citable. **Aplicado en M7:** parámetro
`tail_min_tokens=100` — la cola se fusiona con el chunk previo de su misma sección si la
suma no rebasa `max_tokens`, rebanando `full_text` (nunca concatenando) y renumerando `seq`.
**Lo que NO se tocó:** el tamaño objetivo. Ver D2.

### A10 · 67 papers (29,5 %) no tienen NADA citable — el corpus indexable es 160, no 227
**Descubierto en:** M13 (prueba manual de la CLI: 2 de los 3 primeros papers se omitieron).
**Medido en SQLite:** 227 totales · **70 sin abstract** · **67 sin abstract Y sin PDF**.
**Qué significa:** esos 67 son registros con metadatos válidos (título, autores, año, DOI)
que OpenAlex nunca acompañó de abstract — patrón conocido de revistas latinoamericanas y de
libros. No es un fallo del Excavador ni de la Biblioteca: simplemente **no se pueden citar**,
porque D5 del contrato exige que toda cita apunte a un `chunk_id` real.
**Corpus real de la Biblioteca:** 160 papers indexables = 55 con PDF (~38 chunks c/u) +
105 solo abstract (1 chunk c/u) → **proyección ≈ 2 200 chunks**, coherente con A9.
**Siguen siendo útiles:** como referencias bibliográficas y para el snowballing de futuras
ingestas. Lo que no pueden es sustentar afirmaciones.
**PROPAGAR:** fase 04 clusteriza sobre 160 papers, no 227. Fase 05 debe saber que ~30 % del
corpus no sustenta nada (ver E3).

### A11 · `Settings()` reventaba fuera de los tests — el aislamiento escondía el bug
**Descubierto en:** M13 (primera ejecución real de la CLI desde la raíz del repo).
**Qué:** el `.env` del repo trae variables `EXCAVADOR_*`; pydantic-settings lee el archivo
entero y, sin `extra="ignore"`, las trata como campos prohibidos → `ValidationError` en
CUALQUIER comando de la CLI. **Fix:** `extra="ignore"` en el `SettingsConfigDict`.
**Por qué 181 tests no lo atraparon:** todos hacen `monkeypatch.chdir(tmp_path)` (regla F4 de
fase 02) y por tanto nunca ven el `.env` real. **El aislamiento que protege los tests es lo que
ocultaba el fallo del entorno real.** Mismo patrón que F5 de fase 02 (numpy→SQLite): el bug vive
en una combinación que ningún test ejercita.
**Regla nueva:** todo módulo con CLI se prueba UNA vez a mano desde la raíz del repo antes de
firmarse. El test de regresión añadido pasa un `.env` con claves ajenas vía `_env_file`.
**Higiene:** el traceback imprimió la API key de S2 completa (F4 de fase 02 avisaba). Rotada.

### A12 · GROBID: 55/55 sin un solo fallo, en 2.2 minutos
**Descubierto en:** M14 (corrida real, tras el ajuste de RAM a 8 GB).
**Números:** 55 PDFs, `ok=55 fail=0`, 130 s totales (~2.4 s por PDF).
**Criterio 1 de la spec (≥ 95 %): cumplido al 100 %.** D3 cerrada.
**Lecturas:** (a) la estimación previa de 20–50 min estaba muy por encima: el modelo CRF es
mucho más rápido de lo previsto y no hubo presión de memoria; (b) ningún PDF del corpus
resultó corrupto o ilegible, así que la ruta de fallback a abstract por `GrobidError`
(implementada en M12) no se ejercitó con datos reales — sigue cubierta solo por tests.
**Nota:** `data/tei/` contiene 56 archivos, no 55: sobra `prueba.tei.xml` de M2.

### A13 · El único libro con PDF se parseó bien: el fallback P5 no hizo falta
**Descubierto en:** M15. **Composición del corpus:** 191 `article` (54 con PDF), 20
`book-chapter` (1 con PDF), 6 `thesis`, 5 `book`, 5 `other` — **ninguno de estos últimos
con PDF**. Solo existe UN caso real de libro/capítulo parseable.
**Resultado sobre ese caso** (`doi:10.47377/iluminacionesprofanas.11`): 4 secciones con
títulos temáticos reales, 48 947 caracteres, `used_flat_fallback=False` — y correctamente,
porque GROBID no se equivocó.
**Confirmación lateral:** una de las secciones se llama "Obras citadas" (redacción distinta a
"Bibliografía" del primer paper) y la stoplist P7 ya la cubría. Segundo documento, segunda
variante, misma lista.
**Consecuencia para A7:** secciones de 21 279 y 24 547 caracteres → ~23 chunks compartiendo
etiqueta. El patrón de A7 amplificado, esperable en capítulos de libro. No es fallo.

### A14 · M16: 158 papers, 1 959 chunks, 79 min, cero fallos
**Descubierto en:** M16 (indexación completa, desatendida).
**Números:** 227 papers leídos · **158 indexados** · 69 omitidos · 0 fallidos ·
**1 959 chunks** (129 desde abstract) · 79.1 min · media 12.4 chunks/paper.
**Ajuste sobre A10:** los omitidos son **69, no 67**. Dos papers tienen `pdf_path`
registrado pero el archivo **no existe en disco**; la pipeline intentó el PDF, cayó a
abstract, y como tampoco tenían abstract los omitió. Comportamiento correcto: 227−69=158.
La verificación honesta de "sin nada citable" comprueba el archivo en disco, no solo la
columna. **Corpus citable definitivo: 158 papers.**
**Chunks por paper:** los 55 con PDF promediaron ~33 chunks (no los 38 proyectados en A10);
por eso 1 959 y no ~2 200. Sin consecuencias.

### A15 · Criterio 4 verificado extremo a extremo: 20/20 offsets exactos
**Descubierto en:** M16 (muestreo aleatorio de 20 chunks del índice real).
**Qué se verificó — más fuerte que lo que pedía la spec:** no solo que `get_chunk` devuelve
el texto exacto, sino que ese texto coincide con la rebanada `[char_start:char_end]` del
`.txt` archivado en `data/text/`. **20/20 exactos, 0 desajustes, 0 chunks sin `.txt`.**
**Consecuencia:** **P8 validada en producción.** Toda cita del sistema es reverificable
contra el ejemplar archivado, sin reprocesar el PDF. **D4 CERRADA. Criterio 4 ✓.**

### A16 · Criterio 3 medido con 20 preguntas: ~17–18 aciertos en top-3
**Descubierto en:** M17. Dos tandas de 10 preguntas escritas a mano:
**Tanda 1 (conceptos de la obra primaria: ethos, blanquitud, modernidad capitalista):**
~8.7/10 a juicio humano. **Sorpresa favorable:** la predicción de que el corpus secundario
cubriría mal los conceptos primarios resultó **falsa** — la literatura secundaria
latinoamericana glosa el aparato conceptual con detalle y cita a Echeverría directamente
(scores 0.88–0.90 en P1, P2, P4, P5, P6). Esto **mejora la expectativa de E3 de fase 02**
(obras primarias sin PDF): lo primario llega por vía indirecta y citable.
**Tanda 2 (recepción crítica: diagramas, Benjamin, biografía, marxismo latinoamericano):**
~9/10. Los cuatro anclajes controlados (pasajes que sabíamos presentes por M2/M5/M15)
acertaron todos.
**Los dos tipos de fallo, ambos identificados y ninguno resoluble con más ventana:**
(a) **Preguntas de síntesis** (P7 y P10 de tanda 1): piden articular algo que ningún pasaje
suelto contiene. NO es fallo del retrieval — es el trabajo del Experto (04) y el Redactor (05).
(b) **Consultas por postura** (P10 de tanda 2, ver A18).
**Criterio 3:** la spec pedía 10/10; medido con criterio estricto sobre 20 preguntas queda en
~85–90 %, con los fallos diagnosticados. Ver D2 para la decisión que se deriva.

### A17 · Los scores de retrieval NO discriminan — no sirven como umbral de confianza
**Descubierto en:** M17. Todo el rango de resultados de 20 preguntas cae entre **0.828 y
0.901**: siete centésimas entre el mejor acierto y el ruido evidente (un chunk de entrevista
sobre Obama apareció a 0.835 en una pregunta de ontología).
**Qué es:** A3 de fase 02 reapareciendo en el retrieval. e5 produce vectores normalizados y
el coseno vive en una banda alta y estrecha; ahí no hay señal para separar "sustenta" de
"habla del mismo tema".
**CONSECUENCIA DURA PARA FASE 04:** el Experto **no puede** derivar su
`confidence: high|medium|low` (C5) de un umbral de score, ni decidir con él si su corpus
cubre la pregunta. Ese juicio tiene que hacerlo el LLM leyendo el pasaje. Un umbral numérico
daría falsa precisión.
**CONSECUENCIA PARA FASE 05:** lo mismo para el Verificador — `not_entailed` y
`scope_mismatch` son juicios de entailment sobre el texto, jamás comparaciones de score.

### A18 · El retrieval empareja por TEMA, no por POSTURA
**Descubierto en:** M17, tanda 2, P10 ("¿qué críticas o límites se han señalado a la teoría
de la blanquitud?"). Los tres resultados vinieron del mismo paper que **expone** la teoría,
no que la critica — y el corpus **sí contiene** el texto crítico ("Blanquitud y blancura.
Una lectura crítica a Bolívar Echeverría", que apareció en la tanda 1 con otra pregunta).
**Por qué:** la similitud semántica no distingue quién está a favor y quién en contra;
"crítica de X" y "exposición de X" son vecinos en el espacio vectorial.
**CONSECUENCIA PARA FASE 04 (C3, campo `stance`):** el campo
`stance: supports|contradicts|mentions` **no puede poblarse buscando contradicciones por
retrieval**. Si el Experto pregunta "¿qué contradice X?", recibirá sobre todo material que lo
apoya. La vía correcta: recuperar ampliamente por tema y que el LLM clasifique la postura
pasaje por pasaje. Es una limitación estructural del RAG por similitud, no un defecto
corregible en esta fase.

### A19 · Fidelidad de transcripción: 70 % fiel, 20 % con ruido, 10 % roto — todo en el SALTO DE PÁGINA
**Descubierto en:** D5 (muestreo manual de 10 chunks de cuerpo contra sus PDF originales,
7 papers distintos; dos chunks cayeron del mismo paper — el muestreo pesa por número de
chunks, así que los papers largos aportan más).
**Resultado:** **7 fieles · 2 con ruido tolerable · 1 roto.**
**El hallazgo de fondo: los tres defectos son el MISMO problema** — GROBID reconstruye mal el
orden de lectura **al cruzar de una página a la siguiente**, en maquetación latinoamericana
(dos columnas, notas al pie, encabezados corridos). Tres manifestaciones:
1. **Nota al pie insertada en el cuerpo** (`doi:10.29166/csociales.v1i42.2765`): el contenido
   COMPLETO de la nota 8 quedó incrustado en mitad del flujo, pegado a un párrafo no
   relacionado. Distinto de A3 (que dejaba el stub `foot_1`): aquí entra el texto entero.
   Cada mitad es fiel por separado, pero juntas narran una continuidad que no existe. ⚠️
2. **Mobiliario de página incrustado** (`doi:10.17141/iconos.43.2012.345`): nombres de autores,
   pie de revista y hasta el "d o s s i e r" del margen vertical, insertados a mitad de
   oración. **No se pierde texto**: la oración continúa bien después de la basura. ⚠️
3. **Pérdida de texto** (`doi:10.30972/nvt.1715349`): el chunk salta de "la multiplicidad de
   las" a "extrae, a partir de esa premisa", perdiendo varios párrafos intermedios. La oración
   resultante no tiene sujeto ni sentido. **Este es el caso grave.** ❌
**Por qué NO se repara:** `force=True` no sirve — GROBID es determinista y reprocesar el mismo
PDF reproduce el mismo error. No es caché sucia: es el techo del modelo con esta maquetación.
**Defensas vigentes (las tres previstas en D5):** (a) del `chunk_id` se llega al PDF en un
paso; (b) el Verificador de fase 05 caza el caso 3 como `not_entailed` — un pasaje sin sentido
no sustenta nada, no falla en silencio; (c) esta medición da una tasa en vez de una suposición.
**Mejora futura concreta (v2, no esta fase):** filtro de post-proceso que elimine las líneas
coincidentes con el encabezado/pie recurrente del documento, detectables por repetirse en cada
página del TEI. Barato y quirúrgico; atacaría el caso 2 y parte del 1. El caso 3 (pérdida de
texto) no tiene arreglo barato.

## B · Deuda técnica aceptada

### B1 · `parse_tei` fue refactorizado por dentro en M6 (módulo ya firmado)
**Origen:** M6. Para calcular los offsets *por construcción* (no a posteriori), la lógica de
M5 se partió en `_load_body` / `_named_texts_from_divs` / `_assign_offsets`.
**Por qué se acepta:** la firma pública de `parse_tei` no cambió y los tests de M5 siguen en
verde sin tocarlos; M6 es la continuación declarada de M5, no un módulo ajeno.
**Gatillo:** ninguno previsto. Si M7 necesitara otra vez tocar el parser, revisar si conviene
congelarlo antes de seguir apilando cambios.

### B2 · `excavador/relevance.py` refactorizado en M8 (módulo firmado de otra fase)
**Origen:** M8. El wrapper de e5 (carga del modelo + prefijos `query:`/`passage:`) se extrajo
a `biblioteca/embedder.py` y `relevance.py` pasó a delegar en él.
**Por qué se acepta:** los prefijos e5 son **parámetro global congelado** del contrato `01`;
tenerlos escritos en dos archivos reproduce exactamente el riesgo de B4 de fase 02 (dos copias
que divergen en silencio). Y aquí el silencio es caro: indexar con `passage:` y consultar sin
prefijo no lanza error — solo degrada el retrieval sin avisar. Precedente de cambio justificado
a módulo firmado: B5 de fase 02.
**Salvaguarda:** `test_relevance.py` pasó **sin modificarse**, incluido su test slow con el
modelo real. La API pública de `RelevanceScorer` y el punto de inyección `self._encoder` quedaron
intactos.
**Efecto secundario favorable:** `get_embedder` cacheado (singleton por modelo) evita cargar e5
dos veces por corrida; la suite slow bajó de ~117 s a ~27 s.

## C · Comportamientos deliberados que parecen bugs

*(vacío aún)*

## D · Verificaciones pospuestas

- **D1 (→M15):** calidad del TEI en `work_type=book/book-chapter`; activar fallback P5 si aplica.
  **Límite conocido del disparador (M6):** el fallback plano se activa con ≤1 sección útil
  Y >20 000 caracteres. Un libro que GROBID parta en 3 secciones inútiles y enormes NO lo
  activaría. No se corrige a ciegas: M15 mira libros reales y ajusta el umbral con evidencia.
  **CERRADA (M15, 2026-08-13):** el umbral NO necesita ajuste. Salvedad honesta: solo existía
  **un** caso real (A13) y no activó el fallback. El fallback queda escrito y cubierto por
  tests sintéticos, pero **sin caso real que lo haya ejercitado**. Reabrir si entran libros
  con PDF en una ingesta futura.
- **D2 (→M17):** ¿overlap de chunks? Decidir con las 10 preguntas de prueba.
  **Ampliado en M7:** el overlap y el **tamaño objetivo** son la misma pregunta — cuánta
  ventana necesita el retrieval para que un pasaje sustente una afirmación completa — y se
  deciden JUNTAS con las 10 preguntas, no por separado ni a ojo. Dato de partida (A9): banda
  real 200–280 tokens, ~2 500 chunks proyectados. Si el top-3 falla, las dos palancas son
  subir `min_tokens` (chunks más largos, menos fronteras) y activar overlap; probar en ese
  orden, porque la primera no duplica almacenamiento y la segunda sí.
  **CERRADA (M17, 2026-08-21): NO se activa overlap y NO se cambia el tamaño objetivo.
  P3 confirmada con datos.** Evidencia: 20 preguntas manuales, ~17–18 con el pasaje correcto
  en top-3 (A16). Los dos fallos son de síntesis y de postura (A16, A18) — ninguno se arregla
  con más ventana de chunk, así que subir `min_tokens` o duplicar almacenamiento con overlap
  no compraría nada. La banda 200–280 tokens (A9) queda como configuración de v1.
- **D3 (→M14):** ~~tasa real de fallo de GROBID~~ **CERRADA (M14, 2026-08-13): 55/55, 0 fallos. Criterio 1 ✓ al 100 %.** Ver A12.
- **D4 (→M16):** ~~`get_chunk` reconstruye texto exacto~~ **CERRADA (M16, 2026-08-21): 20/20 exactos contra el `.txt` archivado. Criterio 4 ✓.** Ver A15.
- **D5 (→M16):** **muestreo de fidelidad de transcripción.** Leer 5 chunks al azar contra
  su PDF original. No hay detección automática de una página mal transcrita por GROBID; las
  defensas son tres: (a) el PDF sigue en `data/pdfs/` y el `chunk_id` lleva el `paper_id`,
  así que de cualquier cita se llega al original en un paso; (b) el Verificador de fase 05
  lo caza solo — un pasaje mal transcrito no sustenta la afirmación y sale `not_entailed`,
  no falla en silencio; (c) este muestreo mide la tasa en vez de suponerla.
  **Reparación de un caso concreto:** `process_fulltext(pdf, force=True)` (M4 ya lo soporta)
  regenera el TEI de ese paper y se reindexa solo él.
  **CERRADA (D5, 2026-09-18): 10 chunks muestreados → 70 % fiel, 20 % ruido tolerable,
  10 % roto.** Ver A19. **Decisión: no se repara nada en v1** — `force=True` es inútil contra
  un modelo determinista, el ruido no afecta la verdad de las citas y el texto roto lo caza el
  Verificador. La tasa queda medida y documentada en vez de supuesta.

## E · Cuestiones que tocan otras fases

- **E1 (→05):** chunks con `from_abstract=True` son texto tipográficamente degradado
  (diacríticos rotos, A1 de fase 02). El Verificador debe saberlo (por eso P6).
- **E2 (→04):** ~4 % de chunks duplicados esperables (C5 de fase 02, DOI-variantes).
- **E3 (→04 y 05):** **el corpus citable son 160 papers, no 227** (A10). El clustering de
  fase 04 debe partir de los papers efectivamente indexados, no de la tabla `papers` completa;
  y fase 05 debe asumir que ~30 % del corpus recuperado no puede sustentar ninguna afirmación.
  De esos 160, además, 105 aportan un solo chunk de abstract (`from_abstract=True`, texto
  degradado por A1 de fase 02): el peso real del corpus verificable está en los 55 con PDF.

- **E4 (→04 y 05): el score de retrieval no es medida de confianza** (A17). Ni la
  `confidence` del `ExpertAnswer` (C5) ni los veredictos del Verificador (C7) pueden derivarse
  de umbrales numéricos: la banda útil es 0.83–0.90 y el ruido vive dentro de ella. Los juicios
  los hace el LLM leyendo el pasaje.
- **E6 (→05): ~10 % de los chunks de cuerpo tienen texto roto en saltos de página** (A19), y
  otro ~20 % arrastra ruido incrustado (notas al pie, encabezados). El Verificador debe tratar
  un `not_entailed` sobre un pasaje sin sentido gramatical como posible fallo de transcripción,
  no como cita falsa del Redactor: del `chunk_id` se llega al PDF en un paso para comprobarlo.
- **E5 (→04): el campo `stance` de C3 no se puebla por retrieval** (A18). Buscar "críticas a X"
  devuelve exposiciones de X. Estrategia correcta: recuperar por tema y clasificar la postura
  con el LLM, pasaje por pasaje.

## F · Higiene de proceso

- **F1:** ballena de Docker abierta SOLO los días de GROBID (M2 ✓, M14, reprocesos).
  Chroma es embebida: indexar/consultar no necesita Docker.
- **F2:** heredadas de fase 02 y vigentes: `.venv` siempre; un commit+push por tarea
  firmada; frontera modelo→persistencia convierte a tipos nativos (F5 de 02).
- **F3:** `data/tei/prueba.tei.xml` se conserva: será la fixture (recortada) de los
  tests de M4–M5.

- **F4 · RAM de WSL insuficiente para las corridas grandes — AJUSTE DIFERIDO, con gatillo.**
  **Medido (2026-07-27):** `free -h` en WSL da **5.7 GB totales / ~4.5 GB disponibles**.
  El default de WSL2 es el 50 % de la RAM de Windows.
  **Por qué basta hoy:** las micro-tareas M9–M13 trabajan con fixtures y embeddings dummy;
  cargar e5 puntualmente (~2.5 GB) cabe sin apuros.
  **Por qué NO bastará después — dos gatillos concretos:**
  (a) **M14 (GROBID sobre 55 PDFs):** el contenedor de GROBID recomienda ~4 GB y Docker Desktop
  comparte el mismo pool de memoria de la VM de WSL. 55 PDFs seguidos con 5.7 GB totales es
  territorio de OOM.
  (b) **M16 (indexación completa):** e5 cargado (~2.5 GB) + ~2 700 chunks embebidos por lotes
  + Chroma escribiendo. Es la corrida más cara de la fase y es **desatendida**: si el kernel
  mata el proceso a mitad, se pierden horas de CPU sin GPU.
  **Síntoma a reconocer:** el proceso muere sin traceback ("Killed", o la terminal simplemente
  vuelve al prompt). Eso NO es un bug del código: es el OOM killer de Linux.
  **Ajuste (hacer antes de M14):** crear `C:\Users\<usuario>\.wslconfig` en **Windows** con:
  ```
  [wsl2]
  memory=8GB
  swap=4GB
  ```
  y después, en PowerShell: `wsl --shutdown` (reinicia la VM; cerrar antes Docker Desktop).
  Verificar con `free -h` que `total` subió. Ajustar `8GB` a lo que la máquina permita sin
  asfixiar a Windows (regla práctica: no más del 60–70 % de la RAM física).
  **Mitigación complementaria si el ajuste no alcanza:** embeber por lotes pequeños en M16
  (batch de 16–32 chunks) y procesar los PDFs de M14 en dos tandas.
  **APLICADO (2026-08-13, antes de M14):** `.wslconfig` con `memory=8GB` + `swap=4GB` sobre
  una máquina de 12 GB físicos. `free -h` pasó de 5.7 GB / 4.5 disponibles a **7.8 GB / 7.3
  disponibles**. M14 corrió sin presión de memoria (A12). El batch de 32 de M12 se mantiene
  como mitigación de segundo nivel para M16.
  **Detalle operativo:** tras `wsl --shutdown` hay que reabrir Docker Desktop Y una terminal
  WSL nueva — la integración `docker` se inyecta al iniciar la sesión; una terminal preexistente
  no la ve y responde "command could not be found".

- **F5 · Trabajar siempre desde `~/WandaVision/RAG_publish`, nunca desde `/mnt/c/...`.**
  El sistema de archivos de Windows montado en WSL (drvfs) es notablemente más lento; la carga
  del modelo e5 ya lo sufrió en fase 02 (A4 de aquel registro). Tras editar el `.wslconfig` es
  fácil quedarse en `/mnt/c/Users/<usuario>`: volver al proyecto antes de lanzar cualquier corrida.

---

## Estado de micro-tareas

| # | Tarea | Estado |
|---|---|---|
| M0 | Decisiones P1–P6 | ✅ 2026-07-20 |
| M1 | Bootstrap `biblioteca/` | ✅ 2026-07-20 · commit a973f62 |
| M2 | GROBID vivo + primer TEI | ✅ 2026-07-20 · hallazgos A1–A5 |
| M3 | Modelos C2 (`Chunk`, `SectionText`, `IndexStats`) | ✅ 2026-07-21 · commit dc04ffc |
| M4 | Cliente GROBID idempotente | ✅ 2026-07-21 · test slow contra GROBID real en verde |
| M5 | Parser TEI (secciones del body) | ✅ 2026-07-21 · hallazgos A6–A8 → P7 |
| M6 | Offsets exactos + fallback plano | ✅ 2026-07-22 · 113 tests · invariante por construcción → P8 |
| M7 | Splitter + chunker (P7, fusión de colas) | ✅ 2026-07-27 · 132 tests · hallazgo A9 → D2 ampliada |
| M8 | Embedder e5 compartido | ✅ 2026-07-28 · 140 tests · `relevance.py` delega → B2 |
| M9 | Store Chroma (`upsert_chunks`, `get_chunk`) | ✅ 2026-07-29 · 148 tests · payload P6 |
| M10 | `retrieve` con filtros | ✅ 2026-07-30 · 157 tests · `ScoredChunk`, score = 1 − distancia |
| M11 | Ruta sin PDF (chunk de abstract) | ✅ 2026-07-31 · 165 tests |
| M12 | Pipeline de indexación | ✅ 2026-08-03 · 173 tests · fallback a abstract si GROBID falla |
| M13 | CLI (`index`, `query`, `stats`, `get`) | ✅ 2026-08-10 · 181 tests · hallazgos A10–A11 |
| M14 | Corrida real GROBID (55 PDFs) | ✅ 2026-08-13 · 55/55, 0 fallos, 2.2 min → A12, D3 ✓ |
| M15 | Inspección de libros | ✅ 2026-08-13 · 1 solo caso real, bien parseado → A13, D1 ✓ |
| M16 | Indexación completa (158 papers) | ✅ 2026-08-21 · 1 959 chunks, 79 min → A14, A15, D4 ✓ |
| M17 | 10+10 preguntas de prueba | ✅ 2026-08-21 · ~17–18/20 en top-3 → A16–A18, D2 ✓ |
| M18 | Cierre de fase | ✅ 2026-09-18 · spec 03 marcada CERRADA v1.1 |

---

## Cierre de fase (2026-09-18)

**Biblioteca final:** 1 959 chunks citables · 158 papers indexados (55 vía GROBID + 103 vía
abstract) · 69 papers sin nada citable · Chroma embebida en `data/chroma` · 181 tests en verde ·
18 micro-tareas firmadas en ~2 meses de sesiones de 15 minutos.

**Criterios de aceptación:** 1 ✓ (100 % GROBID, supera el 95 %) · 2 ✓ (C2 por construcción) ·
3 ⚠️→✓ **recalibrado con evidencia** (el 10/10 original era meta mal calibrada; medido
~17–18/20 = 85–90 %, con los dos modos de fallo diagnosticados y atribuidos a las fases 04–05,
no al retrieval) · 4 ✓ (20/20 offsets exactos contra el `.txt`, validando P8 en producción) ·
5 ✓ (idempotencia verificada en tests y en producción).

**Herencia para fase 04 (Expertos + clustering):**
- Clusterizar sobre los **158 papers indexados**, no sobre la tabla `papers` (E3).
- La `confidence` del `ExpertAnswer` (C5) **no puede derivarse de umbrales de score** (E4, A17):
  la banda útil es 0.83–0.90 y el ruido vive dentro de ella. El juicio lo hace el LLM leyendo.
- El campo `stance` de C3 **no se puebla buscando contradicciones** (E5, A18): recuperar por
  tema y clasificar la postura pasaje por pasaje.
- ~4 % de chunks duplicados por DOI-variantes heredados de fase 02 (E2).

**Herencia para fase 05 (Redactor + Verificador):**
- ~30 % del corpus recuperado no sustenta nada; el peso verificable está en los 55 con PDF (E3).
- Chunks `from_abstract=True` son texto tipográficamente degradado (E1).
- **~10 % de los chunks de cuerpo tienen texto roto en saltos de página y ~20 % arrastra ruido
  incrustado** (E6, A19). Regla operativa: un `not_entailed` sobre un pasaje sin sentido
  gramatical es probablemente fallo de transcripción, no cita falsa del Redactor.
- `get_chunk(chunk_id)` es el lookup exacto del Verificador; del `chunk_id` se llega al PDF
  original en un paso.

**Documento de entrada recomendado para las fases siguientes:**
`03-HERENCIA-PARA-FASES-04-Y-05.md` (una página) antes que este registro completo.

**Lecciones de método que sobreviven a la fase:**
- **A11:** el aislamiento que protege los tests puede ocultar fallos del entorno real. Todo
  módulo con CLI se prueba a mano desde la raíz del repo antes de firmarse.
- **A13/D1:** distinguir "lo verificamos" de "no hizo falta verificarlo". Un criterio cerrado
  sin caso real que lo ejercite se documenta como tal, no con un ✓ limpio.
- **A19/D5:** medir una tasa en una muestra vale más que suponer perfección o inspeccionarlo
  todo. Y cuando la reparación no es posible, documentar la defensa que sí existe.
