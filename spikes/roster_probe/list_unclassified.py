"""List artists awaiting a female/not-female decision.

The gender check is the one judgement in this pipeline that no code makes. It is
deliberate: the gallery invites women, and an artist wrongly included is a real
embarrassment in front of a real person. An earlier version with no gate shipped
two male artists to the operator.

So the machine narrows the question and a human answers it. This prints the
artists discovered in qualified organizations who are not yet on
``out/female_artists.json``, and nothing else. Whoever runs the pipeline — or
Claude Code, working alongside them — reads the list, decides, and adds the
confirmed-female names to that file.

Names that cannot be called confidently should be **left out**. The gate fails
closed: excluding a woman costs one lead, including a man costs the campaign's
credibility.

Costs nothing to run; reads only files already on disk.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from sanitize import is_person_name

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"


def slug(name: str) -> str:
    """Match chain.py's cache key, so already-traced artists are recognised."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def load(name: str) -> object | None:
    """Read a JSON file from out/, or None when it does not exist yet."""
    path = OUT / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def main() -> None:
    """Print unclassified artist names, grouped by organization."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--all", action="store_true", help="include artists already traced, not just new ones"
    )
    args = parser.parse_args()

    qualified = load("qualified_orgs.json")
    rosters = load("probe_rosters.json")
    if qualified is None or rosters is None:
        raise SystemExit(
            "!! qualified_orgs.json or probe_rosters.json is missing.\n"
            "   Run the probe first — these are written by evaluate_probe.py and\n"
            "   build_probe_sample.py, which run_pipeline.py invokes for you."
        )

    gate = {str(n).strip().lower() for n in (load("female_artists.json") or [])}
    traced = {path.stem for path in (OUT / "chain").glob("*.json")}
    qualified_names = {str(name) for name in qualified}  # type: ignore[union-attr]

    total = 0
    for item in rosters:  # type: ignore[union-attr]
        org = str(item["name"])
        if org not in qualified_names:
            continue
        pending = [
            str(artist["artist_name"])
            for artist in item["artists"]
            if is_person_name(str(artist["artist_name"]))
            and str(artist["artist_name"]).strip().lower() not in gate
            and (args.all or slug(str(artist["artist_name"])) not in traced)
        ]
        if pending:
            total += len(pending)
            print(f"\n### {org}  [{len(pending)}]")
            print(" | ".join(pending))

    print(f"\n{'-' * 70}")
    print(f"awaiting a decision : {total}")
    print(f"already confirmed   : {len(gate)}")
    print()
    print("Add the names you can confirm are women to:")
    print(f"  {OUT / 'female_artists.json'}")
    print("It is a plain JSON list of strings. Leave out anything you are unsure of —")
    print("a shorter list is safer than one containing a man.")


if __name__ == "__main__":
    main()
