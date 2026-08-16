"""Rank organizations by whether their artists are actually contactable.

Reads the per-artist chain cache and scores each organization on the one signal
that predicted every lead so far: does the artist have an email at their *own*
domain, rather than the organization's shared address?

An organization whose profiles all carry ``info@<the-gallery>.com`` scores zero
here no matter how large its roster, which is the correct verdict — 86 such
artists produced no leads. An organization whose artists link out to their own
sites is where the entire chaining budget should go.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"

#: Free mailbox providers. An artist on gmail is perfectly contactable — the
#: address is theirs — so these count as a win even though the domain is not.
FREE_MAIL = ("gmail.", "yahoo.", "hotmail.", "outlook.", "icloud.", "gmx.", "web.de", "free.fr")

#: Local-parts that mark a shared organizational mailbox rather than a person.
ROLE_LOCALPARTS = {
    "info",
    "contact",
    "hello",
    "admin",
    "office",
    "mail",
    "support",
    "gallery",
    "art",
    "studio",
    "press",
    "sales",
    "submissions",
    "team",
}


def host_of(url: str) -> str:
    """Registrable-ish host for a URL, without the www."""
    return urlparse(url).netloc.lower().removeprefix("www.")


def core(host: str) -> str:
    """Reduce a host to comparable letters, so www/sub/tld noise does not matter."""
    return re.sub(r"[^a-z0-9]", "", host.split(".")[0]) if host else ""


def classify(record: dict[str, object]) -> str:
    """Say what one chained artist is worth: direct, gallery, or nothing."""
    emails = [str(e) for e in (record.get("emails") or [])]
    if not emails:
        return "no_email"

    profile_host = host_of(str(record.get("profile_url") or ""))
    own = str(record.get("own_domain") or "")
    artist_owned = own and core(own) != core(profile_host)

    for email in emails:
        local, _, domain = email.partition("@")
        if local.lower() in ROLE_LOCALPARTS and core(domain) == core(profile_host):
            continue  # the organization's own shared mailbox
        if any(provider in domain for provider in FREE_MAIL):
            return "direct"
        if artist_owned and core(domain) == core(own):
            return "direct"
        if core(domain) != core(profile_host):
            return "direct"
    return "gallery"


def main() -> None:
    """Print the organization ranking and write the qualified list."""
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((OUT / "chain").glob("*.json"))
    ]

    stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"probed": 0, "direct": 0, "gallery": 0, "no_email": 0, "own_domain": 0}
    )
    for record in records:
        org = str(record.get("source_organization") or "?")
        entry = stats[org]
        entry["probed"] += 1
        entry[classify(record)] += 1
        own = str(record.get("own_domain") or "")
        if own and core(own) != core(host_of(str(record.get("profile_url") or ""))):
            entry["own_domain"] += 1

    rosters = (
        {
            str(item["name"]): len(item["artists"])
            for item in json.loads((OUT / "probe_rosters.json").read_text(encoding="utf-8"))
        }
        if (OUT / "probe_rosters.json").is_file()
        else {}
    )

    ranked = sorted(
        stats.items(),
        key=lambda kv: (-(kv[1]["direct"] / kv[1]["probed"]), -kv[1]["probed"]),
    )

    print(
        f"{'organization':<38} {'probed':>6} {'direct':>6} {'own-dom':>7} {'rate':>6} {'roster':>6}"
    )
    print("-" * 76)
    qualified: list[str] = []
    for org, entry in ranked:
        rate = entry["direct"] / entry["probed"]
        roster = rosters.get(org, 0)
        flag = ""
        if rate >= 0.4:
            qualified.append(org)
            flag = "  <-- chain it"
        print(
            f"{org[:36]:<38} {entry['probed']:>6} {entry['direct']:>6} "
            f"{entry['own_domain']:>7} {rate:>5.0%} {roster:>6}{flag}"
        )

    (OUT / "qualified_orgs.json").write_text(
        json.dumps(qualified, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nqualified organizations (>=40% direct): {len(qualified)}")
    print(f"wrote {OUT / 'qualified_orgs.json'}")


if __name__ == "__main__":
    main()
