"""
providers.py — Unified Groq API interface.

Supports multiple Groq-hosted models. Handles retries and timeouts.
"""

import time
import os
from groq import Groq
from config import API_TIMEOUT, MAX_RETRIES, RETRY_DELAY, MAX_TOKENS, TEMPERATURE


def _get_client() -> Groq:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY is not set. Add it to your .env file or environment."
        )
    return Groq(api_key=api_key)


def call_model(
    model_id: str,
    messages: list[dict],
    system_prompt: str | None = None,
    max_tokens: int = MAX_TOKENS,
    temperature: float = TEMPERATURE,
) -> str:
    """
    Send a conversation to a Groq model and return the response text.

    Args:
        model_id:      Groq model identifier (e.g. "llama-3.3-70b-versatile")
        messages:      List of {"role": "user"|"assistant", "content": "..."} dicts
        system_prompt: Optional system prompt prepended to the conversation
        max_tokens:    Max tokens in response
        temperature:   Sampling temperature

    Returns:
        Response string from the model

    Raises:
        RuntimeError on unrecoverable failure after retries
    """
    client = _get_client()

    # Build message list — system prompt as first message if provided
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):  # +2 so MAX_RETRIES=2 means 3 total tries
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=full_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=API_TIMEOUT,
            )
            return response.choices[0].message.content or ""

        except Exception as e:
            last_error = e
            error_str = str(e)

            # Don't retry on auth errors
            if "401" in error_str or "authentication" in error_str.lower():
                raise RuntimeError(f"Authentication failed: {e}") from e

            if attempt <= MAX_RETRIES:
                wait = RETRY_DELAY * attempt
                print(f"  ⚠ Attempt {attempt} failed ({type(e).__name__}). Retrying in {wait}s…")
                time.sleep(wait)

    raise RuntimeError(
        f"All {MAX_RETRIES + 1} attempts failed for model '{model_id}': {last_error}"
    )
