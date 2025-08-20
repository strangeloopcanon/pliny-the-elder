from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
import heapq
import threading
import queue
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from vei.world.scenario import Scenario


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


class MCPError(Exception):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class Observation(BaseModel):
    time_ms: int
    focus: str
    summary: str
    screenshot_ref: Optional[str] = None
    action_menu: List[Dict[str, Any]]
    pending_events: Dict[str, int]


@dataclass
class Event:
    t_due_ms: int
    target: str
    payload: Dict[str, Any]


class LinearCongruentialGenerator:
    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFF

    def next_u32(self) -> int:
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        return self.state

    def next_float(self) -> float:
        return self.next_u32() / 0x100000000

    def randint(self, a: int, b: int) -> int:
        return a + int(self.next_float() * (b - a + 1))


class EventBus:
    def __init__(self, seed: int):
        self.rng = LinearCongruentialGenerator(seed)
        self.clock_ms = 0
        self._heap: list[tuple[int, int, Event]] = []
        self._seq = 0

    def schedule(self, dt_ms: int, target: str, payload: Dict[str, Any]) -> None:
        evt = Event(self.clock_ms + dt_ms, target, payload)
        self._seq += 1
        heapq.heappush(self._heap, (evt.t_due_ms, self._seq, evt))

    def next_if_due(self) -> Optional[Event]:
        if self._heap and self._heap[0][0] <= self.clock_ms:
            _, _, evt = heapq.heappop(self._heap)
            return evt
        return None

    def advance(self, dt_ms: int) -> None:
        self.clock_ms += dt_ms

    def peek_due_time(self) -> Optional[int]:
        return self._heap[0][0] if self._heap else None

    def pending_count(self, target: Optional[str] = None) -> int:
        if target is None:
            return len(self._heap)
        return sum(1 for _, _, e in self._heap if e.target == target)


class TraceLogger:
    def __init__(self, out_dir: Optional[str]):
        self.out_dir = out_dir
        self.entries: List[Dict[str, Any]] = []
        # Optional: stream each entry to an external collector
        self.post_url: Optional[str] = os.environ.get("VEI_TRACE_POST_URL")
        self._flush_idx = 0
        self.append_mode = os.environ.get("VEI_TRACE_APPEND", "1") == "1"
        # Background poster for streaming to avoid inline latency
        self._q: queue.Queue[Dict[str, Any]] | None = None
        self._poster_thread: threading.Thread | None = None
        if self.post_url:
            self._q = queue.Queue(maxsize=256)
            self._poster_thread = threading.Thread(target=self._poster_loop, name="vei-trace-poster", daemon=True)
            self._poster_thread.start()

    def _try_stream(self, entry: Dict[str, Any]) -> None:
        if not self._q:
            return
        try:
            self._q.put_nowait(entry)
        except queue.Full:
            # Drop when saturated to preserve determinism and low latency
            pass

    def _poster_loop(self) -> None:
        # Use stdlib to avoid extra deps
        import urllib.request
        while True:
            try:
                item = self._q.get(timeout=1.0) if self._q else None
            except queue.Empty:
                continue
            if not item:
                continue
            try:
                data = json.dumps(item).encode("utf-8")
                req = urllib.request.Request(
                    self.post_url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=1.0) as _:
                    pass
            except Exception:
                # Best-effort only
                pass

    def record_call(self, tool: str, args: Dict[str, Any], response: Any, time_ms: int) -> None:
        entry = {
            "trace_version": 1,
            "type": "call",
            "tool": tool,
            "args": args,
            "response": response,
            "time_ms": time_ms,
        }
        self.entries.append(entry)
        self._try_stream(entry)

    def record_event(self, target: str, payload: Dict[str, Any], emitted: Any, time_ms: int) -> None:
        entry = {
            "trace_version": 1,
            "type": "event",
            "target": target,
            "payload": payload,
            "emitted": emitted,
            "time_ms": time_ms,
        }
        self.entries.append(entry)
        self._try_stream(entry)

    def flush(self) -> None:
        # Allow late-binding of artifacts dir via environment during tests
        if not self.out_dir:
            env_dir = os.environ.get("VEI_ARTIFACTS_DIR")
            if env_dir:
                self.out_dir = env_dir
            else:
                return
        os.makedirs(self.out_dir, exist_ok=True)
        path = os.path.join(self.out_dir, "trace.jsonl")
        if self.append_mode and os.path.exists(path):
            mode = "a"
        else:
            mode = "w"
            self._flush_idx = 0
        with open(path, mode, encoding="utf-8") as f:
            for entry in self.entries[self._flush_idx : ]:
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        self._flush_idx = len(self.entries)


