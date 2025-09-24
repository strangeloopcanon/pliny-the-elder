from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List

from .state import StateStore


@dataclass
class DriftJob:
    job_id: str
    target: str
    cadence_ms: int
    initial_offset_ms: int
    payload_templates: List[Dict[str, Any]]
    jitter_ms: int = 0


class DriftEngine:
    """Deterministic background event scheduler.

    The engine is deliberately minimal: it schedules synthetic Slack/mail
    activity to keep the environment feeling alive while remaining fully
    reproducible for a given seed + mode. Each delivered drift event queues the
    next instance according to the job cadence.
    """

    def __init__(
        self,
        *,
        state_store: StateStore,
        bus,
        seed: int,
        mode: str = "off",
    ) -> None:
        self.state_store = state_store
        self.bus = bus
        self.mode = (mode or "off").lower()
        self._active = self.mode not in {"off", "none"}
        self._rng = random.Random(int(seed) & 0xFFFFFFFF)
        self._primed = False
        self._jobs: Dict[str, DriftJob] = {}

    def prime(self) -> None:
        if not self._active or self._primed:
            return
        jobs = self._jobs_for_mode()
        for job in jobs:
            self._jobs[job.job_id] = job
            self._schedule_job(job, job.initial_offset_ms)
        self._primed = True

    def handle_delivery(self, target: str, payload: Dict[str, Any]) -> None:
        if not self._active or not payload.get("drift"):
            return
        job_id = payload.get("drift_job")
        self.state_store.append(
            "drift.delivered",
            {
                "job": job_id,
                "target": target,
                "time_ms": self.bus.clock_ms,
            },
        )
        if job_id and job_id in self._jobs:
            job = self._jobs[job_id]
            self._schedule_job(job, job.cadence_ms)

    # ------------------------------------------------------------------
    def _jobs_for_mode(self) -> List[DriftJob]:
        if self.mode in {"light", "slow"}:
            cadence_factor = 2
        elif self.mode in {"fast"}:
            cadence_factor = 1
        else:
            cadence_factor = 1

        base_jobs = [
            DriftJob(
                job_id="mail.weekly_newsletter",
                target="mail",
                cadence_ms=120_000 // cadence_factor,
                initial_offset_ms=45_000 // cadence_factor,
                jitter_ms=10_000 // cadence_factor,
                payload_templates=[
                    {
                        "from": "newsletter@macrocompute.example",
                        "subj": "Weekly procurement digest",
                        "body_text": "Top tickets: MacroBook refresh, monitor replacements, CFO approval backlog.",
                    },
                    {
                        "from": "newsletter@macrocompute.example",
                        "subj": "Vendor scorecard snapshot",
                        "body_text": "Reminder: MacroCompute Q3 supplier review due Friday.",
                    },
                ],
            ),
            DriftJob(
                job_id="slack.procurement_ping",
                target="slack",
                cadence_ms=90_000 // cadence_factor,
                initial_offset_ms=30_000 // cadence_factor,
                jitter_ms=8_000 // cadence_factor,
                payload_templates=[
                    {
                        "channel": "#procurement",
                        "text": "Heads-up: Finance wants laptop refresh status by EOD.",
                        "thread_ts": None,
                    },
                    {
                        "channel": "#procurement",
                        "text": "Reminder: please attach vendor quotes to approvals (auto)",
                        "thread_ts": None,
                    },
                ],
            ),
        ]

        if self.mode in {"aggressive", "fast"}:
            base_jobs.append(
                DriftJob(
                    job_id="mail.alert_security",
                    target="mail",
                    cadence_ms=150_000 // cadence_factor,
                    initial_offset_ms=75_000 // cadence_factor,
                    jitter_ms=12_000 // cadence_factor,
                    payload_templates=[
                        {
                            "from": "security@macrocompute.example",
                            "subj": "Login notice: Procurement portal",
                            "body_text": "We noticed a sign-in from a new device for procurement@macrocompute.example.",
                        }
                    ],
                )
            )

        return base_jobs

    def _schedule_job(self, job: DriftJob, offset_ms: int) -> None:
        jitter = self._rng.randint(0, max(0, job.jitter_ms)) if job.jitter_ms else 0
        dt = max(0, offset_ms + jitter)
        template = dict(self._rng.choice(job.payload_templates))
        template.setdefault("drift", True)
        template.setdefault("drift_job", job.job_id)
        self.bus.schedule(dt_ms=dt, target=job.target, payload=template)
        self.state_store.append(
            "drift.schedule",
            {
                "job": job.job_id,
                "target": job.target,
                "dt_ms": dt,
                "payload": template,
            },
        )

