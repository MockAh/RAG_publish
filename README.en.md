# RAG_publish

[Español](README.md) · **English**

A multi-agent system for academic research and writing with **verifiable citations**.
The user asks a question or requests a section; the system answers in academic prose where
every factual claim is cited and every citation is checked against a corpus of papers.

> **Status:** under development. Phases 02–04 are closed; phase 05 (Orchestrator, Writer
> and Verifier) is in progress. There is no end-to-end question → verified section flow
> yet; what works today is querying each Expert on its own.

> The code, CLI messages and project documents (`docs/`) are written in Spanish.

## How it works

Two phases decoupled by a shared memory:

**Ingestion (offline, periodic)**

```
Excavator → Filter/Dedup → Processor (GROBID) → Indexer → RAG Library
                                   → topic clustering → Experts → Synthesis Map
```

Papers without a PDF take an alternate route: title + abstract as a single chunk.

**Query (online)**

```
User → Orchestrator (reads the Map, routes) → Experts (retrieval within their partition)
     → Writer (prose with [n] citations) → Verifier (citation ↔ passage entailment) → User
```

- **RAG Library:** vector store (embedded Chroma) + metadata in SQLite. It is the citable
  source of truth; every chunk carries DOI, section and offsets.
- **Synthesis Map:** a compact index topic → summary → Experts → papers.

### Design principles

- **Citations are enforced by code, not by the prompt.** Every citation must point to a
  passage that was actually retrieved; any that don't are discarded (in phase 04 this
  caught a realistic-looking, invented `chunk_id`).
- **No judgment comes from a similarity threshold.** Confidence and entailment are LLM
  judgments made by reading the passage, not numeric score comparisons.
- **The Verifier uses a different LLM provider than the Writer.** Agents reach the LLM
  through a provider-agnostic interface (`LLMClient.complete_json`), so switching
  providers is a configuration change.
- **The citable corpus is not the whole retrieved corpus:** only papers with indexed text
  count.

## Status by phase

| Phase | Component | Status |
|-------|-----------|--------|
| 01 | Data contracts (C1–C7) | v1.3 |
| 02 | Excavator + Filter (`excavador/`) | ✅ closed · 227 papers retrieved |
| 03 | Processor + Indexer + Library (`biblioteca/`) | ✅ closed · 1,959 chunks from 158 papers |
| 04 | Clustering + Experts + Synthesis Map (`expertos/`) | ✅ closed · 9 Experts over 154 papers |
| 05 | Orchestrator + Writer + Verifier (`redaccion/`) | 🚧 in progress |

The current corpus covers the critical reception of Bolívar Echeverría's work (baroque
modernity, historical ethos, use value, critical Marxism), split across nine topic
Experts (`C0`–`C8`).

## Repository layout

```
excavador/    search over academic APIs (OpenAlex, Semantic Scholar, Crossref, arXiv),
              normalization, deduplication, relevance scoring and snowballing
biblioteca/   GROBID → TEI → chunks → embeddings → Chroma; querying and lookup by chunk_id
expertos/     per-paper vectors, clustering, labeling, per-Expert synthesis,
              Synthesis Map, query mode and trap questions
redaccion/    phase 05: Orchestrator, Writer and Verifier (under construction)
docs/         vision, contracts, specs, plans and logs for each phase
tests/        pytest suite
```

## Requirements

- Python 3.12
- Docker, for GROBID (PDF parsing), only if you are going to index
- API keys for the LLM providers you use

Embedding model: `intfloat/multilingual-e5-large` (downloaded on first use).

## Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

Each package reads the root `.env` with its own prefix: `EXCAVADOR_`, `BIBLIOTECA_`,
`EXPERTOS_`, `REDACCION_`. The most important ones:

| Variable | Purpose |
|----------|---------|
| `EXCAVADOR_OPENALEX_MAILTO` | Contact email required by OpenAlex (required) |
| `EXCAVADOR_SEMANTICSCHOLAR_API_KEY` | Optional |
| `BIBLIOTECA_GROBID_URL` | Defaults to `http://localhost:8070` |
| `EXPERTOS_LLM_PROVIDER` | `deepseek` or `gemini` |
| `EXPERTOS_DEEPSEEK_API_KEY`, `EXPERTOS_GEMINI_API_KEY` | Provider keys |
| `EXPERTOS_MODEL_SYNTHESIS`, `EXPERTOS_MODEL_LABEL` | Per-task models |

Everything else has sensible defaults; see each package's `config.py`. `.env` and `data/`
are not versioned: the corpus, the SQLite database, the Chroma index and the syntheses are
generated locally.

## Usage

```bash
# 1. Collect papers on a topic
python -m excavador run --tema "..." --max-papers 300
python -m excavador stats

# 2. Index (requires GROBID running) and query the Library
python -m biblioteca index
python -m biblioteca query "query text" --top-k 5
python -m biblioteca get <chunk_id>

# 3. Experts: vectors, clustering, labeling, synthesis and Map
python -m expertos vectors build
python -m expertos cluster sweep              # report for choosing k
python -m expertos cluster inspect --k 9      # human inspection of the candidate k
python -m expertos cluster assign --k 9       # prints the assignment's run_id
python -m expertos cluster label
python -m expertos synthesis retrieve
python -m expertos synthesis draft
python -m expertos map build

# 4. Ask an Expert
python -m expertos ask "¿Qué entiende Echeverría por valor de uso?" --expert-id C6
```

The `expertos` commands after `assign` use the `run_id` from `EXPERTOS_CLUSTER_RUN_ID`
(or `--run-id`); with a new corpus, set it to the value `assign` printed. Run `--help` on
any command to see all its options.

Every LLM call, successful or not, is logged in the `llm_calls` table of
`data/excavador.db`.

## Tests

```bash
pytest              # skips slow tests
pytest -m slow      # tests that load the real embedding model
```

## Documentation

Start with [`docs/00-VISION-Y-ARQUITECTURA.md`](docs/00-VISION-Y-ARQUITECTURA.md) and
[`docs/01-CONTRATOS-DE-DATOS_v11.md`](docs/01-CONTRATOS-DE-DATOS_v11.md) (in Spanish). Each
phase has its spec, micro-task plan and log of considerations (decisions, findings and
open items) in `docs/`.
