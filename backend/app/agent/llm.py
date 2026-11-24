"""The model call layer — Phase 3, increment 1.

Two things this file exists to work around, both found while verifying the
project against CLAUDE.md rather than assumed:

1. The configured model slug (`PORTKEY_MODEL`) is currently rejected by the
   gateway with a 412 `model_not_allowed_error` (see
   `backend/scripts/probe_gateway.py`). That's an allow-list problem on the
   Portkey integration's side, not a code bug — `call_model` fails legibly
   with `LLMConfigError` rather than a raw SDK traceback, and nothing here
   guesses at alternate model slugs. If you're seeing that error, the fix is
   getting the right slug allow-listed, not editing this file.

2. Because every probe above died on the model check, there is no evidence
   either way about whether this gateway forwards `thinking`,
   `output_config.effort`, `cache_control`, or the beta `betas`/`fallbacks`
   params CLAUDE.md's "Model call shape" documents. `call_model` therefore
   builds that full shape but degrades gracefully — strips and retries a
   param the gateway names in a rejection, logs it, and remembers the
   degradation for the rest of the process so it isn't rediscovered on every
   call.

Note `betas` and `fallbacks` only exist on `client.beta.messages.create`, not
`client.messages.create`, in the installed `anthropic==1.6.0` SDK (checked by
inspecting the actual method signatures) — CLAUDE.md's snippet shows them on
the stable method, which does not have them. This calls the beta method.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import anthropic

from app.config import get_settings

logger = logging.getLogger("app.agent.llm")

# Optional call-shape enhancements. If the gateway rejects one of these by
# name, call_model drops it and retries rather than failing the whole call.
FEATURE_PARAMS = ("thinking", "output_config", "betas", "fallbacks", "cache_control")

_degraded: set[str] = set()
"""Params this gateway has already rejected once, for this process's
lifetime. A gateway's capabilities don't change mid-process, so there's no
reason to rediscover the same rejection on every single call."""

_MODEL_ERROR_MARKERS = ("model_not_allowed", "not allowed", "model not found", "does not exist")


class LLMConfigError(RuntimeError):
    """The model or gateway itself is unusable — wrong slug, no key, an
    allow-list rejection. Unlike a single unsupported optional param, there's
    nothing to strip and retry around; the caller should surface this as
    "the assistant isn't available", not crash."""


@dataclass
class LLMResult:
    text: str
    tool_calls: list[dict[str, Any]]
    content_blocks: list[dict[str, Any]]
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    raw: Any


@dataclass
class ParsedLLMResult:
    parsed: Any
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    raw: Any


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.llm_configured:
            raise LLMConfigError(
                "No LLM gateway configured — set PORTKEY_API_KEY / PORTKEY_BASE_URL / "
                "PORTKEY_MODEL (or ANTHROPIC_API_KEY for a direct deployment) in backend/.env."
            )
        _client = anthropic.Anthropic(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            default_headers=settings.llm_default_headers,
            max_retries=1,
            timeout=120.0,
        )
    return _client


def _is_model_error(exc: anthropic.APIStatusError) -> bool:
    body = str(exc).lower()
    return any(marker in body for marker in _MODEL_ERROR_MARKERS)


_PARAM_ALIASES = {
    # A gateway rejects the wire-level header/field name, not the SDK kwarg
    # that produced it — e.g. Bedrock's "Unexpected value(s) ... for the
    # `anthropic-beta` header" never contains the literal substring "betas".
    "anthropic-beta": "betas",
}


def _unsupported_param(exc: anthropic.APIStatusError) -> str | None:
    """Which of FEATURE_PARAMS, if any, this rejection is complaining about."""
    body = str(exc).lower()
    for name in FEATURE_PARAMS:
        if name in body:
            return name
    for alias, name in _PARAM_ALIASES.items():
        if alias in body:
            return name
    return None


def _build_kwargs(
    *,
    model: str,
    messages: list[dict[str, Any]],
    system: list[dict[str, Any]] | str,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    effort: str,
    thinking: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "system": system,
    }
    if tools:
        kwargs["tools"] = tools
    if thinking and "thinking" not in _degraded:
        kwargs["thinking"] = {"type": "adaptive"}
    if "output_config" not in _degraded:
        kwargs["output_config"] = {"effort": effort}
    if "betas" not in _degraded and "fallbacks" not in _degraded:
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
    return kwargs


def _clean_content_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip SDK-internal / gateway-rejected extra fields from content blocks.

    Some gateways (Vertex AI) reject content blocks that carry extra fields the
    Anthropic API added in newer SDK versions (e.g. `toolset_name` on tool_use
    blocks). Keeping only the well-known wire fields prevents 400s on the second
    and subsequent turns of a tool-use conversation.
    """
    out: list[dict[str, Any]] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "tool_use":
            out.append({k: block[k] for k in ("type", "id", "name", "input") if k in block})
        elif btype == "text":
            out.append({k: block[k] for k in ("type", "text") if k in block})
        elif btype in ("thinking", "redacted_thinking"):
            # signature is required by the API when this block is passed back in a later turn
            out.append({k: block[k] for k in ("type", "thinking", "data", "signature") if k in block})
        else:
            out.append(block)
    return out


