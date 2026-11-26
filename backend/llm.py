"""LLM access. Demo mode (no key, or forced) returns the deterministic fallback and flags it as simulated."""
import os
import httpx
import db

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

def live_available():
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and db.get_setting("force_demo") != "1"

def generate(system: str, prompt: str, fallback: str, max_tokens: int = 900):
    """Returns (text, simulated, error). Falls back to the demo text if the live call fails."""
    if not live_available():
        return fallback, True, None
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=60,
            headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
            json={"model": MODEL, "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")
        return text.strip() or fallback, False, None
    except Exception as e:  # network, auth, rate limit
        return fallback, True, f"LLM call failed, used demo output: {type(e).__name__}: {e}"
