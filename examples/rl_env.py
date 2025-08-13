from __future__ import annotations

import json
from vei.rl.env import VEIEnv


def main() -> None:
    env = VEIEnv(seed=42042, reward_mode="dense")
    obs, info = env.reset()
    print("reset: pending=", obs.get("pending_events"))
    steps = [
        {"tool": "browser.read", "args": {}},
        {"tool": "slack.send_message", "args": {"channel": "#procurement", "text": "Summary: budget $3200, citations included."}},
        {"tool": "mail.compose", "args": {"to": "sales@macrocompute.example", "subj": "Quote request", "body_text": "Please send latest price and ETA."}},
    ]
    for a in steps:
        obs, reward, terminated, truncated, info = env.step(a)
        print(json.dumps({"reward": reward, "terminated": terminated, "info": info}, indent=2))
    # Observe until events drain
    for _ in range(20):
        obs, reward, terminated, truncated, info = env.step({"tool": "vei.observe", "args": {}})
        print(json.dumps({"reward": reward, "terminated": terminated, "pending": obs.get("pending_events"), "info": info}, indent=2))
        if terminated:
            break


if __name__ == "__main__":
    main()



