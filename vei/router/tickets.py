from __future__ import annotations

from typing import Dict, List, Optional

from vei.world.scenario import Scenario, Ticket


class TicketsSim:
    """Simple ticket/workflow twin."""

    def __init__(self, scenario: Optional[Scenario] = None):
        base = dict(scenario.tickets) if scenario and scenario.tickets else {}
        self.tickets: Dict[str, Ticket] = base
        self._ticket_seq = self._init_seq()

    def list(self) -> List[Dict[str, object]]:
        return [self._ticket_payload(ticket) for ticket in self.tickets.values()]

    def get(self, ticket_id: str) -> Dict[str, object]:
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            raise ValueError(f"unknown ticket: {ticket_id}")
        return self._ticket_payload(ticket)

    def create(
        self,
        title: str,
        description: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> Dict[str, object]:
        ticket_id = f"TCK-{self._ticket_seq}"
        self._ticket_seq += 1
        ticket = Ticket(
            ticket_id=ticket_id,
            title=title,
            status="open",
            assignee=assignee,
            description=description,
            history=[{"status": "open"}],
        )
        self.tickets[ticket_id] = ticket
        return {"ticket_id": ticket_id}

    def update(
        self,
        ticket_id: str,
        description: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> Dict[str, object]:
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            raise ValueError(f"unknown ticket: {ticket_id}")
        if description is not None:
            ticket.description = description
        if assignee is not None:
            ticket.assignee = assignee
        ticket.history = list(ticket.history or []) + [{"status": ticket.status, "update": "fields"}]
        self.tickets[ticket_id] = ticket
        return {"ticket_id": ticket_id}

    def transition(self, ticket_id: str, status: str) -> Dict[str, object]:
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            raise ValueError(f"unknown ticket: {ticket_id}")
        ticket.status = status
        ticket.history = list(ticket.history or []) + [{"status": status}]
        self.tickets[ticket_id] = ticket
        return {"ticket_id": ticket_id, "status": status}

    def _ticket_payload(self, ticket: Ticket) -> Dict[str, object]:
        return {
            "ticket_id": ticket.ticket_id,
            "title": ticket.title,
            "status": ticket.status,
            "assignee": ticket.assignee,
            "description": ticket.description,
            "history": list(ticket.history or []),
        }

    def _init_seq(self) -> int:
        seq = 1
        for ticket_id in self.tickets.keys():
            try:
                if ticket_id.startswith("TCK-"):
                    seq = max(seq, int(ticket_id.split("-", 1)[1]) + 1)
            except ValueError:
                continue
        return seq

