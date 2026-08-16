"""Build the full chaining list from organizations the probe proved contactable.

Spends the remaining budget where the probe showed artists publish their own
addresses, and nowhere else. Organizations whose profiles carry only the
gallery's switchboard are skipped entirely however large their roster — that is
the whole point of having probed.

Two gates run before an artist costs a credit:

* the organization must have passed the probe, and
* the artist must be on the confirmed-female list, because a male artist is not
  a lead for this gallery and chaining one is a credit spent on a row that will
  be deleted.

``--budget`` caps the number of artists so a run cannot overspend; artists are
taken from the strongest organizations first.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"

#: Measured on the repaired chain cache: most artists cost one scrape, and only
#: those with a site of their own go on to cost the map-and-scrape pair.
CREDITS_PER_ARTIST = 1.7


def slug(name: str) -> str:
    """Match chain.py's cache key, so already-traced artists are free."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main() -> None:
    """Write chain_sample.json for the qualified organizations, within budget."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=int, default=600, help="credits to spend")
    parser.add_argument("--per-org", type=int, default=0, help="cap per org, 0 = no cap")
    args = parser.parse_args()

    qualified = set(json.loads((OUT / "qualified_orgs.json").read_text(encoding="utf-8")))
    rosters = json.loads((OUT / "probe_rosters.json").read_text(encoding="utf-8"))
    female = {
        name.strip().lower()
        for name in json.loads((OUT / "female_artists.json").read_text(encoding="utf-8"))
    }
    cached = {path.stem for path in (OUT / "chain").glob("*.json")}

    max_artists = int(args.budget / CREDITS_PER_ARTIST)
    sample: list[dict[str, str]] = []
    per_org_counts: dict[str, int] = {}

    ranked = sorted(
        (item for item in rosters if str(item["name"]) in qualified),
        key=lambda item: -len(item["artists"]),
    )

    for item in ranked:
        org = str(item["name"])
        taken = 0
        for artist in item["artists"]:
            if len(sample) >= max_artists:
                break
            if args.per_org and taken >= args.per_org:
                break
            key = slug(str(artist["artist_name"]))
            if key in cached or str(artist["artist_name"]).strip().lower() not in female:
                continue
            sample.append(
                {
                    "artist_name": str(artist["artist_name"]),
                    "profile_url": str(artist["profile_url"]),
                    "source_organization": org,
                }
            )
            taken += 1
        per_org_counts[org] = taken

    (OUT / "chain_sample.json").write_text(
        json.dumps(sample, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"{'organization':<40} {'to chain':>9}")
    print("-" * 51)
    for org, count in sorted(per_org_counts.items(), key=lambda kv: -kv[1]):
        if count:
            print(f"{org[:38]:<40} {count:>9}")
    print()
    print(f"artists queued      : {len(sample)}")
    print(f"estimated credits   : {len(sample) * CREDITS_PER_ARTIST:.0f}  (budget {args.budget})")
    print(f"wrote {OUT / 'chain_sample.json'}")


if __name__ == "__main__":
    main()
