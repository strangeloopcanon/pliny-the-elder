from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Scenario:
    # Slack configuration
    budget_cap_usd: Optional[int] = None
    derail_prob: Optional[float] = None
    slack_initial_message: Optional[str] = None

    # Mail configuration
    vendor_reply_variants: Optional[List[str]] = None

    # Browser configuration
    browser_nodes: Optional[Dict[str, dict]] = None

    # Optional pre-scheduled events (e.g., derailments)
    derail_events: Optional[List[Dict[str, Any]]] = None

