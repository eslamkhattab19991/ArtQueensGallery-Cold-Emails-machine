"""Produce the two deliverable sheets from the chain cache.

Two sheets, because the project has exactly one completion rule and a set of
things that are merely nice to have:

* ``completed_leads_final.csv`` — the KPI sheet. A row exists only where there is
  a **name and a verified email**. Nothing else can put a row here: not a phone
  number, not a website, not a gallery's switchboard address.
* ``enrichment_not_a_must.csv`` — everything else worth keeping, phone included.
  A row here is not a completed lead and is never counted as one.

Gender is a hard gate on the KPI sheet, applied from ``female_artists.json``.
The proof-of-concept had no such gate and shipped two male artists to the
operator; the rule here is that an artist is excluded unless positively
confirmed, so the failure mode is a smaller sheet rather than a wrong one.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from verify import verify

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"

#: Bands an operator may actually send to. "low" and "reject" are withheld:
#: a bounced send costs sender reputation, which is shared across the campaign.
SENDABLE = {"high", "medium"}

#: Addresses that pass every mechanical rule but fail on inspection. Each is a
#: case the automated checks cannot reach: the address belongs to a real person
#: or body, just not to the artist whose page it was found on. Kept as an
#: explicit list rather than a silent tweak so the reason survives review.
MISATTRIBUTED = {
    "combermere@madonnahouse.org": "Madonna House, a religious community in Combermere — not the artist",
    "priyasreelatha1978@gmail.com": "belongs to a differently-named person entirely",
    "joannchew66@gmail.com": "a differently-named person; found on Layla Fanucci's page",
    "alan.grimandi@arttourinternational.com": "a differently-named person at a magazine",
}

KPI_COLUMNS = [
    "artist_name",
    "artist_biography",
    "email",
    "email_confidence_band",
    "email_confidence_score",
    "website",
    "source_organization",
    "profile_url",
]
ENRICHMENT_COLUMNS = [
    "artist_name",
    "artist_biography",
    "phone",
    "website",
    "email_found",
    "email_confidence_band",
    "source_organization",
    "profile_url",
    "status",
]


def load_records() -> list[dict[str, object]]:
    """Read every chained artist from the per-artist cache, newest work first.

    The cache file's modification time is when that artist was actually traced,
    so it orders the sheet by when a lead was found rather than by name. An
    operator working a fresh batch wants the new rows at the top, not scattered
    alphabetically among leads they have already contacted.
    """
    records: list[dict[str, object]] = []
    for path in (OUT / "chain").glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        record["_traced_at"] = path.stat().st_mtime
        records.append(record)
    records.sort(key=lambda item: float(str(item["_traced_at"])), reverse=True)
    return records


def load_female_names() -> set[str] | None:
    """Names positively confirmed female. ``None`` when no gate has been built."""
    path = OUT / "female_artists.json"
    if not path.is_file():
        return None
    return {name.strip().lower() for name in json.loads(path.read_text(encoding="utf-8"))}


def main() -> None:
    """Write both sheets and report the single number that counts."""
    records = load_records()
    female = load_female_names()
    if female is None:
        print("!! no female_artists.json — KPI sheet would be ungated. Refusing.")
        print("   Build the gate first; an ungated sheet is what leaked male artists before.")
        raise SystemExit(1)

    kpi: list[dict[str, object]] = []
    enrichment: list[dict[str, object]] = []
    seen: set[str] = set()

    for record in records:
        name = str(record["artist_name"]).strip()
        key = name.lower()
        if key in seen or not name:
            continue
        seen.add(key)

        emails = [str(e) for e in (record.get("emails") or [])]
        domain = record.get("own_domain")
        website = f"https://{domain}" if domain else ""
        phones = [str(p) for p in (record.get("phones") or [])]

        emails = [email for email in emails if email.lower() not in MISATTRIBUTED]

        best: dict[str, object] | None = None
        for email in emails:
            result = verify(email, artist_domain=str(domain or ""), found_via="own_contact_page")
            if best is None or int(result["confidence_score"]) > int(best["confidence_score"]):
                best = result

        is_female = key in female
        sendable = best is not None and str(best["confidence_band"]) in SENDABLE

        if is_female and sendable and best is not None:
            kpi.append(
                {
                    "artist_name": name,
                    # Blank for leads found before biography capture existed; the
                    # page text was not kept, and re-fetching it would mean paying
                    # a second time for work already done.
                    "artist_biography": str(record.get("biography") or ""),
                    "email": best["email"],
                    "email_confidence_band": best["confidence_band"],
                    "email_confidence_score": best["confidence_score"],
                    "website": website,
                    "source_organization": record.get("source_organization", ""),
                    "profile_url": record.get("profile_url", ""),
                }
            )

        # Everything with something worth keeping, whether or not it is a lead.
        if phones or website or emails:
            status = (
                "completed lead"
                if (is_female and sendable)
                else "not confirmed female"
                if not is_female
                else "email not sendable"
                if emails
                else "no email"
            )
            enrichment.append(
                {
                    "artist_name": name,
                    "artist_biography": str(record.get("biography") or ""),
                    "phone": "; ".join(phones),
                    "website": website,
                    "email_found": "; ".join(emails),
                    "email_confidence_band": (best or {}).get("confidence_band", ""),
                    "source_organization": record.get("source_organization", ""),
                    "profile_url": record.get("profile_url", ""),
                    "status": status,
                }
            )

    # Deliberately not re-sorted by name: load_records already ordered these
    # newest-first, which is the order an operator works through them in.
    _write(OUT / "completed_leads.csv", KPI_COLUMNS, kpi)
    _write(OUT / "enrichment_not_a_must.csv", ENRICHMENT_COLUMNS, enrichment)

    with_phone = sum(1 for row in enrichment if row["phone"])
    print(f"artists chained            : {len(records)}")
    print(f"COMPLETED LEADS (the KPI)  : {len(kpi)}")
    print(f"enrichment rows            : {len(enrichment)}  ({with_phone} with a phone)")
    print(f"\nwrote {OUT / 'completed_leads.csv'}")
    print(f"wrote {OUT / 'enrichment_not_a_must.csv'}")


def _write(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    """Write ``rows`` as a BOM'd CSV so Excel opens accents correctly.

    Refuses loudly when the file is open in Excel rather than writing beside it
    under a new name. Working around the lock is what produced four rival
    "completed leads" files in one folder, and a folder where the operator cannot
    tell which sheet is the real one is worse than a run that stops and says so.
    """
    try:
        handle = path.open("w", newline="", encoding="utf-8-sig")
    except PermissionError:
        message = (
            f"\n!! {path.name} is open in Excel (or another program) and cannot be written.\n"
            f"   Close it and run this again. Nothing has been lost — every result is\n"
            f"   still in out/chain/, so re-running costs no credits."
        )
        raise SystemExit(message) from None
    with handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
