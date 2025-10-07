from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional

try:
    from openai import AsyncOpenAI, BadRequestError
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore
    BadRequestError = None # type: ignore

try:
    from anthropic import AsyncAnthropic
except Exception:  # pragma: no cover
    AsyncAnthropic = None  # type: ignore

try:
    from google import genai
except Exception:  # pragma: no cover
    genai = None  # type: ignore


def auto_provider_for_model(model: str, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.strip().lower()
    m = (model or "").strip().lower()
    if m.startswith("claude-"):
        return "anthropic"
    if m.startswith("gemini-") or m.startswith("models/gemini"):
        return "google"
    if m.startswith("grok-") or "grok" in m:
        return "openrouter"
    return "openai"


async def _openai_plan(
    *,
    model: str,
    system: str,
    user: str,
    plan_schema: Optional[dict] = None,
    timeout_s: int = 30,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """OpenAI provider. Uses Responses API for gpt-5, Chat Completions for others."""
    if AsyncOpenAI is None:
        raise RuntimeError("openai SDK not installed; install with extras [llm]")
    
    client = AsyncOpenAI(
        base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
        api_key=api_key or os.environ.get("OPENAI_API_KEY")
    )

    # Per user feedback, gpt-5 requires the Responses API and specific params.
    if model.startswith("gpt-5"):
        prompt = (
            f"[system] {system}\n[user] {user}\n"
            "Reply strictly as JSON with keys 'tool' (string) and 'args' (object)."
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "input": prompt,
            "max_output_tokens": 2048,
            "reasoning": {"effort": "high"},
        }
        try:
            resp = await asyncio.wait_for(client.responses.create(**kwargs), timeout=timeout_s)
            raw = getattr(resp, "output_text", None)
            if not raw and resp.status == "incomplete":
                raise RuntimeError(f"Response incomplete: {resp.incomplete_details}")
            if raw:
                raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
                return json.loads(raw)
        except Exception:
            raise
    else:
        # Fallback to standard Chat Completions for other OpenAI models
        try:
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user + "\nReply strictly as JSON with keys 'tool' (string) and 'args' (object)."},
                    ],
                    max_completion_tokens=2048,
                    temperature=0.0,
                    top_p=1,
                    response_format={"type": "json_object"},
                ),
                timeout=timeout_s,
            )
            choice = resp.choices[0]
            if choice.finish_reason == "length":
                raise RuntimeError(f"OpenAI response truncated due to max_tokens.")
            if choice.message.content:
                return json.loads(choice.message.content)
        except BadRequestError as e:
            # Handle specific error for gpt-5 if it was routed here by mistake
            if "max_completion_tokens" in str(e):
                 raise RuntimeError(f"Model {model} may require the Responses API. Rerun with a more specific model name if this is gpt-5.") from e
            raise
        except Exception:
            raise

    # Fallback if no content extracted
    return {"tool": "vei.observe", "args": {}}


async def _anthropic_plan(
    *,
    model: str,
    system: str,
    user: str,
    timeout_s: int = 30,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Anthropic provider using Messages API."""
    if AsyncAnthropic is None:
        raise RuntimeError("anthropic SDK not installed; install with extras [llm]")
    
    client = AsyncAnthropic(
        api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
    )
    
    try:
        msg = await asyncio.wait_for(
            client.messages.create(
                model=model,
                system=system + "\nYou MUST respond ONLY with valid JSON. No explanations, no prose, ONLY JSON.",
                max_tokens=2048,
                temperature=0,
                top_p=1,
                messages=[
                    {
                        "role": "user",
                        "content": user + "\n\nIMPORTANT: Reply with ONLY a JSON object. No other text. Format: {\"tool\": \"<name>\", \"args\": {...}}",
                    }
                ],
            ),
            timeout=timeout_s,
        )

        if msg.stop_reason == "max_tokens":
            raise RuntimeError(f"Anthropic response truncated due to max_tokens ({msg.usage.output_tokens}).")
        
        for block in msg.content:
            if hasattr(block, "text") and block.text:
                text = block.text.strip()
                if text:
                    return json.loads(text)
        
        raise RuntimeError(f"No text content in Claude response: {msg}")
        
    except Exception:
        raise


async def _google_plan(
    *,
    model: str,
    system: str,
    user: str,
    timeout_s: int = 30,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Google Gemini provider using genai library with JSON mode."""
    if genai is None:
        raise RuntimeError("google-genai not installed; install with extras [llm]")
    
    client = genai.Client(
        api_key=api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    )
    
    prompt = (
        f"[system] {system}\n[user] {user}\n"
        "Reply strictly as JSON with keys 'tool' (string) and 'args' (object)."
    )
    
    config = genai.types.GenerateContentConfig(
        temperature=0.0,
        top_p=1,
        max_output_tokens=2048,
        response_mime_type="application/json"
    )
    
    try:
        resp = await asyncio.wait_for(
            asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=[prompt],
                config=config
            ),
            timeout=timeout_s
        )
        
        if resp.candidates and resp.candidates[0].finish_reason.name == "MAX_TOKENS":
            raise RuntimeError("Google response truncated due to max_tokens.")

        if hasattr(resp, "text") and resp.text:
            return json.loads(resp.text)
        
    except Exception:
        raise
    
    return {"tool": "vei.observe", "args": {}}


async def _openrouter_plan(
    *,
    model: str,
    system: str,
    user: str,
    timeout_s: int = 90,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """OpenRouter provider using OpenAI-compatible API."""
    if AsyncOpenAI is None:
        raise RuntimeError("openai SDK not installed; install with extras [llm]")
    
    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key or os.environ.get("OPENROUTER_API_KEY")
    )
    
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user + "\nReply strictly as JSON with keys 'tool' (string) and 'args' (object)."}
                ],
                max_tokens=2048,
                temperature=0,
                top_p=1,
                response_format={"type": "json_object"}
            ),
            timeout=timeout_s
        )
        
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError(f"OpenRouter response truncated due to max_tokens.")

        if choice.message.content:
            return json.loads(choice.message.content)
        
    except Exception:
        raise
    
    return {"tool": "vei.observe", "args": {}}


async def plan_once(
    *,
    provider: str,
    model: str,
    system: str,
    user: str,
    plan_schema: Optional[dict] = None,
    timeout_s: int = 30,
    openai_base_url: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    google_api_key: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    p = (provider or "openai").strip().lower()
    if p == "auto":
        p = auto_provider_for_model(model)

    if p == "openai":
        return await _openai_plan(
            model=model,
            system=system,
            user=user,
            plan_schema=plan_schema, # Pass it through for gpt-5
            timeout_s=timeout_s,
            base_url=openai_base_url,
            api_key=openai_api_key,
        )
    if p == "anthropic":
        return await _anthropic_plan(model=model, system=system, user=user, timeout_s=timeout_s, api_key=anthropic_api_key)
    if p == "google":
        return await _google_plan(model=model, system=system, user=user, timeout_s=timeout_s, api_key=google_api_key)
    if p == "openrouter":
        return await _openrouter_plan(model=model, system=system, user=user, timeout_s=timeout_s, api_key=openrouter_api_key)
    raise ValueError(f"Unknown provider: {provider}")