class SlackSim:
    def __init__(self, bus: EventBus, scenario: Optional[Scenario] = None):
        self.bus = bus
        # Configurable behavior
        if scenario and scenario.budget_cap_usd is not None:
            self.budget_cap_usd = int(scenario.budget_cap_usd)
        else:
            self.budget_cap_usd = int(os.environ.get("VEI_BUDGET_CAP", "3500"))
        try:
            if scenario and scenario.derail_prob is not None:
                self.derail_prob = float(scenario.derail_prob)
            else:
                self.derail_prob = float(os.environ.get("VEI_SLACK_DERAIL_PCT", "0.1"))
        except ValueError:
            self.derail_prob = 0.1

        initial_text = (
            scenario.slack_initial_message
            if scenario and scenario.slack_initial_message is not None
            else "Reminder: citations required for any request over $2k."
        )

        self.channels = {
            "#procurement": {
                "messages": [
                    {
                        "ts": "1",
                        "user": "itops",
                        "text": initial_text,
                        "thread_ts": None,
                    }
                ],
                "unread": 0,
            }
        }

    # MCP tools
    def list_channels(self) -> List[str]:
        return list(self.channels.keys())

    def open_channel(self, channel: str) -> Dict[str, Any]:
        ch = self.channels.get(channel)
        if not ch:
            raise MCPError("unknown_channel", f"Unknown Slack channel: {channel}")
        return {"messages": ch["messages"], "unread_count": ch["unread"]}

    def send_message(self, channel: str, text: str, thread_ts: Optional[str] = None) -> Dict[str, Any]:
        ch = self.channels.get(channel)
        if not ch:
            raise MCPError("unknown_channel", f"Unknown Slack channel: {channel}")
        # Monotonic 1-based timestamps to avoid duplicate ids
        ts = str(len(ch["messages"]) + 1)
        msg = {"ts": ts, "user": "agent", "text": text, "thread_ts": thread_ts}
        ch["messages"].append(msg)
        lower = text.lower()
        # Occasionally derail/off-topic before anything else
        if self.bus.rng.next_float() < self.derail_prob:
            self.bus.schedule(
                dt_ms=7000,
                target="slack",
                payload={
                    "channel": channel,
                    "text": "Could someone update the Q3 KPI sheet?",
                    "thread_ts": ts,
                },
            )
        # Approval policy: must include a budget number and be <= budget cap
        if ("approve" in lower or "summary" in lower or "budget" in lower):
            m = re.search(r"\$?([0-9]{3,6})", text.replace(",", ""))
            if m:
                amount = int(m.group(1))
                if amount <= self.budget_cap_usd:
                    self.bus.schedule(
                        dt_ms=12000,
                        target="slack",
                        payload={
                            "channel": channel,
                            "text": ":white_check_mark: Approved",
                            "thread_ts": ts,
                        },
                    )
                else:
                    self.bus.schedule(
                        dt_ms=10000,
                        target="slack",
                        payload={
                            "channel": channel,
                            "text": "Need clearer budget justification (over cap).",
                            "thread_ts": ts,
                        },
                    )
            else:
                self.bus.schedule(
                    dt_ms=9000,
                    target="slack",
                    payload={
                        "channel": channel,
                        "text": "What is the budget amount?",
                        "thread_ts": ts,
                    },
                )
        return {"ts": ts}

    def react(self, channel: str, ts: str, emoji: str) -> Dict[str, Any]:
        return {"ok": True}

    def fetch_thread(self, channel: str, thread_ts: str) -> Dict[str, Any]:
        ch = self.channels.get(channel)
        if not ch:
            raise MCPError("unknown_channel", f"Unknown Slack channel: {channel}")
        base = _safe_int(thread_ts, 0)
        msgs = [
            m
            for m in ch["messages"]
            if m.get("thread_ts") in (thread_ts, None) and _safe_int(m.get("ts"), 0) >= base
        ]
        return {"messages": msgs}

    # Event delivery
    def deliver(self, event: Dict[str, Any]) -> Dict[str, Any]:
        channel = event["channel"]
        ch = self.channels.get(channel)
        if not ch:
            raise MCPError("unknown_channel")
        ts = str(len(ch["messages"]) + 1)
        ch["messages"].append({"ts": ts, "user": "cfo", "text": event["text"], "thread_ts": event.get("thread_ts")})
        ch["unread"] += 1
        return {"ok": True}


