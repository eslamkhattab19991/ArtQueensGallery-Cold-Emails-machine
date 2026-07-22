"""Artist prospecting pipeline for Art Queens Gallery.

Discovers, qualifies, and enriches professional female artists as candidates for
international exhibitions. The design is documented in ``ARCHITECTURE.md`` at the
repository root, which is the source of truth for structure and stage contracts.

Layering (dependencies point inward only)::

    cli / config.container      composition root — may import anything
        pipeline / contact / enrichment / scoring / identity / compliance
            ports               abstract capability contracts
                domain          pure model; imports nothing from this package

The boundaries above are enforced mechanically by the Import Linter contracts in
``pyproject.toml`` and by ``tests/architecture/``. They are not conventions.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
