"""Score each mapped site for whether it exposes an extractable artist roster.

Answers the question the whole spike exists for, in two parts:

* **Structure** — does the site have roster-shaped URLs (``/artists/<name>``,
  ``/winners/<name>``, ...)?
* **Yield** — do those URLs carry a plausible person name we could extract?

The name test is deliberately crude (title-cased, two-to-four words, not a
known non-name phrase). This is a probe: over-fitting a name parser here would
be wasted work, and a rough count is enough to tell a rich roster from an empty
one.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

OUT = Path(__file__).parent / "out"

#: URL path segments that mark a per-entity page on an art-world site. Derived
#: by reading the actual mapped URLs across batch 1, not assumed up front.
ROSTER_SEGMENTS = (
    "artist",
    "artists",
    "artiste",
    "artisti",
    "kuenstler",
    "winner",
    "winners",
    "finalist",
    "finalists",
    "shortlist",
    "exhibitor",
    "exhibitors",
    "member",
    "members",
    "portfolio",
    "featured",
)

#: Words that appear in title-cased headings but are never a person's name.
#: Keeps section headers ("Call For Artists") out of the name count.
NON_NAME_WORDS = {
    "art",
    "artist",
    "artists",
    "gallery",
    "call",
    "prize",
    "award",
    "awards",
    "exhibition",
    "exhibitions",
    "submission",
    "submissions",
    "magazine",
    "contact",
    "about",
    "home",
    "news",
    "shop",
    "cart",
    "blog",
    "page",
    "collection",
    "the",
    "and",
    "for",
    "with",
    "your",
    "our",
    "how",
    "why",
    "what",
    "best",
    "top",
    "new",
    "online",
    "free",
    "open",
    "apply",
    "join",
    "buy",
    "sell",
    "price",
    "terms",
    "privacy",
    "policy",
}

NAME_RE = re.compile(r"^[A-Z][\w'’-]+(?: [A-Z][\w'’.-]+){1,3}$")


@dataclass
class SiteReport:
    """What one mapped organization yielded."""

    row: int
    name: str
    org_type: str
    website: str
    total_links: int
    roster_links: int
    candidate_names: list[str]
    top_roster_paths: list[str]

    @property
    def verdict(self) -> str:
        """A blunt three-way call on whether this site yields artists."""
        if self.total_links == 0:
            return "NO_MAP"
        if len(self.candidate_names) >= 5:
            return "RICH"
        if len(self.candidate_names) >= 1 or self.roster_links >= 3:
            return "THIN"
        return "NONE"


def looks_like_person(text: str) -> bool:
    """Whether a page title plausibly names a person."""
    cleaned = re.split(r"[|–—\-–—:]", text)[0].strip()
    if not NAME_RE.match(cleaned):
        return False
    words = {word.lower().strip(".'’") for word in cleaned.split()}
    return not (words & NON_NAME_WORDS)


def roster_segment(url: str) -> str | None:
    """Return the roster-shaped path segment in ``url``, if any.

    Matches on *substring*, not equality. The first version of this function
    required an exact segment match and scored Art Market Experts as having no
    roster — its artists live at ``/investable-artists-2026/<name>``, which is
    plainly a roster but does not equal ``"artists"``. Real sites decorate these
    segments with years, languages, and marketing words, so exact matching
    systematically undercounts.
    """
    path = unquote(urlparse(url).path).lower()
    for segment in path.strip("/").split("/"):
        normalized = re.sub(r"[^a-z]", "", segment)
        for keyword in ROSTER_SEGMENTS:
            if keyword in normalized:
                return keyword
    return None


def analyze(org: dict[str, object]) -> SiteReport:
    """Build the report for one mapped organization."""
    row = int(str(org["row"]))
    map_file = OUT / "maps" / f"row_{row}.json"

    links: list[dict[str, str]] = []
    if map_file.is_file():
        payload = json.loads(map_file.read_text(encoding="utf-8"))
        if payload.get("success"):
            links = payload.get("data", {}).get("links", [])

    roster_links = 0
    names: list[str] = []
    path_counts: dict[str, int] = {}

    for link in links:
        url = link.get("url", "")
        segment = roster_segment(url)
        if segment is not None:
            roster_links += 1
            path_counts[segment] = path_counts.get(segment, 0) + 1

        # Count a person-like title wherever it appears, not only under a
        # roster-shaped path. The page title is the stronger signal: sites name
        # their URL segments however they like, but a page *about* an artist is
        # titled with that artist's name regardless of where it sits.
        title = (link.get("title") or "").strip()
        if title and looks_like_person(title):
            names.append(re.split(r"[|–—\-–—:]", title)[0].strip())

    return SiteReport(
        row=row,
        name=str(org["name"]),
        org_type=str(org["org_type"]),
        website=str(org["website"]),
        total_links=len(links),
        roster_links=roster_links,
        candidate_names=sorted(set(names)),
        top_roster_paths=[
            path for path, _ in sorted(path_counts.items(), key=lambda kv: -kv[1])[:3]
        ],
    )


def main() -> None:
    """Analyze a batch and print the verdict table."""
    batch_file = OUT / (sys.argv[1] if len(sys.argv) > 1 else "batch1.json")
    organizations = json.loads(batch_file.read_text(encoding="utf-8"))
    reports = [analyze(org) for org in organizations]

    print(
        f"{'row':>4} {'verdict':<8} {'type':<11} {'links':>6} {'roster':>7} "
        f"{'names':>6}  {'organization':<34} paths"
    )
    print("-" * 108)
    for report in reports:
        print(
            f"{report.row:>4} {report.verdict:<8} {report.org_type:<11} "
            f"{report.total_links:>6} {report.roster_links:>7} "
            f"{len(report.candidate_names):>6}  {report.name[:32]:<34} "
            f"{','.join(report.top_roster_paths)}"
        )

    counts: dict[str, int] = {}
    for report in reports:
        counts[report.verdict] = counts.get(report.verdict, 0) + 1
    total_names = sum(len(report.candidate_names) for report in reports)

    print("\nverdicts:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"candidate artist names found: {total_names}")

    destination = OUT / f"analysis_{batch_file.stem}.json"
    destination.write_text(
        json.dumps(
            [report.__dict__ | {"verdict": report.verdict} for report in reports],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"wrote {destination}", file=sys.stderr)


if __name__ == "__main__":
    main()
