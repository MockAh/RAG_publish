# 03 · Registro de consideraciones — Biblioteca RAG

> Compañero del plan de micro-tareas (`03-PLAN-MICROTAREAS-BIBLIOTECA.md`).
> Recoge hallazgos, deuda aceptada y herencias entre micro-tareas.
> Estado: **vivo** · fase 03 en curso desde 2026-07-20.

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

## B · Deuda técnica aceptada

*(vacío aún)*

## C · Comportamientos deliberados que parecen bugs

*(vacío aún)*

## D · Verificaciones pospuestas

- **D1 (→M15):** calidad del TEI en `work_type=book/book-chapter`; activar fallback P5 si aplica.
- **D2 (→M17):** ¿overlap de chunks? Decidir con las 10 preguntas de prueba.
- **D3 (→M14):** tasa real de fallo de GROBID sobre los 55 PDFs (criterio 1: ≥ 95 %).
- **D4 (→M16):** `get_chunk` reconstruye texto exacto (criterio 4, requisito del Verificador).

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

---

## Estado de micro-tareas

| # | Tarea | Estado |
|---|---|---|
| M0 | Decisiones P1–P6 | ✅ 2026-07-20 |
| M1 | Bootstrap `biblioteca/` | ✅ 2026-07-20 · commit a973f62 |
| M2 | GROBID vivo + primer TEI | ✅ 2026-07-20 · hallazgos A1–A5 |
| M3–M18 | — | pendientes |
