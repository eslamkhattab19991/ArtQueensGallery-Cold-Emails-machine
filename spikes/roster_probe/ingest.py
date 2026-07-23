"""Read the seed organizations out of the Excel sheet.

This is the one part of the spike whose *logic* carries forward into Phase 4:
the column mapping, the "Not found" sentinel, and the organization-type
classification are all real findings about the input data. The crawling code
around it is throwaway.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import openpyxl

WORKBOOK = Path(__file__).resolve().parents[2] / "Galleries sheet.xlsx"
SHEET = "Collected Accounts"

#: The sheet uses this literal string where a website is unknown.
MISSING_SENTINEL = "not found"

#: Keyword -> organization type. Order matters: the first match wins, so the
#: more specific patterns are listed first. Derived from reading all 192 rows,
#: not guessed — see the Phase 1 analysis.
TYPE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(prize|award|awards|competition)\b", "prize"),
    (r"\b(magazine|mag)\b", "magazine"),
    (r"\b(museum|museo|meam)\b", "museum"),
    (r"\b(foundation|fondazione|fundacion)\b", "foundation"),
    (r"\b(gallery|galerie|galeria|gallerie|galleria)\b", "gallery"),
    (r"\b(art space|artspace|studio|atelier)\b", "art_space"),
)


@dataclass(frozen=True)
class SeedOrganization:
    """One row of the sheet, normalized."""

    row: int
    name: str
    instagram: str
    website: str | None
    org_type: str

    @property
    def has_website(self) -> bool:
        """Whether the sheet gave a website rather than the "Not found" sentinel."""
        return self.website is not None


def classify(name: str) -> str:
    """Guess the organization type from its name.

    Deliberately keyword-based rather than LLM-driven: this is a probe, and a
    wrong guess here costs nothing. Phase 2 of the real pipeline can do better
    by looking at the site itself.
    """
    lowered = name.lower()
    for pattern, org_type in TYPE_PATTERNS:
        if re.search(pattern, lowered):
            return org_type
    return "unknown"


def load() -> list[SeedOrganization]:
    """Load every row of the sheet, normalized and classified."""
    workbook = openpyxl.load_workbook(WORKBOOK, data_only=True)
    sheet = workbook[SHEET]

    organizations: list[SeedOrganization] = []
    for index, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        name, instagram, website = (str(cell).strip() if cell else "" for cell in row[:3])
        if not name:
            continue
        organizations.append(
            SeedOrganization(
                row=index,
                name=name,
                instagram=instagram,
                website=None if website.lower() == MISSING_SENTINEL else website,
                org_type=classify(name),
            )
        )
    return organizations


def main() -> None:
    """Write the normalized seed list and print a summary."""
    organizations = load()
    destination = Path(__file__).parent / "out" / "seeds.json"
    destination.write_text(
        json.dumps([asdict(org) for org in organizations], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with_site = [org for org in organizations if org.has_website]
    by_type: dict[str, int] = {}
    for org in organizations:
        by_type[org.org_type] = by_type.get(org.org_type, 0) + 1

    print(f"total rows          : {len(organizations)}")
    print(f"with website        : {len(with_site)}")
    print(f"instagram only      : {len(organizations) - len(with_site)}")
    print("by type             :")
    for org_type, count in sorted(by_type.items(), key=lambda item: -item[1]):
        print(f"  {org_type:<12} {count}")
    print(f"\nwrote {destination}", file=sys.stderr)


if __name__ == "__main__":
    main()
