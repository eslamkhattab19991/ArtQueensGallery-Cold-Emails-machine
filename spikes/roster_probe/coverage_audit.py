"""Audit artist-discovery coverage per gallery, and say plainly where it is unsafe.

Answers the four questions asked of the machine after review:

1. Does it ever report "no artists" for a gallery that has them?
2. How many artists were discovered, and how many processed?
3. Did it follow the listing to the end, or stop at the first page?
4. Which galleries can we trust, and which need a human to look?

The governing rule is the one the reviewer set: *if a gallery cannot be fully
processed, say so — never silently miss artists.* So every gallery leaves this
audit with an explicit verdict, and "I could not tell" is a first-class answer
rather than being rounded down to zero.

Discovery runs two independent strategies and takes the union, because either
alone under-counts badly:

* **Page title** — reliable when present, but many sites title every page with
  the site's own name. World Illustration Awards mapped 4,970 links and yielded
  40 titles.
* **URL slug** — ``/artist/maria-rossi`` names the artist regardless of what the
  title says, and survives the cases where titles do not.

Reads only cached map files, so it costs nothing to re-run.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from analyze import ROSTER_SEGMENTS, looks_like_person
from expand_rosters import name_from_slug
from sanitize import is_person_name

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"

#: URL shapes that prove a listing continues beyond the page we looked at.
PAGINATION_RE = re.compile(
    r"([?&]page[=/]|/page/\d|[?&]paged=|[?&]p=\d|/p/\d+|[?&]offset=|[?&]start=\d|[?&]per_page=)",
    re.IGNORECASE,
)

#: Link totals that are exactly a service limit rather than a real site size.
#: A map that stops on a round number almost certainly stopped early.
CAP_VALUES = frozenset({100, 250, 500, 1000, 2000, 2500, 5000, 10000})

#: Below this, a "roster" is too small to be a gallery's full artist list, and is
#: more likely a handful of stray matches.
SPARSE_ROSTER = 3

#: Fingerprints that identify the platform a gallery site is built on, from URLs
#: alone. Reliability is reported per platform because the question is not "does
#: it work" but "does it work across the variety of sites we will actually meet".
PLATFORM_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Wix", ("wixstatic.com", "wixsite.com", "/_partials/", "wix-code")),
    ("Squarespace", ("squarespace.com", "/config/", "static1.squarespace")),
    ("Artlogic", ("artlogic.net", "artcld.com", "/usr/library/")),
    ("Shopify", ("shopify.com", "cdn/shop/", "/collections/all")),
    ("WordPress", ("/wp-content/", "/wp-json/", "/wp-includes/", "?p=")),
    ("Webflow", ("webflow.io", "assets.website-files.com")),
    ("Cargo", ("cargocollective.com", "cargo.site")),
)


def detect_platform(links: list[dict[str, str]]) -> str:
    """Name the site-building platform from its URL fingerprints."""
    blob = " ".join(link.get("url", "") for link in links[:400]).lower()
    for platform, markers in PLATFORM_MARKERS:
        if any(marker in blob for marker in markers):
            return platform
    return "Custom / unknown"


@dataclass
class GalleryCoverage:
    """What one gallery's artist discovery actually achieved, and how sure we are."""

    row: int
    name: str
    website: str
    map_ok: bool
    total_links: int
    roster_links: int
    by_title: int
    by_slug: int
    discovered: int
    processed: int
    pagination_seen: bool
    at_cap: bool
    platform: str = "Custom / unknown"
    reasons: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """A blunt statement of whether this gallery's coverage can be trusted."""
        if not self.map_ok:
            return "CANNOT VERIFY - site unreachable"
        if self.total_links == 0:
            return "CANNOT VERIFY - no pages returned"
        if self.at_cap:
            return "INCOMPLETE - hit page limit"
        if self.pagination_seen and self.discovered > 0:
            return "REVIEW - listing is paginated"
        if self.roster_links >= SPARSE_ROSTER and self.discovered == 0:
            return "REVIEW - artist pages found but no names read"
        if self.discovered == 0:
            return "NO ARTISTS FOUND"
        return "OK"

    @property
    def trusted(self) -> bool:
        """Whether this gallery's count may be used without a human check."""
        return self.verdict == "OK"

    @property
    def coverage_ratio(self) -> str:
        """Processed as a share of discovered, for the review table."""
        if self.discovered == 0:
            return "-"
        return f"{self.processed / self.discovered:.0%}"


