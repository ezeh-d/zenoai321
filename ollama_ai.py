# ollama_ai.py

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from ollama import Client

from assistant_mode import get_mode_prompt
from chat_memory import add_message, get_recent_messages
from config import (
    AI_MAX_HISTORY_MESSAGES,
    AI_MAX_RETRIES,
    AI_RETRY_DELAY_SECONDS,
    AI_TEMPERATURE,
    AI_TIMEOUT_SECONDS,
    MODEL,
    OLLAMA_HOST,
    SYSTEM_PROMPT,
)

logger = logging.getLogger("reyes.ollama")

client = Client(
    host=OLLAMA_HOST,
    timeout=AI_TIMEOUT_SECONDS,
)


def _normalize_history_message(
    message: dict[str, Any],
) -> dict[str, str] | None:
    """
    Convert a stored chat message into Ollama's message format.
    """

    role = str(message.get("role", "")).strip().lower()
    content = str(message.get("content", "")).strip()

    if role not in {"user", "assistant", "system"}:
        return None

    if not content:
        return None

    return {
        "role": role,
        "content": content,
    }


def _build_messages(prompt: str) -> list[dict[str, str]]:
    """
    Build the complete conversation sent to Ollama.
    """

    system_content = (
        f"{SYSTEM_PROMPT}\n\n"
        f"{get_mode_prompt()}"
    )

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": system_content,
        }
    ]

    history = get_recent_messages(
        limit=AI_MAX_HISTORY_MESSAGES,
    )

    for stored_message in history:
        normalized = _normalize_history_message(stored_message)

        if normalized is not None:
            messages.append(normalized)

    messages.append(
        {
            "role": "user",
            "content": prompt,
        }
    )

    return messages


def _chat_with_retries(
    messages: list[dict[str, str]],
) -> str:
    """
    Call Ollama, retrying on transient connection/timeout errors.

    Returns the model's answer text. Raises the last error if
    every attempt fails.
    """

    last_error: Exception | None = None
    total_attempts = 1 + max(0, AI_MAX_RETRIES)

    for attempt in range(1, total_attempts + 1):
        try:
            response = client.chat(
                model=MODEL,
                messages=messages,
                options={
                    "temperature": AI_TEMPERATURE,
                },
            )

            return (response.message.content or "").strip()

        except (ConnectionError, httpx.ConnectError, httpx.TimeoutException) as error:
            last_error = error

            logger.warning(
                "Ollama attempt %d/%d failed: %s",
                attempt,
                total_attempts,
                error,
            )

            if attempt < total_attempts:
                time.sleep(AI_RETRY_DELAY_SECONDS)

    assert last_error is not None
    raise last_error


def ask_ai(prompt: str) -> str:
    """
    Send a prompt to the configured Ollama model.
    """

    clean_prompt = prompt.strip()

    if not clean_prompt:
        return "Please give me a question or command."

    try:
        messages = _build_messages(clean_prompt)

        answer = _chat_with_retries(messages)

        if not answer:
            logger.warning("Model %s returned an empty response.", MODEL)
            return "The AI model returned an empty response."

        add_message("user", clean_prompt)
        add_message("assistant", answer)

        return answer

    except (ConnectionError, httpx.ConnectError) as error:
        logger.error("Could not connect to Ollama at %s: %s", OLLAMA_HOST, error)

        return (
            "I could not connect to Ollama. "
            "Make sure Ollama is running."
        )

    except httpx.TimeoutException as error:
        logger.error("Ollama request timed out after %ss: %s", AI_TIMEOUT_SECONDS, error)

        return (
            "The AI model took too long to respond. "
            "Try again, or use a smaller/faster model."
        )

    except Exception as error:
        logger.exception("Unexpected Ollama error: %s", error)

        return (
            "I could not get a response from the local AI model. "
            "Check that Ollama is running and the configured model "
            "is installed."
        )


def test_ai_connection() -> tuple[bool, str]:
    """
    Test whether Ollama and the selected model are available.
    """

    try:
        response = client.chat(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with the single word ONLINE.",
                }
            ],
            options={
                "temperature": 0,
            },
        )

        answer = (response.message.content or "").strip()

        if answer:
            return True, f"{MODEL} is available."

        return False, f"{MODEL} returned an empty response."

    except Exception as error:
        logger.error("Ollama connection test failed: %s", error)
        return False, f"Ollama connection failed: {error}"