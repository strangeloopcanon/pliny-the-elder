from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*args: object, **kwargs: object) -> None:  # type: ignore
        return None

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from openai import AsyncOpenAI

# Reuse robust JSON plan extraction helper
from vei.cli._llm_loop import extract_plan as _extract_plan


SYSTEM_PROMPT = (
    "You are an assistant controlling tools via MCP in a synthetic enterprise world. "
    "Each step: FIRST call 'vei.observe' to see the action_menu, then pick EXACTLY ONE tool to call. "
    "Reply STRICTLY as JSON with keys {\"tool\": str, \"args\": object}."
)


async def main() -> None:
    load_dotenv(override=True)
    task = os.environ.get(
        "VEI_TASK",
        "Research product price, get Slack approval < $3200, email vendor for a quote.",
    )
    model = os.environ.get("VEI_MODEL", "gpt-5")
    max_steps = int(os.environ.get("VEI_MAX_STEPS", "10"))
    timeout_s = int(os.environ.get("VEI_TIMEOUT_S", "60"))
    run_id = os.environ.get("VEI_RUN_ID") or str(int(asyncio.get_running_loop().time() * 1000))

    # Spawn the stdio MCP server (vei.router) with a clean, deterministic env
    env = os.environ.copy()
    env["VEI_DISABLE_AUTOSTART"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    py = sys.executable or "python3"
    params = StdioServerParameters(command=py, args=["-m", "vei.router"], env=env)

    # Establish MCP session over stdio
    async with stdio_client(params, errlog=sys.stderr) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=20)

            # OpenAI-compatible client
            client = AsyncOpenAI(
                base_url=os.environ.get("OPENAI_BASE_URL"),
                api_key=os.environ.get("OPENAI_API_KEY"),
            )

            messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
            if task:
                messages.append({"role": "user", "content": f"Task: {task}"})

            transcript: list[dict[str, Any]] = []
            step = 0

            def _normalize(res: Any) -> dict:
                # Convert CallToolResult into a dict payload
                try:
                    if getattr(res, "isError", False):
                        return {"error": True, "content": getattr(res, "content", None)}
                    sc = getattr(res, "structuredContent", None)
                    if sc is not None:
                        return sc  # already a dict
                    # Fallback: try to parse first text content as JSON
                    content = getattr(res, "content", None)
                    if content and isinstance(content, list) and getattr(content[0], "text", None):
                        import json as _json
                        txt = content[0].text
                        try:
                            return _json.loads(txt)
                        except Exception:
                            return {"text": txt}
                    return {"result": res}
                except Exception:
                    return {"result": str(res)}

            for _ in range(max_steps):
                res_obs = await session.call_tool("vei.observe", {})
                obs = _normalize(res_obs)
                transcript.append({
                    "observation": obs,
                    "meta": {"run_id": run_id, "step": step, "time_ms": obs.get("time_ms")}
                })

                menu = obs.get("action_menu", [])
                menu_text = "\n".join(
                    f"- {m.get('tool')} {json.dumps(m.get('args', m.get('args_schema', {})))}" for m in menu
                )
                user = (
                    f"Time: {obs.get('time_ms')}\n"
                    f"Focus: {obs.get('focus')}\n"
                    f"Summary: {obs.get('summary')}\n"
                    f"Pending: {json.dumps(obs.get('pending_events'))}\n"
                    f"Action menu (choose ONE):\n{menu_text}\n"
                    "Reply strictly as JSON {\"tool\": str, \"args\": object}."
                )
                messages.append({"role": "user", "content": user})

                try:
                    chat = await asyncio.wait_for(
                        client.chat.completions.create(model=model, messages=messages),
                        timeout=timeout_s,
                    )
                except asyncio.TimeoutError:
                    transcript.append({"error": {"type": "llm_timeout", "timeout_s": timeout_s}})
                    break

                content = chat.choices[0].message.content or "{}"
                plan = _extract_plan(content, default_tool="vei.observe")
                tool = plan.get("tool", "vei.observe")
                args = plan.get("args", {}) if isinstance(plan.get("args"), dict) else {}
                transcript.append({
                    "llm_plan": {"raw": content, "parsed": plan},
                    "meta": {"run_id": run_id, "step": step, "time_ms": obs.get("time_ms")}
                })

                try:
                    res_call = await session.call_tool(tool, args)
                    res = _normalize(res_call)
                except Exception as e:  # noqa: BLE001
                    res = {"error": str(e)}
                transcript.append({
                    "action": {"tool": tool, "args": args, "result": res},
                    "meta": {"run_id": run_id, "step": step, "time_ms": obs.get("time_ms")}
                })
                messages.append({"role": "assistant", "content": json.dumps(plan)})

                # Auto-drain after key actions to capture complete episodes
                if tool in ("mail.compose", "slack.send_message"):
                    try:
                        for _i in range(12):
                            # advance time in chunks and observe
                            await session.call_tool("vei.tick", {"dt_ms": 2000})
                            res_obs2 = await session.call_tool("vei.observe", {})
                            obs2 = _normalize(res_obs2)
                            transcript.append({
                                "observation": obs2,
                                "meta": {"run_id": run_id, "step": step, "time_ms": obs2.get("time_ms"), "autodrain": True}
                            })
                            pend = (obs2.get("pending_events") or {})
                            if pend.get("mail", 0) == 0 and pend.get("slack", 0) == 0:
                                break
                    except Exception:
                        ...
                step += 1

            # Emit transcript JSON to stdout or file if specified
            out_path = os.environ.get("VEI_TRANSCRIPT_OUT")
            data = json.dumps(transcript, indent=2)
            if out_path:
                try:
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(data)
                    print(f"Transcript written to {out_path}")
                except Exception as e:  # noqa: BLE001
                    print(f"Failed to write transcript to {out_path}: {e}")
                    print(data)
            else:
                print(data)


if __name__ == "__main__":
    asyncio.run(main())