def discover(links: list[dict[str, str]]) -> tuple[set[str], int, int, int]:
    """Return (artist names, by-title count, by-slug count, roster-shaped links)."""
    by_title: set[str] = set()
    by_slug: set[str] = set()
    roster_links = 0

    for link in links:
        url = link.get("url", "")
        path = unquote(urlparse(url).path).lower()
        if any(
            keyword in re.sub(r"[^a-z]", "", segment)
            for segment in path.strip("/").split("/")
            for keyword in ROSTER_SEGMENTS
        ):
            roster_links += 1

        title = (link.get("title") or "").strip()
        if title and looks_like_person(title):
            candidate = re.split(r"[|–—\-:]", title)[0].strip()
            if is_person_name(candidate):
                by_title.add(candidate.lower())

        slug_name = name_from_slug(url)
        if slug_name:
            by_slug.add(slug_name.lower())

    return by_title | by_slug, len(by_title), len(by_slug), roster_links


def processed_names() -> set[str]:
    """Artists the pipeline actually attempted, from the per-artist cache."""
    names: set[str] = set()
    for path in (OUT / "chain").glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        names.add(str(record["artist_name"]).lower())
    return names


def audit() -> list[GalleryCoverage]:
    """Build a coverage record for every gallery that was mapped."""
    seeds = json.loads((OUT / "seeds.json").read_text(encoding="utf-8"))
    done = processed_names()
    results: list[GalleryCoverage] = []

    for org in seeds:
        row = int(str(org["row"]))
        map_file = OUT / "maps" / f"row_{row}.json"
        if not map_file.is_file():
            continue

        payload = json.loads(map_file.read_text(encoding="utf-8"))
        ok = bool(payload.get("success"))
        links = payload.get("data", {}).get("links", []) if ok else []

        names, n_title, n_slug, roster_links = discover(links)
        pagination = any(PAGINATION_RE.search(link.get("url", "")) for link in links)

        coverage = GalleryCoverage(
            row=row,
            name=str(org["name"]),
            website=str(org.get("website") or ""),
            map_ok=ok,
            total_links=len(links),
            roster_links=roster_links,
            by_title=n_title,
            by_slug=n_slug,
            discovered=len(names),
            processed=len(names & done),
            pagination_seen=pagination,
            at_cap=len(links) in CAP_VALUES,
            platform=detect_platform(links),
        )
        results.append(coverage)

    return results


