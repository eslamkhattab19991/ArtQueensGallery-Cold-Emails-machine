"""Recover artist names from URL slugs, not just page titles.

The roster scan reads the ``title`` a map returns for each link. That is the
strong signal when it is present, but it is often missing, truncated, or set to
the site's name on every page — World Illustration Awards returned 4,970 links
and only 40 usable titles.

The URL itself survives all of that. ``/en/artist/maria-rossi`` names the artist
whatever the title says, so this reads the last path segment of any roster-shaped
URL and reconstructs the name from it. Applied only to organizations the probe
already qualified: a wider net over rosters known to be dead would just cost
credits.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from analyze import ROSTER_SEGMENTS
from sanitize import is_person_name

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"

#: Slug words that mark a listing, a form or a section rather than one artist.
NON_ARTIST_SLUGS = {
    "index",
    "list",
    "all",
    "page",
    "search",
    "apply",
    "submit",
    "login",
    "register",
    "archive",
    "archives",
    "past",
    "current",
    "upcoming",
    "home",
    "more",
    "view",
    "detail",
    "details",
    "profile",
    "profiles",
    "gallery",
    "artists",
    "artist",
    "winners",
    "winner",
    "shortlist",
    "finalists",
    "members",
    "member",
    "category",
    "categories",
    "tag",
    "tags",
    "author",
}


def name_from_slug(url: str) -> str | None:
    """Reconstruct a person's name from the last path segment of ``url``."""
    path = unquote(urlparse(url).path).rstrip("/")
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        return None

    # Only trust a slug that sits under a roster-shaped segment; otherwise every
    # blog post and product page becomes an "artist".
    parents = " ".join(segments[:-1]).lower()
    if not any(keyword in re.sub(r"[^a-z]", "", parents) for keyword in ROSTER_SEGMENTS):
        return None

    tail = segments[-1]
    if "." in tail:  # a file, not a person
        return None
    words = [word for word in re.split(r"[-_+%20]+", tail) if word]
    if not 2 <= len(words) <= 4:
        return None
    if any(word.lower() in NON_ARTIST_SLUGS for word in words):
        return None
    if any(character.isdigit() for character in tail):
        return None

    name = " ".join(word.capitalize() for word in words)
    return name if is_person_name(name) else None


def main() -> None:
    """Widen each qualified organization's roster and rewrite probe_rosters.json."""
    qualified = set(json.loads((OUT / "qualified_orgs.json").read_text(encoding="utf-8")))
    seeds = json.loads((OUT / "seeds.json").read_text(encoding="utf-8"))
    rows = {str(org["name"]): int(str(org["row"])) for org in seeds}
    rosters = json.loads((OUT / "probe_rosters.json").read_text(encoding="utf-8"))

    by_name = {str(item["name"]): item for item in rosters}
    print(f"{'organization':<34} {'before':>7} {'added':>6} {'after':>6}")
    print("-" * 56)

    for org in sorted(qualified):
        entry = by_name.get(org)
        if entry is None:
            continue
        map_file = OUT / "maps" / f"row_{rows.get(org, -1)}.json"
        if not map_file.is_file():
            continue
        payload = json.loads(map_file.read_text(encoding="utf-8"))
        if not payload.get("success"):
            continue

        known = {str(artist["artist_name"]).lower() for artist in entry["artists"]}
        before = len(entry["artists"])
        for link in payload.get("data", {}).get("links", []):
            url = link.get("url", "")
            name = name_from_slug(url)
            if name and name.lower() not in known:
                known.add(name.lower())
                entry["artists"].append({"artist_name": name, "profile_url": url})
        print(
            f"{org[:32]:<34} {before:>7} {len(entry['artists']) - before:>6} {len(entry['artists']):>6}"
        )

    (OUT / "probe_rosters.json").write_text(
        json.dumps(rosters, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    total = sum(len(item["artists"]) for item in rosters if str(item["name"]) in qualified)
    print(f"\ntotal roster across qualified organizations: {total}")


if __name__ == "__main__":
    main()
