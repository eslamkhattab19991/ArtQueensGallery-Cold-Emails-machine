# Art Queens Gallery — Artist Prospecting System

An AI-powered prospecting pipeline that discovers, qualifies, and enriches
professional female artists as candidates for premium international exhibitions.

The objective is a continuously growing database of qualified artists — a
reusable business asset — not a one-off list of scraped email addresses.

**[`ARCHITECTURE.md`](ARCHITECTURE.md) is the source of truth** for pipeline
stages, schemas, and module responsibilities. This README covers only how to work
with the repository.

## Requirements

- Python 3.12 or newer
- Git

## Setup

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -e ".[dev]"
```

```bash
copy .env.example .env
```

On macOS or Linux, activate with `source .venv/bin/activate` and copy with `cp`.

## Quality gates

All four must pass before a commit. They are the same checks CI runs.

```bash
ruff format --check .
```

```bash
ruff check .
```

```bash
mypy
```

```bash
pytest
```

Architectural boundaries are additionally enforced by Import Linter:

```bash
lint-imports
```

## Repository layout

```
config/          YAML configuration and prompt templates — no behaviour is hard-coded
data/            Pipeline artefacts (git-ignored; see ARCHITECTURE.md §3)
src/prospecting/ Application package
tests/           unit · contract · invariants · architecture
```

## Configuration

Behaviour lives in `config/*.yaml`; secrets live in `.env`. Values are layered,
lowest precedence first:

1. `config/runtime.yaml` and `config/icp.yaml` — the committed baseline
2. `config/profiles/<name>.yaml` — selected by `PROSPECTING_PROFILE`
3. `PROSPECTING__SECTION__KEY` environment variables

```bash
PROSPECTING_PROFILE=dev PROSPECTING__LOG__LEVEL=DEBUG python -m pytest
```

Configuration is loaded explicitly and passed explicitly — there is no global
accessor:

```python
from prospecting.config import load_settings

settings = load_settings()
settings.runtime.max_concurrent_requests
```

Every load records its own provenance in `settings.meta`: which files were
merged, which profile applied, and which environment variables overrode a file
value. Invalid configuration fails at startup with every problem listed at once,
not on the first API call an hour into a run.

Inside `src/prospecting`, dependencies point inward only:

```
config.container            composition root — may import anything
  pipeline · contact · enrichment · scoring · identity · compliance
    ports                   abstract capability contracts
      domain                pure model; imports nothing from this package
```

This is enforced mechanically by `tests/architecture/` and the Import Linter
contracts in `pyproject.toml`, not by convention. A change that violates the
layering fails the test suite.

## Command line

Installing the package (`pip install -e .`) puts the `prospect` command on the
path:

```bash
prospect config
```

```bash
prospect run
```

`prospect config` loads, validates, and prints the resolved configuration with
its provenance — the fastest way to confirm an edit to `config/*.yaml` is
well-formed before starting a run, with every problem reported at once. `prospect
run` executes the pipeline for one run; until the provider stages land it reports
that no stages are wired yet rather than doing nothing silently. `--profile`
selects a config overlay; `run` also takes `--run-id` (to resume a run) and
`--no-resume` (to start fresh).

## Implementation status

Built in reviewed phases; each phase compiles, is tested, and is committed before
the next begins.

| Phase | Component | Status |
|------:|-----------|--------|
| 1 | Project skeleton and boundary enforcement | ✅ Complete |
| 2 | Configuration system | ✅ Complete |
| 3 | Domain models | ✅ Complete |
| 4 | Schemas — stage-boundary contracts | ✅ Complete |
| 5 | Ports — abstract capability contracts | ✅ Complete |
| 6 | Plugin system — contact-source registry | ✅ Complete |
| 7 | Checkpoint manager — resumable stages | ✅ Complete |
| 8 | Pipeline engine — orchestrator, gate, budget | ✅ Complete |
| 9 | Logging system — structured text/JSON | ✅ Complete |
| 10 | CLI — `prospect` command + composition root | ✅ Complete |
| 11 | Unit tests across all phases | ✅ Complete (99% coverage) |

The framework skeleton (phases 1–11) is complete: 560+ tests, mypy strict, and
seven architectural boundary contracts, all green. Providers follow, in order:
Firecrawl → HTML parser → contact discovery engine → search providers → LLM
adapters → exporters — and with the framework proven against stubs, each one
slots into a single wiring point.

## Initial input dataset

`Galleries sheet.xlsx` — 192 art-world organizations (name, Instagram, website),
of which 19 have no website and are Instagram-only. These are **discovery
surfaces**, not leads: each is crawled to find the artists it presents.

The rows are heterogeneous — galleries, prizes and open calls, magazines,
museums, and suppliers — and each type presents artists differently, so the
ingestion schema classifies organization type and Stage 2 routes its crawl
strategy accordingly.
