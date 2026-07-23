"""Run the full discovery-to-completed-lead chain for a sample of artists.

    roster profile -> artist's own domain -> contact page -> email -> verify

This measures the one number the project is judged on: what fraction of
*discovered* artists become *completed leads*. Everything else in the spike
answers "can we find artists"; this answers "can we contact them", which is what
the KPI counts.

Deliberately sequential with generous spacing — the earlier map runs showed the
rate limit is far tighter than the advertised concurrency.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

OUT = Path(__file__).parent / "out"
CHAIN_DIR = OUT / "chain"
CHAIN_DIR.mkdir(parents=True, exist_ok=True)

EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.[a-z]{2,}", re.IGNORECASE)

#: Hosts that appear on artist pages but are never the artist's own site.
PLATFORM_HOSTS = (
    "instagram.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
    "pinterest.com",
    "artsy.net",
    "saatchiart.com",
    "artfacts.net",
    "artlogic.net",
    "squarespace.com",
    "wixsite.com",
    "google.com",
    "vimeo.com",
    "tiktok.com",
    "cloudfront.net",
    "gstatic.com",
    "shopify.com",
)

#: Emails that belong to the platform, not the artist.
PLATFORM_EMAIL_DOMAINS = ("sentry.io", "wix.com", "squarespace.com", "artlogic.net")


#: npm installs a `.cmd` shim on Windows. A bash shell resolves the bare name
#: via its own PATH handling, but Python's CreateProcess does not — calling
#: "firecrawl" from subprocess raises FileNotFoundError, which this script
#: originally swallowed and reported as twelve unreachable profiles.
FIRECRAWL = "firecrawl.cmd" if sys.platform == "win32" else "firecrawl"


def run_firecrawl(args: list[str], timeout: int = 150) -> str | None:
    """Run the Firecrawl CLI, returning stdout or None on failure."""
    try:
        result = subprocess.run(
            [FIRECRAWL, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError as exc:
        # Distinguish "the CLI is missing" from "the site failed". Silently
        # treating the former as the latter is what produced a uniform wall of
        # false negatives on the first run.
        print(f"      !! cannot invoke {FIRECRAWL}: {exc}", file=sys.stderr)
        raise
    return result.stdout if result.returncode == 0 and result.stdout else None


def find_own_domain(profile_markdown: str, artist_name: str) -> str | None:
    """Pick the artist's own website out of a profile page's links.

    Prefers a host containing part of the artist's surname, which is how artist
    domains are almost always named. Falls back to the first non-platform host.
    """
    urls = re.findall(r"https?://[^\s\)\"'\]]+", profile_markdown)
    surname = artist_name.strip().split()[-1].lower() if artist_name.strip() else ""
    surname = re.sub(r"[^a-z]", "", surname)

    candidates: list[str] = []
    for url in urls:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if not host or any(platform in host for platform in PLATFORM_HOSTS):
            continue
        candidates.append(host)

    if surname and len(surname) > 3:
        for host in candidates:
            if surname in re.sub(r"[^a-z]", "", host):
                return host
    return candidates[0] if candidates else None


def emails_in(text: str) -> list[str]:
    """Extract plausible artist emails, discarding platform noise."""
    found = []
    for email in EMAIL_RE.findall(text):
        lowered = email.lower()
        if any(domain in lowered for domain in PLATFORM_EMAIL_DOMAINS):
            continue
        if lowered.endswith((".png", ".jpg", ".gif", ".webp")):
            continue
        found.append(lowered)
    return sorted(set(found))


def chain_one(artist: dict[str, str]) -> dict[str, object]:
    """Run the full chain for one artist and record every step's outcome."""
    name = artist["artist_name"]
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    cache = CHAIN_DIR / f"{slug}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))

    record: dict[str, object] = {
        "artist_name": name,
        "source_organization": artist["source_organization"],
        "profile_url": artist["profile_url"],
        "own_domain": None,
        "contact_url": None,
        "emails": [],
        "outcome": "no_profile",
    }

    profile = run_firecrawl(["scrape", artist["profile_url"]])
    time.sleep(6)
    if not profile:
        cache.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    # An email may already be on the roster profile itself — always cheapest.
    direct = emails_in(profile)
    domain = find_own_domain(profile, name)
    record["own_domain"] = domain

    if direct:
        record["emails"] = direct
        record["contact_url"] = artist["profile_url"]
        record["outcome"] = "email_on_profile"
        cache.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    if not domain:
        record["outcome"] = "no_own_domain"
        cache.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    mapped = run_firecrawl(["map", f"https://{domain}/", "--search", "contact", "--json"])
    time.sleep(6)
    contact_url = f"https://{domain}/contact"
    if mapped:
        try:
            links = json.loads(mapped).get("data", {}).get("links", [])
            for link in links:
                if "contact" in link.get("url", "").lower():
                    contact_url = link["url"]
                    break
        except json.JSONDecodeError:
            pass
    record["contact_url"] = contact_url

    page = run_firecrawl(["scrape", contact_url])
    time.sleep(6)
    if not page:
        record["outcome"] = "contact_page_unreachable"
    else:
        found = emails_in(page)
        record["emails"] = found
        record["outcome"] = "email_found" if found else "no_email_on_contact_page"

    cache.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def main() -> None:
    """Chain a sample of artists and report the completed-lead rate."""
    sample = json.loads((OUT / "chain_sample.json").read_text(encoding="utf-8"))
    results = []
    for index, artist in enumerate(sample, 1):
        print(f"[{index}/{len(sample)}] {artist['artist_name']}", flush=True)
        result = chain_one(artist)
        print(f"      -> {result['outcome']}  {result['emails'] or ''}", flush=True)
        results.append(result)

    (OUT / "chain_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nwrote {OUT / 'chain_results.json'}", file=sys.stderr)


if __name__ == "__main__":
    main()
