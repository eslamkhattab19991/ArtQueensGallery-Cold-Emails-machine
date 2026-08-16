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

# Windows consoles default to cp1252, which cannot encode the accented names
# this pipeline exists to collect — printing "Ivana Gagic Kicinbaci" with its
# real diacritics crashed an earlier run mid-batch. Force UTF-8 on our own
# streams rather than degrading the names.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).parent / "out"
CHAIN_DIR = OUT / "chain"
CHAIN_DIR.mkdir(parents=True, exist_ok=True)

EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.[a-z]{2,}", re.IGNORECASE)

#: International phone numbers as artists actually publish them: a leading + or
#: a (0), then 7-14 digits broken by spaces, dots, dashes or brackets. Captured
#: opportunistically from pages already being scraped for email — a phone is an
#: enrichment field, never a completion key, so it is worth nothing extra to
#: fetch and everything to lose by having to re-scrape for it later.
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{1,4}\)[\s.\-]?)?\d(?:[\d\s.\-]{6,16})\d")

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
    # Consent, analytics and asset vendors. Their scripts sit on every page of
    # the sites this spike crawls, so without them the "own domain" search
    # happily settles on a cookie banner's CDN: nine ArtExpo artists were each
    # chained three credits deep to cookieyes.com, returning its support address
    # as though it were the artist's. Vendor infrastructure is never a person.
    "cookieyes.com",
    "cookiebot.com",
    "onetrust.com",
    "usercentrics.com",
    "iubenda.com",
    "termly.io",
    "artcld.com",
    "wixstatic.com",
    "wp.com",
    "jsdelivr.net",
    "unpkg.com",
    "bootstrapcdn.com",
    "fontawesome.com",
    "typekit.net",
    "cloudflare.com",
    "akamaized.net",
    "gravatar.com",
    "schema.org",
    "w3.org",
    "adobe.com",
    "apple.com",
    "microsoft.com",
    "paypal.com",
    "stripe.com",
    "mailchimp.com",
    "hubspot.com",
    "eventbrite.com",
    "issuu.com",
    "calendly.com",
    "linktr.ee",
    "bit.ly",
)

#: Host *prefixes* that mark an asset or infrastructure subdomain rather than a
#: site someone publishes under. Matched on the first label only.
INFRA_PREFIXES = ("cdn", "static", "assets", "img", "images", "media", "js", "css", "fonts", "api")

#: Emails that belong to the platform, not the artist.
PLATFORM_EMAIL_DOMAINS = (
    "sentry.io",
    "wix.com",
    "squarespace.com",
    "artlogic.net",
    "cookieyes.com",
    "cookiebot.com",
    "onetrust.com",
    "iubenda.com",
    "wordpress.com",
    "godaddy.com",
    "example.com",
)

#: Local-parts belonging to a service desk rather than a person or a studio.
VENDOR_LOCALPARTS = ("support", "noreply", "no-reply", "donotreply", "abuse", "postmaster")


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


def core(host: str) -> str:
    """Reduce a host to its comparable brand label, ignoring www, sub and TLD."""
    labels = [label for label in host.split(".") if label and label != "www"]
    return re.sub(r"[^a-z0-9]", "", labels[0]) if labels else ""


def find_own_domain(profile_markdown: str, artist_name: str, profile_url: str = "") -> str | None:
    """Pick the artist's own website out of a profile page's links.

    Prefers a host containing part of the artist's surname, which is how artist
    domains are almost always named. Falls back to the first host that survives
    the exclusions.

    Two exclusions carry the weight, and both were learned from wasted credits:

    * **The hosting organization's own domain.** Every roster page links back to
      its own site far more often than it links out to the artist. Accepting it
      meant chaining forty-two Monat artists to ``monatgallery.com`` and calling
      ``info@monatgallery.com`` a lead forty-two times over.
    * **Infrastructure subdomains.** ``cdn.``/``static.`` hosts are assets, not
      sites.

    The tell for both is the same and is exact: a real artist's domain appears
    for exactly one artist, while these appear for dozens.
    """
    urls = re.findall(r"https?://[^\s\)\"'\]]+", profile_markdown)
    surname = artist_name.strip().split()[-1].lower() if artist_name.strip() else ""
    surname = re.sub(r"[^a-z]", "", surname)
    host_core = core(urlparse(profile_url).netloc.lower()) if profile_url else ""

    candidates: list[str] = []
    for url in urls:
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if not host or any(platform in host for platform in PLATFORM_HOSTS):
            continue
        if host.split(".")[0] in INFRA_PREFIXES:
            continue
        if host_core and core(host) == host_core:
            continue
        candidates.append(host)

    if surname and len(surname) > 3:
        for host in candidates:
            if surname in re.sub(r"[^a-z]", "", host):
                return host
    return candidates[0] if candidates else None


