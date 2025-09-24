from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .memory import MemoryStore
from .tree import BehaviorContext, Observe, SequenceNode, ToolAction, WaitFor


@dataclass
class BehaviorRunner:
    root: SequenceNode
    context: BehaviorContext

    def run(self, max_steps: int = 20) -> List[Dict[str, object]]:
        self.root.tick(self.context)
        return self.context.transcript


def _approval_arrived(ctx: BehaviorContext) -> bool:
    for entry in reversed(ctx.transcript):
        obs = entry.get("observation")
        if not obs:
            continue
        summary = obs.get("summary", "")
        if "approved" in summary.lower() or ":white_check_mark:" in summary:
            return True
    return False


def _mail_received(ctx: BehaviorContext) -> bool:
    for entry in reversed(ctx.transcript):
        obs = entry.get("observation")
        if not obs:
            continue
        pending = obs.get("pending_events", {})
        if pending.get("mail", 0) == 0:
            continue
        return True
    return False


def ScriptedProcurementPolicy(router, *, memory: Optional[MemoryStore] = None) -> BehaviorRunner:
    """Construct a simple scripted procurement behavior for baseline rollouts."""

    store = memory or MemoryStore()
    ctx = BehaviorContext(router=router, memory=store, transcript=[])

    root = SequenceNode(
        Observe(),
        ToolAction("browser.read"),
        ToolAction(
            "slack.send_message",
            {
                "channel": "#procurement",
                "text": "Requesting approval for laptop purchase under $3200 because it meets spec.",
            },
        ),
        WaitFor(_approval_arrived, max_ticks=3, focus="slack"),
        ToolAction(
            "mail.compose",
            {
                "to": "sales@macrocompute.example",
                "subj": "Quote request for MacroBook",
                "body_text": "Hello, please share the latest quote for MacroBook Pro 16 delivered in 5 business days.",
            },
        ),
        WaitFor(_mail_received, max_ticks=5, focus="mail"),
    )

    return BehaviorRunner(root=root, context=ctx)
