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


def list_model_ids() -> set[str]:
    """Return the model IDs currently exposed by Groq."""
    return {model.id for model in _get_client().models.list().data}


def _status_code(error: Exception) -> int | None:
    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        return status_code

    response = getattr(error, "response", None)
    return getattr(response, "status_code", None)


def _is_timeout(error: Exception) -> bool:
    error_name = type(error).__name__.lower()
    error_text = str(error).lower()
    return (
        isinstance(error, TimeoutError)
        or "timeout" in error_name
        or "timed out" in error_text
    )


def _is_connection_error(error: Exception) -> bool:
    return (
        isinstance(error, ConnectionError)
        or "connection" in type(error).__name__.lower()
    )


def _is_retryable(error: Exception) -> bool:
    status_code = _status_code(error)
    return (
        _is_timeout(error)
        or _is_connection_error(error)
        or status_code == 429
        or (status_code is not None and 500 <= status_code <= 599)
    )


def _is_missing_model_error(error: Exception) -> bool:
    error_text = str(error).lower()
    return (
        "model not found" in error_text
        or "decommissioned" in error_text
        or "deprecated model" in error_text
    )


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
        model_id: Groq model identifier
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

            status_code = _status_code(e)
            if _is_missing_model_error(e):
                raise RuntimeError(
                    f"Model '{model_id}' is unavailable or decommissioned: {e}"
                ) from e

            if status_code in {400, 401, 403, 404} or not _is_retryable(e):
                raise RuntimeError(
                    f"Groq request failed for model '{model_id}': {e}"
                ) from e

            if attempt <= MAX_RETRIES:
                wait = RETRY_DELAY * attempt
                print(f"  ⚠ Attempt {attempt} failed ({type(e).__name__}). Retrying in {wait}s…")
                time.sleep(wait)

    raise RuntimeError(
        f"All {MAX_RETRIES + 1} attempts failed for model '{model_id}': {last_error}"
    )
