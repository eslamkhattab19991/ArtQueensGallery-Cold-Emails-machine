"""Produce the clean, outreach-ready completed-leads CSV.

Filters the raw completed_leads.csv down to what an operator can actually send:
drops the two male artists the spike leaked and the one junk address (a magazine
domain with a nonsense local-part), then de-duplicates by artist name.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path("out")

#: Dropped from the completed leads: male artists (the spike has no gender gate),
#: and one junk address the ownership rule did not catch because the magazine
#: domain was not on any list.
DROP = {
    "Eric Dubarry": "male",
    "Nicholas Zalevsky": "male",
    "Richard Prince": "junk email (wesleysnipes@artforum.com — magazine domain)",
}

COLUMNS = [
    "artist_name",
    "email",
    "email_confidence_band",
    "website",
    "source_organization",
    "profile_url",
]


def main() -> None:
    """Write the clean, outreach-ready completed-leads CSV."""
    rows = list(csv.DictReader((OUT / "completed_leads.csv").open(encoding="utf-8-sig")))

    kept: list[dict[str, str]] = []
    seen: set[str] = set()
    dropped: list[tuple[str, str]] = []
    for row in rows:
        name = row["artist_name"]
        if name in DROP:
            dropped.append((name, DROP[name]))
            continue
        if name in seen:
            continue
        seen.add(name)
        kept.append({column: row.get(column, "") for column in COLUMNS})

    out_path = OUT / "completed_leads_final.csv"
    with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(kept)

    print(f"wrote {out_path}")
    print(f"\n{len(kept)} clean female completed leads (ready to email):")
    for row in kept:
        print(f"  {row['artist_name'][:24]:26} {row['email']:34} {row['email_confidence_band']}")
    print(f"\ndropped {len(dropped)}:")
    for name, why in dropped:
        print(f"  {name:22} — {why}")


if __name__ == "__main__":
    main()
