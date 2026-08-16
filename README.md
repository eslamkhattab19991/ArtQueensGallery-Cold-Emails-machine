# Art Queens Gallery - Artist Prospecting System

This repository helps Art Queens Gallery turn a sheet of art-world organizations
into a list of contactable female artists for outreach.

The project is meant to run locally with Claude Code on a Windows PC. The
current handoff flow is simple:

1. Set up the folder on the computer.
2. Put the galleries sheet in the project root.
3. Run the pipeline locally.
4. Pause once for the gender check.
5. Review the CSV files in `output/`.

## What the system does

- Reads `Galleries sheet.xlsx`
- Finds artists on the listed organizations' websites
- Checks which artists fit the project rules
- Finds and verifies personal email addresses
- Writes the final lead files for review

## What command to use

Use this command to run the local workflow:

```bash
python run_pipeline.py --budget 300
```

`prospect run` does not work yet and should not be used for the handoff.

## What you need before starting

- Python 3.12 or newer
- Git
- A Firecrawl account
- Firecrawl CLI installed and signed in on the machine
- The project folder downloaded or cloned locally

## One-time setup

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

Then open `.env` and add the Firecrawl key.

## Where the input goes

Put `Galleries sheet.xlsx` in the project root.

The sheet name should stay `Collected Accounts`.

## What happens when you run it

The pipeline will:

- check that the setup is ready
- use the cached gallery and artist data already in the repository
- stop once for the gender decision
- continue after the confirmed women are added to `spikes/roster_probe/out/female_artists.json`
- write the deliverables into `output/`

## Output files

The main output files are:

- `output/completed_leads.csv`
- `output/enrichment_not_a_must.csv`
- `output/coverage_report.csv`

## Important notes

- Do not commit `output/`
- Do not commit `.env`
- Do not use `prospect run` yet
- If the pipeline stops at the gender gate, that is expected
- The repo is designed for a local operator, not a cloud-hosted run

## Quality checks

Before trusting a change, run:

```bash
ruff format --check .
ruff check .
mypy
pytest
lint-imports
```

## Handoff docs

- [CLAUDE.md](CLAUDE.md)
- [HANDOFF.md](HANDOFF.md)

