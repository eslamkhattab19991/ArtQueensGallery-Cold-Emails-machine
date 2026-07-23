# Roster probe — throwaway validation spike

**This is not production code and must not be imported by `src/prospecting/`.**

## Why it exists

The riskiest untested assumption in the project is:

> a gallery/prize/magazine website exposes a page listing the artists it
> presents, and that page yields extractable artist names and links

Every phase after this one is built on that assumption. This spike tests it
against the real `Galleries sheet.xlsx` before we build nine more phases on top.

## What it does

For each organization, in two cheap steps:

1. **map** the site and look for roster-shaped URLs (`/artists`, `/winners`,
   `/exhibitors`, ...) — answers *"is there a roster page at all?"*
2. **scrape** the best candidate and count extractable artist links — answers
   *"does the roster yield names?"*

## What it deliberately does not do

No checkpointing, no plugin engine, no provenance, no retry policy, no
qualification. Those are what Phases 4–11 build properly. Findings from this
spike inform that work; the code itself is discarded.
