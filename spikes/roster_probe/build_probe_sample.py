"""Build a 5-artist probe sample for every organization with a usable roster.

The measured lesson from the first 140 traced artists: yield is decided almost
entirely by whether an organization's artists have *their own websites*. Art
Market Experts artists do, and produced 7 of 8 clean leads at 16 credits each.
Monat, Galerie C.O.A and Art Loving publish ``info@<the-gallery>.com`` on every
profile — 86 artists, 86 credits, zero leads.

Mapping cannot tell those apart: it reports how many artists an organization has,
not whether they are reachable. Scraping five profiles can. So this builds a
small per-organization probe whose result decides where the chaining budget goes.

The probe is not a throwaway cost. ``chain.py`` caches per artist, so these five
scrapes are simply the first paid step of the full chain for organizations that
pass, and the only cost incurred for those that fail.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from analyze import looks_like_person

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"
PROBE_PER_ORG = 3

#: An organization needs at least this many candidate artists for its roster to
#: be worth probing — below it, even a perfect hit rate cannot repay the probe.
MIN_ROSTER = 10


def slug(name: str) -> str:
    """Match chain.py's cache-key derivation exactly, so cached artists are seen."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def candidates_for(row: int) -> list[dict[str, str]]:
    """Extract (name, profile_url) pairs from one organization's map file."""
    map_file = OUT / "maps" / f"row_{row}.json"
    if not map_file.is_file():
        return []
    payload = json.loads(map_file.read_text(encoding="utf-8"))
    if not payload.get("success"):
        return []

    found: dict[str, str] = {}
    for link in payload.get("data", {}).get("links", []):
        title = (link.get("title") or "").strip()
        url = link.get("url", "")
        if not title or not url or not looks_like_person(title):
            continue
        name = re.split(r"[|–—\-:]", title)[0].strip()
        found.setdefault(name, url)
    return [{"artist_name": name, "profile_url": url} for name, url in found.items()]


def main() -> None:
    """Write chain_sample.json: 5 artists from each organization worth probing."""
    seeds = json.loads((OUT / "seeds.json").read_text(encoding="utf-8"))
    cached = {path.stem for path in (OUT / "chain").glob("*.json")}

    rosters: list[tuple[dict[str, object], list[dict[str, str]]]] = []
    for org in seeds:
        found = candidates_for(int(str(org["row"])))
        if len(found) >= MIN_ROSTER:
            rosters.append((org, found))

    sample: list[dict[str, str]] = []
    new_count = 0
    print(f"{'organization':<40} {'roster':>7} {'probing':>8} {'cached':>7}")
    print("-" * 66)
    for org, found in sorted(rosters, key=lambda pair: -len(pair[1])):
        # Prefer artists not already traced, so each probe buys new information.
        untraced = [a for a in found if slug(a["artist_name"]) not in cached]
        already = len(found) - len(untraced)
        picks = untraced[:PROBE_PER_ORG]
        for artist in picks:
            sample.append({**artist, "source_organization": str(org["name"])})
        new_count += len(picks)
        print(f"{str(org['name'])[:38]:<40} {len(found):>7} {len(picks):>8} {already:>7}")

    (OUT / "probe_rosters.json").write_text(
        json.dumps(
            [{"row": org["row"], "name": org["name"], "artists": found} for org, found in rosters],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (OUT / "chain_sample.json").write_text(
        json.dumps(sample, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print()
    print(f"organizations with a roster >= {MIN_ROSTER}: {len(rosters)}")
    print(f"artists to probe (new credits):        {new_count}")
    print(f"wrote {OUT / 'chain_sample.json'} and {OUT / 'probe_rosters.json'}")


if __name__ == "__main__":
    main()
