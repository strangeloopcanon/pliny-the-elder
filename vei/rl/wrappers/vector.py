from __future__ import annotations

from typing import Any, Iterable, List, Sequence, Tuple


class SimpleVectorEnv:
    """Run multiple VEIEnv instances sequentially to mimic vector environments."""

    def __init__(self, make_env_fns: Sequence[callable]) -> None:
        self.envs = [fn() for fn in make_env_fns]

    def reset(self, *args: Any, **kwargs: Any) -> Tuple[List[dict], List[dict]]:
        observations: List[dict] = []
        infos: List[dict] = []
        for env in self.envs:
            obs, info = env.reset(*args, **kwargs)
            observations.append(obs)
            infos.append(info)
        return observations, infos

    def step(self, actions: Iterable[Any]) -> Tuple[List[dict], List[float], List[bool], List[bool], List[dict]]:
        obs_list: List[dict] = []
        rewards: List[float] = []
        terms: List[bool] = []
        truncs: List[bool] = []
        infos: List[dict] = []
        for env, action in zip(self.envs, actions):
            obs, reward, term, trunc, info = env.step(action)
            obs_list.append(obs)
            rewards.append(reward)
            terms.append(term)
            truncs.append(trunc)
            infos.append(info)
        return obs_list, rewards, terms, truncs, infos

    def close(self) -> None:
        for env in self.envs:
            close = getattr(env, "close", None)
            if close:
                close()
