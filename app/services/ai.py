from __future__ import annotations

import httpx

from .. import db


class AIConfigurationError(RuntimeError):
    pass


def public_ai_status(settings: dict[str, str] | None = None) -> dict[str, str | bool]:
    settings = settings or db.get_settings()
    provider = settings.get("ai_provider", "disabled")
    enabled = settings.get("ai_enabled") == "true" and provider != "disabled"
    return {
        "provider": provider,
        "enabled": enabled,
        "last_test_ok": settings.get("ai_last_test_ok") == "true",
        "model": model_for(settings, provider),
    }


def model_for(settings: dict[str, str], provider: str) -> str:
    if provider == "openai":
        return settings.get("ai_openai_model", "")
    if provider == "claude":
        return settings.get("ai_claude_model", "")
    if provider == "ollama":
        return settings.get("ai_ollama_model", "")
    return ""


def require_active_config(settings: dict[str, str] | None = None) -> dict[str, str]:
    settings = settings or db.get_settings()
    provider = settings.get("ai_provider", "disabled")
    if provider == "disabled" or settings.get("ai_enabled") != "true" or settings.get("ai_last_test_ok") != "true":
        raise AIConfigurationError("AI är inte aktiverat. En admin behöver välja provider och köra ett godkänt anslutningstest.")
    return settings


async def test_provider(settings: dict[str, str] | None = None) -> tuple[bool, str]:
    settings = settings or db.get_settings()
    provider = settings.get("ai_provider", "disabled")
    try:
        if provider == "disabled":
            db.set_settings({"ai_enabled": "false", "ai_last_test_ok": "false"})
            return True, "AI är avstängt."
        if provider == "openai":
            await call_openai(settings, "Svara bara med OK.", "Anslutningstest")
        elif provider == "claude":
            await call_claude(settings, "Svara bara med OK.", "Anslutningstest")
        elif provider == "ollama":
            await call_ollama(settings, "Svara bara med OK.", "Anslutningstest")
        else:
            return False, "Okänd AI-provider."
    except Exception as exc:
        db.set_settings({"ai_enabled": "false", "ai_last_test_ok": "false"})
        return False, f"Anslutningstest misslyckades: {exc.__class__.__name__}"
    db.set_settings({"ai_enabled": "true", "ai_last_test_ok": "true"})
    return True, "Anslutningstest lyckades och providern är aktiv."


async def ask_ai(question: str, context: str, settings: dict[str, str] | None = None) -> str:
    settings = require_active_config(settings)
    provider = settings.get("ai_provider", "disabled")
    system = (
        "Du hjälper en privatperson att förstå arkiverade dokument. "
        "Svara på svenska, hänvisa till dokumentutdrag om det är relevant, "
        "och säg tydligt när underlaget inte räcker."
    )
    prompt = f"Dokumentutdrag:\n{context}\n\nFråga:\n{question}"
    if provider == "openai":
        return await call_openai(settings, system, prompt)
    if provider == "claude":
        return await call_claude(settings, system, prompt)
    if provider == "ollama":
        return await call_ollama(settings, system, prompt)
    raise AIConfigurationError("Okänd AI-provider.")


async def call_openai(settings: dict[str, str], system: str, prompt: str) -> str:
    key = settings.get("ai_openai_api_key", "")
    if not key:
        raise AIConfigurationError("OpenAI API-nyckel saknas.")
    base_url = settings.get("ai_openai_base_url", "https://api.openai.com/v1").rstrip("/")
    model = settings.get("ai_openai_model", "gpt-4o-mini")
    timeout = float(settings.get("ai_timeout_seconds", "30"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
        )
        response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


async def call_claude(settings: dict[str, str], system: str, prompt: str) -> str:
    key = settings.get("ai_claude_api_key", "")
    if not key:
        raise AIConfigurationError("Claude API-nyckel saknas.")
    model = settings.get("ai_claude_model", "claude-3-5-haiku-latest")
    timeout = float(settings.get("ai_timeout_seconds", "30"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={
                "model": model,
                "max_tokens": 800,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
    data = response.json()
    return "\n".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")


async def call_ollama(settings: dict[str, str], system: str, prompt: str) -> str:
    base_url = settings.get("ai_ollama_base_url", "http://host.docker.internal:11434").rstrip("/")
    model = settings.get("ai_ollama_model", "llama3.1")
    timeout = float(settings.get("ai_timeout_seconds", "30"))
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
    data = response.json()
    return data.get("message", {}).get("content", "")
