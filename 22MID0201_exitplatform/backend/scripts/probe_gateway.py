"""
Find out what the LLM gateway actually forwards.

Gateways silently drop parameters they do not understand. A dropped `effort` or
`cache_control` does not error — the call succeeds and the output is quietly
worse. That is an expensive bug to find in Phase 6, so find it now.

Each probe is a small, cheap call. Total cost of a full run: a few cents.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")

# The SDK appends /v1/messages itself, so a base_url ending in /v1 produces
# /v1/v1/messages and a 404. Strip it. (discover_gateway.py established this.)
BASE_URL = os.environ.get("PORTKEY_BASE_URL", "").rstrip("/").removesuffix("/v1")
API_KEY = os.environ.get("PORTKEY_API_KEY", "")
MODEL = os.environ.get("PORTKEY_MODEL", "")

results: list[tuple[str, bool, str]] = []


def probe(label: str):
    def wrap(fn):
        try:
            note = fn()
            results.append((label, True, note or ""))
            print(f"  OK    {label}" + (f"  — {note}" if note else ""))
        except Exception as exc:
            detail = str(exc).replace("\n", " ")[:160]
            results.append((label, False, detail))
            print(f"  FAIL  {label}\n        {detail}")
        return fn

    return wrap


def client() -> anthropic.Anthropic:
    # The gateway speaks the Anthropic wire format, so the official SDK works
    # with a base_url swap. Auth must be x-portkey-api-key — the gateway
    # rejects Anthropic's native x-api-key with a 401.
    return anthropic.Anthropic(
        api_key="unused",  # the SDK requires a value; the gateway ignores it
        base_url=BASE_URL,
        default_headers={"x-portkey-api-key": API_KEY},
        max_retries=1,
        timeout=120.0,
    )


def main() -> int:
    if not (BASE_URL and API_KEY and MODEL):
        print("PORTKEY_BASE_URL / PORTKEY_API_KEY / PORTKEY_MODEL not set in backend/.env")
        return 1

    print(f"Gateway : {BASE_URL}")
    print(f"Model   : {MODEL}\n")

    c = client()
    hello = [{"role": "user", "content": "Reply with exactly: pong"}]

    @probe("basic completion")
    def _basic():
        r = c.messages.create(model=MODEL, max_tokens=16, messages=hello)
        text = "".join(b.text for b in r.content if b.type == "text").strip()
        return f"returned {text!r}, {r.usage.input_tokens}in/{r.usage.output_tokens}out"

    @probe("system prompt")
    def _system():
        r = c.messages.create(
            model=MODEL,
            max_tokens=16,
            system="You always answer in exactly one word.",
            messages=[{"role": "user", "content": "Name a colour."}],
        )
        return "".join(b.text for b in r.content if b.type == "text").strip()[:40]

    @probe("adaptive thinking")
    def _thinking():
        r = c.messages.create(
            model=MODEL,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": "What is 17 * 23? Answer with the number only."}],
        )
        kinds = {b.type for b in r.content}
        return f"blocks={sorted(kinds)}"

    @probe("output_config.effort")
    def _effort():
        r = c.messages.create(
            model=MODEL,
            max_tokens=64,
            output_config={"effort": "low"},
            messages=hello,
        )
        return f"accepted, {r.usage.output_tokens} output tokens"

    @probe("prompt caching (cache_control)")
    def _caching():
        big = "You are an assistant for an HR exit process platform. " * 220
        r = c.messages.create(
            model=MODEL,
            max_tokens=16,
            system=[{"type": "text", "text": big, "cache_control": {"type": "ephemeral"}}],
            messages=hello,
        )
        usage = r.usage
        created = getattr(usage, "cache_creation_input_tokens", None)
        read = getattr(usage, "cache_read_input_tokens", None)
        if created is None and read is None:
            raise RuntimeError("no cache fields in usage — gateway stripped cache_control")
        return f"cache_creation={created} cache_read={read}"

    @probe("tool use")
    def _tools():
        r = c.messages.create(
            model=MODEL,
            max_tokens=256,
            tools=[
                {
                    "name": "get_exit_case",
                    "description": "Fetch an exit case by id.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"case_id": {"type": "string"}},
                        "required": ["case_id"],
                    },
                }
            ],
            messages=[{"role": "user", "content": "Look up exit case abc-123."}],
        )
        calls = [b for b in r.content if b.type == "tool_use"]
        if not calls:
            raise RuntimeError(f"no tool_use block; stop_reason={r.stop_reason}")
        return f"called {calls[0].name}({calls[0].input})"

    @probe("structured output (json_schema)")
    def _structured():
        r = c.messages.create(
            model=MODEL,
            max_tokens=256,
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "risk_score": {"type": "integer"},
                            "reason": {"type": "string"},
                        },
                        "required": ["risk_score", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
            messages=[
                {
                    "role": "user",
                    "content": "A senior engineer with 5 years tenure is leaving. Score exit risk 0-100.",
                }
            ],
        )
        import json

        text = next(b.text for b in r.content if b.type == "text")
        parsed = json.loads(text)
        return f"parsed risk_score={parsed['risk_score']}"

    @probe("streaming")
    def _streaming():
        chunks = 0
        with c.messages.stream(
            model=MODEL,
            max_tokens=64,
            messages=[{"role": "user", "content": "Count from 1 to 5."}],
        ) as stream:
            for _ in stream.text_stream:
                chunks += 1
            stream.get_final_message()
        return f"{chunks} text chunks"

    ok = sum(1 for _, passed, _ in results if passed)
    print(f"\n{ok}/{len(results)} features available through this gateway")

    failed = [label for label, passed, _ in results if not passed]
    if failed:
        print("\nNot available — the agent must work without these:")
        for label in failed:
            print(f"  - {label}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
