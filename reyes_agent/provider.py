"""The thin seam between the agent core and whatever model provider is behind it.

Everything else in the harness calls `run_turn()` and never touches a
provider SDK directly. Swapping providers is a one-line edit to
`MODEL_PROVIDER` in `.env` -- never a code change elsewhere. Adding a new
provider means writing one `_run_<name>` function and one entry in
`_RUNNERS` below.

History is kept in a provider-neutral shape so the agent core and the tool
loop never need to know which provider is behind the seam:
  {"role": "user", "content": "..."}
  {"role": "assistant", "content": "...", "tool_calls": [{"id","name","input","extra"}]}
  {"role": "tool_result", "tool_call_id": "...", "name": "...", "content": "..."}
`extra` on a tool call is optional, provider-specific metadata (see
`ToolCall.extra`) that must round-trip back to whichever provider produced
it. Each provider function translates this to its own wire format and
translates the response back into a plain `AgentTurn`.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from reyes_agent import config, personality

if TYPE_CHECKING:
    import anthropic
    import openai

_MAX_RETRY_ATTEMPTS = 3
# Backoff for a retryable failure (e.g. a free-tier rate-limit blip). Kept
# short on purpose: for an interactive turn the only configured fallback is a
# slow local model, so recovering on the FAST cloud provider a second sooner
# beats failing over. 1.0 => waits of 1s then 2s (was 2s then 4s).
_RETRY_BASE_DELAY_S = 1.0

# CPU-bound local models pay for every token of context on every turn --
# an unbounded history quietly makes each reply slower than the last.
# Cloud providers don't have this problem as acutely, but the cap costs
# them nothing either, so it applies everywhere.
_MAX_HISTORY_TURNS = 8


def _windowed(history: list[dict]) -> list[dict]:
    user_indices = [i for i, turn in enumerate(history) if turn["role"] == "user"]
    if len(user_indices) <= _MAX_HISTORY_TURNS:
        return history
    return history[user_indices[-_MAX_HISTORY_TURNS] :]


class ProviderError(Exception):
    """Raised when the model can't be reached or refuses the request.

    Callers should catch this, show the message, and keep the conversation
    loop alive -- a network hiccup should never crash the assistant.
    """

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        # Set on rate limits and connection hiccups -- run_turn() retries
        # these with backoff automatically, on failed connections/auth/bad
        # input it isn't, since retrying those just fails the same way again.
        self.retryable = retryable


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]
    # Provider-specific metadata that must be echoed back verbatim on the
    # next call, or that provider rejects the turn. Gemini's OpenAI-compat
    # endpoint requires its `thought_signature` be replayed on tool_calls
    # or it 400s on the very next message -- discovered 2026-07-22. Other
    # providers just leave this None.
    extra: dict[str, Any] | None = None


@dataclass
class AgentTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)


OnText = Callable[[str], None]

_anthropic_client: Any = None
_openai_client: Any = None
_xai_client: Any = None
_gemini_client: Any = None
_ollama_client: Any = None
_anthropic_sdk: Any = None
_openai_sdk: Any = None
_client_init_lock = threading.RLock()


def _anthropic_module() -> Any:
    global _anthropic_sdk
    if _anthropic_sdk is None:
        with _client_init_lock:
            if _anthropic_sdk is None:
                import anthropic

                _anthropic_sdk = anthropic
    return _anthropic_sdk


def _openai_module() -> Any:
    global _openai_sdk
    if _openai_sdk is None:
        with _client_init_lock:
            if _openai_sdk is None:
                import openai

                _openai_sdk = openai
    return _openai_sdk


def _get_anthropic_client() -> Any:
    global _anthropic_client
    if _anthropic_client is None:
        with _client_init_lock:
            if _anthropic_client is None:
                if not config.ANTHROPIC_API_KEY:
                    raise ProviderError(
                        "No ANTHROPIC_API_KEY set. Add one to .env, then restart."
                    )
                _anthropic_client = _anthropic_module().Anthropic(
                    api_key=config.ANTHROPIC_API_KEY,
                    timeout=float(config.AI_REQUEST_TIMEOUT_S),
                    max_retries=0,
                )
    return _anthropic_client


def _request_timeout() -> Any:
    """Granular per-request timeout for the model clients.

    A flat 90s timeout meant a stale/half-open pooled connection blocked a
    turn for the full 90s -- and because turns are serialized on one lock, that
    one hang blocked EVERY following command. A single model call never
    legitimately takes tens of seconds, so we cap connect/read/pool tightly:
    a dead connection fails in seconds and the turn releases the lock, and the
    next command gets a fresh connection. The read cap stays generous enough
    for a genuinely slow provider response, but far below the old 90s.
    """
    try:
        import httpx
        read = min(30.0, float(config.AI_REQUEST_TIMEOUT_S))
        return httpx.Timeout(connect=8.0, read=read, write=15.0, pool=8.0)
    except Exception:  # noqa: BLE001 -- fall back to the flat value if httpx shape changes
        return float(config.AI_REQUEST_TIMEOUT_S)


def _http_client() -> Any:
    """A pooled HTTP client whose warm connection SURVIVES between commands.

    httpx's default keepalive_expiry is 5s, so a warmed connection was evicted
    within seconds and almost every model command paid a fresh connect (and
    occasionally a stale-connection stall). Holding the keepalive connection
    for ~2 minutes -- refreshed by warmup's periodic ping -- means back-to-back
    commands reuse ONE warm connection and stay ~1s instead of reconnecting.
    Returns None if httpx isn't shaped as expected (callers fall back to the
    plain timeout kwarg).
    """
    try:
        import httpx
        return httpx.Client(
            timeout=_request_timeout(),
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=10,
                                keepalive_expiry=120.0),
        )
    except Exception:  # noqa: BLE001
        return None


def _transport_kwargs() -> dict[str, Any]:
    """http_client (warm pool) when available, else the plain timeout kwarg."""
    hc = _http_client()
    return {"http_client": hc} if hc is not None else {"timeout": _request_timeout()}


def _get_openai_client() -> Any:
    global _openai_client
    if _openai_client is None:
        with _client_init_lock:
            if _openai_client is None:
                if not config.OPENAI_API_KEY:
                    raise ProviderError("No OPENAI_API_KEY set. Add one to .env, then restart.")
                kwargs = {"api_key": config.OPENAI_API_KEY, "max_retries": 0,
                          **_transport_kwargs()}
                if config.OPENAI_BASE_URL:
                    kwargs["base_url"] = config.OPENAI_BASE_URL
                _openai_client = _openai_module().OpenAI(**kwargs)
    return _openai_client


def _get_xai_client() -> Any:
    global _xai_client
    if _xai_client is None:
        with _client_init_lock:
            if _xai_client is None:
                if not config.XAI_API_KEY:
                    raise ProviderError("No XAI_API_KEY set. Add one to .env, then restart.")
                _xai_client = _openai_module().OpenAI(
                    api_key=config.XAI_API_KEY, base_url="https://api.x.ai/v1",
                    max_retries=0, **_transport_kwargs(),
                )
    return _xai_client


def _get_gemini_client() -> Any:
    global _gemini_client
    if _gemini_client is None:
        with _client_init_lock:
            if _gemini_client is None:
                if not config.GEMINI_API_KEY:
                    raise ProviderError("No GEMINI_API_KEY set. Add one to .env, then restart.")
                _gemini_client = _openai_module().OpenAI(
                    api_key=config.GEMINI_API_KEY,
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    max_retries=0, **_transport_kwargs(),
                )
    return _gemini_client


def _get_ollama_client() -> Any:
    global _ollama_client
    if _ollama_client is None:
        with _client_init_lock:
            if _ollama_client is None:
                # Ollama's OpenAI-compatible endpoint ignores the key -- any string works.
                _ollama_client = _openai_module().OpenAI(
                    api_key="ollama", base_url=config.OLLAMA_BASE_URL,
                    max_retries=0, **_transport_kwargs(),
                )
    return _ollama_client


# --- Anthropic ---------------------------------------------------------


def _to_anthropic_messages(history: list[dict]) -> list[dict]:
    messages: list[dict] = []
    pending_results: list[dict] = []

    def flush() -> None:
        nonlocal pending_results
        if pending_results:
            messages.append({"role": "user", "content": pending_results})
            pending_results = []

    for turn in history:
        if turn["role"] == "tool_result":
            pending_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": turn["tool_call_id"],
                    "content": turn["content"],
                }
            )
            continue
        flush()
        if turn["role"] == "user":
            messages.append({"role": "user", "content": turn["content"]})
        elif turn["role"] == "assistant":
            blocks: list[dict] = []
            if turn.get("content"):
                blocks.append({"type": "text", "text": turn["content"]})
            for tc in turn.get("tool_calls", []):
                blocks.append(
                    {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]}
                )
            messages.append({"role": "assistant", "content": blocks})
    flush()
    return messages


def _run_anthropic(
    history: list[dict], system: str, tools: list[dict], on_text: OnText | None
) -> AgentTurn:
    sdk = _anthropic_module()
    client = _get_anthropic_client()
    kwargs: dict[str, Any] = dict(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1024,
        # Cached block (personality, rarely changes) + uncached block (the
        # tonal checkpoint, reinforced fresh every turn) -- see personality.py.
        system=[
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": personality.TONAL_CHECKPOINT},
        ],
        messages=_to_anthropic_messages(history),
    )
    if tools:
        kwargs["tools"] = [
            {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
            for t in tools
        ]
    try:
        text_parts: list[str] = []
        with client.messages.stream(**kwargs) as stream:
            for delta in stream.text_stream:
                text_parts.append(delta)
                if on_text:
                    on_text(delta)
            final = stream.get_final_message()
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=b.input)
            for b in final.content
            if b.type == "tool_use"
        ]
        return AgentTurn(text="".join(text_parts), tool_calls=tool_calls)
    except sdk.AuthenticationError as exc:
        raise ProviderError(
            "That ANTHROPIC_API_KEY was rejected. Check it in .env."
        ) from exc
    except sdk.RateLimitError as exc:
        raise ProviderError("Rate limited -- give it a moment and try again.", retryable=True) from exc
    except sdk.APIConnectionError as exc:
        raise ProviderError(
            "Couldn't reach the model provider. Check your connection.", retryable=True
        ) from exc
    except sdk.APIStatusError as exc:
        raise ProviderError(f"Model provider returned an error: {exc.message}") from exc


# --- OpenAI-compatible (xAI, Gemini) ------------------------------------


def _to_openai_messages(history: list[dict], system: str) -> list[dict]:
    # No cache_control equivalent in this wire format -- both blocks just
    # get concatenated every call.
    messages: list[dict] = [
        {"role": "system", "content": f"{system}\n{personality.TONAL_CHECKPOINT}"}
    ]
    for turn in history:
        if turn["role"] == "user":
            messages.append({"role": "user", "content": turn["content"]})
        elif turn["role"] == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": turn.get("content") or None}
            if turn.get("tool_calls"):
                msg["tool_calls"] = []
                for tc in turn["tool_calls"]:
                    call = {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["input"])},
                    }
                    if tc.get("extra"):
                        # Must round-trip verbatim -- e.g. Gemini's
                        # thought_signature, or the next call gets rejected.
                        call["extra_content"] = tc["extra"]
                    msg["tool_calls"].append(call)
            messages.append(msg)
        elif turn["role"] == "tool_result":
            messages.append(
                {"role": "tool", "tool_call_id": turn["tool_call_id"], "content": turn["content"]}
            )
    return messages


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _run_openai_compatible(
    client: Any,
    model: str,
    history: list[dict],
    system: str,
    tools: list[dict],
    on_text: OnText | None,
) -> AgentTurn:
    kwargs: dict[str, Any] = dict(
        model=model,
        messages=_to_openai_messages(history, system),
        stream=True,
        # High enough that a tool call carrying real file contents can
        # finish. See config.MAX_OUTPUT_TOKENS for why 600 was actively
        # harmful rather than merely conservative.
        max_tokens=config.MAX_OUTPUT_TOKENS,
    )
    if tools:
        kwargs["tools"] = _to_openai_tools(tools)

    text_parts: list[str] = []
    tool_accum: dict[int, dict] = {}
    _current_key = 0  # slot cursor for providers that send index=None (Gemini)
    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            text_parts.append(delta.content)
            if on_text:
                on_text(delta.content)
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                # Gemini sends index=None on EVERY delta (xAI/OpenAI number
                # them 0, 1, 2...). The old fallback of always using slot 0
                # merged every simultaneous call into one: two delegate
                # calls concatenated their JSON arguments into
                # '{...}{...}', which fails to parse and collapsed to an
                # empty {} -- i.e. parallel delegation silently never
                # worked on Gemini. Root-caused 2026-08-04 after repeatedly
                # seeing `delegate` fire with empty input.
                #
                # Fix: with no index to trust, a delta carrying a NEW id
                # (or a different function name) marks the start of the
                # next call rather than more of the current one.
                if tc_delta.index is not None:
                    key = tc_delta.index
                else:
                    key = _current_key
                    cur = tool_accum.get(key)
                    new_id = tc_delta.id and cur and cur["id"] and cur["id"] != tc_delta.id
                    new_name = (
                        tc_delta.function
                        and tc_delta.function.name
                        and cur
                        and cur["name"]
                        and cur["name"] != tc_delta.function.name
                    )
                    if new_id or new_name:
                        _current_key += 1
                        key = _current_key
                slot = tool_accum.setdefault(
                    key, {"id": None, "name": None, "arguments": "", "extra": None}
                )
                if tc_delta.id:
                    slot["id"] = tc_delta.id
                if tc_delta.function and tc_delta.function.name:
                    slot["name"] = tc_delta.function.name
                if tc_delta.function and tc_delta.function.arguments:
                    slot["arguments"] += tc_delta.function.arguments
                extra = getattr(tc_delta, "extra_content", None)
                if extra:
                    slot["extra"] = extra

    tool_calls = []
    for i, slot in sorted(tool_accum.items()):
        try:
            tool_input = json.loads(slot["arguments"] or "{}")
        except json.JSONDecodeError:
            # Almost always a call cut off at the output limit mid-JSON.
            # Collapsing it to {} silently turned "write these six files"
            # into a no-op the model then had to explain away. Marked
            # instead, so run_tool can tell it exactly what went wrong and
            # it can retry with fewer files per call.
            tool_input = {"__truncated_arguments__": len(slot["arguments"] or "")}
        tool_calls.append(
            ToolCall(
                id=slot["id"] or f"call_{i}",
                name=slot["name"],
                input=tool_input,
                extra=slot["extra"],
            )
        )

    return AgentTurn(text="".join(text_parts), tool_calls=tool_calls)


def _run_xai(
    history: list[dict], system: str, tools: list[dict], on_text: OnText | None
) -> AgentTurn:
    sdk = _openai_module()
    try:
        return _run_openai_compatible(
            _get_xai_client(), config.XAI_MODEL, history, system, tools, on_text
        )
    except sdk.AuthenticationError as exc:
        raise ProviderError(
            "That XAI_API_KEY was rejected by api.x.ai. Check it in .env -- "
            "it may be a key for a different provider."
        ) from exc
    except sdk.RateLimitError as exc:
        raise ProviderError("Rate limited -- give it a moment and try again.", retryable=True) from exc
    except sdk.APIConnectionError as exc:
        raise ProviderError(
            "Couldn't reach the model provider. Check your connection.", retryable=True
        ) from exc
    except sdk.NotFoundError as exc:
        raise ProviderError(
            f"Model '{config.XAI_MODEL}' not found. Check XAI_MODEL in .env."
        ) from exc
    except sdk.APIStatusError as exc:
        raise ProviderError(f"Model provider returned an error: {exc.message}") from exc


def _run_openai(
    history: list[dict], system: str, tools: list[dict], on_text: OnText | None
) -> AgentTurn:
    sdk = _openai_module()
    try:
        return _run_openai_compatible(
            _get_openai_client(), config.OPENAI_MODEL, history, system, tools, on_text
        )
    except sdk.AuthenticationError as exc:
        raise ProviderError("That OPENAI_API_KEY was rejected. Check it in .env.") from exc
    except sdk.RateLimitError as exc:
        raise ProviderError("OpenAI rate limited the request; falling back.", retryable=True) from exc
    except sdk.APIConnectionError as exc:
        raise ProviderError("Couldn't reach OpenAI. Check your connection.", retryable=True) from exc
    except sdk.NotFoundError as exc:
        raise ProviderError(f"Model '{config.OPENAI_MODEL}' was not found.") from exc
    except sdk.APIStatusError as exc:
        raise ProviderError(f"OpenAI returned an error: {exc.message}") from exc


def _run_gemini(
    history: list[dict], system: str, tools: list[dict], on_text: OnText | None
) -> AgentTurn:
    sdk = _openai_module()
    try:
        return _run_openai_compatible(
            _get_gemini_client(), config.GEMINI_MODEL, history, system, tools, on_text
        )
    except sdk.AuthenticationError as exc:
        raise ProviderError(
            "That GEMINI_API_KEY was rejected. Check it in .env."
        ) from exc
    except sdk.RateLimitError as exc:
        raise ProviderError("Rate limited -- give it a moment and try again.", retryable=True) from exc
    except sdk.APIConnectionError as exc:
        raise ProviderError(
            "Couldn't reach the model provider. Check your connection.", retryable=True
        ) from exc
    except sdk.NotFoundError as exc:
        raise ProviderError(
            f"Model '{config.GEMINI_MODEL}' not found. Check GEMINI_MODEL in .env."
        ) from exc
    except sdk.APIStatusError as exc:
        raise ProviderError(f"Model provider returned an error: {exc.message}") from exc


def _run_ollama(
    history: list[dict], system: str, tools: list[dict], on_text: OnText | None
) -> AgentTurn:
    sdk = _openai_module()
    try:
        return _run_openai_compatible(
            _get_ollama_client(), config.OLLAMA_MODEL, history, system, tools, on_text
        )
    except sdk.APIConnectionError as exc:
        raise ProviderError(
            "Couldn't reach Ollama. Is it running? (`ollama serve`)", retryable=True
        ) from exc
    except sdk.NotFoundError as exc:
        raise ProviderError(
            f"Model '{config.OLLAMA_MODEL}' not found locally. "
            f"Run `ollama pull {config.OLLAMA_MODEL}` first."
        ) from exc
    except sdk.APIStatusError as exc:
        raise ProviderError(f"Ollama returned an error: {exc.message}") from exc


_RUNNERS = {
    "anthropic": _run_anthropic,
    "openai": _run_openai,
    "xai": _run_xai,
    "gemini": _run_gemini,
    "ollama": _run_ollama,
}
# Immutable identity map for durable health evidence. Tests and controlled
# adapters may replace entries in ``_RUNNERS``; those injected callables are
# useful for fault isolation but must never poison the real provider-health
# database or make a mock success ONLINE.
_PRODUCTION_RUNNERS = dict(_RUNNERS)


def warm() -> dict[str, bool]:
    """Pre-import the provider SDK and build the configured clients up front.

    The OpenAI SDK is imported lazily on the first turn (see ``_openai_module``)
    and reading the whole package off disk costs seconds. That import used to
    happen INSIDE the first conversation turn, which holds the global turn lock
    -- so every other turn and HTTP request queued behind a one-off disk read,
    and the server looked frozen for its first ~20-40s of real use. Doing it
    here, once, on a background thread that never touches the turn lock, removes
    that stall.

    Network-free: it constructs clients but sends no request, so it cannot fail
    on a flaky connection and cannot be mistaken for provider health. A missing
    key simply skips that provider."""
    warmed: dict[str, bool] = {}
    # One import backs openai, xai, gemini and ollama; it is the expensive step.
    try:
        _openai_module()
        warmed["openai_sdk"] = True
    except Exception:  # noqa: BLE001 -- warming must never raise into boot
        warmed["openai_sdk"] = False
    for name, getter in (
        ("gemini", _get_gemini_client), ("xai", _get_xai_client),
        ("openai", _get_openai_client), ("ollama", _get_ollama_client),
    ):
        try:
            getter()
            warmed[name] = True
        except Exception:  # noqa: BLE001 -- unconfigured provider, skip quietly
            warmed[name] = False
    try:
        if config.ANTHROPIC_API_KEY:
            _get_anthropic_client()
            warmed["anthropic"] = True
    except Exception:  # noqa: BLE001
        warmed["anthropic"] = False
    return warmed


def run_turn(
    history: list[dict],
    system: str = config.SYSTEM_PROMPT,
    tools: list[dict] | None = None,
    on_text: OnText | None = None,
    cancel_check: Callable[[], None] | None = None,
    task_kind: str = "",
) -> AgentTurn:
    """Send the conversation (+ optional tool definitions), get back one turn.

    Streams text through `on_text` as it's generated. If the model asks to
    use a tool, `AgentTurn.tool_calls` is populated and `.text` may be
    empty -- the caller (the agent core) decides what happens next.

    "Serious mode" reliability, per the user's 2026-07-23 ask (see
    AGENT.md): retries automatically, with backoff, on rate limits and
    connection hiccups (`ProviderError.retryable`) -- up to
    `_MAX_RETRY_ATTEMPTS` -- rather than surfacing the first transient
    blip as a failure. Only retries before any text has actually reached
    the caller, though: once a token has streamed to `on_text`, a retry
    would duplicate output, so a failure past that point still raises
    immediately. Non-retryable errors (bad key, bad input, unknown
    provider) raise on the first attempt, same as before -- retrying those
    would just fail the same way three times instead of once.

    CROSS-PROVIDER FALLBACK (added 2026-08-07)
    ------------------------------------------
    This used to retry `config.MODEL_PROVIDER` three times and then give
    up, while `model_router` computed a perfectly good fallback chain that
    nothing ever read. So one provider outage took ZENO down even with two
    other working API keys configured. Now the chain is walked: each
    provider gets its retry budget for transient errors, and a provider
    that is genuinely down (bad key, model gone, breaker open) is skipped
    so the next one answers.

    `task_kind` comes from cognition.Route.model_kind, so a coding question
    can prefer a different provider from a research one -- when more than
    one is configured. With a single key the chain has one entry and this
    is a no-op, which `model_router.explain()` states plainly.
    """
    from reyes_agent import model_router

    chain = [p for p in model_router.chain_for(task_kind or "general") if p in _RUNNERS]
    if not chain:
        raise ProviderError(
            f"Unknown MODEL_PROVIDER '{config.MODEL_PROVIDER}'. "
            f"Valid options: {', '.join(_RUNNERS)}."
        )
    # API-bound copy only -- neither the windowing nor the voice cue ever
    # touch stored history, so nothing here is lossy for the caller.
    api_history = personality.append_voice_cue(_windowed(history))

    last_exc: ProviderError | None = None
    emitted = False   # once ANY token reached the caller, switching would duplicate it

    for provider in chain:
        runner = _RUNNERS[provider]
        is_production_runner = runner is _PRODUCTION_RUNNERS.get(provider)
        for attempt in range(_MAX_RETRY_ATTEMPTS):
            if cancel_check:
                cancel_check()

            def _tracking_on_text(chunk: str) -> None:
                nonlocal emitted
                if cancel_check:
                    cancel_check()
                emitted = True
                if on_text:
                    on_text(chunk)

            _t0 = time.time()
            try:
                _result = runner(api_history, system, tools or [], _tracking_on_text)
                # Real measured latency feeds the Model Router's health/metrics.
                # Never estimated -- see model_router.py.
                try:
                    model_router.record(provider, time.time() - _t0, ok=True,
                                        validated_runtime=is_production_runner)
                except Exception:  # noqa: BLE001 -- telemetry must not break a turn
                    pass
                return _result
            except ProviderError as exc:
                try:
                    model_router.record(provider, time.time() - _t0, ok=False,
                                        error=str(exc), validated_runtime=is_production_runner)
                except Exception:  # noqa: BLE001
                    pass
                last_exc = exc
                # Text already streamed to the user. Neither retrying nor
                # failing over is safe now -- both would repeat output.
                if emitted:
                    raise
                if not exc.retryable:
                    break          # this provider is genuinely down: next one
                if attempt == _MAX_RETRY_ATTEMPTS - 1:
                    break          # transient budget spent: next one
                delay = _RETRY_BASE_DELAY_S * (2**attempt)
                # Backoff must not keep a cancelled request alive. Use short waits
                # only here (not a polling worker loop) so cancellation is prompt.
                while delay > 0:
                    if cancel_check:
                        cancel_check()
                    slice_s = min(0.1, delay)
                    time.sleep(slice_s)
                    delay -= slice_s

    # Every provider in the chain failed. Name them, so "ZENO is down" is
    # never mistaken for "the network hiccuped".
    if last_exc is None:  # pragma: no cover -- chain is never empty here
        raise ProviderError("No model provider was available.")
    raise ProviderError(
        f"Every configured model provider failed ({', '.join(chain)}). "
        f"Last error: {last_exc}",
        retryable=last_exc.retryable,
    ) from last_exc
