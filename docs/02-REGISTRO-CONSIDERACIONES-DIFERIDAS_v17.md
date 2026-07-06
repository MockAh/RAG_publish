# 02 · Registro de consideraciones diferidas — Excavador

> Compañero del plan de implementación. Recoge todo lo que decidimos **anotar
> en vez de resolver ahora**: hallazgos durante la construcción, deuda técnica
> aceptada, y verificaciones que se posponen a T13 o a fases posteriores.
> Estado: vivo · actualizar al cerrar cada tarea. Corte actual: **T12 firmado — código completo; T13 (corrida real + calibración) en curso**.

---

## A · Hallazgos de datos reales (confirmados contra el corpus, no supuestos)

### A1 · Abstracts de OpenAlex con diacríticos degradados en origen
**Descubierto en:** T4 (llamada real `search_exact_phrase("Bolívar Echeverría")`).
**Qué:** el `abstract_inverted_index` de OpenAlex entrega palabras ya sin acentos
(`"Bolvar"`, `"Echeverra"`, y variantes inconsistentes como `"Echeverria's"` junto a
`"Echeverra's"`). El daño viene del depósito del publisher, no de nuestro código:
`invert_abstract` se verificó inocente.
**Por qué no se corrige:**
- e5 es robusto a esa pérdida para el scoring de relevancia.
- El dedup usa *títulos* (que vienen limpios) y además les quita acentos a propósito (T6).
- Los chunks citables de la fase 03 vendrán del PDF vía GROBID, no del abstract;
  solo los papers **sin** PDF se indexan por abstract y arrastrarían este ruido.
**Consecuencia a vigilar:** en fase 03, los papers sin PDF tendrán texto citable de
menor calidad tipográfica. Aceptable; anotarlo si el Verificador (fase 05) se queja.

### A2 · Abstracts en inglés para papers en español
**Descubierto en:** T4 (el primer hit, artículo de *Íconos* en español, trae abstract en inglés).
**Qué:** revistas latinoamericanas frecuentemente depositan el abstract en inglés
aunque el cuerpo sea español. El corpus mezclará idiomas **dentro del mismo registro**.
**Estatus:** no es problema — es la justificación empírica del modelo multilingüe.
El test slow de T7 puede verificar que tema-es ↔ abstract-en quedan cercanos en el
espacio vectorial. Refuerza la decisión A6 del plan (e5 multilingüe), no la contradice.

### A3 · El umbral default 0.35 está en una escala que no corresponde a la de e5
**Descubierto en:** análisis previo a T7 (al juntar la mecánica de scoring del plan con
el default de config).
**Qué:** e5 produce vectores normalizados; el coseno crudo entre dos textos cae en un rango
**estrecho y alto**, típicamente ~0.6–1.0 (rara vez por debajo de 0.6, incluso para textos
no relacionados). El default `relevance_threshold = 0.35` (config, T0) está *por debajo de
ese piso*: con ese valor, el filtro no descartaría prácticamente nada — ni un paper de
química orgánica frente a un tema de filosofía.
**Causa probable:** el 0.35 parece pensado para una escala distinta (p. ej. coseno
re-mapeado a [0,1], o distancia, o un modelo no normalizado). No es bug de código:
el scoring en escala cruda es correcto (así lo pide el plan); es el *parámetro* el que
está en la moneda equivocada.
**Qué esperar:** el umbral final probablemente viva en **~0.75–0.85**, no cerca de 0.35.
**EVIDENCIA EMPÍRICA (test slow de T7, 2026-07-04):** con el modelo real,
tema "recepción crítica de Bolívar Echeverría, filosofía de la cultura":
- abstract on-topic (modernidad barroca, en inglés) → **0.827**
- abstract off-topic (química orgánica, paladio) → **0.699**
Lecturas: (a) el piso del espacio es ~0.70 — hasta lo más ajeno puntúa eso; el 0.35 no
filtraría nada, confirmado. (b) La banda de discriminación es ANGOSTA (~13 centésimas
entre lo perfecto y lo absolutamente ajeno): los casos fronterizos de T13 (menciones de
pasada) vivirán apretados en ~0.72–0.78. La calibración con `papers_discarded` será fina.
(c) El score 0.827 con abstract en INGLÉS y tema en ESPAÑOL valida de paso A2 (alineación
multilingüe de e5 funcionando).
**Acción:** no cambiar el default en config todavía — se ajusta con datos en T13. Solo
tener presente que un umbral bajo en las primeras corridas de prueba dejará pasar ruido,
y eso es esperado, no un fallo.