def emails_in(text: str) -> list[str]:
    """Extract plausible artist emails, discarding platform and vendor noise."""
    found = []
    for email in EMAIL_RE.findall(text):
        lowered = email.lower()
        if any(domain in lowered for domain in PLATFORM_EMAIL_DOMAINS):
            continue
        if lowered.partition("@")[0] in VENDOR_LOCALPARTS:
            continue
        if lowered.endswith((".png", ".jpg", ".gif", ".webp")):
            continue
        found.append(lowered)
    return sorted(set(found))


LEDGER_PATH = OUT / "shared_domain_ledger.json"


def load_ledger() -> dict[str, list[str]]:
    """Domains seen to serve more than one artist, with who they served."""
    if LEDGER_PATH.is_file():
        loaded: dict[str, list[str]] = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        return loaded
    return {}


def record_domain(ledger: dict[str, list[str]], domain: str, artist: str) -> None:
    """Note that ``domain`` answered for ``artist``, and persist it."""
    holders = ledger.setdefault(domain, [])
    if artist not in holders:
        holders.append(artist)
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")


def is_shared(ledger: dict[str, list[str]], domain: str, artist: str) -> bool:
    """Whether ``domain`` already answered for a *different* artist.

    This is the one test that survives contact with reality. Organizations run
    more than one domain — Agora Gallery's roster links to ``art-mine.com``, the
    Future Generation Art Prize's to ``pinchukartcentre.org`` — so no list of
    "the organization's domain" is ever complete, and comparing against the
    profile's host misses every sister site.

    Frequency does not miss them. A person's own domain answers for exactly one
    artist; a shared mailbox answered for four before this check existed, at
    three credits each. Once a domain is seen twice it is skipped, so the same
    mistake is paid for once rather than once per artist.
    """
    holders = ledger.get(domain, [])
    return any(holder != artist for holder in holders)


#: Headings under which an artist's own account of herself is published.
BIO_HEADINGS = (
    "biography",
    "bio",
    "about the artist",
    "about me",
    "about",
    "artist statement",
    "statement",
    "curriculum",
    "cv",
    "profile",
    "biografia",
    "biographie",
    "sobre",
)

#: Boilerplate that sits in page prose but says nothing about the artist.
BIO_NOISE = (
    "cookie",
    "privacy policy",
    "terms of",
    "all rights reserved",
    "newsletter",
    "subscribe",
    "javascript",
    "browser",
    "©",
    "copyright",
    "sign up",
    "log in",
    "add to cart",
    "shipping",
    "returns",
    "follow us",
    "share this",
)

#: A spreadsheet cell should stay readable; the full text lives on the page.
BIO_MAX_CHARS = 600


def biography_in(text: str, artist_name: str) -> str:
    """Pull the artist's biography out of a page already being scraped.

    Costs nothing: the profile page is fetched anyway to find her email, and the
    biography is almost always on it. Discarding that text and re-fetching later
    would mean paying a second time for a page we already had.

    Two strategies, strongest first. A ``Biography`` or ``About`` heading is an
    explicit signal, so text beneath one is preferred. Failing that, the longest
    block of real prose on the page is nearly always the bio — navigation and
    menus are short fragments, and boilerplate is filtered by keyword.

    Returns an empty string rather than a guess when nothing qualifies: a blank
    cell is honest, a wrong biography in an outreach email is not.
    """
    lines = [line.strip() for line in text.splitlines()]

    def usable(block: str) -> bool:
        lowered = block.lower()
        if len(block) < 120 or any(noise in lowered for noise in BIO_NOISE):
            return False
        # Real prose, not a list of links or a nav bar.
        return block.count(".") >= 2 and block.count("|") < 3 and block.count("](") < 3

    # 1. Text directly under a biography-style heading.
    for index, line in enumerate(lines):
        heading = re.sub(r"[^a-z ]", "", line.lower()).strip()
        if heading in BIO_HEADINGS and (line.startswith("#") or len(line) < 40):
            collected: list[str] = []
            for following in lines[index + 1 : index + 30]:
                if following.startswith("#") and collected:
                    break
                if following:
                    collected.append(following)
                if sum(len(part) for part in collected) > BIO_MAX_CHARS:
                    break
            candidate = " ".join(collected).strip()
            if usable(candidate):
                return _trim(candidate)

    # 2. Otherwise the longest genuine paragraph, preferring one that names her.
    surname = artist_name.strip().split()[-1].lower() if artist_name.strip() else ""
    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text) if usable(block.strip())]
    if not paragraphs:
        return ""
    named = [block for block in paragraphs if surname and surname in block.lower()]
    return _trim(max(named or paragraphs, key=len))