class MailSim:
    def __init__(self, bus: EventBus, scenario: Optional[Scenario] = None):
        self.bus = bus
        self.messages: Dict[str, Dict[str, Any]] = {}
        self.inbox: List[str] = []
        self.counter = 1
        self._variants_override = scenario.vendor_reply_variants if scenario and scenario.vendor_reply_variants else None

    def list(self, folder: str = "INBOX") -> List[Dict[str, Any]]:
        return [self.messages[mid] for mid in self.inbox]

    def open(self, id: str) -> Dict[str, Any]:
        m = self.messages.get(id)
        if not m:
            raise MCPError("unknown_message", f"Unknown mail id: {id}")
        return {"headers": m["headers"], "body_text": m["body_text"], "parts": m.get("parts", [])}

    def compose(self, to: str, subj: str, body_text: str, attachments: Optional[List[str]] = None) -> Dict[str, Any]:
        mid = f"m{self.counter}"
        self.counter += 1
        self.messages[mid] = {
            "id": mid,
            "from": "me@example",
            "to": to,
            "subj": subj,
            "time": self.bus.clock_ms,
            "unread": False,
            "headers": {"From": "me@example", "To": to, "Subject": subj},
            "body_text": body_text,
        }
        # Schedule vendor reply with varied templates (scenario override if provided)
        variants = self._variants_override or [
            "Thanks — Price: $3199, ETA: 5-7 business days.",
            "> On Mon, we received your request\nPRICE: USD 3,199\nEta: within 5-7 business days\n--\nBest, MacroCompute",
            "quote attached (inline): total: $3,199.00, ETA: 5 business days. Regards, Sales",
            "PRICE - $3199; eta: approx. 1 week\n\n\nJohn Doe\nSales Representative\nMacroCompute",
        ]
        idx = 0 if not variants else self.bus.rng.randint(0, max(0, len(variants) - 1))
        body = variants[idx] if variants else ""

        self.bus.schedule(
            dt_ms=15000,
            target="mail",
            payload={
                "in_reply_to": mid,
                "from": to,
                "subj": f"Re: {subj}",
                "body_text": body,
            },
        )
        return {"id": mid}

    def reply(self, id: str, body_text: str) -> Dict[str, Any]:
        return self.compose(to=self.messages[id]["from"], subj=f"Re: {self.messages[id]['subj']}", body_text=body_text)

    def deliver(self, event: Dict[str, Any]) -> Dict[str, Any]:
        mid = f"m{self.counter}"
        self.counter += 1
        msg = {
            "id": mid,
            "from": event["from"],
            "to": "me@example",
            "subj": event["subj"],
            "time": self.bus.clock_ms,
            "unread": True,
            "headers": {"From": event["from"], "To": "me@example", "Subject": event["subj"]},
            "body_text": event["body_text"],
        }
        self.messages[mid] = msg
        self.inbox.insert(0, mid)
        return {"id": mid}


