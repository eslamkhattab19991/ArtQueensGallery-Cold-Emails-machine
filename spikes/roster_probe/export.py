"""Write the candidate artists found in a batch to CSV.

The deliverable of the spike: a human-readable list of what the map step
actually produced, so the findings can be judged against real names rather than
summary counts.

Emphatically *not* the Stage 7 exporter. There is no provenance, no
qualification, no verification, no dedup against a master file — those are what
Phases 4-11 build. This exists to make the probe's output inspectable.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

OUT = Path(__file__).parent / "out"


def slug_matches_name(url: str, name: str) -> bool:
    """Whether the URL's last path segment looks like a slug of ``name``.

    A page titled "Bianca Severijns" living at ``/artists/bianca-severijns`` is
    near-certainly that artist's own page. A page titled "Accessibility
    Statement" at ``/post/top-art-books`` is not. This cross-check is the
    cheapest available filter on the crude title-based name detection, and it is
    what separates a real roster entry from a section heading that happens to be
    title-cased.
    """
    tail = unquote(urlparse(url).path.rstrip("/").split("/")[-1]).lower()
    tail_words = set(re.split(r"[^a-z0-9]+", tail)) - {""}
    name_words = {word for word in re.split(r"[^a-z0-9]+", name.lower()) if len(word) > 2}
    if not name_words:
        return False
    return len(name_words & tail_words) >= min(2, len(name_words))


def main() -> None:
    """Emit candidate_artists.csv for a batch."""
    batch_name = sys.argv[1] if len(sys.argv) > 1 else "batch1"
    analysis = json.loads((OUT / f"analysis_{batch_name}.json").read_text(encoding="utf-8"))

    rows: list[dict[str, object]] = []
    for report in analysis:
        map_file = OUT / "maps" / f"row_{report['row']}.json"
        if not map_file.is_file():
            continue
        payload = json.loads(map_file.read_text(encoding="utf-8"))
        if not payload.get("success"):
            continue

        wanted = set(report["candidate_names"])
        for link in payload.get("data", {}).get("links", []):
            title = (link.get("title") or "").strip()
            clean = re.split(r"[|–—\-:]", title)[0].strip()
            if clean not in wanted:
                continue
            url = link.get("url", "")
            rows.append(
                {
                    "artist_name": clean,
                    "profile_url": url,
                    "slug_confirms_name": slug_matches_name(url, clean),
                    "source_organization": report["name"],
                    "source_org_type": report["org_type"],
                    "source_website": report["website"],
                    "org_verdict": report["verdict"],
                    "page_description": (link.get("description") or "")[:200],
                }
            )

    # One row per artist per organization; the same artist listed twice by one
    # org is the same lead.
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, object]] = []
    for row in rows:
        key = (str(row["artist_name"]).lower(), str(row["source_organization"]))
        if key not in seen:
            seen.add(key)
            unique.append(row)

    unique.sort(key=lambda row: (str(row["source_organization"]), str(row["artist_name"])))

    destination = OUT / f"candidate_artists_{batch_name}.csv"
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(unique[0]))
        writer.writeheader()
        writer.writerows(unique)

    confirmed = sum(1 for row in unique if row["slug_confirms_name"])
    print(f"candidate artists       : {len(unique)}")
    print(f"slug-confirmed          : {confirmed}  ({confirmed / len(unique):.0%})")
    print(f"organizations represented: {len({row['source_organization'] for row in unique})}")
    print(f"\nwrote {destination}")


if __name__ == "__main__":
    main()
