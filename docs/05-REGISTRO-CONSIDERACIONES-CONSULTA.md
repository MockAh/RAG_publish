# 05 · Registro de consideraciones — Orquestador + Redactor + Verificador

> Compañero del plan de micro-tareas (`05-PLAN-MICROTAREAS-CONSULTA.md`).
> Recoge hallazgos, deuda aceptada y herencias entre micro-tareas.
> Estado: **fase en curso** · R0 firmada (2026-11-07), R1 firmada (2026-11-15), plan v1.

---

## A · Hallazgos de datos reales

- **A1 · Pares E6 incompletos (R0, 2026-11-07).** De los 7 claims `contradicts` de las Synthesis,
  solo 2 tienen gemelo `supports` con el mismo texto (C6, C8). Los otros 5 están solos (C0, C1,
  C2, C4 ×2). E6 de fase 04 suponía pares completos. Lleva a la regla general de Y9: un chunk
  `contradicts` solo sostiene una pieza que reporta la objeción.
- **A2 · Datos bibliográficos limitados (R0).** `papers` no tiene volumen, número, páginas,
  editores ni editorial. En `excavador.db` (227 filas, incluye no indexados): `venue` 199,
  DOI 130. APA completo imposible → Y12.
- **A3 · Numeración de chunks (R0, sin verificar).** El índice final del `chunk_id` parece
  correlativo por paper, no por sección (`…#Postura…#26`, `#30`, `…#Conclusiones#43` en
  `doi:10.37819/humanrev.v9i2.866`). Afecta a los vecinos de Y13 → verificar en R9.
- **A4 · Coste de referencia de una consulta de Experto (R0).** 147 llamadas `deepseek-v4-pro`
  de fase 04: media ~7 425 tokens de entrada, ~1 740 de salida, ~20,3 s (`llm_calls`). Una
  auditoría de consulta ocupa ~54 KB en disco. Base para Y7 e Y11.
- **A5 · Abreviaturas reales en chunks.** Los chunks de cuerpo traen citas parentéticas
  («Echeverría Andrade, 2006, p. 190»): material para la capa (a) del catálogo de Y6.

## B · Deuda técnica aceptada

*(vacío)*

## C · Comportamientos deliberados que parecen bugs

- **C1 · `VerificationReport(passed=False, failures=[])` es válido (R1).** C7 solo admite fallos
  con `chunk_id`; una pieza ⟨sin fuente⟩ (Y8) no tiene, pero cuenta como fallo. El validador solo
  rechaza `passed=True` con fallos. El detalle por pieza vive en el registro de Y7 (`PieceLog`).
- **C2 · `DraftSection` sin validadores (R1).** Un `[n]` sin entrada en `citations`, o al revés,
  no rechaza el borrador: lo detecta y registra el código del Redactor (Y5, Y6) en R5–R6.
- **C3 · `PieceRecord.status="unverified"` admite veredictos parciales o ninguno (R1).** Es el
  corte por presupuesto (Y11) o el agotamiento de ciclos. Los estados `verified`/`failed` sí
  exigen un veredicto por cada `chunk_id` citado (Y7).

## D · Verificaciones pospuestas

- **D1 · Segmentadores externos (Y6).** pySBD/Punkt citados como candidatos, sin probar: su
  soporte de español se verifica con ejecución real en R6 antes de depender de ellos.
- **D2 · Numeración de vecinos (A3)** → R9.

## E · Cuestiones que tocan otras fases

*(vacío)*

## F · Higiene de proceso

Heredadas y vigentes: F1–F5 de fase 04 (imprimir el valor efectivo antes de formular hipótesis;
`grep -c` y `&&`; `.venv` siempre; una conclusión de un asistente no es evidencia; leer la salida
y `llm_calls.error` antes de relanzar algo que gasta cuota).

---

## Estado de micro-tareas

| # | Tarea | Estado |
|---|---|---|
| R0 | Decisiones Y1–Y14 | ✅ 2026-11-07 |
| R1 | Bootstrap `redaccion/` | ✅ 2026-11-15 |
