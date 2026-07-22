"""Merge pipeline for candidates gathered from all sources.

Four ordered steps, each in its own module::

    normalizer   de-obfuscate, canonicalize, deduplicate
    ownership    artist-owned vs gallery vs institution vs aggregator
    corroboration cross-source agreement scoring
    ranker       ordered candidate list

Ownership is classified here, per candidate, rather than per source. A gallery
address can surface from any source, so source identity cannot determine
ownership — see ARCHITECTURE.md §4.5.4.
"""
