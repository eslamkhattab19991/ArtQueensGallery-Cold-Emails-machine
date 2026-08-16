# Working in this repository

Art Queens Gallery runs paid international exhibitions in Paris, New York and
Milan. Filling them means emailing **professional female artists directly**. This
project reads a spreadsheet of art-world organisations, finds the artists they
present, and hunts for each artist's own email address.

The operator is **not a programmer**. Explain in plain English, report costs
before spending, and never present an unverified number as a result.

## The rule that governs everything

> A lead is complete only when it has the artist's **name** and a **verified email
> address that belongs to her personally**.

Not the gallery's `info@`. Not a magazine's. If we email the gallery, the
invitation reaches a receptionist; if we email the artist, it reaches the person
who would actually travel and exhibit.

A larger list of switchboard addresses is worth less than a smaller list of real
ones. When in doubt, **exclude**.

## Running it

```bash
python run_pipeline.py --budget 300
```

`--dry-run` shows the plan and spends nothing. `--budget 0` rebuilds the output
sheets from existing work, also free. Everything is cached per artist and per
site, so re-running resumes rather than restarting.

**`prospect run` does not work.** It is the entry point for the rebuilt engine,
which has no stages wired yet (`src/prospecting/config/container.py` returns an
empty list). Do not point the operator at it.

## Where things are

| | |
|---|---|
| `run_pipeline.py` | The entry point. Eleven steps, in order |
| `spikes/roster_probe/` | The working pipeline. Every lead came from here |
| `spikes/roster_probe/out/` | Cached results — **expensive**, see below |
| `output/` | The deliverables the operator opens |
| `src/prospecting/` | Tested framework skeleton. Not yet runnable |
| `Galleries sheet.xlsx` | Input: 192 organisations, sheet "Collected Accounts" |

### Never delete `out/chain/` or `out/maps/`

They hold roughly 1,000 credits of paid work — 1,011 traced artists and 173 site
maps. `out/female_artists.json` is worth more still: it is hand-classified and no
code can regenerate it. Losing any of these means paying for them again.

## Money

Reading websites is metered through Firecrawl and is the only running cost.

| Action | Cost |
|---|---:|
| Mapping one organization's site | ~1 credit |
| Testing 3 artists from one organization | ~5 credits |
| Fully tracing one artist | ~1.8 credits |
| **One completed lead, all-in** | **~9 credits** |

Check the balance with `firecrawl --status`.

**The habit that protects the budget:** test three artists from an organisation
before committing to its whole roster. Most galleries publish one shared address
and can never produce a personal email — three artists cost about five credits
and tell you whether the remaining fifty are worth anything. Skipping this is how
86 artists were once traced for zero leads.

**Never start a paid run without saying what it will cost and getting a yes.**

## The classification step

The pipeline stops once and asks which discovered artists are women. This is
deliberate, not an unfinished feature — the machine does not guess gender.

When the operator asks you to classify:

1. Run `python spikes/roster_probe/list_unclassified.py` to see the pending names
2. Add only the names you can confirm are women to
   `spikes/roster_probe/out/female_artists.json` (a plain JSON list of strings)
3. **Leave out anything ambiguous.** Excluding a woman costs one lead; including
   a man costs the campaign's credibility
4. Also leave out world-famous artists — they will not answer a cold email, and
   tracing them wastes credits

Then re-run `run_pipeline.py`; it resumes from the stop.

## Checking the machine's work

```bash
python spikes/roster_probe/coverage_audit.py
```

Free, reads only saved data. Reports per gallery how many artists were
discovered, how many were processed, and whether the coverage can be trusted.

The governing principle: **a gallery that cannot be fully read is reported as
such, never counted as empty.** "Cannot verify" and "no artists" are deliberately
different answers.

## Known limits — state these plainly, never paper over them

- **Emails are not test-mailed.** Verified means the format is valid, the mail
  server exists, and the ownership evidence holds. Expect some bounces.
- **JavaScript-only artist lists are not read.** 12 galleries return nothing.
  They are reported as "cannot verify", never as empty.
- **Pagination is detected but not followed.** 29 galleries are flagged; treat
  their artist counts as a floor.
- **The machine never sends email.** It finds and verifies; a person sends.

## Code conventions

Five gates must pass before any commit — the same ones CI runs. Run them
separately, not chained:

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

```bash
lint-imports
```

Do not redirect `lint-imports` output on Windows. Its progress spinner cannot
encode to cp1252 without a console attached, so it crashes with a
`UnicodeEncodeError` and returns exit 1 **even when all seven contracts pass**.
Run it plainly and read the last line.

Inside `src/`, dependencies point inward only and vendor libraries are banned —
enforced by `tests/architecture/` and seven Import Linter contracts, not by
convention. `openpyxl` is declared as a dependency for the spike but stays banned
in `src/`: when the ingestion adapter lands, the workbook must be read behind a
port like every other vendor library.

The spike scripts are exempt from the print-statement rule because their printed
output is the deliverable.

## Working with the operator

- Lead with the number that matters: completed leads.
- Show costs before spending, and the balance after.
- If something fails, say so with the output. Never round a partial result up.
- When a rule rejects an address, that is the system working. Explain why rather
  than treating it as a loss.