class BrowserVirtual:
    def __init__(self, bus: EventBus, scenario: Optional[Scenario] = None):
        self.bus = bus
        # Very small virtual site with two pages and one affordance
        default_nodes = {
            "home": {
                "url": "https://vweb.local/home",
                "title": "MacroCompute — Home",
                "excerpt": "Welcome to MacroCompute. Find laptops and specs.",
                "affordances": [
                    {"tool": "browser.click", "args": {"node_id": "CLICK:open_pdp#0"}, "name": "Open product page"},
                ],
                "next": {"CLICK:open_pdp#0": "pdp"},
            },
            "pdp": {
                "url": "https://vweb.local/pdp/macrobook-pro-16",
                "title": "MacroBook Pro 16 — Product",
                "excerpt": "Powerful 16-inch laptop. Price $3199. See specifications.",
                "affordances": [
                    {"tool": "browser.click", "args": {"node_id": "CLICK:open_specs#0"}, "name": "See specifications"},
                    {"tool": "browser.back", "args": {}, "name": "Back to home"},
                ],
                "next": {"CLICK:open_specs#0": "specs", "BACK": "home"},
            },
            "specs": {
                "url": "https://vweb.local/pdp/macrobook-pro-16/specs",
                "title": "MacroBook Pro 16 — Specifications",
                "excerpt": "16-core CPU, 32GB RAM, 1TB SSD",
                "affordances": [
                    {"tool": "browser.back", "args": {}, "name": "Back to product"},
                ],
                "next": {"BACK": "pdp"},
            },
        }
        self.nodes = scenario.browser_nodes if scenario and scenario.browser_nodes else default_nodes
        self.state = "home"

    def open(self, url: str) -> Dict[str, Any]:
        if "pdp" in url:
            self.state = "pdp"
        else:
            self.state = "home"
        return {"url": self.nodes[self.state]["url"], "title": self.nodes[self.state]["title"]}

    def find(self, query: str, top_k: int = 10) -> Dict[str, Any]:
        node = self.nodes[self.state]
        hits = []
        for a in node["affordances"]:
            name = a.get("name") or a["args"].get("node_id", "")
            # Only include affordances that have a concrete click target
            args = a.get("args", {})
            node_id = args.get("node_id")
            if node_id is None:
                # Skip generic affordances like browser.back that lack node_id
                continue
            hits.append({
                "node_id": node_id,
                "role": a.get("role", "button"),
                "name": name,
            })
        return {"hits": hits[:top_k]}

    def click(self, node_id: str) -> Dict[str, Any]:
        node = self.nodes[self.state]
        nxt = node["next"].get(node_id)
        if not nxt:
            raise MCPError("invalid_action", f"Invalid click target: {node_id}")
        self.state = nxt
        return {"url": self.nodes[self.state]["url"]}

    def type(self, node_id: str, text: str) -> Dict[str, Any]:
        return {"ok": True}

    def submit(self, form_id: str) -> Dict[str, Any]:
        return {"url": self.nodes[self.state]["url"]}

    def read(self) -> Dict[str, Any]:
        node = self.nodes[self.state]
        return {
            "url": node["url"],
            "title": node["title"],
            "excerpt": node["excerpt"],
        }

    def back(self) -> Dict[str, Any]:
        node = self.nodes[self.state]
        nxt = node["next"].get("BACK")
        if not nxt:
            return {"url": node["url"]}
        self.state = nxt
        return {"url": self.nodes[self.state]["url"]}


