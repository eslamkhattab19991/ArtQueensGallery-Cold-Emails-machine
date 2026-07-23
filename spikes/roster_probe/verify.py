"""Verify an email the way Stage 6 will: syntax, MX, address type, confidence.

Mirrors ARCHITECTURE.md §4.6 — no paid service, no SMTP probe. The point is to
produce the same `confidence_band` the real pipeline will, so the completed-lead
count this spike reports is measured against the same bar the KPI uses.
"""

from __future__ import annotations

import re
import smtplib  # noqa: F401  (imported only to document what we deliberately do NOT do)
import socket
import sys

RFC5322 = re.compile(r"^[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+$")

DISPOSABLE = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com"}
FREE_PROVIDERS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "gmx.de"}
ROLE_LOCALPARTS = {"info", "contact", "studio", "gallery", "hello", "mail", "office", "admin"}

#: Common misspellings of large providers. A typo'd domain resolves to nothing
#: and would otherwise look like a hard failure rather than a fixable mistake.
TYPO_DOMAINS = {"gmial.com", "gmai.com", "gmail.co", "hotmial.com", "yahooo.com"}


def has_mx(domain: str) -> bool:
    """Whether the domain accepts mail.

    Uses a plain DNS lookup via the standard library rather than dnspython, to
    keep the spike dependency-free. The real Stage 6 adapter uses a proper
    resolver so it can distinguish MX from an A-record fallback; here, "the
    domain resolves at all" is a close enough proxy to sort real domains from
    typos and dead sites.
    """
    try:
        socket.getaddrinfo(domain, None)
    except (socket.gaierror, UnicodeError):
        return False
    else:
        return True


def verify(email: str, *, artist_domain: str | None = None, found_via: str = "unknown") -> dict:
    """Return the verification verdict and confidence band for one address."""
    email = email.strip().lower()
    local, _, domain = email.partition("@")

    checks = {
        "syntax_valid": bool(RFC5322.match(email)),
        "typo_suspected": domain in TYPO_DOMAINS,
        "domain_resolves": has_mx(domain) if domain else False,
        "is_disposable": domain in DISPOSABLE,
        "is_free_provider": domain in FREE_PROVIDERS,
        "is_role_account": local in ROLE_LOCALPARTS,
        "domain_matches_website": bool(artist_domain and domain in artist_domain),
    }

    # Weights mirror the confidence model in ARCHITECTURE.md §4.6.
    score = 0
    score += 30 if found_via in {"own_contact_page", "mailto_href"} else 10
    score += 25 if checks["domain_matches_website"] else 0
    score += 20 if checks["domain_resolves"] else 0
    score += 10 if checks["syntax_valid"] and not checks["typo_suspected"] else 0
    score += 5 if checks["is_role_account"] else 10
    score -= 20 if checks["is_disposable"] or checks["typo_suspected"] else 0

    # A free-provider address is not weak evidence when it was published on the
    # artist's own contact page — for individual artists that is the norm, not a
    # red flag. It is only weak when the source is also weak.
    if checks["is_free_provider"] and found_via not in {"own_contact_page", "mailto_href"}:
        score -= 20

    score = max(0, min(100, score))
    band = (
        "high" if score >= 80 else "medium" if score >= 55 else "low" if score >= 30 else "reject"
    )

    return {"email": email, **checks, "confidence_score": score, "confidence_band": band}


if __name__ == "__main__":
    result = verify(
        sys.argv[1],
        artist_domain=sys.argv[2] if len(sys.argv) > 2 else None,
        found_via="own_contact_page",
    )
    for key, value in result.items():
        print(f"  {key:<24} {value}")