def main() -> None:
    """Print the coverage summary and write the reviewable report."""
    results = audit()

    print("=" * 78)
    print("ARTIST DISCOVERY COVERAGE AUDIT".center(78))
    print("=" * 78)

    buckets: dict[str, list[GalleryCoverage]] = {}
    for coverage in results:
        buckets.setdefault(coverage.verdict, []).append(coverage)

    print(f"\ngalleries audited: {len(results)}\n")
    print(f"{'verdict':<44} {'galleries':>9} {'artists found':>14}")
    print("-" * 70)
    for verdict, group in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        found = sum(item.discovered for item in group)
        print(f"{verdict:<44} {len(group):>9} {found:>14}")

    trusted = [item for item in results if item.trusted]
    needs_eyes = [item for item in results if not item.trusted]
    print("-" * 70)
    print(
        f"{'trusted without review':<44} {len(trusted):>9} {sum(i.discovered for i in trusted):>14}"
    )
    print(
        f"{'needs a human check':<44} {len(needs_eyes):>9} "
        f"{sum(i.discovered for i in needs_eyes):>14}"
    )

    print("\n\nDISCOVERY STRATEGY COMPARISON")
    print("-" * 70)
    title_only = sum(item.by_title for item in results)
    slug_only = sum(item.by_slug for item in results)
    union = sum(item.discovered for item in results)
    print(f"  artists found by page title only : {title_only:>6}")
    print(f"  artists found by URL slug only   : {slug_only:>6}")
    print(f"  artists found by both combined   : {union:>6}")
    if title_only:
        print(
            f"  -> using titles alone would miss  {union - title_only:>5} artists "
            f"({(union - title_only) / union:.0%} of the total)"
        )

    # Site size is the variety axis that cached data can actually speak to.
    # Platform fingerprints live in asset URLs, which a link map does not return,
    # so the platform column is recorded but too sparse to draw conclusions from.
    print("\n\nRELIABILITY BY SITE SIZE  (does it only work on one kind of site?)")
    print("-" * 72)
    print(
        f"{'site size (pages found)':<26} {'galleries':>9} {'trusted':>8} {'rate':>6} {'artists':>9}"
    )
    print("-" * 72)
    bands = [
        ("none returned", 0, 0),
        ("tiny (1-10)", 1, 10),
        ("small (11-50)", 11, 50),
        ("medium (51-200)", 51, 200),
        ("large (201-1000)", 201, 1000),
        ("very large (1000+)", 1001, 10**9),
    ]
    for label, low, high in bands:
        group = [item for item in results if low <= item.total_links <= high]
        if not group:
            continue
        good = sum(1 for item in group if item.trusted)
        print(
            f"{label:<26} {len(group):>9} {good:>8} {good / len(group):>5.0%} "
            f"{sum(item.discovered for item in group):>9}"
        )

    print("\n\nGALLERIES REQUIRING ATTENTION (worst first)")
    print("-" * 78)
    print(f"{'row':>4} {'gallery':<30} {'links':>6} {'found':>6} {'done':>5}  verdict")
    print("-" * 78)
    order = {
        "CANNOT VERIFY - site unreachable": 0,
        "CANNOT VERIFY - no pages returned": 1,
        "INCOMPLETE - hit page limit": 2,
        "REVIEW - artist pages found but no names read": 3,
        "REVIEW - listing is paginated": 4,
        "NO ARTISTS FOUND": 5,
    }
    for item in sorted(needs_eyes, key=lambda i: (order.get(i.verdict, 9), -i.roster_links)):
        print(
            f"{item.row:>4} {item.name[:28]:<30} {item.total_links:>6} "
            f"{item.discovered:>6} {item.processed:>5}  {item.verdict}"
        )

    report = OUT / "coverage_report.csv"
    with report.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "row",
                "gallery",
                "website",
                "platform",
                "pages_seen",
                "artist_pages_seen",
                "found_by_title",
                "found_by_url",
                "artists_discovered",
                "artists_processed",
                "processed_share",
                "paginated",
                "hit_page_limit",
                "verdict",
                "trusted",
            ]
        )
        for item in sorted(results, key=lambda i: (i.trusted, -i.discovered)):
            writer.writerow(
                [
                    item.row,
                    item.name,
                    item.website,
                    item.platform,
                    item.total_links,
                    item.roster_links,
                    item.by_title,
                    item.by_slug,
                    item.discovered,
                    item.processed,
                    item.coverage_ratio,
                    "yes" if item.pagination_seen else "no",
                    "yes" if item.at_cap else "no",
                    item.verdict,
                    "yes" if item.trusted else "no",
                ]
            )

    print(f"\nwrote {report}")
    print(f"      {report.stat().st_size:,} bytes — one row per gallery, for review")


if __name__ == "__main__":
    main()
