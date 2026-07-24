"""The ``LLMClient`` port: send a prompt, get text back with token accounting.

ARCHITECTURE.md §7: the LLM adapter wraps the vendor SDK — retries, caching,
token accounting — and explicitly does **not** own prompts or business rules.
Prompts live in ``config/`` and are chosen by the stages; this port only carries
messages to a model and returns what it said, plus how many tokens it cost.

Token accounting is not incidental. The budget ceilings in ARCHITECTURE.md §9
are enforced mid-run, so every response must report its input and output token
counts — that is what lets the orchestrator fold LLM spend into a record's
:class:`~prospecting.schemas.envelope.CostRecord` and stop a runaway stage.

Structured extraction (parsing a model's answer into a typed pydantic object)
is deliberately layered *above* this port by the extraction stage, not baked
into it. The port's contract is "text in, text and usage out"; committing the
port to a particular structured-output mechanism before there is extraction
code to shape it would be guessing at a contract, and this project does not
ship guessed contracts.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field

from prospecting.domain.base import FrozenModel

__all__ = ["LLMClient", "LlmMessage", "LlmRequest", "LlmResponse", "LlmRole"]


class LlmRole(StrEnum):
    """Who authored a message in a conversation turn."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LlmMessage(FrozenModel):
    """One message in the conversation sent to the model."""

    role: LlmRole = Field(description="Who this message is from.")
    content: str = Field(min_length=1, description="The message text.")


class LlmRequest(FrozenModel):
    """A single completion request, independent of any vendor's parameter names.

    ``temperature`` defaults to 0: extraction and classification want the most
    reproducible answer the model can give, so that re-running a stage over the
    same input does not silently change a record. A stage that genuinely needs
    variation sets it explicitly.
    """

    messages: tuple[LlmMessage, ...] = Field(
        min_length=1, description="The conversation, in order. At least one message."
    )
    system: str | None = Field(
        default=None, description="System instruction, if the model takes one."
    )
    max_output_tokens: int = Field(gt=0, description="Upper bound on the response length.")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="Sampling temperature.")


class LlmResponse(FrozenModel):
    """What the model returned, plus the token counts the budget layer needs."""

    text: str = Field(description="The model's reply. May be empty if the model returned nothing.")
    model: str = Field(
        min_length=1, description="Exact model id that produced this, for provenance."
    )
    input_tokens: int = Field(ge=0, description="Prompt tokens billed.")
    output_tokens: int = Field(ge=0, description="Completion tokens billed.")
    stop_reason: str | None = Field(
        default=None, description="Why generation stopped, when the vendor reports it."
    )


@runtime_checkable
class LLMClient(Protocol):
    """Complete one request against a language model."""

    async def complete(self, request: LlmRequest) -> LlmResponse:
        """Send ``request`` to the model and return its reply with token usage.

        Retries and rate-limit handling are the adapter's concern. A response is
        returned even when the model produced empty text; only an unrecoverable
        transport failure raises.
        """
        ...