def _normalize_tool_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize messages list for Anthropic/Vertex AI wire format compatibility.

    Two transformations:

    1. role='tool' → tool_result content block
       The graph stores tool results as {"role": "tool", "tool_use_id": ...,
       "content": ...} (convenient for accumulation). The Anthropic API and the
       Vertex AI gateway only accept {"role": "user", "content": [{"type":
       "tool_result", ...}]}. Consecutive tool messages are merged into one user
       message so the transcript stays valid.

    2. Trailing assistant message → append synthetic user turn
       Vertex AI rejects "assistant message prefill" (a conversation whose last
       message is an assistant turn). This happens in the multi-agent loop when
       the supervisor is called again after a worker has responded. A lightweight
       continuation message fixes it without changing graph semantics.
    """
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "tool":
            blocks: list[dict[str, Any]] = []
            while i < len(messages) and messages[i].get("role") == "tool":
                t = messages[i]
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": t["tool_use_id"],
                    "content": t["content"],
                })
                i += 1
            out.append({"role": "user", "content": blocks})
        else:
            out.append(msg)
            i += 1

    if out and out[-1].get("role") == "assistant":
        out.append({"role": "user", "content": "Continue."})

    return out


def call_model(
    *,
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 16000,
    effort: str = "high",
    thinking: bool = True,
) -> LLMResult:
    """One model turn. `messages` and the return's `tool_calls` are plain
    Anthropic-wire-format dicts — see app/agent/state.py for why this build
    doesn't use LangChain message objects.
    """
    messages = _normalize_tool_messages(messages)
    settings = get_settings()
    client = get_client()
    model = settings.llm_model
    if not model:
        raise LLMConfigError("No model slug configured (PORTKEY_MODEL / ANTHROPIC_MODEL).")

    # Cache breakpoint on the system prompt — CLAUDE.md's documented order is
    # tools -> system -> messages, stable prefix first. Content-block-level
    # cache_control, not the top-level convenience field, so the breakpoint
    # sits exactly at the end of the stable prefix.
    system_param: list[dict[str, Any]] | str
    if "cache_control" in _degraded:
        system_param = system
    else:
        system_param = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    attempts_left = len(FEATURE_PARAMS) + 1
    while True:
        kwargs = _build_kwargs(
            model=model,
            messages=messages,
            system=system_param,
            tools=tools,
            max_tokens=max_tokens,
            effort=effort,
            thinking=thinking,
        )
        try:
            response = client.beta.messages.create(**kwargs)
            break
        except anthropic.APIStatusError as exc:
            if _is_model_error(exc):
                raise LLMConfigError(
                    f"Gateway rejected model {model!r}: {exc}. This is an allow-list "
                    "issue on the gateway's side, not a code bug — see CLAUDE.md's "
                    "open questions, or ask whoever administers the Portkey integration."
                ) from exc

            dropped = _unsupported_param(exc)
            if dropped is None or dropped in _degraded or attempts_left <= 0:
                raise

            _degraded.add(dropped)
            logger.warning("LLM gateway rejected %r — dropping it for this process: %s", dropped, exc)
            if dropped == "cache_control":
                system_param = system
            attempts_left -= 1
            continue

    text = "".join(block.text for block in response.content if block.type == "text")
    tool_calls = [
        {"id": block.id, "name": block.name, "input": block.input}
        for block in response.content
        if block.type == "tool_use"
    ]
    # Serialize every content block verbatim (text, tool_use, thinking,
    # redacted_thinking, ...) rather than just `text` — this is what gets
    # appended back into `state["messages"]` as the assistant turn. Dropping
    # tool_use blocks there would mean the next call sees an assistant message
    # with no record of the tool call that produced the tool_result that
    # follows it, which the Messages API rejects outright.
    content_blocks = _clean_content_blocks([block.model_dump(mode="json") for block in response.content])
    usage = response.usage
    return LLMResult(
        text=text,
        tool_calls=tool_calls,
        content_blocks=content_blocks,
        stop_reason=response.stop_reason,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        raw=response,
    )


def _call_structured_fallback(
    *,
    messages: list[dict[str, Any]],
    system: str,
    output_format: type,
    max_tokens: int,
    effort: str,
    thinking: bool,
) -> ParsedLLMResult:
    """JSON-prompt fallback when the gateway doesn't support json_schema structured output.

    Injects the Pydantic schema into the system prompt and asks the model to
    reply with raw JSON. Strips markdown code fences if the model wraps the
    output, then validates with Pydantic.
    """
    import json
    import re

    schema = output_format.model_json_schema()
    augmented_system = (
        system
        + "\n\nRespond with ONLY valid JSON that matches this exact schema "
        "(no markdown, no code fences, no prose — just the JSON object):\n"
        + json.dumps(schema, indent=2)
    )

    result = call_model(
        messages=messages,
        system=augmented_system,
        max_tokens=max_tokens,
        effort=effort,
        thinking=thinking,
    )

    text = result.text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()

    parsed = output_format.model_validate_json(text)
    return ParsedLLMResult(
        parsed=parsed,
        stop_reason=result.stop_reason,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read_tokens=result.cache_read_tokens,
        raw=result.raw,
    )


def call_structured(
    *,
    messages: list[dict[str, Any]],
    system: str,
    output_format: type,
    max_tokens: int = 8000,
    effort: str = "high",
    thinking: bool = True,
) -> ParsedLLMResult:
    """A one-shot structured analysis call — used by the four analysis tools
    in tools/drafts.py.

    Tries client.beta.messages.parse() first. If the gateway returns an empty
    body (json_schema not supported), falls back to _call_structured_fallback()
    which injects the schema into the system prompt and parses the text reply.
    """
    import json as _json

    messages = _normalize_tool_messages(messages)

    # If we already know json_schema is unsupported, skip straight to fallback.
    if "json_schema" in _degraded:
        return _call_structured_fallback(
            messages=messages, system=system, output_format=output_format,
            max_tokens=max_tokens, effort=effort, thinking=thinking,
        )

    settings = get_settings()
    client = get_client()
    model = settings.llm_model
    if not model:
        raise LLMConfigError("No model slug configured (PORTKEY_MODEL / ANTHROPIC_MODEL).")

    system_param: list[dict[str, Any]] | str
    if "cache_control" in _degraded:
        system_param = system
    else:
        system_param = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

    attempts_left = len(FEATURE_PARAMS) + 1
    while True:
        kwargs = _build_kwargs(
            model=model,
            messages=messages,
            system=system_param,
            tools=None,
            max_tokens=max_tokens,
            effort=effort,
            thinking=thinking,
        )
        kwargs["output_format"] = output_format
        try:
            response = client.beta.messages.parse(**kwargs)
            # Some gateways return 200 but with an empty body — detect that.
            if response.parsed is None:
                raise ValueError("Gateway returned empty structured output (json_schema unsupported)")
            break
        except (ValueError, _json.JSONDecodeError) as exc:
            # Gateway doesn't support json_schema — remember and use fallback.
            _degraded.add("json_schema")
            logger.warning("json_schema structured output not supported by gateway — switching to JSON-prompt fallback: %s", exc)
            return _call_structured_fallback(
                messages=messages, system=system, output_format=output_format,
                max_tokens=max_tokens, effort=effort, thinking=thinking,
            )
        except anthropic.APIStatusError as exc:
            if _is_model_error(exc):
                raise LLMConfigError(
                    f"Gateway rejected model {model!r}: {exc}. This is an allow-list "
                    "issue on the gateway's side, not a code bug."
                ) from exc

            dropped = _unsupported_param(exc)
            if dropped is None or dropped in _degraded or attempts_left <= 0:
                raise

            _degraded.add(dropped)
            logger.warning("LLM gateway rejected %r — dropping it for this process: %s", dropped, exc)
            if dropped == "cache_control":
                system_param = system
            attempts_left -= 1
            continue

    usage = response.usage
    return ParsedLLMResult(
        parsed=response.parsed,
        stop_reason=response.stop_reason,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        raw=response,
    )
