from __future__ import annotations

from vei.rl.env import VEIEnv


def test_step_penalty_accumulates():
    env = VEIEnv(seed=123)
    env.reset()

    rewards = []
    action = {"tool": "mail.list", "args": {}}
    for _ in range(3):
        _, reward, _, _, _ = env.step(action)
        rewards.append(reward)

    assert rewards[0] < 0
    assert rewards[1] < rewards[0]
    assert rewards[2] < rewards[1]
