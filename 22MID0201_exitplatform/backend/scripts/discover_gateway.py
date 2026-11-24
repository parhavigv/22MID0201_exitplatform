"""
Find the gateway's real endpoint and auth shape.

Tries the plausible combinations of path, wire format, and auth header, and
reports which one answers. Run this before probe_gateway.py when the gateway
is unfamiliar.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")

RAW_BASE = os.environ.get("PORTKEY_BASE_URL", "").rstrip("/")
API_KEY = os.environ.get("PORTKEY_API_KEY", "")
MODEL = os.environ.get("PORTKEY_MODEL", "")

# base_url with and without the /v1 the SDK adds itself
BASES = [RAW_BASE, RAW_BASE.removesuffix("/v1")]

PATHS_ANTHROPIC = ["/v1/messages", "/messages"]
PATHS_OPENAI = ["/v1/chat/completions", "/chat/completions"]

AUTH_VARIANTS = {
    "x-portkey-api-key": {"x-portkey-api-key": API_KEY},
    "x-api-key": {"x-api-key": API_KEY},
    "Authorization: Bearer": {"Authorization": f"Bearer {API_KEY}"},
    "both portkey+anthropic": {
        "x-portkey-api-key": API_KEY,
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
    },
}

ANTHROPIC_BODY = {
    "model": MODEL,
    "max_tokens": 16,
    "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
}

OPENAI_BODY = {
    "model": MODEL,
    "max_tokens": 16,
    "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
}


def summarise(res: httpx.Response) -> str:
    body = res.text.strip()
    if body.startswith("<"):
        return "HTML error page"
    try:
        data = res.json()
    except Exception:
        return body[:120]
    if "error" in data:
        err = data["error"]
        return str(err.get("message", err))[:140] if isinstance(err, dict) else str(err)[:140]
    if "content" in data:  # Anthropic shape
        text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        return f"ANTHROPIC OK -> {text.strip()!r}"
    if "choices" in data:  # OpenAI shape
        return f"OPENAI OK -> {data['choices'][0]['message']['content'].strip()!r}"
    return json.dumps(data)[:140]


def main() -> int:
    if not (RAW_BASE and API_KEY and MODEL):
        print("Portkey settings missing from backend/.env")
        return 1

    print(f"Base from .env : {RAW_BASE}")
    print(f"Model          : {MODEL}\n")

    winners = []

    with httpx.Client(timeout=45) as client:
        for base in dict.fromkeys(BASES):  # dedupe, keep order
            for wire, paths, body in (
                ("anthropic", PATHS_ANTHROPIC, ANTHROPIC_BODY),
                ("openai", PATHS_OPENAI, OPENAI_BODY),
            ):
                for path in paths:
                    url = f"{base}{path}"
                    for auth_name, headers in AUTH_VARIANTS.items():
                        try:
                            res = client.post(
                                url,
                                headers={"Content-Type": "application/json", **headers},
                                json=body,
                            )
                        except Exception as exc:
                            print(f"  {url}  [{auth_name}]  -> connection error: {exc}")
                            continue

                        note = summarise(res)
                        flag = "OK  " if res.status_code == 200 else f"{res.status_code:<4}"
                        # Only print the interesting ones; 404s are noise.
                        if res.status_code != 404:
                            print(f"  {flag} {wire:9} {path:22} [{auth_name:22}] {note}")
                        if res.status_code == 200:
                            winners.append((base, wire, path, auth_name))

    print()
    if winners:
        base, wire, path, auth = winners[0]
        print("WORKING COMBINATION")
        print(f"  base_url   {base}")
        print(f"  path       {path}")
        print(f"  wire       {wire}")
        print(f"  auth       {auth}")
        if wire == "anthropic" and path == "/v1/messages":
            print(f"\n  For the Anthropic SDK, pass base_url={base!r}")
            print("  (the SDK appends /v1/messages itself)")
    else:
        print("Nothing answered with 200.")
        print("Likely causes: the key is not valid for this gateway, the model")
        print("slug is wrong, or the gateway needs a VPN / corporate network.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