### A4 · Corrida de humo (T12, tema="Bolívar Echeverría", max=10): predicciones confirmadas
**Números:** 350 raw · 81 dup · **0 low_relevance** · 10 aceptados (tope) · 1 PDF (10 %) ·
30 % DOI · 443.7 s.
**Lecturas:** (a) `low_relevance=0` confirma A3 en producción: con umbral 0.35 nada se
descarta; el corte por max_papers hizo toda la selección y `papers_discarded` no acumuló
scores. (b) El bajo % de PDF/DOI del top-10 es coherente con E3: el tema de humo era solo
el nombre, y lo más similar al puro nombre son las obras primarias (libros sin DOI/OA), no
la literatura secundaria. El tema completo de T13 inclina el espacio hacia la secundaria.
(c) 443 s fueron mayormente costos fijos (carga del modelo vía drvfs, embeddings de ~269
candidatos); T13 con 300 papers ≈ 15–30 min, no proporcional.
**Consecuencia para T13:** la calibración va en dos pasos — corrida completa con umbral
default para poblar 300 scores reales, luego distribución por SQL para elegir el umbral
(no depender de `papers_discarded`, que estará vacía de low_relevance).

---

## B · Deuda técnica aceptada (código que funciona pero podría mejorarse)

### B1 · Conexión SQLite nunca se cierra explícitamente
**Origen:** T2 (`storage.py`).
**Qué:** no hay `close()` ni context manager; la conexión vive hasta que el proceso muere.
**Por qué se acepta en v1:** la pipeline crea un `Storage` por corrida; el SO libera al salir.
**Gatillo para revisar:** si T11 convierte `Storage` en context manager o añade `close()`,
aceptarlo como mejora. No forzarlo ahora.

### B2 · `per-page=200` fijo aunque `max_results` sea menor
**Origen:** T4 (`openalex.py`, `_paginated_works`).
**Qué:** pide 200 resultados por página aunque solo quieras 10. Desperdicia algo de ancho de banda.
**Por qué se acepta:** jamás afecta corrección, solo eficiencia marginal. OpenAlex lo tolera.
**Gatillo:** solo si en T13 la latencia de búsqueda molesta; improbable.

### B3 · `canonical_enrich` no completa el DOI faltante
**Origen:** T5 (`normalize.py`).
**Qué:** si un hit (p. ej. de S2) llega sin DOI pero OpenAlex sí lo conoce, el enriquecimiento
completa abstract/venue/refs/work_type pero **no** rellena el DOI ni recalcula el `paper_id`.
El record conserva su `paper_id` de fallback (`semanticscholar:<id>`).
**Consecuencia:** ese record dedupeará por (título, año), no por DOI (ver C1 abajo).
**Sospechoso nº1** si en T13 aparecen duplicados residuales entre S2 y OpenAlex.
**Decisión:** fiel a la spec; el fallback existe justo para esto. Revisar solo con evidencia en T13.

### B4 · `pipeline._dedup_key` replica la clave privada de `dedup._group_key`
**Origen:** T11 (el `accepted_keys` en memoria necesita la misma clave que usa T6).
**Qué:** la lógica de la clave de agrupación existe en dos lugares. Si algún día cambia en
`dedup.py`, la copia de `pipeline.py` divergiría en silencio.
**Por qué se acepta:** evitó tocar `dedup.py` (regla de no modificar módulos firmados) y la
clave es estable. **Gatillo:** si T6 alguna vez cambia su clave, mover `_group_key` a función
pública y que ambos la importen.

---

## C · Comportamientos deliberados que parecen bugs (no tocar sin causa)

### C1 · Record con DOI y record sin DOI NO se dedupean entre sí
**Definido en:** T6 (spec del prompt).
**Qué:** las claves de agrupación son distintas — `("doi", ...)` vs `("title", ..., year)` —
así que dos versiones del mismo paper, una con DOI y otra sin, no colisionan.
**Por qué es deliberado:** evita fusiones erróneas por títulos genéricos coincidentes.
El enriquecimiento canónico (A2 del plan) minimiza el caso al poblar DOIs antes del dedup.
**Interacción con B3:** si el enriquecimiento no logra el DOI, este caso se materializa.
Es el mecanismo por el que B3 se vuelve visible.