def _trim(text: str) -> str:
    """Collapse whitespace and markdown, and cut at a sentence near the limit."""
    cleaned = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> their text
    cleaned = re.sub(r"[*_#>`]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= BIO_MAX_CHARS:
        return cleaned
    cut = cleaned[:BIO_MAX_CHARS]
    stop = cut.rfind(". ")
    return (cut[: stop + 1] if stop > BIO_MAX_CHARS // 2 else cut.rstrip()) + "…"


def phones_in(text: str) -> list[str]:
    """Extract plausible phone numbers, discarding dates, prices and image sizes.

    Deliberately conservative: a wrong phone number is worse than no phone
    number, and phone is a nice-to-have field that never decides whether a lead
    counts as complete. Anything ambiguous is dropped rather than guessed.
    """
    found: list[str] = []
    for match in PHONE_RE.finditer(text):
        raw = match.group().strip()
        digits = re.sub(r"\D", "", raw)
        if not 8 <= len(digits) <= 15:
            continue
        # Years, prices and pixel dimensions are the common false positives.
        if not raw.startswith("+") and (len(digits) < 9 or digits.startswith(("19", "20"))):
            continue
        if len(set(digits)) <= 2:
            continue
        found.append(re.sub(r"[\s.\-]+", " ", raw))
    return sorted(set(found))[:3]


#: Local-parts that address a desk rather than a person.
ROLE_LOCALPARTS = frozenset(
    {
        "info",
        "contact",
        "hello",
        "admin",
        "office",
        "mail",
        "support",
        "sales",
        "help",
        "gallery",
        "art",
        "studio",
        "press",
        "submissions",
        "team",
        "enquiries",
        "inquiries",
        "bonjour",
        "kontakt",
        "general",
        # Editorial and commercial desks. A magazine that features an artist
        # publishes its own curator's address on her page, and
        # curator@contemporaryartcurator.com reached the magazine rather than
        # Aase Hilde Brekke — it survived the first pass because the word was
        # missing here, not because the rule was wrong.
        "curator",
        "editor",
        "editorial",
        "publisher",
        "marketing",
        "media",
        "represented",
        "booking",
        "bookings",
        "events",
        "shop",
        "orders",
        "newsletter",
        "subscribe",
        "hola",
        "ciao",
        "hallo",
        # Service desks. "books@brooklynrail.org" reached a magazine's books
        # department and "customercare@partial.gallery" a shop counter; both
        # were recorded as artists' addresses because the word was missing here.
        "books",
        "customercare",
        "customer",
        "service",
        "services",
        "reception",
        "welcome",
        "apply",
        "entries",
        "entry",
        "competition",
        "awards",
        "jury",
    }
)


def local_part_echoes_domain(email: str) -> bool:
    """Whether the address is the organisation naming itself.

    ``clio@clioartfair.com`` is the Clio Art Fair, not the artist whose page it
    sat on. When the local part is simply the domain's own brand word, the
    mailbox belongs to the body that owns the domain — no list of role words can
    anticipate every such name, but the pattern itself is unmistakable.
    """
    local, _, domain = email.lower().partition("@")
    local = re.sub(r"[^a-z0-9]", "", local)
    brand = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
    if len(local) < 3 or not brand:
        return False
    return local == brand or (len(local) >= 4 and local in brand)


def is_personal_address(email: str, artist_name: str) -> bool:
    """Whether ``email`` plausibly reaches this artist rather than an office.

    A role local-part is not disqualifying on its own: a working artist very
    often publishes ``office@<their-own-name>.com``, and Cornelia Bienz and Vian
    Borchert are both real leads found exactly that way. It is disqualifying when
    the domain is somebody else's — ``sales@agora-gallery.com`` reaches the
    gallery's sales desk no matter which of its artists' pages it was found on.

    So the test is not the local-part alone but the pair: a desk address counts
    only when the desk is the artist's own.
    """
    local, _, domain = email.lower().partition("@")
    surname_raw = artist_name.strip().split()[-1].lower() if artist_name.strip() else ""
    surname = re.sub(r"[^a-z]", "", surname_raw)
    domain_core = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])

    # Her own domain settles it before any other rule runs. marie@marietippets.com
    # is the strongest lead shape there is, and an earlier version of the echo
    # check rejected four such addresses because the first name is a substring of
    # the domain — exactly what you would expect on a personal site.
    #
    # Any part of her name counts, not only the surname: Smadar Katz publishes at
    # smadar.com, and testing "katz" alone threw her away.
    parts = [re.sub(r"[^a-z]", "", part.lower()) for part in artist_name.split()]
    if any(len(part) > 3 and part in domain_core for part in parts):
        return True

    if local_part_echoes_domain(email):
        return False
    if local not in ROLE_LOCALPARTS:
        return True
    surname = (
        re.sub(r"[^a-z]", "", artist_name.strip().split()[-1].lower())
        if artist_name.strip()
        else ""
    )
    domain_core = re.sub(r"[^a-z]", "", domain.split(".")[0])
    return bool(surname) and len(surname) > 3 and surname in domain_core


