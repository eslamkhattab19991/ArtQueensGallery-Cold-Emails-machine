"""Assign each chained artist its terminal business outcome (ARCHITECTURE.md §0).

Produces the three outcome files in miniature, so the KPI can be read off real
data rather than estimated:

    completed_leads.csv          outcome 1 — the KPI
    qualified_without_email.csv  outcome 2 — incl. gallery-only
    rejected_candidates.csv      outcome 3 — not exercised here (no ICP stage yet)
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from verify import verify  # noqa: E402

OUT = Path(__file__).parent / "out"

#: Domains belonging to the organizations that listed the artist, not the artist.
#: In the real pipeline this comes from config/gallery_domains.yaml plus the
#: artist's own representation records; here it is derived from the seed sheet.
GALLERY_DOMAINS = {
    "galeriecoa.com",
    "monatgallery.com",
    "teravarna.com",
    "artmarketexperts.com",
    "artexpo-gallery.it",
}

#: Service vendors whose addresses appear in page furniture — cookie banners,
#: analytics, hosting. Never a contact for anyone.
VENDOR_DOMAINS = {
    "cookieyes.com",
    "sentry.io",
    "wix.com",
    "squarespace.com",
    "artlogic.net",
    "wordpress.com",
    "shopify.com",
}


def classify_ownership(email: str, own_domain: str | None) -> str:
    """Decide whose address this is — the heart of ARCHITECTURE.md §4.5.4."""
    domain = email.partition("@")[2].lower()

    if domain in VENDOR_DOMAINS:
        return "aggregator"
    if domain in GALLERY_DOMAINS:
        return "gallery"
    if own_domain and domain in own_domain.lower():
        return "artist_owned"
    # A free-provider address published on the artist's own contact page is the
    # artist's. That is the normal case for individual artists, who rarely run
    # mail on their own domain.
    if own_domain:
        return "artist_owned"
    return "unknown"


def main() -> None:
    """Assign outcomes and write the three files."""
    results = json.loads((OUT / "chain_results.json").read_text(encoding="utf-8"))

    completed: list[dict[str, object]] = []
    without_email: list[dict[str, object]] = []

    for record in results:
        emails = record.get("emails") or []
        own_domain = record.get("own_domain")

        best: dict[str, object] | None = None
        gallery_email: str | None = None

        for email in emails:
            ownership = classify_ownership(email, own_domain)
            if ownership == "artist_owned":
                verdict = verify(email, artist_domain=own_domain, found_via="own_contact_page")
                if verdict["confidence_band"] in {"high", "medium"}:
                    best = {**verdict, "ownership": ownership}
                    break
            elif ownership in {"gallery", "institution"} and gallery_email is None:
                gallery_email = email

        common = {
            "artist_name": record["artist_name"],
            "source_organization": record["source_organization"],
            "website": f"https://{own_domain}" if own_domain else "",
            "profile_url": record["profile_url"],
        }

        if best:
            completed.append(
                {
                    **common,
                    "email": best["email"],
                    "email_confidence_score": best["confidence_score"],
                    "email_confidence_band": best["confidence_band"],
                    "email_ownership": best["ownership"],
                    "is_role_account": best["is_role_account"],
                    "contact_status": "direct",
                    "outcome": "COMPLETED_LEAD",
                }
            )
        else:
            without_email.append(
                {
                    **common,
                    "contact_status": "indirect" if gallery_email else "exhausted",
                    "gallery_email": gallery_email or "",
                    "reason": record["outcome"],
                    "outcome": "QUALIFIED_NO_CONTACT",
                }
            )

    for rows, filename in (
        (completed, "completed_leads.csv"),
        (without_email, "qualified_without_email.csv"),
    ):
        if not rows:
            continue
        path = OUT / filename
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    total = len(results)
    print("=" * 62)
    print(
        f"  COMPLETED LEADS          {len(completed):>3}   ({len(completed) / total:.0%})  <- THE KPI"
    )
    print(
        f"  QUALIFIED, NO CONTACT    {len(without_email):>3}   ({len(without_email) / total:.0%})"
    )
    print(f"  {'-' * 58}")
    print(f"  artists chained          {total:>3}")
    print("=" * 62)

    print("\nCOMPLETED LEADS:")
    for row in completed:
        print(
            f"  {row['artist_name'][:24]:<26} {row['email']:<32} "
            f"{row['email_confidence_band']} ({row['email_confidence_score']})"
        )

    print("\nWHY THE REST DID NOT COMPLETE:")
    breakdown: dict[str, int] = {}
    for row in without_email:
        key = f"{row['contact_status']}: {row['reason']}"
        breakdown[key] = breakdown.get(key, 0) + 1
    for key, count in sorted(breakdown.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>2}  {key}")


if __name__ == "__main__":
    main()
