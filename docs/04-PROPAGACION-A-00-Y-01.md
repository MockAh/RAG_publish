# 04 · Cambios a propagar a `00` y `01` (cierre de fase, 2026-11-05)

> Aplicar estos cambios a mano en los documentos maestros, como en la fase 03. Son pocos y
> aditivos: **ningún contrato existente se rompe**. Los esquemas C3, C4 y C5 se
> transcribieron literalmente en `expertos/models.py` (N6).
> Si la propagación de fase 03 (`03-PROPAGACION-A-00-Y-01.md`, `01` → v1.2) todavía no se ha
> aplicado, aplicarla primero: esta lleva `01` a v1.3.

---

## A · `01-CONTRATOS-DE-DATOS.md` → v1.3

### A1 · C3 · Claim — nota sobre `supporting_chunks` (el esquema NO cambia)

Añadir tras el bloque de C3:

> **Nota v1.3 (fase 04):** una `Claim` con `supporting_chunks=[]` es inválida (lo exige D5:
> nada se afirma sin `chunk_id`). La implementación lo valida con `min_length=1`, también
> dentro de `ExpertAnswer.evidence` (C5). Además, todo `chunk_id` debe estar entre los
> pasajes que el Experto recuperó: la claim que cite otro se **descarta, no se repara**
> (X3 de fase 04).
>
> **Semántica de `stance` (fase 04, A19):** cuando una tesis tiene defensores y críticos en
> el corpus, el Experto emite un **par** de claims con el mismo texto de la tesis: una
> `supports` (cita el pasaje que la atribuye) y otra `contradicts` (cita el pasaje que la
> discute). El chunk del miembro `contradicts` no sustenta la atribución por sí solo
> (E6 → fase 05).

### A2 · Nuevo bloque tras C4 · contenedor `SynthesisMap`

C4 define solo la entrada. El archivo `data/synthesis_map.json` es este contenedor
(decisión de fase 04, C3 del registro):

```python
class SynthesisMap(BaseModel):
    run_id: str              # run de clustering del que sale la partición
    updated_at: datetime
    entries: list[SynthesisMapEntry]   # C4 literal; expert_id único
```

Tamaño medido: ~1 453 tokens para 9 entradas (criterio ≤ 4 000).

### A3 · C5 · ExpertAnswer — nota sobre `gaps` y `confidence` (el esquema NO cambia)

> **Nota v1.3 (fase 04):** `gaps` no tiene default: el Experto siempre se pronuncia, y
> `None` significa «los pasajes leídos cubren la pregunta». `gaps` se refiere a los
> pasajes recuperados, no a todo el corpus del Experto. Sin ninguna claim válida, la
> respuesta es `confidence="low"` con prosa fija, sea cual sea el juicio del LLM.
> `confidence` es juicio del LLM, no umbral numérico (L1), y solo se ha medido que separa
> preguntas trampa de controles (N13).

### A4 · Tabla de parámetros globales — añadir filas

| Parámetro | Valor v1.3 |
|---|---|
| Clustering de Expertos | k-means sobre vectores `passage: título. abstract` normalizados, **k = 9**, seed 42 (k elegido por inspección humana, no por silhouette). Re-clusterizar desde cero en cada ingesta. |
| Retrieval del modo consulta | Pregunta tal cual como única consulta, `top_k = 32`, filtrada a la partición del Experto |
| Retrieval del modo síntesis | 8–12 sub-consultas generadas por el LLM; 6–15 claims por Synthesis |

## B · `00-VISION-Y-ARQUITECTURA.md`

### B1 · Sección 3 · Decisiones ya tomadas — añadir filas

| # | Decisión | Razón |
|---|----------|-------|
| D10 | Los agentes LLM se acceden vía una interfaz agnóstica de proveedor (`LLMClient.complete_json(system, user, schema)`) | Cambiar de proveedor es una línea de configuración; hace posible D11. La fase 04 pasó de Gemini a DeepSeek (X6‴) sin tocar código de agentes |
| D11 | El Verificador (fase 05) usa un proveedor LLM distinto al del Redactor | Decisión de arquitectura, no solo de la fase 05 (tomada en N0 de fase 04). Ya es posible sin tocar código de agentes gracias a D10 |
| D12 | Las restricciones de cita las garantiza el código, no el prompt | En fase 04 la validación `supporting_chunks ⊆ recuperados` cazó un `chunk_id` inventado con apariencia realista (A21) |

### B2 · Sección 4 · Stack por defecto — sustituir la línea de agentes

Antes:
> - **Agentes LLM:** API de Anthropic; cada agente = un prompt de sistema + herramientas, no un proceso aparte.

Después:
> - **Agentes LLM:** proveedor configurable tras una interfaz común (D10); cada agente = un
>   prompt de sistema + herramientas, no un proceso aparte. Fase 04: DeepSeek
>   (`deepseek-flash` para etiquetado, `deepseek-v4-pro` para síntesis y consulta);
>   Gemini (`gemini-3.6-flash`) reservado como segundo proveedor para D11. Elegidos por
>   disponibilidad, no por calidad de juicio medida. Toda llamada queda en la tabla
>   SQLite `llm_calls`.

### B3 · Sección 5 · Orden de implementación

Marcar el punto 4 como hecho:
> 4. Clustering + Expertos + Mapa de Síntesis (`04`) — **CERRADA 2026-11-05**
