Contracts (Observation, Action Menu, Trace)

Observation
- time_ms: integer logical time
- focus: one of "browser" | "slack" | "mail"
- summary: short human-readable summary of the current focus
- screenshot_ref: currently null (reserved)
- action_menu: list of actions the agent may take next
- pending_events: object with integer counters by target, e.g., {"slack": 0, "mail": 1}

Action menu entries
- Concrete affordance (visible on the current page):
  { "tool": "browser.click", "args": { "node_id": "CLICK:open_pdp#0" }, "name": "Open product page" }

- Generic actions (LLM guidance):
  { "tool": "browser.read", "args_schema": {} }
  { "tool": "browser.find", "args_schema": { "query": "str", "top_k": "int?" } }
  { "tool": "browser.open", "args_schema": { "url": "str" } }
  { "tool": "browser.back", "args_schema": {} }

Notes:
- args_schema keys ending with '?' are optional.
- Concrete affordances include a concrete args object; generic entries include an args_schema for the LLM to construct args.
- The menu always contains the generic browser actions when focus == "browser", and minimal send/compose actions when focus == "slack"/"mail".

Available tools (MCP names)
- vei.observe { focus?: "browser"|"slack"|"mail" } -> Observation
- vei.ping {} -> { ok: true, time_ms }
- vei.reset { seed?: int } -> { ok: true, seed, time_ms: 0 }
- vei.pending {} -> { slack: int, mail: int, total: int }
- vei.tick { dt_ms?: int } -> { delivered: { slack, mail }, time_ms, pending }
- vei.act_and_observe { tool: string, args: object } -> { result, observation }
- vei.state { include_state?: bool, tool_tail?: int, include_receipts?: bool } -> { head, branch, time_ms, tool_tail: [...], receipts: [...], ... }
- browser.* (open, find, click, type, submit, read, back)
- slack.* (list_channels, open_channel, send_message, react, fetch_thread)
- mail.* (list, open, compose, reply)

Trace entries (one JSON object per line)
- Common fields:
  - trace_version: 1
  - type: "call" | "event"
  - time_ms: integer logical time when recorded
- For type == "call":
  - tool: tool name
  - args: object of arguments
  - response: raw tool response (tool-specific)
- For type == "event":
  - target: "slack" | "mail"
  - payload: event payload (target-specific)
  - emitted: result of delivery (target-specific)

Return shape consistency
- Tool calls return their direct result.
- vei.observe returns an Observation object.
- vei.act_and_observe returns { result, observation }.
- Errors are returned as { error: { code, message } } where code is a stable string.

Error handling conventions
- Unknown tools and invalid actions surface as error objects with a stable string code (e.g., "unknown_tool", "invalid_action").
- Server adapters avoid raising transport exceptions for domain errors; instead they return the error object for LLM/tooling friendliness.
