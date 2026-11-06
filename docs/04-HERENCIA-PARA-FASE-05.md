# 04 → 05 · Herencia de los Expertos

> Resumen de lo que la fase 05 (Orquestador, Redactor, Verificador) debe saber antes de empezar.
> El detalle completo está en `04-REGISTRO-CONSIDERACIONES-EXPERTOS.md` (las referencias A·B·C·E
> apuntan allí). Estado de la fase 04: **CERRADA 2026-11-05** (N0–N14).
> Sigue vigente `03-HERENCIA-PARA-FASES-04-Y-05.md` (L1, L2, E1–E6 de la fase 03).

## 1 · Qué existe y cómo se usa

**9 Expertos** (`C0`–`C8`) sobre **154 papers** efectivos. Partición en la tabla `clusters` de
`data/excavador.db`, run `kmeans-k9-seed42-98b2c308` (`Settings.cluster_run_id`). Leerla siempre
con `load_corpus_assignment`, que aplica la stoplist (E4), nunca con `load_assignment`.

| Artefacto | Ruta | Cómo se lee | En git |
|---|---|---|---|
| Mapa (C4) | `data/synthesis_map.json` | `load_synthesis_map(path=...)`; texto para el prompt con `map_text` | no |
| Synthesis (C3) | `data/synthesis/{expert_id}.json` | `load_synthesis` / `load_all_syntheses(synthesis_dir=...)` | no |
| Etiquetas | `data/cluster_labels.json` | las necesita `answer_question` | sí |
| Consultas auditadas | `data/consult/` | `load_consult` | no |

**Modo consulta** (lo que llamará el Orquestador):

```python
from expertos.consult import answer_question, save_consult
rec = answer_question(expert_id, question, label, make_client("synthesis", settings),
                      ChunkStore(settings.chroma_dir), run_id=settings.cluster_run_id,
                      db_path=settings.db_path, excavador_storage=...)
save_consult(rec, consult_dir=settings.consult_dir)   # auditoría: nunca pisa un archivo
rec.answer  # ExpertAnswer (C5)
```

Desde la terminal: `python -m expertos ask --expert-id C6 "<pregunta>"`. Una llamada al LLM
(`deepseek-v4-pro`) por pregunta, `top_k = 32` y sin sub-consultas.

## 2 · Lo que el Orquestador debe saber al rutear

- **El mapa no dice qué Expertos son débiles (E7).** C1 y C8 se etiquetaron `coherent=false` (A13).
  C7 es un volumen de homenaje, no un tema (A9). C0 (6 papers) y C8 (5) son pequeños. C4 no tiene
  campo para esto: decidir con preguntas de ruteo reales si hace falta.
- **`confidence` solo está medida para separar trampa de control** (N13: 45/45 `low`, 18/18
  responden). Que `high` sea más fiable que `medium` no se ha medido. Es juicio del LLM, no score
  (L1). No usarla como peso numérico.
- **`gaps` habla de los pasajes leídos** (top 32), no de todo el corpus del Experto. Un hueco puede
  estar cubierto por pasajes que el retrieval no trajo: con `top_k=32` llegaron 47 de 58 pasajes de
  referencia (A28).
- **Corpus monotemático** (todo gira en torno a Echeverría): varios Expertos pueden responder
  a la misma pregunta. Las etiquetas se solapan (C1/C2/C4 mencionan «modernidad» y «marxismo»).

## 3 · Lo que el Redactor y el Verificador deben saber

- **La prosa de `answer` no la valida el código (A26).** El código solo garantiza que cada
  `chunk_id` de `evidence` existe y estaba entre los pasajes recuperados (D5, X3). Lo que se
  verifica con código son las claims; la prosa, no. Tampoco se ha medido la fidelidad de las
  respuestas de control ni la de las citas textuales (N13 → 05).
- **E6 · Pares `supports`/`contradicts` (A19).** El miembro `contradicts` cita el pasaje que
  *discute* la tesis, no el que la atribuye. Un Verificador frase-contra-chunk lo marcaría
  `not_entailed` por diseño. Afecta a los 7 `contradicts` de las Synthesis. Hay dos salidas:
  (a) el Redactor cita la atribución con el chunk del miembro `supports`;
  (b) el Verificador trata el par como unidad.
- **E5 · Obras primarias (A17).** `doi:10.29166/economia.v70i111.1393` (C1) es *El capital* de
  Marx traducido por Echeverría. La atribución sigue a `authors` del paper. Lista en
  `PRIMARY_WORKS` (`expertos/assignments.py`, 4 papers).
- **E4 · DOI cruzado.** `doi:10.1002/ajpa.22921` titula un artículo sobre Echeverría, pero el DOI
  y el abstract son de otro artículo. Está excluido de la partición, pero sigue en `excavador.db` y
  en Chroma. Si aparece en una bibliografía, la cita es falsa.
- **B2 · Títulos con HTML escapado.** Aplicar `html.unescape` al imprimir la bibliografía.
- **`stance` casi siempre `supports`** (121/128). `mentions` = 0 por estructura (A24), no por
  fallo. No inferir ausencia de crítica en el corpus a partir de ahí.

## 4 · Infraestructura reutilizable

- **Cliente LLM agnóstico** (`expertos/llm.py`, X8/D10): `make_client(task, settings)` →
  `complete_json(system, user, schema)`. DeepSeek y Gemini implementados: **D11** (Verificador con
  otro proveedor que el Redactor) es cuestión de configuración (E1). Gemini free tier: 5 RPM,
  20 peticiones/día, 503 frecuentes (A10). Hay que sondear la cuota real antes de depender de él.
- **`llm_calls`** registra toda llamada con `context` JSON. Base para el presupuesto por consulta
  de la spec 05 (E2). Ante un fallo, leer `llm_calls.error` en vez de relanzar (F5).
- **Coste de referencia:** regenerar todas las síntesis cuesta 0,26 USD y 908 s (A22). DeepSeek es
  prepago: un 402 significa saldo agotado y no se reintenta.

## 5 · Deuda que hereda

- **B3 · Regeneración tras ingesta (Q1) sin implementar.** Es una secuencia manual de CLI.
  La regeneración selectiva por Jaccard < 0.8 no existe. Al re-clusterizar cambian el `run_id` y,
  posiblemente, los `expert_id`. El Orquestador no debe guardar `expert_id` fijos.
- **E3 · DOI-variante duplicados** en `excavador.db` y Chroma (3 colapsados, 4 grupos sospechosos
  más). No distorsionan la partición.
- **Q2 · Sin síntesis jerárquicas.** Gatillo: un clúster con > 40 papers o > 600 chunks. Hoy el
  mayor es C2, con 35.