class Router:
    def __init__(self, seed: int, artifacts_dir: Optional[str] = None, scenario: Optional[Scenario] = None):
        self.bus = EventBus(seed)
        self.trace = TraceLogger(artifacts_dir)
        self.scenario = scenario or Scenario()
        self.slack = SlackSim(self.bus, self.scenario)
        self.mail = MailSim(self.bus, self.scenario)
        self.browser = BrowserVirtual(self.bus, self.scenario)
        # Optional ERP twin
        try:
            from .erp import ErpSim  # local import to avoid import-time failures
            self.erp = ErpSim(self.bus, self.scenario)
        except Exception:
            self.erp = None  # type: ignore[attr-defined]
        # Optional CRM twin
        try:
            from .crm import CrmSim
            self.crm = CrmSim(self.bus, self.scenario)
        except Exception:
            self.crm = None  # type: ignore[attr-defined]

    def call_and_step(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call, deliver any due event, advance time, and persist trace.

        This keeps the simulation deterministic and ensures artifacts are flushed
        so downstream scoring can consume trace.jsonl during tests.
        """
        result = self._execute(tool, args)
        self.trace.record_call(tool, args, result, time_ms=self.bus.clock_ms)
        evt = self.bus.next_if_due()
        if evt:
            emitted = None
            if evt.target == "slack":
                emitted = self.slack.deliver(evt.payload)
            elif evt.target == "mail":
                emitted = self.mail.deliver(evt.payload)
            self.trace.record_event(evt.target, evt.payload, emitted, time_ms=self.bus.clock_ms)
        self.bus.advance(1000)
        # Persist after each step when artifacts directory is configured
        self.trace.flush()
        return result

    def _execute(self, tool: str, args: Dict[str, Any]) -> Any:
        if tool == "slack.list_channels":
            return self.slack.list_channels()
        if tool == "slack.open_channel":
            return self.slack.open_channel(**args)
        if tool == "slack.send_message":
            return self.slack.send_message(**args)
        if tool == "slack.react":
            return self.slack.react(**args)
        if tool == "slack.fetch_thread":
            return self.slack.fetch_thread(**args)

        if tool == "mail.list":
            return self.mail.list(**args)
        if tool == "mail.open":
            return self.mail.open(**args)
        if tool == "mail.compose":
            return self.mail.compose(**args)
        if tool == "mail.reply":
            return self.mail.reply(**args)

        if tool == "browser.open":
            return self.browser.open(**args)
        if tool == "browser.find":
            return self.browser.find(**args)
        if tool == "browser.click":
            return self.browser.click(**args)
        if tool == "browser.type":
            return self.browser.type(**args)
        if tool == "browser.submit":
            return self.browser.submit(**args)
        if tool == "browser.read":
            return self.browser.read()
        if tool == "browser.back":
            return self.browser.back()

        # ERP tools
        if tool.startswith("erp."):
            if not getattr(self, "erp", None):
                raise MCPError("unsupported_tool", "ERP twin not available")
            erp = getattr(self, "erp")
            if tool == "erp.create_po":
                return erp.create_po(**args)
            if tool == "erp.get_po":
                return erp.get_po(**args)
            if tool == "erp.list_pos":
                return erp.list_pos()
            if tool == "erp.receive_goods":
                return erp.receive_goods(**args)
            if tool == "erp.submit_invoice":
                return erp.submit_invoice(**args)
            if tool == "erp.get_invoice":
                return erp.get_invoice(**args)
            if tool == "erp.list_invoices":
                return erp.list_invoices()
            if tool == "erp.match_three_way":
                return erp.match_three_way(**args)
            if tool == "erp.post_payment":
                return erp.post_payment(**args)
            raise MCPError("unknown_tool", f"No such tool: {tool}")

        # CRM tools
        if tool.startswith("crm."):
            if not getattr(self, "crm", None):
                raise MCPError("unsupported_tool", "CRM twin not available")
            crm = getattr(self, "crm")
            if tool == "crm.create_contact":
                return crm.create_contact(**args)
            if tool == "crm.get_contact":
                return crm.get_contact(**args)
            if tool == "crm.list_contacts":
                return crm.list_contacts()
            if tool == "crm.create_company":
                return crm.create_company(**args)
            if tool == "crm.get_company":
                return crm.get_company(**args)
            if tool == "crm.list_companies":
                return crm.list_companies()
            if tool == "crm.associate_contact_company":
                return crm.associate_contact_company(**args)
            if tool == "crm.create_deal":
                return crm.create_deal(**args)
            if tool == "crm.get_deal":
                return crm.get_deal(**args)
            if tool == "crm.list_deals":
                return crm.list_deals()
            if tool == "crm.update_deal_stage":
                return crm.update_deal_stage(**args)
            if tool == "crm.log_activity":
                return crm.log_activity(**args)
            raise MCPError("unknown_tool", f"No such tool: {tool}")

        raise MCPError("unknown_tool", f"No such tool: {tool}")

    def snapshot_observation(self, focus_hint: Optional[str] = None) -> Observation:
        """Build an Observation without advancing time or delivering events.

        Useful for server adapters that need to return an observation after a
        call_and_step without mutating simulator state a second time.
        """
        focus = focus_hint or "browser"
        return Observation(
            time_ms=self.bus.clock_ms,
            focus=focus,
            summary=self._summary(focus),
            screenshot_ref=None,
            action_menu=self._action_menu(focus),
            pending_events={
                "slack": self.bus.pending_count("slack"),
                "mail": self.bus.pending_count("mail"),
            },
        )

    def step_and_observe(self, tool: str, args: Dict[str, Any]) -> Observation:
        """Execute a tool call with deterministic step, then return an observation snapshot."""
        self.call_and_step(tool, args)
        focus = "browser"
        if tool.startswith("slack."):
            focus = "slack"
        elif tool.startswith("mail."):
            focus = "mail"
        elif tool.startswith("erp."):
            focus = "erp"
        elif tool.startswith("crm."):
            focus = "crm"
        elif tool.startswith("browser."):
            focus = "browser"
        return self.snapshot_observation(focus)

    def act_and_observe(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool call, advance deterministic time, and return both result and observation.

        This is a convenience for clients that want a single call semantics.
        """
        result = self.call_and_step(tool, args)
        # Choose focus consistent with action
        focus = "browser"
        if tool.startswith("slack."):
            focus = "slack"
        elif tool.startswith("mail."):
            focus = "mail"
        elif tool.startswith("erp."):
            focus = "erp"
        elif tool.startswith("crm."):
            focus = "crm"
        obs = self.snapshot_observation(focus)
        return {"result": result, "observation": obs.model_dump()}

    def pending(self) -> Dict[str, int]:
        """Return pending event counts per target without advancing time."""
        return {
            "slack": self.bus.pending_count("slack"),
            "mail": self.bus.pending_count("mail"),
            "total": self.bus.pending_count(),
        }

    def tick(self, dt_ms: int = 1000) -> Dict[str, Any]:
        """Advance logical time by dt_ms and deliver all due events deterministically.

        Returns the number of delivered events per target and the new time.
        """
        delivered = {"slack": 0, "mail": 0}
        target_time = self.bus.clock_ms + max(0, int(dt_ms))
        # Deliver in order at due timestamps
        while (self.bus.peek_due_time() is not None) and (self.bus.peek_due_time() <= target_time):
            next_due = int(self.bus.peek_due_time() or self.bus.clock_ms)
            # advance clock to the event due time
            self.bus.clock_ms = next_due
            evt = self.bus.next_if_due()
            if evt:
                emitted = None
                if evt.target == "slack":
                    emitted = self.slack.deliver(evt.payload)
                elif evt.target == "mail":
                    emitted = self.mail.deliver(evt.payload)
                delivered[evt.target] += 1
                self.trace.record_event(evt.target, evt.payload, emitted, time_ms=self.bus.clock_ms)
        # Advance remaining time to target_time
        self.bus.clock_ms = target_time
        self.trace.flush()
        return {"delivered": delivered, "time_ms": self.bus.clock_ms, "pending": self.pending()}

    def observe(self, focus_hint: Optional[str] = None) -> Observation:
        """Produce an observation and drain time/event queue incrementally.

        Unlike a pure read, observation advances logical time and delivers at
        most one due event to allow tests to "tick" the simulation forward
        without invoking a side-effecting tool.
        """
        # Deliver one due event if any
        evt = self.bus.next_if_due()
        if evt:
            emitted = None
            if evt.target == "slack":
                emitted = self.slack.deliver(evt.payload)
            elif evt.target == "mail":
                emitted = self.mail.deliver(evt.payload)
            self.trace.record_event(evt.target, evt.payload, emitted, time_ms=self.bus.clock_ms)
        # Advance time per observation to make future events become due
        self.bus.advance(1000)
        focus = focus_hint or "browser"
        obs = Observation(
            time_ms=self.bus.clock_ms,
            focus=focus,
            summary=self._summary(focus),
            screenshot_ref=None,
            action_menu=self._action_menu(focus),
            pending_events={
                "slack": self.bus.pending_count("slack"),
                "mail": self.bus.pending_count("mail"),
            },
        )
        # Persist observations/events so trace is available while running
        self.trace.flush()
        return obs

    def _summary(self, focus: str) -> str:
        if focus == "browser":
            r = self.browser.read()
            return f"Browser: {r['title']} — {r['excerpt']}"
        if focus == "slack":
            ch = self.slack.open_channel("#procurement")
            latest = ch["messages"][-1]["text"] if ch["messages"] else ""
            return f"Slack #procurement latest: {latest}"
        if focus == "mail":
            lst = self.mail.list()
            if lst:
                return f"Mail: {lst[0]['subj']} from {lst[0]['from']}"
            return "Mail: INBOX empty"
        if focus == "erp":
            # Surface a short state summary for agents
            pos = len(getattr(self, "erp").pos) if getattr(self, "erp", None) else 0
            invs = len(getattr(self, "erp").invoices) if getattr(self, "erp", None) else 0
            return f"ERP: {pos} POs, {invs} invoices"
        if focus == "crm":
            cs = len(getattr(self, "crm").contacts) if getattr(self, "crm", None) else 0
            ds = len(getattr(self, "crm").deals) if getattr(self, "crm", None) else 0
            return f"CRM: {cs} contacts, {ds} deals"
        return ""

    def _action_menu(self, focus: str) -> List[Dict[str, Any]]:
        if focus == "browser":
            node_aff = self.browser.nodes[self.browser.state]["affordances"]
            # Provide both concrete affordances and generic actions with schemas for LLMs
            generic: List[Dict[str, Any]] = [
                {"tool": "browser.read", "args_schema": {}},
                {"tool": "browser.find", "args_schema": {"query": "str", "top_k": "int?"}},
                {"tool": "browser.open", "args_schema": {"url": "str"}},
                {"tool": "browser.back", "args_schema": {}},
            ]
            return [*node_aff, *generic]
        if focus == "slack":
            return [
                {"tool": "slack.send_message", "args_schema": {"channel": "str", "text": "str", "thread_ts": "str?"}},
            ]
        if focus == "mail":
            return [
                {"tool": "mail.compose", "args_schema": {"to": "str", "subj": "str", "body_text": "str"}},
            ]
        if focus == "erp" and getattr(self, "erp", None):
            return [
                {"tool": "erp.create_po", "args_schema": {"vendor": "str", "currency": "str", "lines": "[{item_id,desc,qty,unit_price}]"}},
                {"tool": "erp.list_pos", "args_schema": {}},
                {"tool": "erp.submit_invoice", "args_schema": {"vendor": "str", "po_id": "str", "lines": "[{item_id,qty,unit_price}]"}},
                {"tool": "erp.match_three_way", "args_schema": {"po_id": "str", "invoice_id": "str", "receipt_id": "str?"}},
            ]
        if focus == "crm" and getattr(self, "crm", None):
            return [
                {"tool": "crm.create_contact", "args_schema": {"email": "str", "first_name": "str?", "last_name": "str?", "do_not_contact": "bool?"}},
                {"tool": "crm.create_company", "args_schema": {"name": "str", "domain": "str?"}},
                {"tool": "crm.associate_contact_company", "args_schema": {"contact_id": "str", "company_id": "str"}},
                {"tool": "crm.create_deal", "args_schema": {"name": "str", "amount": "number", "stage": "str?", "contact_id": "str?", "company_id": "str?"}},
                {"tool": "crm.update_deal_stage", "args_schema": {"id": "str", "stage": "str"}},
                {"tool": "crm.log_activity", "args_schema": {"kind": "str", "contact_id": "str?", "deal_id": "str?", "note": "str?"}},
            ]
        return []
