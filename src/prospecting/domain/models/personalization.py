"""Personalization hooks: the concrete material outreach copy is built from."""

from __future__ import annotations

from pydantic import Field

from prospecting.domain.base import FrozenModel
from prospecting.domain.provenance import Provenance

__all__ = ["PersonalizationHook"]


class PersonalizationHook(FrozenModel):
    """One concrete, citable fact an outreach email can open with.

    ARCHITECTURE.md §4.7: "Every hook must cite a named work, exhibition,
    venue, or documented theme, with its source URL attached. Hooks that can't
    clear that bar are omitted rather than padded." That specificity rule is
    enforced by the prompt that produces hooks
    (``config/prompts/personalization.md``), not by this model — there is no
    reliable, general way to verify specificity from code. What this model
    *does* enforce is that a hook is never unsourced: like any other extracted
    claim, its provenance is required.

    ``hook_type`` is a free-text tag (``"recent_exhibition"``, ``"thematic"``,
    ``"international_presence"``, ...) rather than an enum. Unlike the
    controlled vocabularies in :mod:`prospecting.domain.enums`, the set of
    useful hook categories is expected to grow as outreach copy is iterated on,
    and that iteration should happen by editing a prompt, not by shipping a
    code change.
    """

    text: str = Field(min_length=1, description="The hook as it would appear in an email.")
    hook_type: str = Field(min_length=1, description="Category tag, e.g. 'recent_exhibition'.")
    recency_rank: int = Field(ge=1, description="1 is the most recent or strongest hook.")
    provenance: Provenance = Field(description="Where this hook's supporting fact was read from.")
