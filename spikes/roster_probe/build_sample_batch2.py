"""Build a chain sample: everything already traced (from cache) + 50 new female picks.

Throwaway spike helper. The 90 cached artists are re-included so the final
outcome files cover the whole traced set, not just the new batch; chain.py serves
them from cache, so only the 50 new artists spend Firecrawl credits.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path("out")

#: Indices into the untraced-candidate list (see the listing) selected as
#: female / likely-female real artists, biased away from org-name noise and
#: obvious male names so credits are not spent on records we would discard.
PICKS = [
    0,
    13,
    17,
    18,
    21,
    26,
    27,
    36,
    37,
    39,
    40,
    41,
    43,
    45,
    47,
    48,
    49,
    50,
    51,
    53,
    54,
    55,
    58,
    59,
    60,
    61,
    62,
    63,
    65,
    67,
    68,
    71,
    73,
    77,
    79,
    80,
    82,
    85,
    86,
    89,
    91,
    92,
    95,
    96,
    98,
    101,
    102,
    106,
    114,
    122,
]


def slug(name: str) -> str:
    """Match chain.py's cache key, so traced artists are recognised."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def main() -> None:
    """Write chain_sample.json: everything cached, plus the new picks."""
    sample: list[dict[str, str]] = []
    seen: set[str] = set()

    # Everything already traced, reconstructed from the per-artist cache.
    for path in sorted((OUT / "chain").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        key = slug(record["artist_name"])
        if key in seen:
            continue
        seen.add(key)
        sample.append(
            {
                "artist_name": record["artist_name"],
                "source_organization": record["source_organization"],
                "profile_url": record["profile_url"],
            }
        )
    cached_count = len(sample)

    # The 50 new female picks from the untraced pool.
    cached_slugs = {path.stem for path in (OUT / "chain").glob("*.json")}
    rows = list(csv.DictReader((OUT / "candidate_artists_batch1.csv").open(encoding="utf-8-sig")))
    untraced = [
        row
        for row in rows
        if slug(row["artist_name"]) not in cached_slugs and row["artist_name"].strip()
    ]

    added = 0
    for index in PICKS:
        row = untraced[index]
        key = slug(row["artist_name"])
        if key in seen:
            continue
        seen.add(key)
        sample.append(
            {
                "artist_name": row["artist_name"],
                "source_organization": row["source_organization"],
                "profile_url": row["profile_url"],
            }
        )
        added += 1

    (OUT / "chain_sample.json").write_text(
        json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"sample written: {len(sample)} artists total, {cached_count} cached, {added} new to trace"
    )
    print("\nnew artists to trace:")
    for row in sample[cached_count:]:
        print(f"  {row['artist_name']}  ({row['source_organization']})")


if __name__ == "__main__":
    main()
