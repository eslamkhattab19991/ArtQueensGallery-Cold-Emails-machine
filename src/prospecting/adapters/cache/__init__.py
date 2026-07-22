"""Content-addressed cache adapters.

Crawl results are keyed by content hash so a URL is fetched at most once across
all runs. This is the single largest cost control in the system.
"""