def is_org_address(email: str, profile_url: str) -> bool:
    """Whether ``email`` belongs to the hosting organization rather than a person.

    A gallery's shared address is the single most common thing on an artist
    profile page and the single least useful: it is not a lead, it is the
    gallery's switchboard. Recording it as an email found is what let the
    proof-of-concept report contact for artists nobody could actually contact.
    """
    domain = email.lower().partition("@")[2]
    host_core = core(urlparse(profile_url).netloc.lower())
    return bool(host_core) and core(domain) == host_core


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
        "org_emails": [],
        "phones": [],
        "biography": "",
        "outcome": "no_profile",
    }

    profile = run_firecrawl(["scrape", artist["profile_url"]])
    time.sleep(6)
    if not profile:
        cache.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    # An email may already be on the roster profile itself — always cheapest.
    found_on_profile = emails_in(profile)
    domain = find_own_domain(profile, name, artist["profile_url"])
    record["own_domain"] = domain
    record["phones"] = phones_in(profile)
    # Free: this page was fetched for the email, so the bio costs nothing extra.
    record["biography"] = biography_in(profile, name)

    # Only the artist's own address ends the chain. A gallery switchboard on the
    # page is recorded for the audit trail but does not stop the search, because
    # the artist may still have a reachable site of their own.
    direct = [e for e in found_on_profile if not is_org_address(e, artist["profile_url"])]
    if direct:
        record["emails"] = direct
        record["contact_url"] = artist["profile_url"]
        record["outcome"] = "email_on_profile"
        cache.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    record["org_emails"] = [e for e in found_on_profile if is_org_address(e, artist["profile_url"])]

    if not domain:
        record["outcome"] = "no_own_domain"
        cache.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record

    # Stop before the expensive half of the chain if this domain has already
    # answered for someone else: it is the organization's, not the artist's.
    ledger = load_ledger()
    if is_shared(ledger, domain, name):
        record["outcome"] = "shared_org_domain"
        record["own_domain"] = domain
        cache.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return record
    record_domain(ledger, domain, name)

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
        # The artist's own contact page: an address here is theirs by definition,
        # so the org-address filter that guards the roster page does not apply.
        found = emails_in(page)
        record["emails"] = found
        # A contact page is where a phone actually lives; prefer it over the
        # roster profile's, which is usually the gallery's switchboard.
        record["phones"] = phones_in(page) or record["phones"]
        record["biography"] = biography_in(page, name) or record["biography"]
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
