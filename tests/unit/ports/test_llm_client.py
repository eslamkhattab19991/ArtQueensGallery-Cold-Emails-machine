"""Tests for the ``LLMClient`` port."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from prospecting.ports.llm_client import LLMClient, LlmMessage, LlmRequest, LlmResponse, LlmRole


def make_request(**overrides: object) -> LlmRequest:
    values: dict[str, object] = {
        "messages": (LlmMessage(role=LlmRole.USER, content="Extract the artist's country."),),
        "max_output_tokens": 256,
    }
    values.update(overrides)
    return LlmRequest(**values)


class TestDefaults:
    def test_temperature_defaults_to_zero(self) -> None:
        """Extraction wants the model's most reproducible answer, not variety."""
        assert make_request().temperature == 0.0

    def test_system_prompt_is_optional(self) -> None:
        assert make_request().system is None


class TestValidation:
    def test_requires_at_least_one_message(self) -> None:
        with pytest.raises(ValidationError):
            LlmRequest(messages=(), max_output_tokens=256)

    def test_rejects_a_non_positive_token_budget(self) -> None:
        with pytest.raises(ValidationError):
            make_request(max_output_tokens=0)

    def test_message_content_cannot_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            LlmMessage(role=LlmRole.USER, content="")


class TestLlmResponse:
    def test_token_counts_are_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            LlmResponse(text="France", model="claude-opus-4-8", input_tokens=-1, output_tokens=0)

    def test_may_carry_empty_text(self) -> None:
        """A model that returned nothing is still a valid response, not an error."""
        response = LlmResponse(text="", model="claude-opus-4-8", input_tokens=10, output_tokens=0)
        assert response.text == ""


class _FakeLLMClient:
    async def complete(self, request: LlmRequest) -> LlmResponse:
        return LlmResponse(
            text=f"echo: {request.messages[-1].content}",
            model="fake-model",
            input_tokens=10,
            output_tokens=5,
        )


class TestStructuralTyping:
    def test_a_shape_matching_object_satisfies_the_protocol(self) -> None:
        assert isinstance(_FakeLLMClient(), LLMClient)

    def test_an_unrelated_object_does_not(self) -> None:
        assert not isinstance(object(), LLMClient)

    def test_the_fake_returns_a_response_with_usage(self) -> None:
        response = asyncio.run(_FakeLLMClient().complete(make_request()))
        assert response.input_tokens == 10
        assert response.output_tokens == 5
