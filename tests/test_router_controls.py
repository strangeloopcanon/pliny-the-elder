from __future__ import annotations

from vei.router.core import Router


def test_act_and_observe_basic():
    r = Router(seed=1, artifacts_dir=None)
    ao = r.act_and_observe("browser.read", {})
    assert "result" in ao and "observation" in ao
    assert "title" in ao["result"]
    assert "action_menu" in ao["observation"]


def test_pending_and_tick_mail_delivery(tmp_path):
    r = Router(seed=1, artifacts_dir=str(tmp_path / "artifacts"))
    # Compose schedules a mail reply in the future
    r.call_and_step(
        "mail.compose",
        {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."},
    )
    p = r.pending()
    assert p["mail"] >= 1
    # Advance enough time to deliver
    res = r.tick(15000)
    assert res["pending"]["mail"] == 0
    # Ensure the message was delivered to inbox
    inbox = r.mail.list()
    assert len(inbox) >= 1

