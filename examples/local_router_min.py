from __future__ import annotations

import json
from vei.router.core import Router


def main() -> None:
    r = Router(seed=42042, artifacts_dir=None)
    obs = r.observe().model_dump()
    print(json.dumps(obs, indent=2))
    r.call_and_step("browser.read", {})
    r.call_and_step("slack.send_message", {"channel": "#procurement", "text": "Budget $3200 summary"})
    r.call_and_step("mail.compose", {"to": "sales@macrocompute.example", "subj": "Quote", "body_text": "latest price and ETA?"})
    for _ in range(10):
        o = r.observe("mail").model_dump()
        print(json.dumps(o, indent=2))
        if o["pending_events"]["mail"] == 0 and o["pending_events"]["slack"] == 0:
            break


if __name__ == "__main__":
    main()