### C2 · NFD sobre «ñ» produce «n» (Diseño → diseno)
**Definido en:** T6 (`normalize_title`).
**Qué:** la descomposición Unicode trata «ñ» como n + tilde combinante y la elimina.
**Por qué es correcto para dedup:** un título depositado sin eñe en una API y con eñe en otra
debe colapsar a un solo registro. Para *dedup* esto es la conducta deseada.
**Ojo:** esto es solo para la CLAVE de dedup. El título *almacenado* conserva su «ñ» intacta
(el ganador se guarda tal cual; solo su clave se normaliza). No confundir ambos.

### C3 · Re-corrida con `max_papers` truncante puede "promover" candidatos antes cortados
**Descubierto en:** T11 (diseño de tests de idempotencia).
**Qué:** si una corrida trunca por `max_papers`, los cortados no se guardan ni se descartan.
En una re-corrida, los que sí se guardaron ya son "conocidos" (se saltan sin competir), así
que candidatos antes cortados pueden entrar al cupo: `storage.count()` puede crecer entre
corridas idénticas cuando hubo truncamiento.
**Por qué es deliberado:** propiedad del orden filtrar-antes-de-cortar. La idempotencia
estricta (count idéntico) se garantiza cuando `max_papers` no trunca; con truncamiento, el
sistema *converge* en corridas sucesivas en vez de en una. Para D4 (T13): la verificación de
idempotencia debe hacerse con el corpus ya convergido o con cupo holgado.

### C4 · Precedencia del `raw` en duplicados: OpenAlex gana (fix manual en T11)
**Qué:** el dict `paper_id → raw` que alimenta la descarga sufría last-write-wins cuando dos
fuentes compartían DOI: el ganador del dedup (OpenAlex) podía recibir el raw del perdedor
(S2), perdiendo `best_oa_location` → PDFs perdidos justo en los papers multi-fuente (que
suelen ser los importantes). **Fix aplicado:** el raw de OpenAlex siempre pisa; entre
no-OpenAlex, el primero queda. Si en T13 el % de PDF sale sospechosamente bajo, verificar
primero que este fix sigue en su sitio.

---

## D · Verificaciones y calibraciones pospuestas a T13 (corrida real)

### D1 · Umbral de relevancia — calibración con evidencia
**Default:** 0.35 (config) — pero ver **A3**: ese 0.35 está en una escala que no corresponde
a la de e5; el valor real probablemente viva en ~0.75–0.85. **Pendiente:** revisar
`papers_discarded` alrededor del umbral que salga del test slow de T7. Si hay falsos descartes
relevantes → bajar. Si en aceptados hay ruido (papers que solo citan a Echeverría de pasada)
→ subir. En tema-autor probablemente el filtro deba ser exigente. **Documentar valor final y
actualizar el default en config una vez calibrado.** Criterio de aceptación 6 del plan.

### D2 · Criterio de PDFs recalibrado a ≥ 40 %
**Origen:** decisión A8. El 60 % original es para STEM (cobertura arXiv). Humanidades en
español tiene cobertura OA estructuralmente menor. Verificar el % real en T13 y, si queda
muy por debajo del 40 %, no es necesariamente un bug: puede ser el techo del dominio. Anotar el valor.
**Primer dato (T10, muestra n=5 del top de búsqueda exacta):** 4/5 con PDF descargado (80 %) —
SciELO/FLACSO/UNAM/USP. El fallido fue una landing HTML de biblat correctamente rechazada por
el guardián `%PDF-`. Muestra pequeña y sesgada al top (los más citados suelen ser OA); el % de
T13 sobre ~300 papers será menor, pero el arranque es alentador.

### D3 · Duplicados residuales por DOI
**Verificación:** `SELECT doi, COUNT(*) FROM papers WHERE doi IS NOT NULL GROUP BY doi
HAVING COUNT(*)>1` debe salir **vacío**. Si no: revisar B3/C1 como causa probable.

