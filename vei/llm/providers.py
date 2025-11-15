from __future__ import annotations

import asyncio
import json
import os
import re
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

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _parse_plan_text(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    match = _JSON_FENCE_RE.match(text)
    if match:
        text = match.group(1).strip()
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    brace_index = text.find("{")
    if brace_index != -1:
        try:
            obj, _ = decoder.raw_decode(text[brace_index:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    raise json.JSONDecodeError("Could not parse plan JSON", raw, 0)


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
    timeout_s: int = 240,
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
            "reasoning": {"effort": "high"},
        }
        try:
            resp = await asyncio.wait_for(client.responses.create(**kwargs), timeout=timeout_s)
            raw = getattr(resp, "output_text", None)
            if not raw and resp.status == "incomplete":
                detail = getattr(resp, "incomplete_details", None)
                if detail and getattr(detail, "reason", "") == "max_output_tokens":
                    # Fall back to safetensors tool output if present
                    try:
                        for item in getattr(resp, "output", []) or []:
                            if getattr(item, "type", None) == "tool_call" and getattr(item, "content", None):
                                content = getattr(item, "content", None)
                                if isinstance(content, dict):
                                    return content
                                raw = json.dumps(content)
                                break
                    except Exception:
                        raw = None
                if not raw:
                    raise RuntimeError(f"Response incomplete: {detail}")
            if raw:
                return _parse_plan_text(raw)
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
                return _parse_plan_text(choice.message.content)
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
    timeout_s: int = 240,
    api_key: Optional[str] = None,
    tool_schemas: Optional[list[Dict[str, Any]]] = None,
    alias_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Anthropic provider using Messages API."""
    if AsyncAnthropic is None:
        raise RuntimeError("anthropic SDK not installed; install with extras [llm]")
    
    headers: Dict[str, str] = {}
    version = os.environ.get("ANTHROPIC_VERSION")
    beta = os.environ.get("ANTHROPIC_BETA")
    if version:
        headers["anthropic-version"] = version.strip()
    if beta:
        headers["anthropic-beta"] = beta.strip()
    client_kwargs: Dict[str, Any] = {
        "api_key": api_key or os.environ.get("ANTHROPIC_API_KEY")
    }
    if headers:
        client_kwargs["default_headers"] = headers
    client = AsyncAnthropic(**client_kwargs)
    
    use_beta_api = (os.environ.get("ANTHROPIC_USE_BETA", "").strip().lower() in {"1", "true", "yes"}) or model.startswith("claude-4.5")
    messages_api = client.beta.messages if use_beta_api else client.messages

    try:
        bridge_mode = bool(tool_schemas and len(tool_schemas) == 1 and tool_schemas[0]["name"] == "vei_call")
        if tool_schemas:
            first_name = tool_schemas[0]["name"] if tool_schemas else "<none>"
            msg = await asyncio.wait_for(
                messages_api.create(
                    model=model,
                    system=system,
                    max_tokens=2048,
                    temperature=0,
                    tools=tool_schemas,
                    messages=[
                        {
                            "role": "user",
                            "content": user,
                        }
                    ],
                ),
                timeout=timeout_s,
            )
        else:
            msg = await asyncio.wait_for(
                messages_api.create(
                    model=model,
                    system=system + "\nYou MUST respond ONLY with valid JSON. No explanations, no prose, ONLY JSON.",
                    max_tokens=2048,
                    temperature=0,
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
        
        if tool_schemas:
            for block in getattr(msg, "content", []) or []:
                if getattr(block, "type", None) == "tool_use":
                    alias = getattr(block, "name", "")
                    tool_input = getattr(block, "input", {})
                    if hasattr(tool_input, "model_dump"):
                        tool_input = tool_input.model_dump()
                    if bridge_mode and alias == "vei_call":
                        if isinstance(tool_input, dict):
                            actual_tool = tool_input.get("tool")
                            args = tool_input.get("args", {})
                            if not isinstance(args, dict):
                                args = {}
                            if actual_tool:
                                return {"tool": actual_tool, "args": args}
                        raise RuntimeError("Claude returned vei_call without valid tool/args")
                    tool_name = alias_map.get(alias, alias) if alias_map else alias
                    return {"tool": tool_name, "args": tool_input if isinstance(tool_input, dict) else {}}

        for block in msg.content:
            if hasattr(block, "text") and block.text:
                text = block.text.strip()
                if text:
                    parsed = json.loads(text)
                    if bridge_mode and parsed.get("tool") == "vei_call":
                        actual_tool = parsed.get("args", {}).get("tool") if isinstance(parsed.get("args"), dict) else parsed.get("tool_name")
                        args = parsed.get("args", {}) if isinstance(parsed.get("args"), dict) else parsed.get("tool_args", {})
                        if not isinstance(args, dict):
                            args = {}
                        if actual_tool:
                            return {"tool": actual_tool, "args": args}
                    if alias_map:
                        alias = parsed.get("tool")
                        if alias in alias_map:
                            parsed["tool"] = alias_map[alias]
                    return parsed
        
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

    genai.configure(
        api_key=api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    )

    model_instance = genai.GenerativeModel(model_name=model)

    prompt = (
        f"[system] {system}\n[user] {user}\n"
        "Reply strictly as JSON with keys 'tool' (string) and 'args' (object)."
    )

    config = genai.types.GenerationConfig(
        temperature=0.0,
        top_p=1,
        response_mime_type="application/json",
    )

    try:
        resp = await asyncio.wait_for(
            model_instance.generate_content_async(
                contents=[prompt],
                generation_config=config,
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
    
    headers: Dict[str, str] = {}
    referer = os.environ.get("OPENROUTER_HTTP_REFERER")
    app_title = os.environ.get("OPENROUTER_APP_TITLE")
    if referer:
        headers["HTTP-Referer"] = referer
    if app_title:
        headers["X-Title"] = app_title

    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key or os.environ.get("OPENROUTER_API_KEY"),
        default_headers=headers or None,
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
            try:
                return json.loads(choice.message.content)
            except json.JSONDecodeError as exc:
                snippet = choice.message.content.strip()
                if len(snippet) > 200:
                    snippet = snippet[:200] + "…"
                raise RuntimeError(f"OpenRouter returned non-JSON payload: {snippet}") from exc
        
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
    timeout_s: int = 240,
    openai_base_url: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    google_api_key: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
    tool_schemas: Optional[list[Dict[str, Any]]] = None,
    alias_map: Optional[Dict[str, str]] = None,
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
        return await _anthropic_plan(
            model=model,
            system=system,
            user=user,
            timeout_s=timeout_s,
            api_key=anthropic_api_key,
            tool_schemas=tool_schemas,
            alias_map=alias_map,
        )
    if p == "google":
        return await _google_plan(model=model, system=system, user=user, timeout_s=timeout_s, api_key=google_api_key)
    if p == "openrouter":
        return await _openrouter_plan(model=model, system=system, user=user, timeout_s=timeout_s, api_key=openrouter_api_key)
    raise ValueError(f"Unknown provider: {provider}")
