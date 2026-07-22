"""LLM client adapters.

Wrap the vendor SDK: retries, structured outputs, prompt caching, batching, and
token accounting. Prompts and business rules live in ``config/prompts`` and the
pipeline stages respectively — never here.
"""
