# 03 · Registro de consideraciones — Biblioteca RAG

> Compañero del plan de micro-tareas (`03-PLAN-MICROTAREAS-BIBLIOTECA.md`).
> Recoge hallazgos, deuda aceptada y herencias entre micro-tareas.
> Estado: **vivo** · fase 03 en curso desde 2026-07-20 · última actualización 2026-07-28 (M8).

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
- **D2 (→M17):** ¿overlap de chunks? Decidir con las 10 preguntas de prueba.
  **Ampliado en M7:** el overlap y el **tamaño objetivo** son la misma pregunta — cuánta
  ventana necesita el retrieval para que un pasaje sustente una afirmación completa — y se
  deciden JUNTAS con las 10 preguntas, no por separado ni a ojo. Dato de partida (A9): banda
  real 200–280 tokens, ~2 500 chunks proyectados. Si el top-3 falla, las dos palancas son
  subir `min_tokens` (chunks más largos, menos fronteras) y activar overlap; probar en ese
  orden, porque la primera no duplica almacenamiento y la segunda sí.
- **D3 (→M14):** tasa real de fallo de GROBID sobre los 55 PDFs (criterio 1: ≥ 95 %).
- **D4 (→M16):** `get_chunk` reconstruye texto exacto (criterio 4, requisito del Verificador).
- **D5 (→M16):** **muestreo de fidelidad de transcripción.** Leer 5 chunks al azar contra
  su PDF original. No hay detección automática de una página mal transcrita por GROBID; las
  defensas son tres: (a) el PDF sigue en `data/pdfs/` y el `chunk_id` lleva el `paper_id`,
  así que de cualquier cita se llega al original en un paso; (b) el Verificador de fase 05
  lo caza solo — un pasaje mal transcrito no sustenta la afirmación y sale `not_entailed`,
  no falla en silencio; (c) este muestreo mide la tasa en vez de suponerla.
  **Reparación de un caso concreto:** `process_fulltext(pdf, force=True)` (M4 ya lo soporta)
  regenera el TEI de ese paper y se reindexa solo él.

## E · Cuestiones que tocan otras fases

- **E1 (→05):** chunks con `from_abstract=True` son texto tipográficamente degradado
  (diacríticos rotos, A1 de fase 02). El Verificador debe saberlo (por eso P6).
- **E2 (→04):** ~4 % de chunks duplicados esperables (C5 de fase 02, DOI-variantes).

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
| M9–M18 | — | pendientes |
