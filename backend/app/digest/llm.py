"""Provider-agnostic LLM summarizer.

Talks the OpenAI-compatible ``/chat/completions`` shape, so the same code works
against any free provider by configuration alone — a local Ollama
(``http://ollama:11434/v1``, no key), Groq, OpenRouter, or Gemini's
OpenAI-compatible endpoint. No paid/SDK dependency.
"""
import logging

import httpx

from app.config import get_settings

log = logging.getLogger("digest.llm")

_SYSTEM = (
    "You summarize security/identity blog posts for a Jira ticket. Write a "
    "concise, factual 3-4 sentence summary for a technical audience. No preamble."
)


async def ensure_model() -> None:
    """For Ollama, pull the model if it isn't present yet (no-op elsewhere).
    Best-effort: failures are logged, not raised."""
    s = get_settings()
    if not s.llm_auto_pull or "11434" not in s.llm_base_url:
        return
    # Ollama's native pull endpoint sits at the host root, not under /v1.
    host = s.llm_base_url.rstrip("/").removesuffix("/v1")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
            await client.post(f"{host}/api/pull", json={"name": s.llm_model})
            log.info("Ensured Ollama model present: %s", s.llm_model)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not pre-pull model %s: %s", s.llm_model, exc)


async def summarize(title: str, body: str) -> str:
    s = get_settings()
    content = (
        f"Title: {title}\n\n{body[:8000]}\n\n"
        "Summarize the above in 3-4 sentences."
    )
    payload = {
        "model": s.llm_model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": content},
        ],
        "temperature": 0.3,
        "max_tokens": 300,
    }
    headers = {"Content-Type": "application/json"}
    if s.llm_api_key:
        headers["Authorization"] = f"Bearer {s.llm_api_key}"

    url = f"{s.llm_base_url.rstrip('/')}/chat/completions"
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"].strip()
