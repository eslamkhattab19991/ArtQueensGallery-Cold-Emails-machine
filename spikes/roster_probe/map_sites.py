"""List every page on each organization's website, to find its artists.

A Windows-native replacement for ``run_maps.sh``. The bash version needs
``mapfile``, process substitution and GNU ``timeout``, none of which exist in
PowerShell or cmd — and mapping is the step that discovers artists in the first
place, so leaving it bash-only left the whole pipeline unrunnable on the machine
the operator actually has.

Behaviour matches the shell script deliberately, because 173 already-mapped
organizations depend on the format:

* one ``out/maps/row_<N>.json`` per organization,
* a row whose file already records ``"success": true`` is skipped, never re-paid,
* a failure writes ``{"success": false, ...}`` rather than nothing, so "we tried
  and could not read it" stays distinguishable from "we never looked",
* requests run one at a time with a pause between them.

Sequential is not an oversight. The first version of the shell script ran two at
a time against a stated concurrency limit of two, and every request after the
sixth failed; the same URLs succeed one at a time.

Default target is every organization in ``seeds.json`` that has a website and is
not yet mapped. Pass ``--batch`` to map a specific list instead.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from chain import FIRECRAWL, run_firecrawl

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"
MAPS = OUT / "maps"

#: Seconds between requests. Matches run_maps.sh; see the module docstring for
#: why this is not tunable upward without re-testing against the rate limit.
PAUSE_SECONDS = 8

#: Mapping one site costs one credit, so this doubles as the credit estimate.
CREDITS_PER_SITE = 1


def already_mapped(row: int) -> bool:
    """Whether this organization has a usable map on disk already.

    A recorded failure does *not* count as mapped: it is worth retrying, since
    the earlier attempt may have hit a transient timeout rather than a dead site.
    """
    target = MAPS / f"row_{row}.json"
    if not target.is_file() or target.stat().st_size == 0:
        return False
    try:
        return bool(json.loads(target.read_text(encoding="utf-8")).get("success"))
    except (json.JSONDecodeError, OSError):
        return False


def map_one(row: int, url: str) -> int | None:
    """Map one site, writing the result. Returns the link count, or None if it failed."""
    target = MAPS / f"row_{row}.json"
    output = run_firecrawl(["map", url, "--search", "artist", "--json"], timeout=120)

    if output:
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            payload = None
        if payload and payload.get("success"):
            target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return len(payload.get("data", {}).get("links", []))

    # Record the failure. An unreachable site is a finding, not an absence of one.
    target.write_text(
        json.dumps({"success": False, "error": "map failed or timed out"}),
        encoding="utf-8",
    )
    return None


def targets(batch: Path | None) -> list[dict[str, object]]:
    """The organizations to consider, from a batch file or from seeds.json."""
    source = batch if batch is not None else OUT / "seeds.json"
    if not source.is_file():
        message = (
            f"!! {source} not found.\n"
            f"   Run `python spikes/roster_probe/ingest.py` first to build seeds.json "
            f"from the workbook."
        )
        raise SystemExit(message)
    organizations = json.loads(source.read_text(encoding="utf-8"))
    return [org for org in organizations if org.get("website")]


def main() -> None:
    """Map every unmapped organization, within the requested limit."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch", type=Path, help="map only the organizations in this JSON file")
    parser.add_argument(
        "--limit", type=int, default=0, help="stop after this many sites (0 = no limit)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would be mapped, spend nothing"
    )
    args = parser.parse_args()

    MAPS.mkdir(parents=True, exist_ok=True)
    considered = targets(args.batch)
    unmapped = [org for org in considered if not already_mapped(int(str(org["row"])))]
    pending = unmapped[: args.limit] if args.limit else unmapped

    print(f"organizations with a website : {len(considered)}")
    print(f"already mapped, skipping     : {len(considered) - len(unmapped)}")
    print(
        f"to map now                   : {len(pending)}  "
        f"(~{len(pending) * CREDITS_PER_SITE} credits)"
    )

    if args.dry_run:
        print("\ndry run — nothing was mapped and no credits were spent.")
        return
    if not pending:
        print("\nnothing to do; every organization already has a map.")
        return

    # Fail on the first call if the CLI is missing, rather than writing a
    # failure file for every site and reporting the whole sheet as unreachable.
    try:
        ok = failed = 0
        for index, org in enumerate(pending, start=1):
            row = int(str(org["row"]))
            name = str(org.get("name", ""))[:34]
            print(f"[{index}/{len(pending)}] row {row:>3}  {name}", flush=True)

            count = map_one(row, str(org["website"]))
            if count is None:
                failed += 1
                print("      -> FAILED (recorded, not fatal)", flush=True)
            else:
                ok += 1
                print(f"      -> ok, {count} pages", flush=True)

            if index < len(pending):
                time.sleep(PAUSE_SECONDS)
    except OSError:
        raise SystemExit(
            f"\n!! The Firecrawl CLI ({FIRECRAWL}) is not installed or not on PATH.\n"
            f"   It is an npm package and needs Node.js:  npm install -g firecrawl\n"
            f"   Then sign in with:  firecrawl config"
        ) from None

    print(f"\nmapped ok : {ok}")
    print(f"failed    : {failed}   (recorded in out/maps/, retried on the next run)")
    print(f"maps are in {MAPS}")


if __name__ == "__main__":
    main()
