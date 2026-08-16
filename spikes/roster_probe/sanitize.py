"""Strip the two classes of false lead the chain cannot see one record at a time.

Both are only visible across the whole set, which is why they live here rather
than in ``chain.py``:

* **An address shared by several artists.** ``sofiamobilia@web.de`` was recorded
  for three different Artist Talk Magazine artists and ``awards@theaoi.com`` for
  two. One artist may own an address; three may not.
* **A "name" that is not a person.** The roster scan keys on title-cased page
  titles, so ``Expo Chicago``, ``Beyond Dystopia`` and ``All Artwork Category``
  enter the pipeline looking exactly like artists. They are pages, and the
  addresses attached to them are switchboards.

Run after any chain run, before export. Idempotent.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

from chain import is_personal_address

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"

#: Words that mark a page or an organization rather than a person. A real name
#: never contains one of these, and every false positive so far did.
NOT_A_PERSON = {
    "gallery",
    "galleri",
    "galerie",
    "expo",
    "museum",
    "magazine",
    "awards",
    "award",
    "prize",
    "biennale",
    "fair",
    "week",
    "category",
    "artwork",
    "artworks",
    "collection",
    "exhibition",
    "practice",
    "dystopia",
    "studios",
    "foundation",
    "council",
    "institute",
    "society",
    "association",
    "company",
    "media",
    "house",
    "club",
    "project",
    "projects",
    "creativity",
    "art",
    "arts",
    "design",
    "school",
    "academy",
    "festival",
    "centre",
    "center",
    "contemporary",
    "international",
    "national",
    "the",
    "and",
    "for",
}

#: Local-parts and domains that are plainly not a working artist's mailbox.
JUNK_PATTERNS = (
    "abc@xyz",
    "@example.",
    "@test.",
    "noreply",
    "no-reply",
    "webmaster",
    "hostmaster",
    "@sentry.",
    "@xiaohongshu.",
    "@capetown.travel",
    # Magazines that print a staff member's address on every artist they feature.
    # Two different Art Tour International employees were recorded under two
    # different artists, and a staff name defeats every structural rule.
    "@arttourinternational.",
    "@brooklynrail.",
    "@artrenewal.",
    "@magzoid.",
)


def is_malformed(email: str) -> bool:
    """Whether ``email``'s local part is a fragment rather than a real mailbox.

    Markdown emphasis around an address (``**contact**_art@outlook.com``) makes
    the address regex start matching part-way through, yielding ``_art@`` — a
    syntactically valid but non-existent mailbox. A leading separator or a
    one-to-two character local part is the signature of that truncation.
    """
    local = email.lower().partition("@")[0]
    return local.startswith(("_", ".", "-", "+")) or len(local) < 3


def org_domain_cores() -> set[str]:
    """Brand labels of every organization in the source sheet.

    An address at one of these is the organization's, whichever artist's page it
    turned up on. The frequency rule misses it when it appears only once —
    ``info@teravarna.com`` was recorded against a Circle Foundation artist that
    way — so the seed list is consulted directly. The sheet already names all 192
    organizations; there is no reason to re-derive them from behaviour.
    """
    seeds = json.loads((OUT / "seeds.json").read_text(encoding="utf-8"))
    cores: set[str] = set()
    for org in seeds:
        website = str(org.get("website") or "")
        host = re.sub(r"^https?://(www\.)?", "", website).split("/")[0]
        label = re.sub(r"[^a-z0-9]", "", host.split(".")[0].lower())
        if len(label) > 3:
            cores.add(label)
    return cores


def is_person_name(name: str) -> bool:
    """Whether ``name`` reads as a human being rather than a page heading."""
    words = [word for word in re.split(r"[^A-Za-z'’\-]+", name) if word]
    if not 2 <= len(words) <= 4:
        return False
    if any(word.lower() in NOT_A_PERSON for word in words):
        return False
    # A real name is mostly letters and has no digits anywhere.
    return not any(character.isdigit() for character in name)


def main() -> None:
    """Demote shared addresses, junk addresses, and non-person records."""
    paths = sorted((OUT / "chain").glob("*.json"))
    records = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in paths]

    counts: collections.Counter[str] = collections.Counter()
    for _, record in records:
        for email in record.get("emails") or []:
            counts[str(email).lower()] += 1

    shared = {email for email, count in counts.items() if count > 1}

    # Free providers legitimately serve thousands of artists; a *custom* domain
    # answering for more than one is a magazine or gallery, whatever the local
    # part says. arttourinternational.com supplied two different staff addresses
    # under two different artists before this check existed.
    free_providers = (
        "gmail.",
        "yahoo.",
        "hotmail.",
        "outlook.",
        "icloud.",
        "gmx.",
        "aol.",
        "web.de",
        "free.fr",
        "libero.it",
        "mail.ru",
        "yandex",
        "protonmail",
        "me.com",
        "live.",
        "comcast",
        "att.net",
        "msn.",
        "walla.co.il",
        "wp.pl",
    )
    by_domain: collections.defaultdict[str, set[str]] = collections.defaultdict(set)
    for _, record in records:
        for email in record.get("emails") or []:
            domain = str(email).lower().partition("@")[2]
            if not any(f in domain for f in free_providers):
                by_domain[domain].add(str(record["artist_name"]).lower())
    shared_domains = {d for d, artists in by_domain.items() if len(artists) > 1}
    org_cores = org_domain_cores()
    removed = collections.Counter()

    for path, record in records:
        emails = [str(e) for e in (record.get("emails") or [])]
        if not emails and is_person_name(str(record["artist_name"])):
            continue

        name = str(record["artist_name"])
        kept: list[str] = []
        for email in emails:
            lowered = email.lower()
            domain_core = re.sub(r"[^a-z0-9]", "", lowered.partition("@")[2].split(".")[0])
            surname = re.sub(r"[^a-z]", "", name.split()[-1].lower()) if name.split() else ""
            own_name_domain = bool(surname) and len(surname) > 3 and surname in domain_core

            if lowered in shared:
                removed["shared address"] += 1
            elif lowered.partition("@")[2] in shared_domains and not own_name_domain:
                removed["custom domain serving several artists"] += 1
            elif is_malformed(lowered):
                removed["malformed / truncated address"] += 1
            elif any(pattern in lowered for pattern in JUNK_PATTERNS):
                removed["junk address"] += 1
            elif not is_person_name(name):
                removed["not a person"] += 1
            elif domain_core in org_cores and not own_name_domain:
                removed["organization's own domain"] += 1
            elif not is_personal_address(email, name):
                removed["desk address on someone else's domain"] += 1
            else:
                kept.append(email)

        if kept != emails:
            record["org_emails"] = sorted(
                set((record.get("org_emails") or []) + [e for e in emails if e not in kept])
            )
            record["emails"] = kept
            record["outcome"] = "email_found" if kept else "rejected_not_personal"
            path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        if not is_person_name(str(record["artist_name"])):
            record["not_a_person"] = True
            path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"addresses shared by more than one artist: {len(shared)}")
    for email in sorted(shared):
        print(f"   {email}  (x{counts[email]})")
    print()
    for reason, count in removed.most_common():
        print(f"removed {count:>3}  {reason}")

    survivors = [
        record
        for _, record in records
        if record.get("emails") and is_person_name(str(record["artist_name"]))
    ]
    print(f"\nartists holding a genuine personal email: {len(survivors)}")


if __name__ == "__main__":
    main()
