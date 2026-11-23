# RAG_publish

**Español** · [English](README.en.md)

Sistema multiagente de investigación y escritura académica con **citas verificables**.
El usuario hace una pregunta o encarga una sección; el sistema responde con prosa académica
donde cada afirmación factual está citada y cada cita se coteja contra un corpus de papers.

> **Estado:** en desarrollo. Fases 02–04 cerradas; la fase 05 (Orquestador, Redactor y
> Verificador) está en curso. Todavía no hay un flujo de pregunta → sección verificada de
> extremo a extremo; lo que funciona hoy es la consulta a cada Experto por separado.

## Cómo funciona

Dos fases desacopladas por una memoria compartida:

**Ingesta (offline, periódica)**

```
Excavador → Filtro/Dedup → Procesador (GROBID) → Indexador → Biblioteca RAG
                                   → clustering temático → Expertos → Mapa de Síntesis
```

Los papers sin PDF entran por una ruta alterna: título + abstract como chunk único.

**Consulta (online)**

```
Usuario → Orquestador (lee el Mapa, rutea) → Expertos (retrieval en su partición)
        → Redactor (prosa con citas [n]) → Verificador (entailment cita ↔ pasaje) → Usuario
```

- **Biblioteca RAG:** base vectorial (Chroma embebida) + metadatos en SQLite. Es la fuente
  de verdad citable; cada chunk lleva DOI, sección y offsets.
- **Mapa de Síntesis:** índice compacto tema → resumen → Expertos → papers.

### Principios de diseño

- **El código garantiza las citas, no el prompt.** Toda cita debe apuntar a un pasaje
  recuperado de verdad; las que no, se descartan (en la fase 04 esto cazó un `chunk_id`
  inventado con apariencia realista).
- **Ningún juicio sale de un umbral de similitud.** La confianza y el entailment son
  juicios del LLM leyendo el pasaje, no comparaciones numéricas de scores.
- **El Verificador usa un proveedor LLM distinto al del Redactor.** Los agentes acceden
  al LLM por una interfaz agnóstica (`LLMClient.complete_json`), así que cambiar de
  proveedor es configuración.
- **El corpus citable no es todo el corpus recuperado:** solo cuentan los papers con
  texto indexado.

## Estado por fase

| Fase | Componente | Estado |
|------|------------|--------|
| 01 | Contratos de datos (C1–C7) | v1.3 |
| 02 | Excavador + Filtro (`excavador/`) | ✅ cerrada · 227 papers recuperados |
| 03 | Procesador + Indexador + Biblioteca (`biblioteca/`) | ✅ cerrada · 1 959 chunks de 158 papers |
| 04 | Clustering + Expertos + Mapa de Síntesis (`expertos/`) | ✅ cerrada · 9 Expertos sobre 154 papers |
| 05 | Orquestador + Redactor + Verificador (`redaccion/`) | 🚧 en curso |

El corpus actual trata la recepción crítica de la obra de Bolívar Echeverría (modernidad
barroca, ethos histórico, valor de uso, marxismo crítico), repartido en nueve Expertos
temáticos (`C0`–`C8`).

## Estructura del repositorio

```
excavador/    búsqueda en APIs académicas (OpenAlex, Semantic Scholar, Crossref, arXiv),
              normalización, deduplicación, relevancia y snowballing
biblioteca/   GROBID → TEI → chunks → embeddings → Chroma; consulta y lectura por chunk_id
expertos/     vectores por paper, clustering, etiquetado, síntesis por Experto,
              Mapa de Síntesis, modo consulta y preguntas trampa
redaccion/    fase 05: Orquestador, Redactor y Verificador (en construcción)
docs/         visión, contratos, specs, planes y registros de cada fase
tests/        suite de pytest
```

## Requisitos

- Python 3.12
- Docker, para GROBID (parsing de PDF), solo si vas a indexar
- Claves de API de los proveedores LLM que uses

Modelo de embeddings: `intfloat/multilingual-e5-large` (se descarga la primera vez).

## Instalación

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuración

Cada paquete lee el `.env` de la raíz con su propio prefijo: `EXCAVADOR_`, `BIBLIOTECA_`,
`EXPERTOS_`, `REDACCION_`. Las más importantes:

| Variable | Para qué |
|----------|----------|
| `EXCAVADOR_OPENALEX_MAILTO` | Correo de contacto que pide OpenAlex (obligatoria) |
| `EXCAVADOR_SEMANTICSCHOLAR_API_KEY` | Opcional |
| `BIBLIOTECA_GROBID_URL` | Por defecto `http://localhost:8070` |
| `EXPERTOS_LLM_PROVIDER` | `deepseek` o `gemini` |
| `EXPERTOS_DEEPSEEK_API_KEY`, `EXPERTOS_GEMINI_API_KEY` | Claves de los proveedores |
| `EXPERTOS_MODEL_SYNTHESIS`, `EXPERTOS_MODEL_LABEL` | Modelos por tarea |

El resto tiene valores por defecto razonables; consulta el `config.py` de cada paquete.
`.env` y `data/` no están versionados: el corpus, la base SQLite, el índice Chroma y las
síntesis se generan localmente.

## Uso

```bash
# 1. Recolectar papers sobre un tema
python -m excavador run --tema "..." --max-papers 300
python -m excavador stats

# 2. Indexar (requiere GROBID corriendo) y consultar la Biblioteca
python -m biblioteca index
python -m biblioteca query "texto de la consulta" --top-k 5
python -m biblioteca get <chunk_id>

# 3. Expertos: vectores, clustering, etiquetado, síntesis y Mapa
python -m expertos vectors build
python -m expertos cluster sweep              # informe para elegir k
python -m expertos cluster inspect --k 9      # inspección humana del k candidato
python -m expertos cluster assign --k 9       # imprime el run_id de la asignación
python -m expertos cluster label
python -m expertos synthesis retrieve
python -m expertos synthesis draft
python -m expertos map build

# 4. Preguntarle a un Experto
python -m expertos ask "¿Qué entiende Echeverría por valor de uso?" --expert-id C6
```

Los comandos de `expertos` posteriores a `assign` usan el `run_id` de
`EXPERTOS_CLUSTER_RUN_ID` (o `--run-id`); con un corpus nuevo, ponlo al valor que imprimió
`assign`. Usa `--help` en cada comando para ver todas sus opciones.

Toda llamada a un LLM, con éxito o con fallo, queda registrada en la tabla `llm_calls` de
`data/excavador.db`.

## Tests

```bash
pytest              # excluye los tests lentos
pytest -m slow      # tests que cargan el modelo real de embeddings
```

## Documentación

Empieza por [`docs/00-VISION-Y-ARQUITECTURA.md`](docs/00-VISION-Y-ARQUITECTURA.md) y
[`docs/01-CONTRATOS-DE-DATOS_v11.md`](docs/01-CONTRATOS-DE-DATOS_v11.md). Cada fase tiene en
`docs/` su spec, su plan de micro-tareas y su registro de consideraciones (decisiones,
hallazgos y pendientes).