### D4 · Idempotencia extremo a extremo
Re-ejecución completa de la pipeline: `count()` idéntico antes y después. Garantizado en
teoría por los upserts; verificar en la práctica con red real (puede haber no-determinismo
en el orden de llegada de las APIs que exponga algún supuesto).

### D5 · Revisión humana del top-20 por score
Los 20 papers de mayor `relevance_score` deben ser, a ojo, inequívocamente sobre Echeverría.
Es la prueba de que el scoring semántico + búsqueda exacta funcionan juntos.

---

## E · Cuestiones abiertas que tocan otras fases (propagar cuando lleguen)

### E1 · Tablas y fórmulas de GROBID (fase 03)
La spec 03 tiene abierto si indexar/ignorar/separar tablas y fórmulas. No es asunto del
Excavador, pero el corpus de humanidades tendrá pocas — probablemente baja prioridad allí.

### E2 · Overlap de chunks (fase 03)
Abierto en spec 03: ¿chunks con solapamiento o sin él? Se decide con las 10 preguntas de prueba
de esa fase. Mención aquí solo para no perderlo de vista.

### E3 · Obras primarias de Echeverría sin PDF OA
**Contexto:** los libros del propio Echeverría (Era, FCE) casi nunca tendrán PDF abierto;
entrarán como registros con `pdf_path=None` + abstract. El corpus **verificable** será la
literatura secundaria; el conocimiento de las obras primarias lo aporta el usuario.
Esto afecta la expectativa de cobertura (D2) y el diseño de síntesis en fase 04.

---

## F · Higiene de proceso (aprendido sobre la marcha)

### F1 · Dos-Pythons: activar `.venv` siempre
Verificar el intérprete antes de correr comandos: la cabecera de pytest debe decir
`.venv/bin/python`, no `/usr/bin/python3`. En VS Code: "Python: Select Interpreter" → `.venv`.
Copilot ya tropezó con esto una vez (corrió `pip install` con el pip del sistema y recibió
`externally-managed-environment`); inofensivo pero reconocible.

### F2 · Un commit por tarea firmada
Cada T que pasa sus criterios de "hecho" → un commit con mensaje `TN: descripción`.
Es la red de seguridad para revertir si una tarea posterior rompe algo.

### F3 · Ruta real de los docs en el repo
Los contratos viven en `docs/01-CONTRATOS-DE-DATOS_v11.md` (con sufijo `_v11`) y
`docs/02-PLAN-IMPLEMENTACION-EXCAVADOR.md`. El preámbulo de cada prompt debe usar la ruta exacta.

### F4 · Tests de Settings deben aislarse del `.env` real; los logs imprimen secretos
**Descubierto en:** T8 (fallo de `test_settings_defaults...` al añadir la API key de S2 al `.env`).
**Qué:** (a) todo test que instancie `Settings()` debe hacer `monkeypatch.chdir(tmp_path)`
primero, o hereda el `.env` real del repo y se vuelve dependiente del entorno de la máquina.
(b) Los tracebacks de pytest imprimen el repr completo de Settings, **incluidos los secretos**:
un log de test pegado en cualquier lado filtra la API key. La key de S2 expuesta el 2026-07-05
se rotó (o debe rotarse). Regla: antes de compartir logs, revisar si contienen valores de Settings.

---

## Estado de tareas

| Tarea | Estado | Commit |
|-------|--------|--------|
| T0 · Bootstrap | ✅ firmado | sí |
| T1 · Modelos C1 | ✅ firmado | sí |
| T2 · Storage SQLite | ✅ firmado | sí |
| T3 · ApiClient base | ✅ firmado | sí |
| T4 · Cliente OpenAlex | ✅ firmado | sí |
| T5 · Normalización | ✅ firmado | sí |
| T6 · Dedup | ✅ firmado | sí |
| T7 · Relevancia (e5) | ✅ firmado | sí |
| T8 · Crossref + S2 | ✅ firmado | sí |
| T9 · Snowball | ✅ firmado | sí |
| T10 · Descarga PDFs | ✅ firmado | sí |
| T11 · Pipeline | ✅ firmado | sí |
| T12 · CLI | ✅ firmado | sí |
| T13 · Corrida real | 🔄 en curso | — |
